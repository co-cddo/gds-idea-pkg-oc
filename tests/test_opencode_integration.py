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


def resolve_models(tmp_path, models: dict) -> dict[str, dict]:
    """Run ``opencode models amazon-bedrock --verbose`` against a config holding ``models``."""
    config_dir = tmp_path / "xdg" / "opencode"
    config_dir.mkdir(parents=True)
    provider = {"options": {"region": "eu-west-2", "profile": "bedrockonly"}, "models": models}
    (config_dir / "opencode.json").write_text(json.dumps({"provider": {"amazon-bedrock": provider}}))
    project = tmp_path / "project"
    project.mkdir()
    subprocess.run(["git", "init", "-q", "."], cwd=project, check=True)
    # Config, data and state are isolated. The cache is not: it holds OpenCode's downloaded model
    # catalogue, and without it OpenCode cannot resolve the catalogue model we compare against. The
    # test environment fakes $HOME, so take the real cache from the account's real home directory.
    real_cache = pathlib.Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache"
    env = {
        **os.environ,
        **{f"XDG_{name}_HOME": str(tmp_path / "xdg") for name in ("CONFIG", "DATA", "STATE")},
        "XDG_CACHE_HOME": str(real_cache),
    }
    output = subprocess.run(
        ["opencode", "models", "amazon-bedrock", "--verbose"],
        cwd=project,
        env=env,
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
