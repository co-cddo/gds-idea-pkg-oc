"""Tests for the skill planner."""

import pytest

from idea_oc.github import TreeEntry
from idea_oc.models import Source
from idea_oc.planner import (
    PlanError,
    PlannedSkill,
    SkillFile,
    check_unique_names,
    plan_source,
    validate_skill_md,
    validate_skill_name,
)


def tree(*paths: str, folders: tuple[str, ...] = (), modes: dict[str, str] | None = None) -> list[TreeEntry]:
    """Build a tree listing from blob paths, inferring parent folders."""
    modes = modes or {}
    all_folders = set(folders)
    for path in paths:
        parts = path.split("/")
        all_folders.update("/".join(parts[:i]) for i in range(1, len(parts)))
    entries = [TreeEntry(f, "040000", "tree", "f" * 40) for f in sorted(all_folders)]
    entries += [TreeEntry(p, modes.get(p, "100644"), "blob", f"{i:040x}") for i, p in enumerate(paths)]
    return entries


def discover(root="skills", **kwargs) -> Source:
    return Source(repo="co-cddo/x", discover=root, **kwargs)


def test_discover_finds_every_skill_folder():
    t = tree("skills/a/SKILL.md", "skills/b/SKILL.md", "skills/b/references/r.md", "skills/__init__.py")

    skills = plan_source(discover(), t)

    assert [s.name for s in skills] == ["a", "b"]
    assert [f.rel_path for f in skills[1].files] == ["SKILL.md", "references/r.md"]
    assert skills[0].source_path == "skills/a"


def test_discover_picks_up_skills_added_later():
    before = plan_source(discover(), tree("skills/a/SKILL.md"))
    after = plan_source(discover(), tree("skills/a/SKILL.md", "skills/new-one/SKILL.md"))

    assert [s.name for s in before] == ["a"]
    assert [s.name for s in after] == ["a", "new-one"]


def test_discover_ignores_folders_without_skill_md_and_nested_skills():
    t = tree("skills/a/SKILL.md", "skills/notes/readme.md", "skills/a/deep/other/SKILL.md")

    skills = plan_source(discover(), t)

    assert [s.name for s in skills] == ["a"]
    assert "deep/other/SKILL.md" in [f.rel_path for f in skills[0].files]


def test_discover_exclude():
    t = tree("skills/a/SKILL.md", "skills/draft/SKILL.md")

    skills = plan_source(discover(exclude=["draft"]), t)

    assert [s.name for s in skills] == ["a"]


def test_discover_nested_root():
    t = tree("src/pkg/skills/a/SKILL.md", "src/pkg/other.py")

    skills = plan_source(discover("src/pkg/skills"), t)

    assert [(s.name, s.source_path) for s in skills] == [("a", "src/pkg/skills/a")]


def test_discover_missing_folder():
    with pytest.raises(PlanError, match="does not exist"):
        plan_source(discover("nope"), tree("skills/a/SKILL.md"))


def test_discover_rejects_invalid_skill_name():
    with pytest.raises(PlanError, match="Invalid skill name"):
        plan_source(discover(), tree("skills/Bad_Name/SKILL.md"))


def test_multiple_named_skills_from_one_repo():
    t = tree("skills/a/SKILL.md", "skills/a/scripts/run.sh", "skills/b/SKILL.md", "skills/c/SKILL.md")
    source = Source(repo="co-cddo/x", skills=["skills/b", "skills/a"])

    skills = plan_source(source, t)

    assert [s.name for s in skills] == ["a", "b"]
    assert [f.rel_path for f in skills[0].files] == ["SKILL.md", "scripts/run.sh"]


def test_single_file_skill_installs_only_skill_md():
    t = tree("docs/pr-style/SKILL.md", "docs/pr-style/extra.md")
    source = Source(repo="co-cddo/x", skills=["docs/pr-style/SKILL.md"])

    [skill] = plan_source(source, t)

    assert skill.name == "pr-style"
    assert [f.rel_path for f in skill.files] == ["SKILL.md"]


def test_single_file_at_repo_root_has_no_name():
    source = Source(repo="co-cddo/x", skills=["SKILL.md"])

    with pytest.raises(PlanError, match="derive a skill name"):
        plan_source(source, tree("SKILL.md"))


def test_file_not_named_skill_md_is_rejected():
    source = Source(repo="co-cddo/x", skills=["docs/readme.md"])

    with pytest.raises(PlanError, match="not named SKILL.md"):
        plan_source(source, tree("docs/readme.md"))


def test_missing_path_is_rejected():
    source = Source(repo="co-cddo/x", skills=["skills/gone"])

    with pytest.raises(PlanError, match="does not exist"):
        plan_source(source, tree("skills/a/SKILL.md"))


def test_folder_without_skill_md_is_rejected():
    source = Source(repo="co-cddo/x", skills=["skills/a"])

    with pytest.raises(PlanError, match="has no SKILL.md"):
        plan_source(source, tree("skills/a/readme.md"))


def test_executable_bit_is_preserved():
    t = tree("skills/a/SKILL.md", "skills/a/run.sh", modes={"skills/a/run.sh": "100755"})

    [skill] = plan_source(discover(), t)

    assert {f.rel_path: f.executable for f in skill.files} == {"SKILL.md": False, "run.sh": True}


def test_symlink_inside_skill_is_rejected():
    t = tree("skills/a/SKILL.md", "skills/a/link", modes={"skills/a/link": "120000"})

    with pytest.raises(PlanError, match="symlink"):
        plan_source(discover(), t)


def test_blob_shas_come_from_the_tree():
    t = tree("skills/a/SKILL.md")

    [skill] = plan_source(discover(), t)

    assert skill.files[0] == SkillFile("SKILL.md", t[-1].sha)


def test_duplicate_names_across_sources_are_rejected():
    a = PlannedSkill("same", "co-cddo/one", "skills/same", ())
    b = PlannedSkill("same", "co-cddo/two", "x/same", ())

    with pytest.raises(PlanError, match="provided twice.*co-cddo/one.*co-cddo/two"):
        check_unique_names([a, b])


def test_unique_names_pass():
    check_unique_names([PlannedSkill("a", "r", "p", ()), PlannedSkill("b", "r", "p", ())])


@pytest.mark.parametrize("name", ["a", "cdk-review", "python3", "a-b-c"])
def test_valid_skill_names(name):
    validate_skill_name(name)


@pytest.mark.parametrize("name", ["", "A", "a_b", "-a", "a-", "a--b", "a b", "x" * 65])
def test_invalid_skill_names(name):
    with pytest.raises(PlanError):
        validate_skill_name(name)


def test_skill_md_valid():
    validate_skill_md(
        "cdk-review", b"---\nname: cdk-review\ndescription: Review: CDK code\nmetadata:\n  k: v\n---\nBody\n"
    )


def test_skill_md_accepts_quoted_values():
    validate_skill_md("a", b"---\nname: 'a'\ndescription: \"d\"\n---\n")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"no frontmatter", "no frontmatter"),
        (b"---\nname: a\ndescription: d\n", "not closed"),
        (b"---\nname: other\ndescription: d\n---\n", "expected 'a'"),
        (b"---\ndescription: d\n---\n", "expected 'a'"),
        (b"---\nname: a\n---\n", "no description"),
        (b"---\nname: a\nmetadata:\n  description: nested\n---\n", "no description"),
    ],
)
def test_skill_md_invalid(content, message):
    with pytest.raises(PlanError, match=message):
        validate_skill_md("a", content)
