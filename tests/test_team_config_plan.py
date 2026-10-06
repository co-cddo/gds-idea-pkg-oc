"""Tests for working out what the preferred config would change."""

from pathlib import Path

import pytest

from idea_oc.jsonc_doc import JsoncDocument, JsoncError
from idea_oc.permissions import effective
from idea_oc.team_config import (
    Change,
    ChangeKind,
    apply_changes,
    describe,
    plan_changes,
    team_config,
)

STORE = Path("/home/u/.local/share/idea-oc/skills")
STORE_VALUE = "/home/u/.local/share/idea-oc/skills"


def plan(text: str = "{}\n", **kwargs):
    return plan_changes(JsoncDocument.parse(text), STORE, STORE_VALUE, **kwargs)


def applied(text: str) -> JsoncDocument:
    document = JsoncDocument.parse(text)
    apply_changes(document, plan_changes(document, STORE, STORE_VALUE).changes)
    return document


def by_path(changes: list[Change]) -> dict[tuple, Change]:
    return {c.path: c for c in changes}


def current_team_without_plugins() -> dict:
    data = team_config().data
    data.pop("plugin")
    data.pop("$schema")
    return data


# --- a brand new user -----------------------------------------------------------------------


def test_a_new_user_gets_everything_except_plugins_and_the_schema():
    changes = by_path(plan().changes)

    assert ("provider", "amazon-bedrock", "options", "region") in changes
    assert ("model",) in changes
    assert ("disabled_providers",) in changes
    assert ("permission", "bash", "gh pr merge *") in changes
    assert ("skills", "paths") in changes
    assert ("plugin",) not in changes
    assert ("$schema",) not in changes


def test_applying_the_plan_to_an_empty_config_reproduces_the_preferred_config():
    document = applied("{}\n")

    expected = current_team_without_plugins()
    expected["skills"] = {"paths": [STORE_VALUE]}
    assert document.data == expected
    assert list(document.data["permission"]["bash"]) == list(expected["permission"]["bash"])  # rule order matters


def test_the_plan_is_empty_once_applied_so_syncing_twice_changes_nothing():
    first = applied("{}\n")

    assert plan_changes(first, STORE, STORE_VALUE).pending is False


def test_plugins_are_never_added_even_for_an_empty_config():
    assert "plugin" not in applied("{}\n").data


# --- existing configs -----------------------------------------------------------------------


def test_a_different_model_is_proposed_as_a_change_showing_both_values():
    result = plan('{"model": "amazon-bedrock/eu.anthropic.claude-sonnet-5"}\n')

    change = by_path(result.changes)[("model",)]
    assert (change.kind, change.old, change.new) == (
        ChangeKind.CHANGE,
        "amazon-bedrock/eu.anthropic.claude-sonnet-5",
        "amazon-bedrock/eu.anthropic.claude-sonnet-5-5",
    )


def test_a_matching_value_is_not_in_the_plan():
    team_model = team_config().get(("model",))

    assert ("model",) not in by_path(plan(f'{{"model": "{team_model}"}}\n').changes)


def test_extra_list_items_the_user_has_are_kept_and_only_missing_ones_are_appended():
    result = plan('{"disabled_providers": ["openai"]}\n')

    change = by_path(result.changes)[("disabled_providers",)]
    assert (change.kind, change.new) == (ChangeKind.APPEND, ["anthropic"])
    document = applied('{"disabled_providers": ["openai"]}\n')
    assert document.get(("disabled_providers",)) == ["openai", "anthropic"]


def test_a_list_that_already_has_every_team_item_is_left_alone():
    assert ("disabled_providers",) not in by_path(plan('{"disabled_providers": ["anthropic", "other"]}\n').changes)


def test_a_non_list_where_a_list_belongs_is_replaced_and_shown_as_a_change():
    change = by_path(plan('{"disabled_providers": "anthropic"}\n').changes)[("disabled_providers",)]

    assert (change.kind, change.old, change.new) == (ChangeKind.CHANGE, "anthropic", ["anthropic"])


def test_settings_the_user_added_that_the_team_does_not_have_are_untouched():
    document = applied('{"theme": "dark", "provider": {"amazon-bedrock": {"options": {"endpoint": "x"}}}}\n')

    assert document.get(("theme",)) == "dark"
    assert document.get(("provider", "amazon-bedrock", "options", "endpoint")) == "x"
    assert document.get(("provider", "amazon-bedrock", "options", "region")) == "eu-west-2"


def test_the_users_own_plugin_list_is_never_touched():
    text = '{"plugin": ["something-else"]}\n'

    document = applied(text)

    assert document.get(("plugin",)) == ["something-else"]


def test_an_object_where_the_team_has_a_value_is_reported_not_overwritten():
    result = plan('{"provider": "custom"}\n')

    assert not any(c.path[0] == "provider" for c in result.changes)
    assert any("provider is not an object" in note for note in result.notes)


