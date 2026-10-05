"""Plan and apply a sync of the registry's skills into the store.

Syncing is two phases. Planning resolves every source and works out its skills
from the git tree (a few cheap API calls, no file downloads). Applying then
installs whatever differs from what is on disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from idea_oc.github import GitHubClient, GitHubError, ResolvedRef
from idea_oc.models import Registry, Source
from idea_oc.planner import (
    SKILL_FILE,
    PlanError,
    PlannedSkill,
    SkillFile,
    check_unique_names,
    plan_source,
    validate_skill_md,
)
from idea_oc.store import Provenance, Store, StoreError

_INSTALL_ERRORS = (GitHubError, PlanError, StoreError, OSError)


class Action(Enum):
    """What a sync does (or would do) to a skill."""

    ADDED = "added"
    UPDATED = "updated"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class SourcePlan:
    """The outcome of planning one registry source.

    Attributes:
        source: The registry entry.
        resolved: The ref it resolved to, or None if resolution failed.
        skills: Skills the source provides at that ref.
        error: Why planning failed, if it did.
    """

    source: Source
    resolved: ResolvedRef | None = None
    skills: tuple[PlannedSkill, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class SkillOutcome:
    """What happened to one skill."""

    name: str
    repo: str
    action: Action
    files_changed: int = 0
    error: str | None = None


@dataclass
class SyncResult:
    """Everything a sync did, for reporting.

    Attributes:
        plans: One per registry source.
        outcomes: One per skill, in install order.
        removed: Skill folders pruned from the store (or that would be, in a dry run).
    """

    plans: list[SourcePlan] = field(default_factory=list)
    outcomes: list[SkillOutcome] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def errors(self) -> list[str]:
        """Every failure, as a printable line."""
        plan_errors = [f"{p.source.repo}: {p.error}" for p in self.plans if p.error]
        skill_errors = [f"{o.name}: {o.error}" for o in self.outcomes if o.error]
        return plan_errors + skill_errors

    @property
    def ok(self) -> bool:
        return not self.errors

    def count(self, action: Action) -> int:
        return sum(1 for o in self.outcomes if o.action is action and not o.error)


def plan_source_at_ref(client: GitHubClient, source: Source) -> SourcePlan:
    """Resolve one source and list its skills. Failures are captured, not raised."""
    try:
        resolved = client.resolve_ref(source.repo, source.ref)
        tree = client.get_tree(source.repo, resolved.sha)
        return SourcePlan(source, resolved, tuple(plan_source(source, tree)))
    except (GitHubError, PlanError) as e:
        return SourcePlan(source, error=str(e))


def plan_registry(client: GitHubClient, registry: Registry) -> list[SourcePlan]:
    """Plan every source in the registry.

    Raises:
        PlanError: If two sources provide a skill with the same name.
    """
    plans = [plan_source_at_ref(client, source) for source in registry.source]
    check_unique_names([skill for plan in plans for skill in plan.skills])
    return plans


def _fetcher(client: GitHubClient, skill: PlannedSkill):
    """A fetch function that also validates ``SKILL.md`` before it is installed."""

    def fetch(file: SkillFile) -> bytes:
        data = client.get_blob(skill.repo, file.sha)
        if file.rel_path == SKILL_FILE:
            validate_skill_md(skill.name, data)
        return data

    return fetch


def _install_one(
    client: GitHubClient, store: Store, plan: SourcePlan, skill: PlannedSkill, *, dry_run: bool
) -> SkillOutcome:
    assert plan.resolved is not None  # skills only exist for successfully resolved sources
    existed = store.skill_dir(skill.name).is_dir()
    provenance = Provenance(skill.repo, skill.source_path, plan.resolved.name, plan.resolved.sha)
    try:
        if dry_run:
            diff = store.diff(skill)
        else:
            diff = store.install(skill, provenance, _fetcher(client, skill))
    except _INSTALL_ERRORS as e:
        return SkillOutcome(skill.name, skill.repo, Action.UPDATED, error=str(e))

    action = Action.UNCHANGED if diff.clean else Action.UPDATED if existed else Action.ADDED
    return SkillOutcome(skill.name, skill.repo, action, files_changed=len(diff.to_download))


def apply_plans(
    client: GitHubClient,
    store: Store,
    plans: list[SourcePlan],
    *,
    dry_run: bool = False,
    prune: bool = True,
) -> SyncResult:
    """Install every planned skill, then prune the store.

    Pruning is skipped if any source failed to plan or any skill failed to
    install, so a temporary outage can never delete skills that are still approved.

    Args:
        client: GitHub client used to download changed files.
        store: The skill store.
        plans: Output of ``plan_registry``.
        dry_run: Compute outcomes without writing anything.
        prune: Remove store folders that no source provides.

    Returns:
        A result describing every source, skill and removal.
    """
    result = SyncResult(plans=plans)
    for plan in plans:
        result.outcomes += [_install_one(client, store, plan, skill, dry_run=dry_run) for skill in plan.skills]

    if prune and result.ok:
        wanted = {skill.name for plan in plans for skill in plan.skills}
        result.removed = store.stale(wanted)
        if not dry_run:
            for name in result.removed:
                store.remove(name)
    return result
