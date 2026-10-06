"""Work out what the team's preferred config would change in a user's OpenCode config.

The preferred config (``opencode.jsonc``, bundled with idea-oc) is the reference. Everything in it is
compared with the user's config, except two keys:

- ``$schema``, which only helps editors, and
- ``plugin``, which idea-oc advises on but never changes.

What is left is the provider and model settings, and the permission rules. Each rule or setting is a
separate entry, so we can say exactly what would change. Three kinds of change exist:

- ``ADD``: the key is missing,
- ``CHANGE``: a single value differs,
- ``APPEND``: items are missing from a list (lists are only ever added to, never trimmed, so extra
  entries a user has are left alone).

Permission rules are read top to bottom and the last match wins, so *where* a missing rule goes
matters. The team's relative order is kept: a missing rule goes after the team rules that should
precede it and before the specific team rules it refines. If the user has none of the team's rules in
that section, the team's rules go first, which puts them above the user's own so the user's later
rules can still override them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from importlib.resources import files
from pathlib import Path
from typing import Any

from idea_oc.jsonc_doc import JsoncDocument, JsoncError, KeyPath
from idea_oc.permissions import find_overridden

SKIPPED_KEYS: frozenset[KeyPath] = frozenset({("$schema",), ("plugin",)})
SKILLS_PATH: KeyPath = ("skills", "paths")
PERMISSION = "permission"
_MISSING = object()


class ChangeKind(Enum):
    ADD = "add"
    CHANGE = "change"
    APPEND = "append"


@dataclass(frozen=True)
class Change:
    """One edit to the user's config.

    Attributes:
        kind: Whether the key is added, its value changed, or items appended to a list.
        path: The key path in the config.
        new: The value to set, or for ``APPEND`` the list of items to add.
        old: The current value, for ``CHANGE``.
        after: For a new permission rule, the sibling it goes straight after.
        first: For a new permission rule, put it before all the others.
    """

    kind: ChangeKind
    path: KeyPath
    new: Any
    old: Any = None
    after: str | None = None
    first: bool = False


@dataclass
class Plan:
    """What syncing the config would do.

    Attributes:
        changes: The edits, in the order they are applied.
        notes: Things idea-oc left alone and why.
        warnings: Team rules that a rule in the user's config would stop from working.
    """

    changes: list[Change] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def pending(self) -> bool:
        return bool(self.changes)


def team_config() -> JsoncDocument:
    """The preferred config bundled with idea-oc."""
    return JsoncDocument.parse(files("idea_oc").joinpath("opencode.jsonc").read_text())


def _flatten(node: dict, path: KeyPath = ()) -> list[tuple[KeyPath, Any]]:
    """The leaves of ``node`` as (path, value), in order. Lists count as leaves."""
    leaves = []
    for key, value in node.items():
        here = (*path, key)
        if here in SKIPPED_KEYS:
            continue
        leaves += _flatten(value, here) if isinstance(value, dict) else [(here, value)]
    return leaves


def _blocked_by(user: JsoncDocument, path: KeyPath) -> KeyPath | None:
    """The part of ``path`` that exists in the user's config as something other than an object, if any."""
    for depth in range(1, len(path)):
        value = user.get(path[:depth], _MISSING)
        if value is _MISSING:
            return None
        if not isinstance(value, dict):
            return path[:depth]
    return None


def _rule_position(team_order: list[str], order: list[str], pattern: str) -> int:
    """Where in ``order`` (the user's rules for a section) a missing team rule should be inserted.

    A rule is placed after the latest team rule that should precede it and that the user already has.
    But a general rule must also come *before* the specific rules that refine it, so it never goes
    after the first later team rule the user already has: if the user's own ordering would put it
    there, it goes just before that rule instead. For example ``gh pr *`` goes before an existing
    ``gh pr merge *``, even when the user's ``git push *`` (which the team lists earlier) sits after it.
    """
    at = team_order.index(pattern)
    after = max((order.index(p) for p in team_order[:at] if p in order), default=-1)
    before = min((order.index(p) for p in team_order[at + 1 :] if p in order), default=len(order))
    return after + 1 if after < before else before


def _is_registered(paths: list, store_value: str, store_dir: Path) -> bool:
    return any(p == store_value or Path(p).expanduser() == store_dir for p in paths)


