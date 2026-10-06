"""Tests for planning and applying a sync."""

import pytest

from idea_oc.github import GitHubClient
from idea_oc.models import Registry, Source
from idea_oc.planner import PlanError
from idea_oc.registry import load_registry
from idea_oc.store import Store, default_store_dir
from idea_oc.sync import Action, apply_plans, plan_registry
from tests.conftest import skill_md

REVIEWER = "co-cddo/reviewer"
KIT = "co-cddo/kit"


@pytest.fixture
def client(github):
    with GitHubClient(token="t") as c:
        yield c


@pytest.fixture
def store():
    return Store(default_store_dir())


def registry(*sources: Source) -> Registry:
    return Registry(source=list(sources))


def reviewer_files(*names: str, **extra: str) -> dict[str, str]:
    files = {f"skills/{n}/SKILL.md": skill_md(n) for n in names}
    files.update(extra)
    return files


def sync(client, store, reg, **kwargs):
    return apply_plans(client, store, plan_registry(client, reg), **kwargs)


def test_first_sync_installs_everything_discovered(github, client, store):
    github.add_repo(REVIEWER, reviewer_files("a", "b", **{"skills/a/references/r.md": "ref"}))

    result = sync(client, store, registry(Source(repo=REVIEWER, discover="skills")))

    assert result.ok
    assert [(o.name, o.action) for o in result.outcomes] == [("a", Action.ADDED), ("b", Action.ADDED)]
    assert (store.root / "a" / "references" / "r.md").read_text() == "ref"
    assert store.installed()["a"].ref == "v1.0.0"


def test_second_sync_downloads_no_blobs(github, client, store):
    github.add_repo(REVIEWER, reviewer_files("a", "b"))
    reg = registry(Source(repo=REVIEWER, discover="skills"))
    sync(client, store, reg)
    github.requests.clear()

    result = sync(client, store, reg)

    assert result.count(Action.UNCHANGED) == 2
    assert github.blob_requests() == []


def test_new_upstream_skill_is_picked_up_without_registry_change(github, client, store):
    reg = registry(Source(repo=REVIEWER, discover="skills"))
    github.add_repo(REVIEWER, reviewer_files("a"))
    sync(client, store, reg)
    github.add_repo(REVIEWER, reviewer_files("a", "brand-new"), tag="v1.1.0")

    result = sync(client, store, reg)

    assert {o.name: o.action for o in result.outcomes} == {"a": Action.UNCHANGED, "brand-new": Action.ADDED}
    assert store.installed()["brand-new"].ref == "v1.1.0"


def test_changed_skill_is_updated_and_only_its_files_downloaded(github, client, store):
    reg = registry(Source(repo=REVIEWER, discover="skills"))
    github.add_repo(REVIEWER, reviewer_files("a", "b"))
    sync(client, store, reg)
    github.add_repo(REVIEWER, {**reviewer_files("a", "b"), "skills/a/SKILL.md": skill_md("a", body="new")}, tag="v2")
    github.requests.clear()

    result = sync(client, store, reg)

    assert {o.name: o.action for o in result.outcomes} == {"a": Action.UPDATED, "b": Action.UNCHANGED}
    assert len(github.blob_requests()) == 1
    assert "new" in (store.root / "a" / "SKILL.md").read_text()


def test_dry_run_reports_but_writes_nothing(github, client, store):
    github.add_repo(REVIEWER, reviewer_files("a"))

    result = sync(client, store, registry(Source(repo=REVIEWER, discover="skills")), dry_run=True)

    assert result.count(Action.ADDED) == 1
    assert not store.root.exists()
    assert github.blob_requests() == []


def test_multiple_sources_including_single_file_and_named_folders(github, client, store):
    github.add_repo(REVIEWER, reviewer_files("a"))
    github.add_repo(
        KIT,
        {
            "skills/one/SKILL.md": skill_md("one"),
            "skills/two/SKILL.md": skill_md("two"),
            "skills/two/scripts/run.sh": "#!/bin/sh",
            "docs/solo/SKILL.md": skill_md("solo"),
            "skills/unlisted/SKILL.md": skill_md("unlisted"),
        },
        modes={"skills/two/scripts/run.sh": "100755"},
    )
    reg = registry(
        Source(repo=REVIEWER, discover="skills"),
        Source(repo=KIT, skills=["skills/one", "skills/two", "docs/solo/SKILL.md"]),
    )

    result = sync(client, store, reg)

    assert sorted(o.name for o in result.outcomes) == ["a", "one", "solo", "two"]
    assert not (store.root / "unlisted").exists()
    assert (store.root / "two" / "scripts" / "run.sh").stat().st_mode & 0o111


def test_duplicate_skill_names_across_sources_fail_planning(github, client):
    github.add_repo(REVIEWER, reviewer_files("same"))
    github.add_repo(KIT, {"skills/same/SKILL.md": skill_md("same")})
    reg = registry(Source(repo=REVIEWER, discover="skills"), Source(repo=KIT, skills=["skills/same"]))

    with pytest.raises(PlanError, match="provided twice"):
        plan_registry(client, reg)


def test_removed_upstream_skill_is_pruned(github, client, store):
    reg = registry(Source(repo=REVIEWER, discover="skills"))
    github.add_repo(REVIEWER, reviewer_files("a", "b"))
    sync(client, store, reg)
    github.add_repo(REVIEWER, reviewer_files("a"), tag="v2")

    result = sync(client, store, reg)

    assert result.removed == ["b"]
    assert not (store.root / "b").exists()
    assert "b" not in store.installed()


