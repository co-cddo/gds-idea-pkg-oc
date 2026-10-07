"""Compare the machine's skill setup with what the registry says it should be."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from idea_oc.github import GitHubClient, GitHubError, TreeEntry
from idea_oc.models import Registry
from idea_oc.opencode_config import ConfigError, plan_config
from idea_oc.planner import SKILL_FILE, PlanError, PlannedSkill, frontmatter_name, plan_source
from idea_oc.profiles import TeamChoice
from idea_oc.store import SkillDiff, Store
from idea_oc.sync import SourcePlan, plan_registry
from idea_oc.team_config import Change


@dataclass(frozen=True)
class SkillStatus:
    """How one approved skill compares with its installed copy.

    A difference from the latest release can mean two different things: the user edited the files, or
    upstream has a newer version. ``local`` and ``update`` tell them apart.

    Attributes:
        name: Skill name.
        installed: Whether a folder for it exists in the store.
        diff: Differences from the latest release (clean means identical).
        local: Differences from the version that was installed, which are the user's own changes.
            None when that version could not be checked.
        update: (installed ref, latest ref) when upstream has moved on since the skill was installed.
    """

    name: str
    installed: bool
    diff: SkillDiff
    local: SkillDiff | None = None
    update: tuple[str, str] | None = None

    @property
    def ok(self) -> bool:
        return self.installed and self.diff.clean

    @property
    def edited(self) -> bool:
        """True when the files in the store differ from the version that was installed."""
        return self.local is not None and not self.local.clean

    @property
    def detail(self) -> str:
        if not self.installed:
            return "not installed"
        parts = []
        if self.local is None:
            parts.append(f"differs from the latest release ({_counts(self.diff)})")
        elif self.edited:
            parts.append(f"{_counts(self.local)} locally")
        if self.update:
            installed, latest = self.update
            parts.append(f"update available: {installed} -> {latest}")
        return "; ".join(parts)


def _counts(diff: SkillDiff) -> str:
    """'1 changed, 2 extra' for the non-empty parts of ``diff``."""
    counts = {"changed": diff.changed, "missing": diff.missing, "extra": diff.extra}
    return ", ".join(f"{len(files)} {label}" for label, files in counts.items() if files)


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
        team: Which team's inference profile the config was compared against, and why.
    """

    changes: list[Change] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    exists: bool = True
    error: str | None = None
    team: TeamChoice | None = None

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


class _InstalledVersions:
    """Looks up what a skill was at the commit it was installed from, fetching each tree at most once."""

    def __init__(self, client: GitHubClient):
        self._client = client
        self._trees: dict[tuple[str, str], list[TreeEntry]] = {}

    def skill_at(self, plan: SourcePlan, name: str, commit: str) -> PlannedSkill | None:
        """The skill as it was at ``commit``, or None if that cannot be worked out."""
        key = (plan.source.repo, commit)
        try:
            if key not in self._trees:
                self._trees[key] = self._client.get_tree(plan.source.repo, commit)
            then = plan_source(plan.source, self._trees[key])
        except (GitHubError, PlanError):
            return None
        return next((skill for skill in then if skill.name == name), None)


def _skill_status(store: Store, plan: SourcePlan, skill: PlannedSkill, versions: _InstalledVersions) -> SkillStatus:
    """Compare one skill with the latest release, and work out whether a difference is an edit or an update."""
    installed = store.skill_dir(skill.name).is_dir()
    diff = store.diff(skill)
    if not installed or diff.clean:
        return SkillStatus(skill.name, installed, diff)

    origin = store.installed().get(skill.name)
    if origin is None or plan.resolved is None:
        return SkillStatus(skill.name, installed, diff)
    if origin.commit == plan.resolved.sha:  # nothing upstream has changed, so every difference is local
        return SkillStatus(skill.name, installed, diff, local=diff)

    update = (origin.ref, plan.resolved.name)
    then = versions.skill_at(plan, skill.name, origin.commit)
    return SkillStatus(skill.name, installed, diff, local=store.diff(then) if then else None, update=update)


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
    versions = _InstalledVersions(client)
    skills = [_skill_status(store, plan, skill, versions) for plan in plans for skill in plan.skills]
    names = {s.name for s in skills} | set(store.installed())
    unchecked = [p.message for p in plans if p.message]

    return SkillsReport(
        skills=skills,
        stale=[] if unchecked else store.stale({s.name for s in skills}),
        shadowed=find_shadowed(names, personal_dirs, ignore=store.root),
        unchecked=unchecked,
    )


def check_config(config_path: Path, store_dir: Path, team: str | None = None) -> ConfigReport:
    """Compare the OpenCode config with the team's preferred config. Works offline."""
    try:
        config = plan_config(config_path, store_dir, team)
    except ConfigError as e:
        return ConfigReport(error=str(e))
    plan = config.plan
    return ConfigReport(plan.changes, plan.warnings, plan.notes, config.exists, team=config.team)
