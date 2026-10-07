"""``--team``: which Bedrock inference profile a user's config points at, and so whose usage is tracked."""

import json
import os
from pathlib import Path

import pytest

from idea_oc.cli import cli
from idea_oc.profiles import load_profiles
from tests.conftest import skill_md

PROFILES = load_profiles()


@pytest.fixture
def config_file():
    return Path(os.environ["IDEA_OC_CONFIG"])


def read(config_file: Path) -> dict:
    return json.loads(config_file.read_text())


def sync_config(cli_runner, *args):
    return cli_runner.invoke(cli, ["sync", "config", "--yes", *args])


# --- choosing a team --------------------------------------------------------------------------


def test_a_new_user_gets_the_default_team_and_is_told_how_to_pick_another(cli_runner, config_file):
    result = sync_config(cli_runner)

    assert result.exit_code == 0, result.output
    assert read(config_file)["model"] == PROFILES.model_ref("ds")
    assert "Team: ds (the default)." in result.output
    assert "If you are in econ or sds, run again with --team <name>." in result.output


@pytest.mark.parametrize("team", ["ds", "sds", "econ"])
def test_the_team_flag_points_the_config_at_that_teams_profile(cli_runner, config_file, team):
    result = sync_config(cli_runner, "--team", team)

    config = read(config_file)
    assert f"Team: {team} (chosen with --team)." in result.output
    assert config["model"] == PROFILES.model_ref(team)
    assert "small_model" not in config
    assert list(config["provider"]["amazon-bedrock"]["models"]) == [PROFILES.model_key(team)]
    assert config["provider"]["amazon-bedrock"]["models"][PROFILES.model_key(team)]["id"] == PROFILES.arn(team)


def test_a_later_plain_sync_keeps_the_team_instead_of_flipping_back_to_the_default(cli_runner, config_file):
    sync_config(cli_runner, "--team", "sds")

    result = cli_runner.invoke(cli, ["sync", "config", "--yes"])

    assert "Config is up to date. Team: sds (kept from your current model)." in result.output
    assert read(config_file)["model"] == PROFILES.model_ref("sds")


def test_the_flag_moves_a_user_from_one_team_to_another(cli_runner, config_file):
    sync_config(cli_runner, "--team", "ds")

    result = sync_config(cli_runner, "--team", "econ")

    config = read(config_file)
    assert config["model"] == PROFILES.model_ref("econ")
    assert "change  model" in result.output
    assert (
        PROFILES.model_key("ds") in config["provider"]["amazon-bedrock"]["models"]
    )  # the old entry is left for the user


def test_the_change_list_shows_the_profile_not_a_wall_of_settings(cli_runner):
    result = cli_runner.invoke(cli, ["sync", "config", "--dry-run", "--team", "sds"])

    assert "inference profile ca6k31qi6v37" in result.output
    assert "context" not in result.output and "reasoningConfig" not in result.output
    assert result.output.count("\n  add     provider.amazon-bedrock.models") == 1


def test_an_unknown_team_is_a_usage_error_naming_the_valid_ones_and_touches_nothing(cli_runner, config_file):
    result = cli_runner.invoke(cli, ["sync", "config", "--yes", "--team", "nobody"])

    assert result.exit_code == 2
    assert "Unknown team 'nobody'. The teams are: ds, econ, sds" in result.output
    assert not config_file.exists()


def test_every_configured_team_is_named_in_the_help(cli_runner):
    """The help text lists the teams by hand, so it must not fall out of step with profiles.toml."""
    for command in ("sync", "status"):
        text = " ".join(cli_runner.invoke(cli, [command, "--help"]).output.split())
        assert all(team in text for team in PROFILES.teams), command


# --- declining, dry runs and the .new file ----------------------------------------------------


def test_declining_saves_a_proposal_for_the_chosen_team_and_leaves_the_config_alone(cli_runner, config_file):
    config_file.parent.mkdir(parents=True)
    config_file.write_text('{\n  "model": "amazon-bedrock/eu.anthropic.claude-sonnet-5-5" // mine\n}\n')
    original = config_file.read_text()

    result = cli_runner.invoke(cli, ["sync", "config", "--team", "sds"], input="n\n")

    assert config_file.read_text() == original
    proposal = config_file.with_name(f"{config_file.name}.new").read_text()
    assert PROFILES.model_key("sds") in proposal and PROFILES.model_key("ds") not in proposal
    assert "// mine" in proposal
    assert "Not changed" in result.output


def test_a_dry_run_names_the_team_and_writes_nothing(cli_runner, config_file):
    result = cli_runner.invoke(cli, ["sync", "config", "--dry-run", "--team", "econ"])

    assert "Team: econ (chosen with --team)." in result.output
    assert not config_file.exists()


def test_both_stages_accept_the_flag_and_only_the_config_stage_uses_it(cli_runner, config_file, github, reviewer_only):
    files = {"src/ai_reviewer/skills/a/SKILL.md": skill_md("a")}
    github.add_repo("co-cddo/gds-idea-ai-reviewer", files, tag="v0.1.22")

    result = cli_runner.invoke(cli, ["sync", "--yes", "--team", "sds"])

    assert result.exit_code == 0, result.output
    assert read(config_file)["model"] == PROFILES.model_ref("sds")


# --- status -----------------------------------------------------------------------------------


def test_status_compares_against_the_team_the_config_already_uses(cli_runner):
    sync_config(cli_runner, "--team", "sds")

    result = cli_runner.invoke(cli, ["status", "config"])

    assert result.exit_code == 0
    assert "Config:  ok" in result.output
    assert "Team: sds (kept from your current model)." in result.output


def test_status_with_another_team_lists_what_would_change(cli_runner):
    sync_config(cli_runner, "--team", "ds")

    result = cli_runner.invoke(cli, ["status", "config", "--team", "econ"])

    assert result.exit_code == 1
    assert "Team: econ (chosen with --team)." in result.output
    assert "inference profile sbs7oxfolxbz" in result.output


def test_quiet_status_prints_nothing_for_a_config_that_matches_its_team(cli_runner):
    sync_config(cli_runner, "--team", "econ")

    result = cli_runner.invoke(cli, ["status", "config", "--quiet"])

    assert result.exit_code == 0
    assert result.output == ""


def test_status_for_a_user_still_on_the_plain_model_reports_the_move_to_a_profile(cli_runner, config_file):
    config_file.parent.mkdir(parents=True)
    config_file.write_text('{"model": "amazon-bedrock/eu.anthropic.claude-sonnet-5-5"}\n')

    result = cli_runner.invoke(cli, ["status", "config"])

    assert result.exit_code == 1
    assert "Team: ds (the default)." in result.output
    assert "change  model" in result.output and PROFILES.model_key("ds") in result.output


def test_renaming_the_key_does_not_lose_the_team_it_is_recognised_from_the_arn(cli_runner, config_file):
    sync_config(cli_runner, "--team", "econ")
    config = read(config_file)
    entry = config["provider"]["amazon-bedrock"]["models"].pop(PROFILES.model_key("econ"))
    config["provider"]["amazon-bedrock"]["models"]["my-claude"] = entry
    config["model"] = "amazon-bedrock/my-claude"
    config_file.write_text(json.dumps(config))

    result = cli_runner.invoke(cli, ["status", "config"])

    # the renamed key still differs from the preferred one and is listed, but it is econ's, never flipped to ds
    assert "Team: econ (kept from your current model)." in result.output
    assert PROFILES.model_key("ds") not in result.output
    assert PROFILES.model_key("econ") in result.output
