"""End-to-end tests for ``idea-oc sync`` through the CLI."""

import json
import os
from pathlib import Path

import pytest

from idea_oc.cli import cli
from tests.conftest import skill_md

REVIEWER = "co-cddo/gds-idea-ai-reviewer"  # the repo in the bundled registry
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
    files[f"{ROOT}/__init__.py"] = ""
    github.add_repo(REVIEWER, files, tag="v0.1.22")
    return github


def test_first_sync_installs_registers_and_reports(cli_runner, reviewer, store_dir, config_file):
    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert result.exit_code == 0, result.output
    assert f"{REVIEWER}  v0.1.22" in result.output
    assert "+ cdk-review" in result.output
    assert "+ readme-review" in result.output
    assert "2 installed, 0 updated, 0 removed." in result.output
    assert "Registered." in result.output
    assert "Restart OpenCode" in result.output
    assert (store_dir / "cdk-review" / "SKILL.md").exists()
    assert json.loads(config_file.read_text())["skills"]["paths"] == ["~/.local/share/idea-oc/skills"]


def test_second_sync_is_a_quiet_no_op(cli_runner, reviewer):
    cli_runner.invoke(cli, ["sync", "--yes"])
    reviewer.requests.clear()

    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert result.exit_code == 0
    assert "Everything is up to date (2 skills)." in result.output
    assert "Restart OpenCode" not in result.output
    assert "Registered." not in result.output
    assert reviewer.blob_requests() == []


def test_prompt_can_be_declined_and_shows_the_snippet(cli_runner, reviewer, config_file):
    result = cli_runner.invoke(cli, ["sync"], input="n\n")

    assert result.exit_code == 0
    assert "Not changed" in result.output
    assert '"paths"' in result.output
    assert not config_file.exists()


def test_prompt_can_be_accepted(cli_runner, reviewer, config_file):
    result = cli_runner.invoke(cli, ["sync"], input="y\n")

    assert "Registered." in result.output
    assert config_file.exists()


def test_non_interactive_without_yes_leaves_config_alone(cli_runner, reviewer, config_file):
    result = cli_runner.invoke(cli, ["sync"], input="")

    assert result.exit_code == 0
    assert "Not changed" in result.output
    assert not config_file.exists()


def test_commented_config_is_updated_and_its_comments_kept(cli_runner, reviewer, config_file):
    config_file.parent.mkdir(parents=True)
    config_file.write_text('{\n  // hi\n  "model": "m" // keep\n}\n')

    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert result.exit_code == 0, result.output
    text = config_file.read_text()
    assert "// hi" in text and "// keep" in text
    assert '"model": "m", // keep' in text
    assert "skills" in text


def test_unparseable_config_is_not_rewritten_and_shows_the_snippet(cli_runner, reviewer, config_file):
    config_file.parent.mkdir(parents=True)
    config_file.write_text('{ "model": ')

    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert result.exit_code == 0
    assert "cannot edit" in result.output
    assert "Add this yourself" in result.output
    assert config_file.read_text() == '{ "model": '


def test_dry_run_writes_nothing_and_does_not_prompt(cli_runner, reviewer, store_dir, config_file):
    result = cli_runner.invoke(cli, ["sync", "--dry-run"])

    assert result.exit_code == 0
    assert "Would install to" in result.output
    assert "Dry run, nothing written: 2 installed" in result.output
    assert "Would ask to register" in result.output
    assert "Registered." not in result.output
    assert not store_dir.exists()
    assert not config_file.exists()


def test_new_upstream_skill_appears_and_removed_one_is_pruned(cli_runner, reviewer, store_dir):
    cli_runner.invoke(cli, ["sync", "--yes"])
    files = {f"{ROOT}/{n}/SKILL.md": skill_md(n) for n in ("cdk-review", "fresh")}
    reviewer.add_repo(REVIEWER, files, tag="v0.1.23")

    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert "+ fresh" in result.output
    assert "- readme-review" in result.output
    assert "1 installed, 0 updated, 1 removed." in result.output
    assert not (store_dir / "readme-review").exists()


def test_no_prune_flag_keeps_removed_skills(cli_runner, reviewer, store_dir):
    cli_runner.invoke(cli, ["sync", "--yes"])
    reviewer.add_repo(REVIEWER, {f"{ROOT}/cdk-review/SKILL.md": skill_md("cdk-review")}, tag="v0.1.23")

    result = cli_runner.invoke(cli, ["sync", "--yes", "--no-prune"])

    assert "- readme-review" not in result.output
    assert (store_dir / "readme-review").exists()


def test_source_failure_exits_non_zero_and_names_the_source(cli_runner, github, store_dir):
    result = cli_runner.invoke(cli, ["sync", "--yes"])  # reviewer repo does not exist in the fake

    assert result.exit_code == 1
    assert REVIEWER in result.output
    assert "Some skills could not be synced" in result.output


def test_unreachable_source_does_not_delete_installed_skills(cli_runner, reviewer, store_dir):
    cli_runner.invoke(cli, ["sync", "--yes"])
    del reviewer.repos[REVIEWER]

    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert result.exit_code == 1
    assert (store_dir / "cdk-review" / "SKILL.md").exists()


def test_custom_registry_with_several_sources(cli_runner, github, store_dir, tmp_path):
    github.add_repo("co-cddo/one", {"skills/a/SKILL.md": skill_md("a"), "skills/b/SKILL.md": skill_md("b")})
    github.add_repo("co-cddo/two", {"docs/c/SKILL.md": skill_md("c")})
    registry = tmp_path / "registry.toml"
    registry.write_text(
        '[[source]]\nrepo = "co-cddo/one"\nskills = ["skills/a", "skills/b"]\n'
        '[[source]]\nrepo = "co-cddo/two"\nskills = ["docs/c/SKILL.md"]\n'
    )

    result = cli_runner.invoke(cli, ["--registry", str(registry), "sync", "--yes"])

    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in store_dir.iterdir() if not p.name.startswith(".")) == ["a", "b", "c"]


def test_invalid_registry_is_a_clean_error(cli_runner, tmp_path):
    registry = tmp_path / "registry.toml"
    registry.write_text("bogus = 1\n")

    result = cli_runner.invoke(cli, ["--registry", str(registry), "sync"])

    assert result.exit_code == 1
    assert "Invalid registry" in result.output
    assert "Traceback" not in result.output


def test_duplicate_names_across_sources_abort_before_installing(cli_runner, github, store_dir, tmp_path):
    github.add_repo("co-cddo/one", {"skills/same/SKILL.md": skill_md("same")})
    github.add_repo("co-cddo/two", {"skills/same/SKILL.md": skill_md("same")})
    registry = tmp_path / "registry.toml"
    registry.write_text(
        '[[source]]\nrepo = "co-cddo/one"\nskills = ["skills/same"]\n'
        '[[source]]\nrepo = "co-cddo/two"\nskills = ["skills/same"]\n'
    )

    result = cli_runner.invoke(cli, ["--registry", str(registry), "sync", "--yes"])

    assert result.exit_code == 1
    assert "provided twice" in result.output
    assert not store_dir.exists()
