"""Tests for the plugin advice. idea-oc only checks which plugins are listed; it never changes them."""

import os
from pathlib import Path

import pytest

from idea_oc import plugins as plugins_module
from idea_oc.cli import cli
from idea_oc.jsonc_doc import JsoncDocument
from idea_oc.plugins import RECOMMENDED, check_plugins, identity, listed_plugins
from idea_oc.team_config import team_config
from tests.conftest import skill_md


@pytest.fixture
def config_file():
    return Path(os.environ["IDEA_OC_CONFIG"])


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture
def snip_installed(monkeypatch):
    monkeypatch.setattr(plugins_module.shutil, "which", lambda name: f"/usr/local/bin/{name}")


@pytest.fixture
def snip_absent(monkeypatch):
    monkeypatch.setattr(plugins_module.shutil, "which", lambda name: None)


FULL = (
    '{"plugin": [["./plugin-scripts/inject-env.js", {"AWS_PROFILE": "bedrockonly"}],'
    ' "@tarquinen/opencode-dcp@latest", "envsitter-guard", "opencode-snip", "cc-safety-net"]}'
)


# --- identifying plugins --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("envsitter-guard", "envsitter-guard"),
        ("opencode-snip@1.2.3", "opencode-snip"),
        ("@tarquinen/opencode-dcp", "@tarquinen/opencode-dcp"),
        ("@tarquinen/opencode-dcp@latest", "@tarquinen/opencode-dcp"),
        ("./plugin-scripts/inject-env.js", "inject-env.js"),
        (["./plugin-scripts/inject-env.js", {"AWS_PROFILE": "x"}], "inject-env.js"),
        (["opencode-snip", {"opt": 1}], "opencode-snip"),
        ("file:///Users/me/plugins/inject-env.js", "inject-env.js"),
        ("~/plugins/inject-env.js", "inject-env.js"),
        ("/abs/path/inject-env.js", "inject-env.js"),
        ("", None),
        ([], None),
        (None, None),
        (42, None),
        ({"name": "x"}, None),
    ],
)
def test_identity(spec, expected):
    assert identity(spec) == expected


# --- reading the config ---------------------------------------------------------------------


def test_listed_plugins_ignores_versions_and_options(config_file):
    write(config_file, FULL)

    assert listed_plugins(config_file) == {
        "inject-env.js",
        "@tarquinen/opencode-dcp",
        "envsitter-guard",
        "opencode-snip",
        "cc-safety-net",
    }


def test_commented_configs_with_trailing_commas_are_read(config_file):
    write(config_file, '{\n  // plugins\n  "plugin": [\n    "envsitter-guard", // safe\n  ],\n}\n')

    assert listed_plugins(config_file) == {"envsitter-guard"}


def test_a_config_without_plugins_lists_none(config_file):
    write(config_file, "{}")

    assert listed_plugins(config_file) == set()


def test_a_missing_config_lists_none(config_file):
    assert listed_plugins(config_file) == set()


def test_the_plugin_list_comes_from_whichever_global_file_defines_it_and_the_last_one_wins(config_file):
    folder = config_file.parent
    write(folder / "config.json", '{"plugin": ["envsitter-guard"]}')
    write(folder / "opencode.json", '{"plugin": ["cc-safety-net"]}')
    write(folder / "opencode.jsonc", "{}")  # defines no list, so the earlier one stands

    assert listed_plugins(folder / "opencode.jsonc") == {"cc-safety-net"}


def test_a_later_file_replaces_an_earlier_list_as_in_opencode(config_file):
    folder = config_file.parent
    write(folder / "opencode.json", '{"plugin": ["envsitter-guard"]}')
    write(folder / "opencode.jsonc", '{"plugin": ["cc-safety-net"]}')

    assert listed_plugins(folder / "opencode.jsonc") == {"cc-safety-net"}


# --- the report -----------------------------------------------------------------------------


def test_an_empty_config_is_missing_everything_and_the_required_plugin_is_singled_out(config_file, snip_absent):
    write(config_file, "{}")

    report = check_plugins(config_file)

    assert [p.identity for p in report.missing_required] == ["inject-env.js"]
    assert {p.identity for p in report.missing_recommended} == {
        "@tarquinen/opencode-dcp",
        "envsitter-guard",
        "opencode-snip",
        "cc-safety-net",
    }
    assert report.snip_missing is False  # snip is only checked when the plugin that needs it is listed
    assert report.all_good is False


def test_everything_listed_and_snip_installed_is_all_good(config_file, snip_installed):
    write(config_file, FULL)

    assert check_plugins(config_file).all_good


def test_the_snip_program_is_only_checked_when_its_plugin_is_listed(config_file, snip_absent):
    write(config_file, '{"plugin": ["opencode-snip"]}')
    assert check_plugins(config_file).snip_missing is True

    write(config_file, '{"plugin": ["envsitter-guard"]}')
    assert check_plugins(config_file).snip_missing is False


def test_an_unreadable_config_gives_an_error_not_an_exception(config_file):
    write(config_file, "{ not json")

    report = check_plugins(config_file)

    assert report.error
    assert report.plugins == []


# --- consistency with the preferred config --------------------------------------------------


