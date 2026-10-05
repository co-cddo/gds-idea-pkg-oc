"""Work out which skills a registry source provides, from a repo's git tree.

This module is pure: it takes already-fetched tree listings and returns plans.
It performs no network or disk access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath

from idea_oc.github import TreeEntry
from idea_oc.models import Source

SKILL_FILE = "SKILL.md"
_NAME_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_MAX_NAME_LENGTH = 64
_SYMLINK_MODE = "120000"
_EXECUTABLE_MODE = "100755"


class PlanError(Exception):
    """Raised when a source cannot be turned into valid skills."""


@dataclass(frozen=True)
class SkillFile:
    """One file belonging to a skill.

    Attributes:
        rel_path: Path inside the skill folder (for example ``references/a.md``).
        sha: Git blob SHA of the content in the source repo.
        executable: Whether the file has the executable bit set.
    """

    rel_path: str
    sha: str
    executable: bool = False


@dataclass(frozen=True)
class PlannedSkill:
    """A skill to install.

    Attributes:
        name: Skill name, which is also its folder name.
        repo: Source repository as ``owner/name``.
        source_path: Folder (or ``SKILL.md`` file) in the repo the skill comes from.
        files: Every file to install, always including ``SKILL.md``.
    """

    name: str
    repo: str
    source_path: str
    files: tuple[SkillFile, ...]


def validate_skill_name(name: str) -> None:
    """Check ``name`` against OpenCode's skill naming rules.

    Raises:
        PlanError: If the name is not 1-64 lowercase alphanumerics separated by single hyphens.
    """
    if len(name) > _MAX_NAME_LENGTH or not _NAME_PATTERN.match(name):
        raise PlanError(f"Invalid skill name {name!r}: use lowercase letters, digits and single hyphens (max 64)")


def _frontmatter(name: str, content: bytes) -> dict[str, str]:
    """Parse the top-level ``key: value`` pairs of a ``SKILL.md`` frontmatter block."""
    lines = content.decode("utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        raise PlanError(f"Skill {name!r}: SKILL.md has no frontmatter")

    end = next((i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---"), None)
    if end is None:
        raise PlanError(f"Skill {name!r}: SKILL.md frontmatter is not closed")

    pairs = (line.partition(":") for line in lines[1:end] if not line.startswith((" ", "\t")))
    return {key.strip(): value.strip().strip("\"'") for key, sep, value in pairs if sep}


def validate_skill_md(name: str, content: bytes) -> None:
    """Check a ``SKILL.md`` has frontmatter whose ``name`` matches its folder.

    OpenCode silently ignores skills that fail these checks, so we fail loudly instead.

    Args:
        name: The folder name the skill will be installed under.
        content: Raw ``SKILL.md`` bytes.

    Raises:
        PlanError: If the frontmatter is missing, has no description, or names a different skill.
    """
    fields = _frontmatter(name, content)
    if fields.get("name") != name:
        raise PlanError(f"Skill {name!r}: SKILL.md frontmatter name is {fields.get('name')!r}, expected {name!r}")
    if not fields.get("description"):
        raise PlanError(f"Skill {name!r}: SKILL.md frontmatter has no description")


def _skill_file(rel_path: str, entry: TreeEntry, *, where: str) -> SkillFile:
    """Build a ``SkillFile`` from a tree entry, refusing symlinks."""
    if entry.mode == _SYMLINK_MODE:
        raise PlanError(f"{where}: {entry.path} is a symlink, which is not supported in skills")
    return SkillFile(rel_path, entry.sha, executable=entry.mode == _EXECUTABLE_MODE)


def _files_under(folder: str, blobs: dict[str, TreeEntry], *, where: str) -> tuple[SkillFile, ...]:
    """Every blob under ``folder``, as paths relative to it."""
    prefix = f"{folder}/"
    return tuple(
        _skill_file(path.removeprefix(prefix), entry, where=where)
        for path, entry in sorted(blobs.items())
        if path.startswith(prefix)
    )


def _discover_names(root: str, blobs: dict[str, TreeEntry]) -> set[str]:
    """Names of the immediate subfolders of ``root`` that contain a ``SKILL.md``."""
    root_parts = PurePosixPath(root).parts
    depth = len(root_parts)
    candidates = (PurePosixPath(path).parts for path in blobs)
    return {
        parts[depth]
        for parts in candidates
        if parts[:depth] == root_parts and len(parts) == depth + 2 and parts[-1] == SKILL_FILE
    }


def _plan_discover(source: Source, blobs: dict[str, TreeEntry], folders: set[str]) -> list[PlannedSkill]:
    root = source.discover or ""
    if root not in folders:
        raise PlanError(f"{source.repo}: discover folder {root!r} does not exist")

    planned = []
    for name in sorted(_discover_names(root, blobs) - set(source.exclude)):
        validate_skill_name(name)
        folder = f"{root}/{name}"
        planned.append(PlannedSkill(name, source.repo, folder, _files_under(folder, blobs, where=source.repo)))
    return planned


def _plan_single_file(path: str, repo: str, blobs: dict[str, TreeEntry]) -> PlannedSkill:
    if PurePosixPath(path).name != SKILL_FILE:
        raise PlanError(f"{repo}: {path!r} is a file but not named {SKILL_FILE}")
    name = PurePosixPath(path).parent.name
    if not name:
        raise PlanError(f"{repo}: cannot derive a skill name from {path!r}; put it in a folder")
    validate_skill_name(name)
    return PlannedSkill(name, repo, path, (_skill_file(SKILL_FILE, blobs[path], where=repo),))


def _plan_folder(path: str, repo: str, blobs: dict[str, TreeEntry]) -> PlannedSkill:
    if f"{path}/{SKILL_FILE}" not in blobs:
        raise PlanError(f"{repo}: {path!r} has no {SKILL_FILE}")
    name = PurePosixPath(path).name
    validate_skill_name(name)
    return PlannedSkill(name, repo, path, _files_under(path, blobs, where=repo))


def _plan_listed(source: Source, blobs: dict[str, TreeEntry], folders: set[str]) -> list[PlannedSkill]:
    planned = []
    for path in source.skills or []:
        if path in blobs:
            planned.append(_plan_single_file(path, source.repo, blobs))
        elif path in folders:
            planned.append(_plan_folder(path, source.repo, blobs))
        else:
            raise PlanError(f"{source.repo}: {path!r} does not exist")
    return planned


def plan_source(source: Source, tree: list[TreeEntry]) -> list[PlannedSkill]:
    """List the skills a source provides at the given tree.

    Args:
        source: The registry source.
        tree: Full recursive tree listing of the source repo at the resolved commit.

    Returns:
        The skills to install, ordered by name.

    Raises:
        PlanError: If a path is missing, a skill name is invalid, or a skill contains a symlink.
    """
    blobs = {e.path: e for e in tree if e.type == "blob"}
    folders = {e.path for e in tree if e.type == "tree"}
    plan = _plan_discover if source.discover is not None else _plan_listed
    return sorted(plan(source, blobs, folders), key=lambda skill: skill.name)


def check_unique_names(skills: list[PlannedSkill]) -> None:
    """Ensure no two planned skills share a name.

    Raises:
        PlanError: Naming both origins of the first clash.
    """
    seen: dict[str, PlannedSkill] = {}
    for skill in skills:
        if skill.name in seen:
            other = seen[skill.name]
            raise PlanError(
                f"Skill name {skill.name!r} is provided twice: "
                f"{other.repo}:{other.source_path} and {skill.repo}:{skill.source_path}"
            )
        seen[skill.name] = skill