def test_a_note_is_given_once_per_blocking_key():
    result = plan('{"provider": "custom"}\n')

    assert len([n for n in result.notes if n.startswith("provider ")]) == 1


# --- skills.paths ---------------------------------------------------------------------------


def test_the_store_is_appended_to_existing_skill_paths():
    result = plan('{"skills": {"paths": ["~/mine"]}}\n')

    change = by_path(result.changes)[("skills", "paths")]
    assert (change.kind, change.new) == (ChangeKind.APPEND, [STORE_VALUE])
    assert applied('{"skills": {"paths": ["~/mine"]}}\n').get(("skills", "paths")) == ["~/mine", STORE_VALUE]


def test_an_already_registered_store_is_not_in_the_plan():
    assert ("skills", "paths") not in by_path(plan(f'{{"skills": {{"paths": ["{STORE_VALUE}"]}}}}\n').changes)


def test_the_tilde_form_of_the_store_counts_as_registered(monkeypatch):
    monkeypatch.setenv("HOME", "/home/u")

    result = plan_changes(
        JsoncDocument.parse('{"skills": {"paths": ["~/.local/share/idea-oc/skills"]}}\n'),
        STORE,
        "~/.local/share/idea-oc/skills",
    )

    assert ("skills", "paths") not in by_path(result.changes)


def test_malformed_skill_paths_are_an_error():
    with pytest.raises(JsoncError):
        plan('{"skills": {"paths": "x"}}\n')


# --- permission rule placement --------------------------------------------------------------


def bash_rules(document: JsoncDocument) -> dict:
    return document.get(("permission", "bash"))


def test_missing_rules_keep_the_teams_order_around_the_ones_the_user_already_has():
    document = applied('{"permission": {"bash": {"*": "allow", "gh pr *": "ask", "rm -rf*": "deny"}}}\n')

    rules = list(bash_rules(document))
    assert rules.index("*") == 0
    assert rules.index("gh pr *") < rules.index("gh pr create *") < rules.index("gh pr create --draft*")
    assert rules.index("gh pr create *") < rules.index("gh pr merge *")


def test_a_general_rule_goes_before_the_specific_rules_the_user_already_has():
    """Regression: from a real config. `gh pr *` must not land after the user's `gh pr merge *` deny."""
    original = (
        '{"permission": {"bash": {"*": "allow", "gh pr merge *": "deny", "gh pr ready *": "deny",'
        ' "gh pr close *": "ask", "git push *": "ask"}}}\n'
    )

    result = plan(original)
    document = applied(original)

    assert result.warnings == []
    rules = bash_rules(document)
    order = list(rules)
    assert order.index("gh pr *") < order.index("gh pr create *") < order.index("gh pr create --draft*")
    assert order.index("gh pr create --draft*") < order.index("gh pr merge *")
    assert effective(rules, "gh pr merge 5") == ("gh pr merge *", "deny")
    assert effective(rules, "gh pr ready 5") == ("gh pr ready *", "deny")
    assert effective(rules, "gh pr view 5") == ("gh pr *", "ask")
    assert effective(rules, "gh pr create --title x") == ("gh pr create *", "deny")
    assert effective(rules, "git push origin x") == ("git push *", "ask")


def subsets_of_the_team_rules():
    """Deterministic, varied subsets of the team's bash rules, always keeping the catch-all first."""
    team_rules = list(team_config().get(("permission", "bash")))
    for seed in range(len(team_rules) * 2):
        yield [rule for i, rule in enumerate(team_rules) if rule == "*" or (i * 7 + seed) % 3 == 0]


def user_config_with(rules: list[str]) -> JsoncDocument:
    actions = team_config().get(("permission", "bash"))
    document = JsoncDocument.empty()
    document.set(("permission", "bash"), {rule: actions[rule] for rule in rules})
    return JsoncDocument.parse(document.text)


SUBSETS = [pytest.param(rules, id=f"subset-{i}") for i, rules in enumerate(subsets_of_the_team_rules())]


@pytest.mark.parametrize("rules", SUBSETS)
def test_whatever_team_rules_the_user_starts_with_in_the_teams_order_every_rule_works_afterwards(rules):
    document = user_config_with(rules)
    team_actions = team_config().get(("permission", "bash"))

    apply_changes(document, plan_changes(document, STORE, STORE_VALUE).changes)

    synced = bash_rules(document)
    assert set(team_actions) <= set(synced)
    for pattern, action in team_actions.items():
        if pattern != "*":
            assert effective(synced, pattern.replace("*", "").strip())[1] == action, pattern
    assert plan_changes(document, STORE, STORE_VALUE).changes == []  # and syncing again changes nothing