def test_prune_dry_run_only_reports(github, client, store):
    reg = registry(Source(repo=REVIEWER, discover="skills"))
    github.add_repo(REVIEWER, reviewer_files("a", "b"))
    sync(client, store, reg)
    github.add_repo(REVIEWER, reviewer_files("a"), tag="v2")

    result = sync(client, store, reg, dry_run=True)

    assert result.removed == ["b"]
    assert (store.root / "b").exists()


def test_no_prune_keeps_old_skills(github, client, store):
    reg = registry(Source(repo=REVIEWER, discover="skills"))
    github.add_repo(REVIEWER, reviewer_files("a", "b"))
    sync(client, store, reg)
    github.add_repo(REVIEWER, reviewer_files("a"), tag="v2")

    result = sync(client, store, reg, prune=False)

    assert result.removed == []
    assert (store.root / "b").exists()


def test_a_failing_source_never_triggers_pruning_of_its_skills(github, client, store):
    github.add_repo(REVIEWER, reviewer_files("a"))
    github.add_repo(KIT, {"skills/k/SKILL.md": skill_md("k")})
    reg = registry(Source(repo=REVIEWER, discover="skills"), Source(repo=KIT, skills=["skills/k"]))
    sync(client, store, reg)
    del github.repos[KIT]  # kit becomes unreachable

    result = sync(client, store, reg)

    assert not result.ok
    assert result.removed == []
    assert (store.root / "k" / "SKILL.md").exists()
    assert result.count(Action.UNCHANGED) == 1  # the healthy source still synced


def test_bad_source_reports_error_but_others_install(github, client, store):
    github.add_repo(REVIEWER, reviewer_files("a"))
    reg = registry(Source(repo=REVIEWER, discover="skills"), Source(repo=KIT, discover="skills"))

    result = sync(client, store, reg)

    assert not result.ok
    assert any(KIT in e for e in result.errors)
    assert (store.root / "a" / "SKILL.md").exists()


def test_skill_with_mismatched_frontmatter_is_not_installed(github, client, store):
    github.add_repo(REVIEWER, {"skills/a/SKILL.md": skill_md("other-name"), "skills/b/SKILL.md": skill_md("b")})

    result = sync(client, store, registry(Source(repo=REVIEWER, discover="skills")))

    assert not result.ok
    assert "expected 'a'" in result.errors[0]
    assert not (store.root / "a").exists()
    assert (store.root / "b" / "SKILL.md").exists()


def test_repo_without_releases_falls_back_to_default_branch(github, client, store):
    github.add_repo(REVIEWER, reviewer_files("a"), tag=None)

    result = sync(client, store, registry(Source(repo=REVIEWER, discover="skills")))

    assert result.ok
    assert result.plans[0].resolved.floating is True
    assert store.installed()["a"].ref == "main"


def test_failed_install_keeps_the_previous_version(github, client, store, monkeypatch):
    reg = registry(Source(repo=REVIEWER, discover="skills"))
    github.add_repo(REVIEWER, reviewer_files("a"))
    sync(client, store, reg)
    github.add_repo(REVIEWER, {"skills/a/SKILL.md": skill_md("a", body="v2")}, tag="v2")
    monkeypatch.setattr(GitHubClient, "get_blob", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))

    result = sync(client, store, reg)

    assert not result.ok
    assert "Body" in (store.root / "a" / "SKILL.md").read_text()


def test_the_bundled_registry_plans_cleanly_with_unique_skill_names(github, client):
    """Every approved source together must install without a name clash."""
    github.add_repo(
        "co-cddo/gds-idea-ai-reviewer",
        {f"src/ai_reviewer/skills/{n}/SKILL.md": skill_md(n) for n in ("cdk-review", "readme-review")},
    )
    github.add_repo("co-cddo/gds-idea-app-kit", {"skills/idea-app-usage/SKILL.md": skill_md("idea-app-usage")})
    github.add_repo("co-cddo/gds-idea-gh-kit", {"skills/idea-gh-usage/SKILL.md": skill_md("idea-gh-usage")})

    plans = plan_registry(client, load_registry())

    assert all(plan.error is None for plan in plans)
    names = sorted(skill.name for plan in plans for skill in plan.skills)
    assert names == ["cdk-review", "idea-app-usage", "idea-gh-usage", "readme-review"]


def test_a_kit_release_without_its_skill_fails_that_source_only(github, client, store):
    """Before a kit's release contains the skill, syncing reports it and still installs the others."""
    github.add_repo("co-cddo/gds-idea-ai-reviewer", {"src/ai_reviewer/skills/a/SKILL.md": skill_md("a")})
    github.add_repo("co-cddo/gds-idea-app-kit", {"README.md": "no skills folder in this release yet"})
    github.add_repo("co-cddo/gds-idea-gh-kit", {"skills/idea-gh-usage/SKILL.md": skill_md("idea-gh-usage")})

    result = apply_plans(client, store, plan_registry(client, load_registry()))

    assert not result.ok
    assert any("gds-idea-app-kit" in error and "does not exist" in error for error in result.errors)
    assert (store.root / "a" / "SKILL.md").exists()
    assert (store.root / "idea-gh-usage" / "SKILL.md").exists()


def test_a_source_error_starts_with_its_repo_without_repeating_it(github, client):
    github.add_repo(KIT, {"README.md": "no skills here"})
    planner_error = plan_registry(client, registry(Source(repo=KIT, skills=["skills/gone"])))[0]
    github_error = plan_registry(client, registry(Source(repo="co-cddo/not-there", skills=["skills/x"])))[0]

    assert planner_error.message == f"{KIT}: 'skills/gone' does not exist"
    assert github_error.message.startswith("co-cddo/not-there: Not found on GitHub")
    assert not github_error.message.startswith("co-cddo/not-there: co-cddo/not-there")
