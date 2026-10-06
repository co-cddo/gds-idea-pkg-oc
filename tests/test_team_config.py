"""Tests for the bundled preferred OpenCode config.

The permission rules are read top to bottom and the last matching rule wins, so a rule's
position decides whether it works. These tests evaluate the rules the way OpenCode does.
"""

import re
from importlib.resources import files

import pytest

from idea_oc.jsonc_doc import JsoncDocument
from idea_oc.permissions import effective, find_overridden, wildcard_match


def evaluate(rules: dict[str, str], command: str) -> str:
    return effective(rules, command)[1]


def team_config_text() -> str:
    return files("idea_oc").joinpath("opencode.jsonc").read_text()


@pytest.fixture(scope="module")
def config() -> JsoncDocument:
    return JsoncDocument.parse(team_config_text())


@pytest.fixture(scope="module")
def bash_rules(config) -> dict[str, str]:
    return config.get(("permission", "bash"))


def test_the_file_is_valid_and_survives_an_untouched_round_trip(config):
    assert config.text == team_config_text()


def test_it_sets_up_bedrock_in_the_team_region(config):
    assert config.get(("provider", "amazon-bedrock", "options")) == {"region": "eu-west-2", "profile": "bedrockonly"}
    assert config.get(("model",)) == "amazon-bedrock/eu.anthropic.claude-sonnet-5-5"
    assert config.get(("disabled_providers",)) == ["anthropic"]


def test_the_required_environment_plugin_comes_first(config):
    first = config.get(("plugin",))[0]

    assert first == ["./plugin-scripts/inject-env.js", {"AWS_PROFILE": "bedrockonly"}]


def test_the_catch_all_rule_is_first_so_every_specific_rule_can_override_it(bash_rules):
    assert next(iter(bash_rules)) == "*"
    assert bash_rules["*"] == "allow"


def test_every_rule_carries_an_explanatory_comment():
    lines = [ln for ln in team_config_text().splitlines() if re.match(r'\s+"[^"]+": "(allow|ask|deny)"', ln)]
    uncommented = [ln.strip() for ln in lines if "//" not in ln and '"*": "allow"' not in ln]

    assert uncommented == []


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("ls -la", "allow"),
        ("rm -rf /tmp/x", "deny"),
        ("cdk deploy", "ask"),
        ("cdk destroy", "deny"),
        ("git reset --hard HEAD~1", "deny"),
        ("git push origin feature", "ask"),
        ("git push --force origin main", "ask"),  # a force-push after a rebase is allowed once confirmed
        ("gh pr view 3", "ask"),
        ("gh pr merge 12", "deny"),
        ("gh pr ready 3", "deny"),
        ("gh pr close 4", "ask"),
        ("gh pr create --title x", "deny"),
        ("gh pr create --draft --title x", "ask"),
        ("sudo apt install x", "ask"),
    ],
)
def test_bash_commands_get_the_action_the_comments_promise(bash_rules, command, expected):
    assert evaluate(bash_rules, command) == expected


def test_no_rule_is_shadowed_by_a_later_one(bash_rules):
    """A rule that a later rule overrides for its own command is dead: it can never take effect."""
    assert find_overridden(bash_rules) == []


def test_the_shadow_check_catches_the_original_force_push_mistake():
    mistaken = {"*": "allow", "git push --force*": "deny", "git push *": "ask"}

    [dead] = find_overridden(mistaken)

    assert (dead.pattern, dead.action, dead.by_pattern, dead.by_action) == (
        "git push --force*",
        "deny",
        "git push *",
        "ask",
    )


def test_the_shadow_check_accepts_specific_rules_placed_after_general_ones():
    assert find_overridden({"*": "allow", "git push *": "ask", "git push --force*": "deny"}) == []


@pytest.mark.parametrize("section", ["external_directory", "edit"])
def test_the_other_permission_sections_are_just_a_catch_all_ask(config, section):
    assert config.get(("permission", section)) == {"*": "ask"}


def test_the_plugin_script_is_bundled_and_does_what_the_config_expects():
    script = files("idea_oc").joinpath("plugin-scripts/inject-env.js").read_text()

    assert "shell.env" in script
    assert "output.env[key] = value" in script
    assert "export const InjectEnvPlugin" in script


def test_matcher_follows_opencodes_wildcard_rules():
    assert wildcard_match("git push", "git push *")  # trailing " *" is optional
    assert wildcard_match("git push origin", "git push *")
    assert not wildcard_match("git pushed", "git push *")
    assert wildcard_match("rm -rf /", "rm -rf*")
    assert not wildcard_match("sudo rm -rf /", "rm -rf*")  # patterns are anchored
