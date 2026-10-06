"""Tests for evaluating permission rules like OpenCode."""

import pytest

from idea_oc.permissions import Overridden, effective, find_overridden, wildcard_match, witness


@pytest.mark.parametrize(
    ("text", "pattern", "expected"),
    [
        ("git push", "git push *", True),  # the trailing " *" is optional
        ("git push origin", "git push *", True),
        ("git pushed", "git push *", False),
        ("rm -rf /", "rm -rf*", True),
        ("sudo rm -rf /", "rm -rf*", False),  # patterns match the whole command
        ("anything at all", "*", True),
        ("cdk deploy", "cdk deploy*", True),
        ("a.b", "a.b", True),
        ("aXb", "a.b", False),  # regex characters in a pattern are literal
        ("ab", "a?", True),
        ("a\nb", "a*b", True),  # newlines are matched too
    ],
)
def test_wildcard_matching(text, pattern, expected):
    assert wildcard_match(text, pattern) is expected


def test_the_last_matching_rule_wins():
    rules = {"*": "allow", "gh pr *": "ask", "gh pr merge *": "deny"}

    assert effective(rules, "gh pr view 1") == ("gh pr *", "ask")
    assert effective(rules, "gh pr merge 1") == ("gh pr merge *", "deny")
    assert effective(rules, "ls") == ("*", "allow")


def test_no_matching_rule_means_ask():
    assert effective({"rm *": "deny"}, "ls") == ("", "ask")
    assert effective({}, "ls") == ("", "ask")


def test_witness_is_the_pattern_without_wildcards():
    assert witness("git push --force*") == "git push --force"
    assert witness("gh pr *") == "gh pr"
    assert witness("*") == ""


def test_a_rule_overridden_by_a_later_one_is_found():
    rules = {"*": "allow", "git push --force*": "deny", "git push *": "ask"}

    assert find_overridden(rules) == [Overridden("git push --force*", "deny", "git push *", "ask")]


def test_a_trailing_catch_all_overrides_everything_before_it():
    rules = {"rm -rf*": "deny", "*": "allow"}

    assert find_overridden(rules) == [Overridden("rm -rf*", "deny", "*", "allow")]


def test_the_leading_catch_all_is_never_reported():
    assert find_overridden({"*": "allow", "rm *": "deny"}) == []


def test_only_restricts_what_is_reported():
    rules = {"a*": "deny", "*": "allow", "b*": "deny"}  # "a*" is overridden by the trailing "*", "b*" is not

    assert [o.pattern for o in find_overridden(rules)] == ["a*"]
    assert find_overridden(rules, only={"b*"}) == []


def test_a_default_ask_can_be_the_overrider():
    # "x" has no matching rule of its own except itself, so only an explicit later rule can override it
    assert find_overridden({"x": "deny"}) == []
