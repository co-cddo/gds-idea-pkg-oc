"""The local skill store: a directory owned entirely by idea-oc.

Layout::

    <store>/
      .manifest.json        where each installed skill came from
      <skill-name>/         one folder per skill, exactly as in the source repo
        SKILL.md
        ...

OpenCode is pointed at the store through ``skills.paths``, so personal skills
elsewhere are never touched. Change detection hashes the files on disk and
compares them to the git blob SHAs in the source tree, so no per-file state
is kept.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from idea_oc.github import git_blob_sha
from idea_oc.planner import PlannedSkill, SkillFile, validate_skill_name

MANIFEST_NAME = ".manifest.json"
STAGING_NAME = ".staging"
_READ_ONLY = 0o444
_READ_ONLY_EXECUTABLE = 0o555


class StoreError(Exception):
    """Raised when the store cannot be read or written safely."""


@dataclass(frozen=True)
class Provenance:
    """Where an installed skill came from.

    Attributes:
        repo: Source repository as ``owner/name``.
        source_path: Folder (or ``SKILL.md`` file) in the repo.
        ref: Resolved release tag or branch name.
        commit: Commit SHA the files were read from.
    """

    repo: str
    source_path: str
    ref: str
    commit: str


@dataclass(frozen=True)
class SkillDiff:
    """How an installed skill differs from what the source says it should be.

    Attributes:
        missing: Files that should exist but do not.
        changed: Files whose content or executable bit differs.
        extra: Files present locally that the source does not have.
    """

    missing: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    extra: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        return not (self.missing or self.changed or self.extra)

    @property
    def to_download(self) -> frozenset[str]:
        return frozenset(self.missing) | frozenset(self.changed)


def default_store_dir() -> Path:
    """Where the store lives: ``$IDEA_OC_STORE``, else the XDG data directory."""
    if override := os.environ.get("IDEA_OC_STORE"):
        return Path(override).expanduser()
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data_home / "idea-oc" / "skills"


def _is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def _local_files(folder: Path) -> set[str]:
    """Relative paths of every file (or symlink) under ``folder``."""
    return {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file() or p.is_symlink()}


def _matches(path: Path, expected: SkillFile) -> bool:
    """Whether the local file has the expected content and executable bit."""
    if path.is_symlink() or not path.is_file():
        return False
    return git_blob_sha(path.read_bytes()) == expected.sha and _is_executable(path) == expected.executable


class Store:
    """Reads and writes the skill store at ``root``."""

    def __init__(self, root: Path):
        self.root = root

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    def skill_dir(self, name: str) -> Path:
        validate_skill_name(name)
        return self.root / name

    def installed(self) -> dict[str, Provenance]:
        """Provenance of every installed skill. An unreadable manifest counts as empty."""
        try:
            raw = json.loads(self.manifest_path.read_text())
            return {name: Provenance(**fields) for name, fields in raw["skills"].items()}
        except (OSError, ValueError, KeyError, TypeError):
            return {}

    def _write_manifest(self, skills: dict[str, Provenance]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "skills": {name: asdict(p) for name, p in sorted(skills.items())}}
        tmp = self.manifest_path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        tmp.replace(self.manifest_path)

    def diff(self, skill: PlannedSkill) -> SkillDiff:
        """Compare the installed copy of ``skill`` to the planned files by hash."""
        folder = self.skill_dir(skill.name)
        if not folder.is_dir():
            return SkillDiff(missing=tuple(f.rel_path for f in skill.files))

        wanted = {f.rel_path: f for f in skill.files}
        present = _local_files(folder)
        return SkillDiff(
            missing=tuple(sorted(wanted.keys() - present)),
            changed=tuple(sorted(p for p in wanted.keys() & present if not _matches(folder / p, wanted[p]))),
            extra=tuple(sorted(present - wanted.keys())),
        )

    def install(
        self,
        skill: PlannedSkill,
        provenance: Provenance,
        fetch: Callable[[SkillFile], bytes],
    ) -> SkillDiff:
        """Bring the installed copy of ``skill`` in line with the plan.

        Only files that differ are fetched. The new copy is built in a staging
        folder and swapped in, so a failed fetch leaves the existing copy intact.

        Args:
            skill: The skill to install.
            provenance: Where it came from, recorded in the manifest.
            fetch: Returns the verified content of a file.

        Returns:
            The diff that was applied. ``clean`` means no files were touched.
        """
        diff = self.diff(skill)
        if not diff.clean:
            self._replace(skill, diff, fetch)
        self._record(skill.name, provenance)
        return diff

    def _replace(self, skill: PlannedSkill, diff: SkillDiff, fetch: Callable[[SkillFile], bytes]) -> None:
        target = self.skill_dir(skill.name)
        staging = self.root / STAGING_NAME / f"{skill.name}.{os.getpid()}"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            for file in skill.files:
                source = fetch(file) if file.rel_path in diff.to_download else (target / file.rel_path).read_bytes()
                self._write_file(staging, file, source)
            self._swap(staging, target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _write_file(folder: Path, file: SkillFile, data: bytes) -> None:
        dest = folder / file.rel_path
        if not dest.resolve().is_relative_to(folder.resolve()):
            raise StoreError(f"Refusing to write outside the skill folder: {file.rel_path}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.chmod(_READ_ONLY_EXECUTABLE if file.executable else _READ_ONLY)

    @staticmethod
    def _swap(new: Path, target: Path) -> None:
        old = target.with_name(f".old-{target.name}")
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        new.rename(target)
        shutil.rmtree(old, ignore_errors=True)

    def _record(self, name: str, provenance: Provenance) -> None:
        skills = self.installed()
        if skills.get(name) != provenance:
            self._write_manifest({**skills, name: provenance})

    def stale(self, keep: set[str]) -> list[str]:
        """Names of skill folders in the store that are not in ``keep``."""
        if not self.root.is_dir():
            return []
        folders = {p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")}
        return sorted(folders - keep)

    def remove(self, name: str) -> None:
        """Delete an installed skill and its manifest entry."""
        shutil.rmtree(self.skill_dir(name), ignore_errors=True)
        skills = self.installed()
        if skills.pop(name, None) is not None:
            self._write_manifest(skills)
