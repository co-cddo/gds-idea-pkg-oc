"""The skills and config stages are independent: either can run, fail or be skipped on its own."""

import json
import os
from pathlib import Path

import pytest

from idea_oc.cli import cli
from idea_oc.docs import SYNC_WHY_URL as DOCS_URL
from tests.conftest import skill_md

REVIEWER = "co-cddo/gds-idea-ai-reviewer"
ROOT = "src/ai_reviewer/skills"


@pytest.fixture
def store_dir():
    return Path(os.environ["IDEA_OC_STORE"])


@pytest.fixture
def config_file():
    return Path(os.environ["IDEA_OC_CONFIG"])


@pytest.fixture
def reviewer(github):
    files = {f"{ROOT}/{n}/SKILL.md": skill_md(n) for n in ("cdk-review", "readme-review")}
    github.add_repo(REVIEWER, files, tag="v0.1.22")
    return github


def registered(config_file: Path) -> bool:
    return config_file.exists() and bool(json.loads(config_file.read_text()).get("skills", {}).get("paths"))


# --- sync skills -----------------------------------------------------------------------------


def test_sync_skills_installs_but_never_touches_the_config(cli_runner, reviewer, store_dir, config_file):
    result = cli_runner.invoke(cli, ["sync", "skills", "--yes"])

    assert result.exit_code == 0, result.output
    assert (store_dir / "cdk-review" / "SKILL.md").exists()
    assert not config_file.exists()
    assert "Updated" not in result.output


def test_sync_skills_explains_why_the_folder_is_not_registered_and_what_to_do(cli_runner, reviewer):
    result = cli_runner.invoke(cli, ["sync", "skills"])

    assert "installed, but OpenCode will not load them yet" in result.output
    assert "skills.paths" in result.output
    assert "separate step" in result.output
    assert "Run:  idea-oc sync config" in result.output
    assert f"Why:  {DOCS_URL}" in result.output


def test_sync_skills_does_not_advise_once_registered(cli_runner, reviewer):
    cli_runner.invoke(cli, ["sync", "--yes"])

    result = cli_runner.invoke(cli, ["sync", "skills"])

    assert "idea-oc sync config" not in result.output


def test_combined_sync_does_not_duplicate_the_advice(cli_runner, reviewer):
    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert "idea-oc sync config" not in result.output
    assert "will not load them yet" not in result.output


# --- sync config -----------------------------------------------------------------------------


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)  # the fake must stay unused
def test_sync_config_updates_the_config_without_any_network_or_store(cli_runner, github, store_dir, config_file):
    result = cli_runner.invoke(cli, ["sync", "config", "--yes"])

    assert result.exit_code == 0, result.output
    assert registered(config_file)
    assert github.requests == []
    assert not store_dir.exists()


def test_sync_config_ignores_a_broken_registry(cli_runner, config_file, tmp_path):
    registry = tmp_path / "registry.toml"
    registry.write_text("bogus = 1\n")

    result = cli_runner.invoke(cli, ["--registry", str(registry), "sync", "config", "--yes"])

    assert result.exit_code == 0, result.output
    assert registered(config_file)


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)  # the fake must stay unused
def test_sync_config_when_already_registered_is_a_no_op(cli_runner, github):
    cli_runner.invoke(cli, ["sync", "config", "--yes"])

    result = cli_runner.invoke(cli, ["sync", "config"])

    assert result.exit_code == 0
    assert "Config is up to date." in result.output


def test_sync_config_can_be_declined(cli_runner, config_file):
    result = cli_runner.invoke(cli, ["sync", "config"], input="n\n")

    assert result.exit_code == 0
    assert "Not changed" in result.output
    assert not config_file.exists()


def test_sync_config_dry_run_writes_nothing_and_does_not_prompt(cli_runner, config_file):
    result = cli_runner.invoke(cli, ["sync", "config", "--dry-run"])

    assert result.exit_code == 0
    assert "Would create" in result.output
    assert "skills.paths" in result.output
    assert "Dry run, nothing written." in result.output
    assert not config_file.exists()


# --- both stages -----------------------------------------------------------------------------


def test_combined_sync_labels_each_stage(cli_runner, reviewer):
    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert result.output.index("--- skills ---") < result.output.index("--- config ---")


def test_single_stage_output_has_no_headings(cli_runner, reviewer):
    result = cli_runner.invoke(cli, ["sync", "skills"])

    assert "---" not in result.output


def test_failed_skills_stage_does_not_stop_the_config_stage(cli_runner, github, config_file):
    result = cli_runner.invoke(cli, ["sync", "--yes"])  # the reviewer repo does not exist in the fake

    assert result.exit_code == 1
    assert registered(config_file)


def test_broken_registry_fails_skills_but_config_still_runs(cli_runner, config_file, tmp_path):
    registry = tmp_path / "registry.toml"
    registry.write_text("bogus = 1\n")

    result = cli_runner.invoke(cli, ["--registry", str(registry), "sync", "--yes"])

    assert result.exit_code == 1
    assert "Invalid registry" in result.output
    assert registered(config_file)


def test_unknown_stage_is_a_usage_error(cli_runner):
    result = cli_runner.invoke(cli, ["sync", "everything"])

    assert result.exit_code == 2
    assert "skills" in result.output and "config" in result.output


# --- status ----------------------------------------------------------------------------------


@pytest.fixture
def synced(cli_runner, reviewer):
    assert cli_runner.invoke(cli, ["sync", "--yes"]).exit_code == 0
    reviewer.requests.clear()
    return reviewer


def test_status_skills_ignores_the_config(cli_runner, synced, config_file):
    config_file.write_text("{}")

    result = cli_runner.invoke(cli, ["status", "skills"])

    assert result.exit_code == 0
    assert "Config:" not in result.output
    assert "Skills:  2 approved, 0 need syncing" in result.output


def test_status_config_ignores_the_skills_and_needs_no_network(cli_runner, synced, store_dir):
    (store_dir / "cdk-review" / "SKILL.md").chmod(0o644)
    (store_dir / "cdk-review" / "SKILL.md").write_text("tampered")

    result = cli_runner.invoke(cli, ["status", "config"])

    assert result.exit_code == 0
    assert "Config:  ok" in result.output
    assert "Skills:" not in result.output
    assert synced.requests == []


def test_status_config_reports_a_missing_registration(cli_runner, synced, config_file):
    config_file.write_text("{}")

    result = cli_runner.invoke(cli, ["status", "config"])

    assert result.exit_code == 1
    assert "run: idea-oc sync config" in result.output


def test_status_reports_both_and_exits_1_if_either_has_a_problem(cli_runner, synced, config_file):
    config_file.write_text("{}")

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "Skills:  2 approved, 0 need syncing" in result.output
    assert "differences from the team's preferred config" in result.output


def test_status_skills_failure_does_not_hide_the_config_result(cli_runner, config_file, tmp_path):
    registry = tmp_path / "registry.toml"
    registry.write_text("bogus = 1\n")

    result = cli_runner.invoke(cli, ["--registry", str(registry), "status"])

    assert result.exit_code == 1
    assert "Invalid registry" in result.output
    assert "Config:" in result.output
