"""Tests for comment-preserving JSONC edits.

json-five's editing model is documented as unstable and has a known fault with trailing
comments, so these tests pin down every behaviour the rest of idea-oc relies on.
"""

import json
import re

import pytest

from idea_oc.jsonc_doc import JsoncDocument, JsoncError

WALKTHROUGH = """{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "amazon-bedrock": {
      "options": {
        "region": "eu-west-2",
        "profile": "bedrockonly"
      }
    }
  },
  "model": "amazon-bedrock/eu.anthropic.claude-sonnet-5",
  "disabled_providers": ["anthropic"],
  "plugin": [
    ["./plugin-scripts/inject-env.js", { "AWS_PROFILE": "bedrockonly" }],
    "@tarquinen/opencode-dcp@latest"
  ],
  "permission": {
    "bash": {
      "*": "allow",
      "cdk deploy*": "ask", //Stop AI deploying whatever it wants
      "cdk destroy*": "deny", //Stop AI destroying without review
      "gh pr *": "ask", //Default: confirm before any PR action
      "gh pr merge *": "deny" //Merging is annoying to undo
    },
    "external_directory": {
      "*": "ask", //Pause before AI reads/writes anything outside this project
    },
    "edit": {
      "*": "ask" //Show every file write before it happens
    }
  }
}
"""


def comments(text: str) -> list[str]:
    return re.findall(r"//[^\n]*|/\*.*?\*/", text)


def keys(doc: JsoncDocument, *path: str) -> list[str]:
    return list(doc.get(path))


@pytest.fixture
def doc() -> JsoncDocument:
    return JsoncDocument.parse(WALKTHROUGH)


# --- parsing ---------------------------------------------------------------------------------


def test_parse_and_dump_is_byte_identical(doc):
    assert doc.text == WALKTHROUGH


def test_data_and_get_read_through_comments_and_trailing_commas(doc):
    assert doc.get(("model",)) == "amazon-bedrock/eu.anthropic.claude-sonnet-5"
    assert doc.get(("permission", "external_directory", "*")) == "ask"
    assert doc.get(("nope", "nothing"), "fallback") == "fallback"
    assert doc.data["disabled_providers"] == ["anthropic"]


def test_data_and_get_return_copies(doc):
    doc.data["model"] = "changed"
    doc.get(("disabled_providers",)).append("x")

    assert doc.get(("model",)) != "changed"
    assert doc.get(("disabled_providers",)) == ["anthropic"]


@pytest.mark.parametrize("text", ["", "[1, 2]", '"just a string"', "{not json", '{"a": }'])
def test_unusable_text_is_rejected(text):
    with pytest.raises(JsoncError):
        JsoncDocument.parse(text)


def test_empty_document_is_an_empty_object():
    assert JsoncDocument.empty().data == {}


# --- set: existing keys ----------------------------------------------------------------------


def test_changing_a_value_leaves_everything_else_untouched(doc):
    doc.set(("model",), "amazon-bedrock/NEW")

    expected = WALKTHROUGH.replace("eu.anthropic.claude-sonnet-5", "NEW")
    assert doc.text == expected


def test_changing_a_value_keeps_the_trailing_comment(doc):
    doc.set(("permission", "bash", "cdk deploy*"), "deny")

    assert '"cdk deploy*": "deny", //Stop AI deploying whatever it wants' in doc.text
    assert comments(doc.text) == comments(WALKTHROUGH)


def test_replacing_an_array_value(doc):
    doc.set(("disabled_providers",), ["anthropic", "openai"])

    assert '"disabled_providers": ["anthropic", "openai"],' in doc.text


def test_an_existing_key_keeps_its_position(doc):
    doc.set(("permission", "bash", "cdk deploy*"), "deny")

    assert keys(doc, "permission", "bash") == ["*", "cdk deploy*", "cdk destroy*", "gh pr *", "gh pr merge *"]


# --- set: new keys ---------------------------------------------------------------------------


def test_new_key_goes_straight_after_the_named_sibling(doc):
    doc.set(("permission", "bash", "rm -rf*"), "deny", after="*")

    assert keys(doc, "permission", "bash")[:3] == ["*", "rm -rf*", "cdk deploy*"]
    assert '      "*": "allow",\n      "rm -rf*": "deny",\n      "cdk deploy*"' in doc.text
    assert comments(doc.text) == comments(WALKTHROUGH)


def test_insert_after_a_sibling_keeps_that_siblings_trailing_comment_with_it(doc):
    doc.set(("permission", "bash", "new *"), "ask", after="cdk deploy*")

    assert '"cdk deploy*": "ask", //Stop AI deploying whatever it wants\n      "new *": "ask",' in doc.text


def test_insert_after_the_last_sibling_appends(doc):
    doc.set(("permission", "bash", "sudo *"), "ask", after="gh pr merge *")

    assert keys(doc, "permission", "bash")[-1] == "sudo *"


def test_missing_after_sibling_appends_to_the_end(doc):
    doc.set(("permission", "bash", "sudo *"), "ask", after="no such key")

    assert keys(doc, "permission", "bash")[-1] == "sudo *"