def test_the_recommended_plugins_are_exactly_those_in_the_preferred_config():
    configured = {identity(spec) for spec in team_config().get(("plugin",))}

    assert {p.identity for p in RECOMMENDED} == configured


def test_only_the_environment_plugin_is_required_and_it_comes_first():
    assert [p.identity for p in RECOMMENDED if p.required] == ["inject-env.js"]
    assert RECOMMENDED[0].required


# --- the output -----------------------------------------------------------------------------


def test_sync_config_advises_on_missing_plugins_and_still_never_adds_them(cli_runner, config_file, snip_absent):
    result = cli_runner.invoke(cli, ["sync", "config", "--yes"])

    assert result.exit_code == 0
    assert "Plugins (idea-oc does not install or change these):" in result.output
    assert "missing (REQUIRED)  inject-env.js" in result.output
    assert "missing             cc-safety-net" in result.output
    assert "guides/plugins/#the-required-plugin" in result.output
    assert "guides/plugins/#recommended-plugins" in result.output
    assert "plugin" not in config_file.read_text().replace("opencode-snip", "")  # nothing was added to the config
    assert "inject-env" not in config_file.read_text()


def test_the_required_plugin_is_listed_before_the_others(cli_runner, config_file, snip_absent):
    result = cli_runner.invoke(cli, ["sync", "config", "--dry-run"])

    lines = [ln for ln in result.output.splitlines() if "missing" in ln]
    assert "REQUIRED" in lines[0]


def test_advice_is_given_whether_or_not_the_user_applies_the_changes(cli_runner, config_file, snip_absent):
    declined = cli_runner.invoke(cli, ["sync", "config"], input="n\n")
    dry = cli_runner.invoke(cli, ["sync", "config", "--dry-run"])

    assert "missing (REQUIRED)  inject-env.js" in declined.output
    assert "missing (REQUIRED)  inject-env.js" in dry.output


def test_a_user_with_every_plugin_just_sees_a_one_line_confirmation(cli_runner, config_file, snip_installed):
    write(config_file, FULL)
    cli_runner.invoke(cli, ["sync", "config", "--yes"])

    result = cli_runner.invoke(cli, ["sync", "config"])

    assert "Plugins: all the recommended plugins are listed." in result.output
    assert "missing" not in result.output


def test_the_snip_warning_explains_the_silent_failure_and_how_to_fix_it(cli_runner, config_file, snip_absent):
    write(config_file, '{"plugin": ["opencode-snip"]}')

    result = cli_runner.invoke(cli, ["sync", "config", "--dry-run"])

    assert "opencode-snip is listed but the 'snip' program is not installed, so it does nothing." in result.output
    assert "brew install edouard-claude/tap/snip" in result.output
    assert "guides/plugins/#opencode-snip-needs-a-separate-program" in result.output


def test_no_snip_warning_when_the_program_is_installed(cli_runner, config_file, snip_installed):
    write(config_file, '{"plugin": ["opencode-snip"]}')

    result = cli_runner.invoke(cli, ["sync", "config", "--dry-run"])

    assert "'snip' program" not in result.output


def test_the_users_plugin_list_is_never_modified(cli_runner, config_file, snip_absent):
    original = '{\n  "plugin": ["my-own-plugin"] // mine\n}\n'
    write(config_file, original)

    cli_runner.invoke(cli, ["sync", "config", "--yes"])

    text = config_file.read_text()
    assert JsoncDocument.parse(text).get(("plugin",)) == ["my-own-plugin"]
    assert "// mine" in text
    assert "cc-safety-net" not in text


def test_status_config_shows_the_advice_but_it_does_not_fail_the_check(cli_runner, config_file, snip_absent):
    cli_runner.invoke(cli, ["sync", "config", "--yes"])

    result = cli_runner.invoke(cli, ["status", "config"])

    assert result.exit_code == 0
    assert "Config:  ok" in result.output
    assert "missing (REQUIRED)  inject-env.js" in result.output


def test_status_config_exit_code_ignores_plugins_even_when_the_required_one_is_missing(
    cli_runner, config_file, snip_absent
):
    cli_runner.invoke(cli, ["sync", "config", "--yes"])

    assert cli_runner.invoke(cli, ["status", "config"]).exit_code == 0
    assert cli_runner.invoke(cli, ["status", "config", "--quiet"]).exit_code == 0


def test_quiet_status_stays_silent_about_plugins(cli_runner, config_file, snip_absent):
    cli_runner.invoke(cli, ["sync", "config", "--yes"])

    result = cli_runner.invoke(cli, ["status", "config", "--quiet"])

    assert result.output == ""


def test_an_unreadable_config_gets_no_plugin_advice(cli_runner, config_file):
    write(config_file, '{ "model": ')

    result = cli_runner.invoke(cli, ["sync", "config", "--yes"])

    assert "Plugins" not in result.output
    assert "cannot edit" in result.output


def test_the_skills_stage_says_nothing_about_plugins(cli_runner, github, reviewer_only, snip_absent):
    github.add_repo("co-cddo/gds-idea-ai-reviewer", {"src/ai_reviewer/skills/a/SKILL.md": skill_md("a")}, tag="v0.1.22")

    result = cli_runner.invoke(cli, ["sync", "skills"])

    assert "Plugins" not in result.output
