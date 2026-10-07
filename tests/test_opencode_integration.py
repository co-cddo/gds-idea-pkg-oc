"""Checks against the real OpenCode, which decides what a model can do from its id.

An inference profile's ARN says nothing about the model behind it, so OpenCode would otherwise treat
a profile as a model with no context window, no reasoning and the wrong thinking settings. These tests
ask OpenCode what it resolves a generated profile entry to, and compare it with the catalogue model
the profile routes to. They need the ``opencode`` command, so they run with ``pytest -m integration``.
"""

import json
import os
import pathlib
import pwd
import shutil
import subprocess

import pytest

from idea_oc.profiles import load_profiles

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("opencode") is None, reason="needs the opencode command"),
]

CATALOGUE_MODEL = "amazon-bedrock/eu.anthropic.claude-sonnet-5-5"


def opencode_env(tmp_path) -> dict[str, str]:
    """An environment where OpenCode reads the config in ``tmp_path/xdg`` and nothing of the user's.

    Config, data and state are isolated. The cache is not: it holds OpenCode's downloaded model
    catalogue, and without it OpenCode cannot resolve the catalogue model we compare against. The
    test environment fakes $HOME, so take the real cache from the account's real home directory.
    """
    real_cache = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache"
    return {
        **os.environ,
        **{f"XDG_{name}_HOME": str(tmp_path / "xdg") for name in ("CONFIG", "DATA", "STATE")},
        "XDG_CACHE_HOME": str(real_cache),
    }


def project_dir(tmp_path) -> pathlib.Path:
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
    return project


def resolve_models(tmp_path, models: dict) -> dict[str, dict]:
    """Run ``opencode models amazon-bedrock --verbose`` against a config holding ``models``."""
    config_dir = tmp_path / "xdg" / "opencode"
    config_dir.mkdir(parents=True)
    provider = {"options": {"region": "eu-west-2", "profile": "bedrockonly"}, "models": models}
    (config_dir / "opencode.json").write_text(json.dumps({"provider": {"amazon-bedrock": provider}}))
    output = subprocess.run(
        ["opencode", "models", "amazon-bedrock", "--verbose"],
        cwd=project_dir(tmp_path),
        env=opencode_env(tmp_path),
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    ).stdout

    decoder, resolved, offset = json.JSONDecoder(), {}, 0
    for line in output.splitlines(keepends=True):
        offset += len(line)
        if line.startswith("amazon-bedrock/"):
            resolved[line.strip()], _ = decoder.raw_decode(output, offset)
    return resolved


def behaviour(model: dict) -> dict:
    """The parts of a resolved model that change how OpenCode talks to it."""
    caps = model["capabilities"]
    return {
        "limit": model["limit"],
        "reasoning": caps["reasoning"],
        "toolcall": caps["toolcall"],
        "attachment": caps["attachment"],
        "temperature": caps["temperature"],
        "input": caps["input"],
        "output": caps["output"],
        "cost": model["cost"],
        "family": model["family"],
        "variants": model["variants"],
    }


@pytest.mark.parametrize("team", sorted(load_profiles().teams))
def test_a_profile_entry_behaves_exactly_like_the_model_it_routes_to(tmp_path, team):
    profiles = load_profiles()
    models = resolve_models(tmp_path, {profiles.model_key(team): profiles.model_entry(team)})

    ours = models[profiles.model_ref(team)]
    catalogue = models[CATALOGUE_MODEL]

    assert behaviour(ours) == behaviour(catalogue)
    assert ours["api"]["id"] == profiles.arn(team)  # ... but requests go through the profile


def test_a_bare_arn_would_not_behave_like_the_model(tmp_path):
    """The reason the settings are restated: without them OpenCode knows nothing about the model."""
    profiles = load_profiles()
    models = resolve_models(tmp_path, {profiles.model_key("ds"): {"id": profiles.arn("ds")}})

    bare = models[profiles.model_ref("ds")]
    assert bare["limit"] == {"context": 0, "output": 0}
    assert bare["capabilities"]["reasoning"] is False
    assert bare["variants"] == {}


# --- the Claude prompt ------------------------------------------------------------------------

CLAUDE_PROMPT_MARKER = "You are OpenCode, the best coding agent on the planet"


def write_synced_config(tmp_path) -> pathlib.Path:
    """The config and prompt file ``idea-oc sync config`` would write, in OpenCode's config folder."""
    from idea_oc.opencode_config import apply_plan, plan_config

    config_path = tmp_path / "xdg" / "opencode" / "opencode.json"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    apply_plan(plan_config(config_path, tmp_path / "store"), config_path)
    return config_path


def show_agent(tmp_path, name: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["opencode", "debug", "agent", name],
        cwd=project_dir(tmp_path),
        env=opencode_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize("agent", ["build", "plan", "general"])
def test_agents_on_a_profile_get_the_claude_instructions(tmp_path, agent):
    """OpenCode would otherwise give a profile the general instructions, because an ARN does not say claude."""
    write_synced_config(tmp_path)

    shown = show_agent(tmp_path, agent)

    assert shown.returncode == 0, shown.stderr
    assert CLAUDE_PROMPT_MARKER in shown.stdout


def test_agents_with_their_own_instructions_keep_them(tmp_path):
    write_synced_config(tmp_path)

    shown = show_agent(tmp_path, "explore")

    assert shown.returncode == 0, shown.stderr
    assert CLAUDE_PROMPT_MARKER not in shown.stdout


def test_opencode_will_not_start_if_the_prompt_file_it_is_told_to_read_is_missing(tmp_path):
    """The reason idea-oc writes the file before the config, and warns when it is gone.

    If OpenCode ever tolerates a missing file this fails, and that safeguard can be relaxed.
    """
    from idea_oc.prompts import prompt_path

    config_path = write_synced_config(tmp_path)
    prompt_path(config_path).unlink()

    shown = show_agent(tmp_path, "build")

    assert shown.returncode != 0
    assert "bad file reference" in shown.stdout + shown.stderr