def test_appending_after_a_trailing_comment_moves_the_comma_before_the_comment(doc):
    doc.set(("permission", "bash", "sudo *"), "ask")

    assert '"gh pr merge *": "deny", //Merging is annoying to undo\n      "sudo *": "ask"\n    },' in doc.text
    assert comments(doc.text) == comments(WALKTHROUGH)


def test_appending_to_an_object_with_a_trailing_comma_keeps_the_trailing_comma(doc):
    doc.set(("permission", "external_directory", "/tmp/*"), "allow")

    assert (
        '      "*": "ask", //Pause before AI reads/writes anything outside this project\n'
        '      "/tmp/*": "allow",\n    },'
    ) in doc.text


def test_new_top_level_key_and_nested_parents_are_created(doc):
    doc.set(("skills", "paths"), ["~/.local/share/idea-oc/skills"])

    assert doc.get(("skills", "paths")) == ["~/.local/share/idea-oc/skills"]
    assert doc.text.endswith('  },\n  "skills": {\n    "paths": ["~/.local/share/idea-oc/skills"]\n  }\n}\n')


def test_creating_deeply_nested_missing_parents():
    doc = JsoncDocument.parse('{\n  "a": 1\n}\n')

    doc.set(("x", "y", "z"), True)

    assert doc.data == {"a": 1, "x": {"y": {"z": True}}}


def test_new_key_inside_an_existing_nested_object():
    doc = JsoncDocument.parse(WALKTHROUGH)

    doc.set(("provider", "amazon-bedrock", "options", "endpoint"), "https://example.invalid")

    assert keys(doc, "provider", "amazon-bedrock", "options") == ["region", "profile", "endpoint"]


def test_a_parent_that_is_not_an_object_is_an_error(doc):
    with pytest.raises(JsoncError, match="not an object"):
        doc.set(("model", "name"), "x")


def test_empty_path_is_an_error(doc):
    with pytest.raises(JsoncError):
        doc.set((), "x")


# --- append ----------------------------------------------------------------------------------


def test_append_to_an_inline_array(doc):
    doc.append(("disabled_providers",), "openai")

    assert '"disabled_providers": ["anthropic", "openai"],' in doc.text


def test_append_to_a_multiline_array_keeps_layout():
    text = '{\n  "paths": [\n    "a", // first\n    "b"  // second\n  ]\n}\n'
    doc = JsoncDocument.parse(text)

    doc.append(("paths",), "c")

    assert doc.get(("paths",)) == ["a", "b", "c"]
    assert comments(doc.text) == ["// first", "// second"]
    assert doc.text.index("// second") < doc.text.index('"c"')


def test_append_to_an_empty_array():
    doc = JsoncDocument.parse('{"paths": []}\n')

    doc.append(("paths",), "a")

    assert doc.text == '{"paths": ["a"]}\n'


def test_append_to_a_missing_array_is_an_error(doc):
    with pytest.raises(JsoncError, match="no array"):
        doc.append(("nope",), "x")


def test_append_to_something_that_is_not_an_array_is_an_error(doc):
    with pytest.raises(JsoncError, match="no array"):
        doc.append(("model",), "x")


def test_append_an_object_to_an_array(doc):
    doc.append(("plugin",), {"name": "x"})

    assert doc.get(("plugin",))[-1] == {"name": "x"}


# --- formatting styles -----------------------------------------------------------------------

STYLES = {
    "plain json, no comments": '{\n  "a": 1,\n  "b": {\n    "c": 2\n  },\n  "list": ["x", "y"]\n}\n',
    "comments everywhere": (
        '{\n  // lead\n  "a": 1, // one\n  "b": { // open\n    "c": 2 /* block */\n  }, // two\n'
        '  "list": ["x", "y"] // end\n}\n'
    ),
    "trailing commas": '{\n  "a": 1,\n  "b": {\n    "c": 2,\n  },\n  "list": ["x", "y",],\n}\n',
    "tabs": '{\n\t"a": 1,\n\t"b": {\n\t\t"c": 2\n\t},\n\t"list": ["x"]\n}\n',
    "four spaces": '{\n    "a": 1,\n    "b": {\n        "c": 2\n    },\n    "list": ["x"]\n}\n',
    "compact one line": '{"a":1,"b":{"c":2},"list":["x"]}',
    "spaced one line": '{ "a": 1, "b": { "c": 2 }, "list": ["x"] }\n',
    "no trailing newline": '{\n  "a": 1,\n  "b": {\n    "c": 2\n  },\n  "list": ["x"]\n}',
}


@pytest.mark.parametrize("style", STYLES)
def test_every_operation_produces_valid_data_and_keeps_comments(style):
    text = STYLES[style]
    doc = JsoncDocument.parse(text)
    assert doc.text == text

    doc.set(("a",), 99)
    doc.set(("b", "d"), "new")
    doc.set(("b", "e"), "after c", after="c")
    doc.set(("top",), {"nested": ["p", "q"]})
    doc.set(("deep", "er", "still"), 1)
    doc.append(("list",), "z")

    assert doc.data == {
        "a": 99,
        "b": {"c": 2, "e": "after c", "d": "new"},
        "list": ["x", "y", "z"] if "y" in text else ["x", "z"],
        "top": {"nested": ["p", "q"]},
        "deep": {"er": {"still": 1}},
    }
    assert list(doc.data["b"]) == ["c", "e", "d"]
    assert comments(doc.text) == comments(text)
    assert JsoncDocument.parse(doc.text).data == doc.data  # the output is itself editable


