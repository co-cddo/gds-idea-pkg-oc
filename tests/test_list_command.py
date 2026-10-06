"""Tests for ``idea-oc list``."""

from idea_oc.cli import cli
from tests.conftest import skill_md

REVIEWER = "co-cddo/gds-idea-ai-reviewer"


def test_list_before_sync_points_at_sync(cli_runner):
    result = cli_runner.invoke(cli, ["list"])

    assert result.exit_code == 0
    assert "No skills installed. Run: idea-oc sync" in result.output
    assert f"{REVIEWER}  latest  (discover src/ai_reviewer/skills)" in result.output


def test_list_shows_installed_skills_with_source_and_version(cli_runner, github):
    files = {f"src/ai_reviewer/skills/{n}/SKILL.md": skill_md(n) for n in ("cdk-review", "readme-review")}
    github.add_repo(REVIEWER, files, tag="v0.1.22")
    cli_runner.invoke(cli, ["sync", "--yes"])
    github.requests.clear()

    result = cli_runner.invoke(cli, ["list"])

    assert result.exit_code == 0
    assert f"cdk-review     {REVIEWER}  v0.1.22  (" in result.output
    assert f"readme-review  {REVIEWER}  v0.1.22  (" in result.output
    assert github.requests == []  # list works offline


def test_list_describes_named_skill_sources(cli_runner, tmp_path):
    registry = tmp_path / "registry.toml"
    registry.write_text('[[source]]\nrepo = "co-cddo/kit"\nskills = ["a", "b"]\nref = "v1"\n')

    result = cli_runner.invoke(cli, ["--registry", str(registry), "list"])

    assert "co-cddo/kit  v1  (2 named skill(s))" in result.output
