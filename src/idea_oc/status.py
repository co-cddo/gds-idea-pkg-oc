"""Compare the machine's skill setup with what the registry says it should be."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from idea_oc.github import GitHubClient
from idea_oc.models import Registry
from idea_oc.opencode_config import ConfigError, plan_config
from idea_oc.planner import SKILL_FILE, PlannedSkill, frontmatter_name
from idea_oc.store import SkillDiff, Store
from idea_oc.sync import plan_registry
from idea_oc.team_config import Change


@dataclass(frozen=True)
class SkillStatus:
    """How one approved skill compares with its installed copy.

    Attributes:
        name: Skill name.
        installed: Whether a folder for it exists in the store.
        diff: File-level differences from the source (clean means identical).
    """

    name: str
    installed: bool
    diff: SkillDiff

    @property
    def ok(self) -> bool:
        return self.installed and self.diff.clean

    @property
    def detail(self) -> str:
        if not self.installed:
            return "not installed"
        parts = [
            f"{len(files)} {label}"
            for files, label in (
                (self.diff.changed, "changed"),
                (self.diff.missing, "missing"),
                (self.diff.extra, "extra"),
            )
            if files
        ]
        return ", ".join(parts) + " locally"


@dataclass(frozen=True)
class Shadow:
    """A personal skill that a team skill of the same name overrides."""

    name: str
    path: Path


@dataclass
class SkillsReport:
    """What ``idea-oc status skills`` reports.

    Attributes:
        skills: Status of every approved skill that could be checked.
        stale: Store folders no source provides any more (only known when every source was checked).
        shadowed: Personal skills overridden by team skills.
        unchecked: Sources that could not be reached, so were not compared.
    """

    skills: list[SkillStatus] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    shadowed: list[Shadow] = field(default_factory=list)
    unchecked: list[str] = field(default_factory=list)

    @property
    def problems(self) -> bool:
        """True when something needs ``idea-oc sync skills``."""
        return any(not s.ok for s in self.skills) or bool(self.stale)


@dataclass
class ConfigReport:
    """What ``idea-oc status config`` reports.

    Attributes:
        changes: Differences between the user's config and the team's preferred config.
        warnings: Team rules that a rule in the user's own config stops from working.
        notes: Things that were left alone and why.
        exists: Whether the config file exists.
        error: Why the config could not be read, if it could not.
    """

    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    exists: bool = True
    error: str | None = None

    @property
    def problems(self) -> bool:
        """True when something needs ``idea-oc sync config``."""
        return bool(self.error or self.changes)


def personal_skill_dirs(config_path: Path) -> list[Path]:
    """Folders OpenCode loads personal skills from that load before the store."""
    config_dir = config_path.parent
    return [
        config_dir / "skills",
        config_dir / "skill",
        Path.home() / ".claude" / "skills",
        Path.home() / ".agents" / "skills",
    ]


def _skill_files(root: Path) -> Iterator[Path]:
    """Every ``SKILL.md`` under ``root``, following symlinked folders like OpenCode does."""
    for folder, _, files in os.walk(root, followlinks=True):
        if SKILL_FILE in files:
            yield Path(folder) / SKILL_FILE


def find_shadowed(names: set[str], dirs: list[Path], *, ignore: Path) -> list[Shadow]:
    """Personal skills whose declared name matches one of ``names``.

    Args:
        names: Names of team skills.
        dirs: Personal skill folders to search.
        ignore: A folder (the store) to skip even if it sits inside one of ``dirs``.
    """
    found = []
    for root in dirs:
        for skill_file in _skill_files(root) if root.is_dir() else ():
            if skill_file.is_relative_to(ignore):
                continue
            name = frontmatter_name(skill_file.read_bytes())
            if name in names:
                found.append(Shadow(name, skill_file.parent))
    return sorted(found, key=lambda s: (s.name, str(s.path)))


def _skill_status(store: Store, skill: PlannedSkill) -> SkillStatus:
    installed = store.skill_dir(skill.name).is_dir()
    return SkillStatus(skill.name, installed, store.diff(skill))


def check_skills(
    client: GitHubClient,
    registry: Registry,
    store: Store,
    personal_dirs: list[Path],
) -> SkillsReport:
    """Compare the store with the registry. Downloads nothing: it reads trees and hashes local files.

    Raises:
        PlanError: If two sources provide a skill with the same name.
    """
    plans = plan_registry(client, registry)
    skills = [_skill_status(store, skill) for plan in plans for skill in plan.skills]
    names = {s.name for s in skills} | set(store.installed())
    unchecked = [p.message for p in plans if p.message]

    return SkillsReport(
        skills=skills,
        stale=[] if unchecked else store.stale({s.name for s in skills}),
        shadowed=find_shadowed(names, personal_dirs, ignore=store.root),
        unchecked=unchecked,
    )


def check_config(config_path: Path, store_dir: Path) -> ConfigReport:
    """Compare the OpenCode config with the team's preferred config. Works offline."""
    try:
        config = plan_config(config_path, store_dir)
    except ConfigError as e:
        return ConfigReport(error=str(e))
    plan = config.plan
    return ConfigReport(plan.changes, plan.warnings, plan.notes, config.exists)