def test_empty_object_gets_a_member():
    doc = JsoncDocument.parse("{}\n")

    doc.set(("skills", "paths"), ["x"])

    assert doc.text == '{\n  "skills": {\n    "paths": ["x"]\n  }\n}\n'


def test_empty_nested_object_gets_a_member():
    doc = JsoncDocument.parse('{\n  "a": {}\n}\n')

    doc.set(("a", "b"), 1)

    assert doc.text == '{\n  "a": {\n    "b": 1\n  }\n}\n'


def test_indentation_style_is_followed(doc):
    tabbed = JsoncDocument.parse('{\n\t"a": {\n\t\t"b": 1\n\t}\n}\n')

    tabbed.set(("a", "c"), 2)
    tabbed.set(("d", "e"), 3)

    assert '\t\t"b": 1,\n\t\t"c": 2\n\t},' in tabbed.text
    assert '\t"d": {\n\t\t"e": 3\n\t}\n' in tabbed.text


# --- set: first ------------------------------------------------------------------------------


def test_first_puts_a_new_key_before_all_the_others(doc):
    doc.set(("permission", "bash", "head *"), "deny", first=True)

    assert keys(doc, "permission", "bash")[:2] == ["head *", "*"]
    assert '    "bash": {\n      "head *": "deny",\n      "*": "allow",' in doc.text
    assert comments(doc.text) == comments(WALKTHROUGH)


def test_first_keeps_a_comment_that_led_the_old_first_member_with_it():
    text = '{\n  // about a\n  "a": 1, // one\n  "b": 2\n}\n'
    doc = JsoncDocument.parse(text)

    doc.set(("z",), 0, first=True)

    assert doc.text == '{\n  "z": 0,\n  // about a\n  "a": 1, // one\n  "b": 2\n}\n'


@pytest.mark.parametrize("style", STYLES)
def test_first_works_in_every_formatting_style(style):
    text = STYLES[style]
    doc = JsoncDocument.parse(text)

    doc.set(("top",), "x", first=True)
    doc.set(("b", "head"), "y", first=True)

    assert list(doc.data)[0] == "top"
    assert list(doc.data["b"])[0] == "head"
    assert comments(doc.text) == comments(text)
    assert JsoncDocument.parse(doc.text).data == doc.data


def test_first_on_an_empty_object_just_adds_the_member():
    doc = JsoncDocument.parse("{}\n")

    doc.set(("a",), 1, first=True)

    assert doc.data == {"a": 1}


def test_first_and_after_apply_to_the_final_key_not_to_parents_being_created(doc):
    doc.set(("brand", "new", "rule"), "x", first=True)
    doc.set(("another", "one", "rule"), "y", after="model")

    assert keys(doc)[0] == "$schema"  # "brand" and "another" were appended, not put first or after "model"
    assert keys(doc)[-2:] == ["brand", "another"]


def test_first_is_ignored_when_the_key_already_exists(doc):
    doc.set(("model",), "other", first=True)

    assert keys(doc)[0] == "$schema"
    assert doc.get(("model",)) == "other"


# --- verification ----------------------------------------------------------------------------


def test_edits_are_verified_against_independent_expectations(doc, monkeypatch):
    """If the text edit and the expected data ever disagree, the edit is refused."""
    from idea_oc import jsonc_doc

    monkeypatch.setattr(jsonc_doc, "_append", lambda *a, **k: None)  # a broken edit that changes nothing

    with pytest.raises(JsoncError, match="expected result"):
        doc.set(("permission", "bash", "sudo *"), "ask")


def test_key_order_is_part_of_the_verification(doc, monkeypatch):
    from idea_oc import jsonc_doc

    real = jsonc_doc._insert_after
    monkeypatch.setattr(jsonc_doc, "_insert_after", lambda obj, index, key, value: real(obj, index - 1, key, value))

    with pytest.raises(JsoncError, match="expected result"):
        doc.set(("permission", "bash", "rm -rf*"), "deny", after="cdk deploy*")


def test_unrelated_text_is_never_reformatted(doc):
    doc.set(("permission", "bash", "sudo *"), "ask")
    doc.set(("model",), "x")

    before = WALKTHROUGH.splitlines()
    after = doc.text.splitlines()
    unchanged = [line for line in before if line in after]
    assert len(unchanged) >= len(before) - 3  # only the lines we meant to touch differ


def test_output_is_valid_for_a_strict_json_reader_once_comments_are_removed():
    doc = JsoncDocument.parse(STYLES["plain json, no comments"])
    doc.set(("x",), {"y": [1, 2, {"z": None}]})

    assert json.loads(doc.text)["x"] == {"y": [1, 2, {"z": None}]}