def plan_changes(user: JsoncDocument, store_dir: Path, store_value: str, team: JsoncDocument | None = None) -> Plan:
    """Compare the user's config with the preferred config and the skill store.

    Args:
        user: The user's config (an empty document if they have none).
        store_dir: The skill store, which must be listed in ``skills.paths``.
        store_value: How the store should be written in the config (``~/...`` when possible).
        team: The preferred config. Defaults to the one bundled with idea-oc.

    Raises:
        JsoncError: If ``skills.paths`` is not a list of strings.
    """
    team = team or team_config()
    plan = Plan()

    paths = user.get(SKILLS_PATH, [])
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise JsoncError("'skills.paths' must be a list of strings")
    if not _is_registered(paths, store_value, store_dir):
        plan.changes.append(Change(ChangeKind.APPEND, SKILLS_PATH, [store_value]))

    sections: dict[str, list[str]] = {}  # permission section -> the user's rules in order, as edits are planned
    team_rules: dict[str, list[str]] = {}
    for path, _ in _flatten(team.data):
        if path[0] == PERMISSION and len(path) == 3:
            team_rules.setdefault(path[1], []).append(path[2])

    skipped: set[KeyPath] = set()
    for path, value in _flatten(team.data):
        if blocker := _blocked_by(user, path):
            if blocker not in skipped:
                skipped.add(blocker)
                plan.notes.append(f"{_dotted(blocker)} is not an object in your config, so it was left alone.")
            continue
        current = user.get(path, _MISSING)
        if isinstance(value, list):
            _plan_list(plan, path, value, current)
        elif path[0] == PERMISSION and len(path) == 3:
            order = sections.setdefault(path[1], list(user.get((PERMISSION, path[1]), {})))
            _plan_rule(plan, path, value, current, order, team_rules[path[1]])
        elif current is _MISSING:
            plan.changes.append(Change(ChangeKind.ADD, path, value))
        elif current != value:
            plan.changes.append(Change(ChangeKind.CHANGE, path, value, old=current))

    plan.warnings = _overridden_rules(user, plan, team_rules)
    return plan


def _plan_list(plan: Plan, path: KeyPath, wanted: list, current: Any) -> None:
    if current is _MISSING:
        plan.changes.append(Change(ChangeKind.ADD, path, wanted))
    elif not isinstance(current, list):
        plan.changes.append(Change(ChangeKind.CHANGE, path, wanted, old=current))
    elif missing := [item for item in wanted if item not in current]:
        plan.changes.append(Change(ChangeKind.APPEND, path, missing))


def _plan_rule(plan: Plan, path: KeyPath, action: str, current: Any, order: list[str], team_order: list[str]) -> None:
    pattern = path[2]
    if current is _MISSING:
        position = _rule_position(team_order, order, pattern)
        after = order[position - 1] if position > 0 else None
        plan.changes.append(Change(ChangeKind.ADD, path, action, after=after, first=position == 0))
        order.insert(position, pattern)
    elif current != action:
        plan.changes.append(Change(ChangeKind.CHANGE, path, action, old=current))


def apply_changes(document: JsoncDocument, changes: list[Change]) -> None:
    """Make the edits in ``changes`` to ``document``.

    Raises:
        JsoncError: If an edit cannot be made safely, in which case ``document`` must be discarded.
    """
    for change in changes:
        if change.kind is ChangeKind.APPEND:
            for item in change.new:
                if isinstance(document.get(change.path), list):
                    document.append(change.path, item)
                else:
                    document.set(change.path, [item])
        else:
            document.set(change.path, change.new, after=change.after, first=change.first)


def _overridden_rules(user: JsoncDocument, plan: Plan, team_rules: dict[str, list[str]]) -> list[str]:
    """Team rules that, once the plan is applied, a later rule in the user's own config overrides."""
    result = JsoncDocument.parse(user.text)
    apply_changes(result, plan.changes)
    warnings = []
    for section, patterns in team_rules.items():
        rules = result.get((PERMISSION, section))
        if not isinstance(rules, dict):
            continue
        for found in find_overridden(rules, only=set(patterns)):
            by = "the default" if found.by_pattern == "" else f"{found.by_pattern!r} ({found.by_action})"
            warnings.append(
                f"{_dotted((PERMISSION, section, found.pattern))} ({found.action}) is overridden by {by} "
                "and will have no effect."
            )
    return warnings


def _dotted(path: KeyPath) -> str:
    """A readable key path. Permission patterns go in brackets because they contain spaces and dots."""
    if path[0] == PERMISSION and len(path) == 3:
        return f"{PERMISSION}.{path[1]}[{json.dumps(path[2])}]"
    return ".".join(path)


def describe(change: Change) -> tuple[str, str, str]:
    """(verb, key, detail) for showing a change to the user."""

    def show(value: Any) -> str:
        return value if isinstance(value, str) else json.dumps(value)

    detail = {
        ChangeKind.ADD: show(change.new),
        ChangeKind.CHANGE: f"{show(change.old)} -> {show(change.new)}",
        ChangeKind.APPEND: ", ".join(show(item) for item in change.new),
    }[change.kind]
    return change.kind.value, _dotted(change.path), detail
