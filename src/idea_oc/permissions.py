"""Evaluate OpenCode permission rules the way OpenCode does.

A section of the ``permission`` block (for example ``bash``) is an ordered mapping of pattern to
action. OpenCode takes the *last* rule whose pattern matches the command, and asks if none match.
So a rule only works if no later rule matches the same commands, and the order in the file decides.

This follows OpenCode's ``Wildcard.match`` and ``Permission.evaluate`` (v1.18.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def wildcard_match(text: str, pattern: str) -> bool:
    """Whether ``pattern`` matches the whole of ``text``. ``*`` matches anything, and ``?`` any character."""
    escaped = re.sub(r"[.+^${}()|\[\]\\]", r"\\\g<0>", pattern.replace("\\", "/"))
    escaped = escaped.replace("*", ".*").replace("?", ".")
    if escaped.endswith(" .*"):  # "git push *" also matches a bare "git push"
        escaped = escaped[:-3] + "( .*)?"
    return re.fullmatch(escaped, text.replace("\\", "/"), re.S) is not None


def effective(rules: dict[str, str], command: str) -> tuple[str, str]:
    """The (pattern, action) OpenCode applies to ``command``: the last match, else ask."""
    matching = [(pattern, action) for pattern, action in rules.items() if wildcard_match(command, pattern)]
    return matching[-1] if matching else ("", "ask")


def witness(pattern: str) -> str:
    """A command the pattern describes: the pattern with its wildcards taken out."""
    return pattern.replace("*", "").strip()


@dataclass(frozen=True)
class Overridden:
    """A rule that a later rule overrides for the command the rule itself describes.

    Attributes:
        pattern: The rule that cannot take effect.
        action: What the rule says.
        by_pattern: The later rule that wins instead ("" means the default, ask).
        by_action: What the winning rule does.
    """

    pattern: str
    action: str
    by_pattern: str
    by_action: str


def find_overridden(rules: dict[str, str], only: set[str] | None = None) -> list[Overridden]:
    """Rules that never take effect because of a later rule.

    The catch-all ``*`` is skipped: it is meant to be overridden by every more specific rule.

    Args:
        rules: One section of the permission block, in file order.
        only: If given, only report on these patterns.
    """
    found = []
    for pattern, action in rules.items():
        if pattern == "*" or (only is not None and pattern not in only):
            continue
        by_pattern, by_action = effective(rules, witness(pattern))
        if by_action != action:
            found.append(Overridden(pattern, action, by_pattern, by_action))
    return found