def test_when_the_users_own_order_defeats_a_team_rule_it_is_always_reported_never_silent():
    team_actions = team_config().get(("permission", "bash"))
    for rules in subsets_of_the_team_rules():
        # the user's rules in the wrong order, with their own catch-all last: the worst they could write
        backwards = [r for r in reversed(rules) if r != "*"] + ["*"]
        document = user_config_with(backwards)
        result = plan_changes(document, STORE, STORE_VALUE)
        apply_changes(document, result.changes)
        synced = bash_rules(document)

        silent = [
            pattern
            for pattern, action in team_actions.items()
            if pattern != "*"
            and effective(synced, pattern.replace("*", "").strip())[1] != action
            and not any(pattern in warning for warning in result.warnings)
        ]
        assert silent == [], (backwards, silent)


def test_the_users_own_rules_stay_where_they_were_and_still_win():
    original = '{"permission": {"bash": {"*": "allow", "gh pr merge 5": "allow"}}}\n'

    document = applied(original)

    rules = bash_rules(document)
    assert list(rules)[:1] == ["*"]
    assert effective(rules, "gh pr merge 5") == ("gh pr merge 5", "allow")  # the user's later, more specific rule wins
    assert effective(rules, "gh pr merge 6")[1] == "deny"  # but the team's rule covers everything else


def test_team_rules_go_above_the_users_rules_when_there_is_no_team_rule_to_follow():
    document = applied('{"permission": {"bash": {"my cmd *": "allow"}}}\n')

    rules = list(bash_rules(document))
    assert rules.index("*") < rules.index("my cmd *")
    assert rules[-1] == "my cmd *"


def test_a_user_catch_all_that_is_not_first_overriding_team_rules_is_reported():
    original = '{"permission": {"bash": {"rm -rf*": "allow", "*": "allow"}}}\n'

    result = plan(original)

    assert any("rm -rf*" in w and "overridden" in w for w in result.warnings)


def test_a_clean_ordering_produces_no_warnings():
    assert plan("{}\n").warnings == []
    assert plan(team_config().text).warnings == []


def test_a_stricter_catch_all_is_shown_as_a_change_for_the_user_to_accept_or_decline():
    result = plan('{"permission": {"bash": {"*": "deny"}}}\n')

    change = by_path(result.changes)[("permission", "bash", "*")]
    assert (change.kind, change.old, change.new) == (ChangeKind.CHANGE, "deny", "allow")


def test_a_changed_rule_value_changes_in_place_and_the_team_order_is_built_around_it():
    original = '{"permission": {"bash": {"*": "allow", "gh pr merge *": "allow", "zzz": "ask"}}}\n'

    document = applied(original)

    rules = bash_rules(document)
    assert rules["gh pr merge *"] == "deny"
    order = list(rules)
    # the user's rule stays where it was relative to their own rules, and the team's rules fall into
    # their usual order around it
    assert order[:1] == ["*"]
    assert order.index("gh pr create --draft*") < order.index("gh pr merge *") < order.index("gh pr ready *")
    assert order.index("gh pr ready *") < order.index("gh pr close *") < order.index("zzz")
    assert order[-1] == "zzz"


def test_edit_and_external_directory_catch_alls_are_compared_too():
    result = plan('{"permission": {"edit": {"*": "allow"}, "external_directory": {"*": "ask"}}}\n')

    changes = by_path(result.changes)
    assert changes[("permission", "edit", "*")].kind is ChangeKind.CHANGE
    assert ("permission", "external_directory", "*") not in changes


# --- the edits keep the file readable -------------------------------------------------------


def test_comments_in_the_users_config_survive_the_plan():
    original = '{\n  // my notes\n  "model": "old", // keep\n  "theme": "dark"\n}\n'

    document = applied(original)

    assert "// my notes" in document.text and "// keep" in document.text
    assert document.get(("theme",)) == "dark"


def test_applying_a_plan_to_a_commented_walkthrough_style_config_is_stable():
    original = (
        team_config()
        .text.replace("sonnet-5-5", "sonnet-5")
        .replace('"rm -rf*": "deny", //Stop AI deleting files without warning\n      ', "")
    )

    document = applied(original)

    assert document.data["model"] == team_config().get(("model",))
    assert "rm -rf*" in document.data["permission"]["bash"]
    assert (
        plan_changes(document, STORE, STORE_VALUE).changes
        == plan_changes(JsoncDocument.parse(document.text), STORE, STORE_VALUE).changes
    )


# --- describing changes ---------------------------------------------------------------------


def test_describe_shows_what_will_happen():
    changes = by_path(plan('{"model": "old", "disabled_providers": ["x"]}\n').changes)

    assert describe(changes[("model",)]) == ("change", "model", "old -> amazon-bedrock/eu.anthropic.claude-sonnet-5-5")
    assert describe(changes[("disabled_providers",)]) == ("append", "disabled_providers", "anthropic")
    assert describe(changes[("permission", "bash", "gh pr merge *")]) == (
        "add",
        'permission.bash["gh pr merge *"]',
        "deny",
    )
