"""Tests for ``idea-oc status`` and the shadowing scan."""

import json
import os
from pathlib import Path

import pytest

from idea_oc.cli import cli
from idea_oc.status import find_shadowed
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
def home():
    return Path(os.environ["HOME"])


@pytest.fixture
def reviewer(github, reviewer_only):
    files = {f"{ROOT}/{n}/SKILL.md": skill_md(n) for n in ("cdk-review", "readme-review")}
    github.add_repo(REVIEWER, files, tag="v0.1.22")
    return github


@pytest.fixture
def synced(cli_runner, reviewer):
    assert cli_runner.invoke(cli, ["sync", "--yes"]).exit_code == 0
    reviewer.requests.clear()
    return reviewer


def write_skill(folder: Path, name: str) -> Path:
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(skill_md(name))
    return folder


def test_status_is_clean_after_sync_and_downloads_nothing(cli_runner, synced):
    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 0, result.output
    assert "Config:  ok" in result.output
    assert "Skills:  2 approved, 0 need syncing" in result.output
    assert synced.blob_requests() == []


def test_status_before_first_sync_reports_everything_missing(cli_runner, reviewer):
    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "differences from the team's preferred config" in result.output
    assert "skills.paths" in result.output
    assert "Skills:  2 approved, 2 need syncing" in result.output
    assert "cdk-review" in result.output
    assert "not installed" in result.output


def test_locally_edited_file_is_reported_as_drift(cli_runner, synced, store_dir):
    edited = store_dir / "cdk-review" / "SKILL.md"
    edited.chmod(0o644)
    edited.write_text("tampered")

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "cdk-review" in result.output
    assert "1 changed locally" in result.output


def test_extra_and_missing_files_are_reported(cli_runner, synced, store_dir):
    (store_dir / "cdk-review" / "notes.md").write_text("mine")
    (store_dir / "readme-review" / "SKILL.md").unlink()

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "1 extra locally" in result.output
    assert "1 missing locally" in result.output


def test_stale_store_folder_is_reported(cli_runner, synced, store_dir):
    (store_dir / "old-skill").mkdir()

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "Stale" in result.output
    assert "old-skill" in result.output


def test_removed_config_entry_is_reported(cli_runner, synced, config_file):
    config_file.write_text("{}")

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "differences from the team's preferred config" in result.output
    assert "skills.paths" in result.output


def test_commented_config_is_read_correctly(cli_runner, synced, config_file):
    config_file.write_text(config_file.read_text().replace("{", "{ // a comment", 1))

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "Config:  ok" in result.output


def test_unreadable_config_is_reported(cli_runner, synced, config_file):
    config_file.write_text("{ not json")

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 1
    assert "could not be read" in result.output


def test_personal_skill_with_same_name_is_reported_but_is_not_a_problem(cli_runner, synced, config_file):
    personal = write_skill(config_file.parent / "skills" / "readme-review", "readme-review")

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "Shadowing" in result.output
    assert "readme-review" in result.output.split("Shadowing")[1]
    assert personal.name in result.output


def test_unrelated_personal_skills_are_not_reported(cli_runner, synced, config_file, home):
    write_skill(config_file.parent / "skills" / "mine", "mine")
    write_skill(home / ".claude" / "skills" / "other", "other")

    result = cli_runner.invoke(cli, ["status"])

    assert "Shadowing" not in result.output


def test_quiet_prints_nothing_when_healthy(cli_runner, synced, config_file):
    write_skill(config_file.parent / "skills" / "readme-review", "readme-review")

    result = cli_runner.invoke(cli, ["status", "--quiet"])

    assert result.exit_code == 0
    assert result.output == ""


def test_quiet_still_prints_problems(cli_runner, synced, store_dir):
    (store_dir / "old-skill").mkdir()

    result = cli_runner.invoke(cli, ["status", "--quiet"])

    assert result.exit_code == 1
    assert "old-skill" in result.output
    assert "Config:  ok" not in result.output


def test_unreachable_source_warns_without_claiming_drift_or_stale(cli_runner, synced, store_dir):
    del synced.repos[REVIEWER]

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "Could not check upstream" in result.output
    assert "Stale" not in result.output
    assert (store_dir / "cdk-review").exists()


def test_find_shadowed_matches_on_declared_name_not_folder_name(tmp_path):
    write_skill(tmp_path / "personal" / "my-copy", "readme-review")

    found = find_shadowed({"readme-review"}, [tmp_path / "personal"], ignore=tmp_path / "store")

    assert [(s.name, s.path.name) for s in found] == [("readme-review", "my-copy")]


def test_find_shadowed_skips_the_store_even_when_nested_in_a_personal_folder(tmp_path):
    personal = tmp_path / "personal"
    write_skill(personal / "store" / "readme-review", "readme-review")

    assert find_shadowed({"readme-review"}, [personal], ignore=personal / "store") == []


def test_find_shadowed_tolerates_missing_folders_and_broken_skills(tmp_path):
    broken = tmp_path / "personal" / "broken"
    broken.mkdir(parents=True)
    (broken / "SKILL.md").write_text("no frontmatter")

    assert find_shadowed({"x"}, [tmp_path / "nope", tmp_path / "personal"], ignore=tmp_path / "s") == []


def test_find_shadowed_follows_symlinked_skill_folders(tmp_path):
    real = write_skill(tmp_path / "clone" / "readme-review", "readme-review")
    personal = tmp_path / "personal"
    personal.mkdir()
    (personal / "readme-review").symlink_to(real, target_is_directory=True)

    found = find_shadowed({"readme-review"}, [personal], ignore=tmp_path / "s")

    assert [s.name for s in found] == ["readme-review"]


def test_config_written_by_sync_is_what_status_expects(cli_runner, synced, config_file):
    assert json.loads(config_file.read_text())["skills"]["paths"]
    assert cli_runner.invoke(cli, ["status"]).exit_code == 0
