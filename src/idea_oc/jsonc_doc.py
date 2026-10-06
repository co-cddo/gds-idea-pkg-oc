"""Edit a JSONC file without disturbing its comments or formatting.

This is a thin layer over json-five's round-trip model. json-five does the parsing
and reproduces untouched text exactly; this module adds the three edits we need
(set a value, insert a key after a sibling, append to an array) and fixes the one
case json-five gets wrong: appending to an object whose last entry ends in a
comment, where it writes the comma inside the comment.

Every edit is checked: the edited text is parsed again and must equal the data we
expected, key order included. Order matters because OpenCode's permission rules
are read top to bottom and the last match wins.

json-five's model API is documented as unstable, so the dependency is pinned
exactly and ``tests/test_jsonc_doc.py`` guards the behaviour we rely on.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import json5
from json5 import model as nodes
from json5.dumper import ModelDumper
from json5.dumper import dumps as _dump_model
from json5.loader import ModelLoader
from json5.loader import loads as _load_model

KeyPath = tuple[str, ...]

_DEFAULT_STEP = "  "


class JsoncError(Exception):
    """Raised when a file cannot be parsed or edited safely."""


def _parse_data(text: str) -> Any:
    return json5.loads(text, parse_json5_identifiers=str)


def _ordered(data: Any) -> str:
    """A canonical form that, unlike ``==`` on dicts, also compares key order."""
    return json.dumps(data, sort_keys=False)


def _key_name(key: nodes.Key) -> str:
    return key.characters if hasattr(key, "characters") else key.name


def _index(obj: nodes.JSONObject, name: str) -> int | None:
    return next((i for i, key in enumerate(obj.keys) if _key_name(key) == name), None)


def _render(value: Any, indent: str, step: str) -> str:
    """JSON text for ``value``: objects span lines, lists of plain values stay on one line."""
    if isinstance(value, dict):
        if not value:
            return "{}"
        inner = indent + step
        members = ",\n".join(f"{inner}{json.dumps(k)}: {_render(v, inner, step)}" for k, v in value.items())
        return f"{{\n{members}\n{indent}}}"
    if isinstance(value, list):
        if not any(isinstance(item, (dict, list)) for item in value):
            return "[" + ", ".join(json.dumps(item, ensure_ascii=False) for item in value) + "]"
        inner = indent + step
        return "[\n" + ",\n".join(inner + _render(item, inner, step) for item in value) + f"\n{indent}]"
    return json.dumps(value, ensure_ascii=False)


def _node(value: Any, indent: str, step: str) -> nodes.Value:
    return _load_model(_render(value, indent, step), loader=ModelLoader()).value


def _key_node(name: str) -> nodes.Key:
    return _load_model(json.dumps(name), loader=ModelLoader()).value


def _line_indent(pieces: list) -> str | None:
    """The indentation that follows the last newline in a run of whitespace and comments."""
    breaks = [piece for piece in pieces if isinstance(piece, str) and "\n" in piece]
    return breaks[-1].rsplit("\n", 1)[1] if breaks else None


def _inner_indent(container: nodes.JSONObject | nodes.JSONArray) -> str | None:
    """How members of ``container`` are indented, or None if it is written on one line."""
    leads = container.keys if isinstance(container, nodes.JSONObject) else container.values
    if container.leading_wsc and (indent := _line_indent(container.leading_wsc)) is not None:
        return indent
    return _line_indent(leads[1].wsc_before) if len(leads) > 1 else None


def _split_closing(carried: list) -> tuple[list, list]:
    """Split whitespace-and-comments into (comments to keep with the last entry, whitespace before the bracket)."""
    if carried and isinstance(carried[-1], str):
        return carried[:-1], [carried[-1]]
    return carried, []


def _append(
    container: nodes.JSONObject | nodes.JSONArray,
    key: nodes.Key | None,
    value: nodes.Value,
    outer_indent: str,
    step: str,
) -> None:
    """Add a member to the end of ``container`` (``key`` is None for arrays)."""
    lead = key if key is not None else value
    if key is not None:
        value.wsc_before = [" "]

    if not container.values:
        if not any(not isinstance(p, str) for p in container.leading_wsc):
            container.leading_wsc = ["\n" + outer_indent + step] if key is not None else []
        value.wsc_after = ["\n" + outer_indent] if key is not None else []
    else:
        indent = _inner_indent(container)
        separator = ["\n" + indent] if indent is not None else [" "]
        last = container.values[-1]
        comma = container.trailing_comma
        carried, closing = _split_closing(list(comma.wsc_after if comma else last.wsc_after))
        lead.wsc_before = [*carried, *separator]
        if comma:
            comma.wsc_after, value.wsc_after = closing, []
        else:
            last.wsc_after, value.wsc_after = [], closing

    if key is not None:
        container.keys.append(key)
    container.values.append(value)


def _insert_after(obj: nodes.JSONObject, index: int, key: nodes.Key, value: nodes.Value) -> None:
    """Insert a member after the one at ``index`` (which must not be the last)."""
    following = obj.keys[index + 1]
    indent = _inner_indent(obj)
    key.wsc_before = following.wsc_before  # keeps any comment that belongs to the earlier entry
    following.wsc_before = ["\n" + indent] if indent is not None else [" "]
    value.wsc_before, value.wsc_after = [" "], []
    obj.keys.insert(index + 1, key)
    obj.values.insert(index + 1, value)


def _insert_first(obj: nodes.JSONObject, key: nodes.Key, value: nodes.Value) -> None:
    """Insert a member before all the others (``obj`` must not be empty)."""
    old_first = obj.keys[0]
    indent = _inner_indent(obj)
    before = obj.leading_wsc
    if indent is not None:  # multi-line: the new member takes the line, the old first member keeps its comments
        line_start = before[-1] if before and isinstance(before[-1], str) else "\n" + indent
        obj.leading_wsc = [line_start]
        old_first.wsc_before = before
    else:
        old_first.wsc_before = [" "]
    key.wsc_before = []
    value.wsc_before, value.wsc_after = [" "], []
    obj.keys.insert(0, key)
    obj.values.insert(0, value)


class JsoncDocument:
    """A parsed JSONC file whose edits keep comments and formatting."""

    def __init__(self, model: nodes.JSONText, data: dict):
        self._model = model
        self._expected = data
        self._step = _inner_indent(model.value) or _DEFAULT_STEP  # one level of the file's own indentation

    @classmethod
    def parse(cls, text: str) -> JsoncDocument:
        """Parse ``text``, which must be a JSON object.

        Raises:
            JsoncError: If it is not valid, is not an object, or would not be reproduced exactly
                by the parser (in which case editing it could change more than we intend).
        """
        try:
            model = _load_model(text, loader=ModelLoader())
            data = _parse_data(text)
        except Exception as e:  # json-five raises a variety of parser errors
            raise JsoncError(f"Not valid JSON with comments: {e}") from e
        if not isinstance(model.value, nodes.JSONObject) or not isinstance(data, dict):
            raise JsoncError("Expected a JSON object at the top level")
        if _dump_model(model, dumper=ModelDumper()) != text:
            raise JsoncError("This file cannot be edited without risking unrelated changes")
        return cls(model, data)

    @classmethod
    def empty(cls) -> JsoncDocument:
        return cls.parse("{}\n")

    @property
    def text(self) -> str:
        return _dump_model(self._model, dumper=ModelDumper())

    @property
    def data(self) -> dict:
        """The document as plain Python data (a copy)."""
        return copy.deepcopy(self._expected)

    def get(self, path: KeyPath, default: Any = None) -> Any:
        """The value at ``path``, or ``default`` if any part of it is missing."""
        current: Any = self._expected
        for name in path:
            if not isinstance(current, dict) or name not in current:
                return default
            current = current[name]
        return copy.deepcopy(current)

    def set(self, path: KeyPath, value: Any, *, after: str | None = None, first: bool = False) -> None:
        """Set the value at ``path``, creating the key (and any parent objects) if needed.

        A new key goes at the end of its object, or straight after the sibling named
        ``after`` if that exists, or at the very start if ``first`` is set. An existing key
        keeps its position.

        Raises:
            JsoncError: If a parent on the path exists but is not an object, or if the
                edited text fails verification (the document must then be discarded).
        """
        if not path:
            raise JsoncError("A path is required")
        existing = self._deepest_object(path[:-1])
        missing = path[len(existing) :]
        if len(missing) > 1:  # create the missing parents in one go
            value = self._nest(missing[1:], value)
        name, parent_path = missing[0], existing
        if len(missing) > 1:  # `after` and `first` describe the final key, not a parent we are creating
            after, first = None, False

        obj, outer = self._container(parent_path)
        inner = _inner_indent(obj) or outer + self._step
        at = _index(obj, name)
        if at is not None:
            replacement = _node(value, inner, self._step)
            replacement.wsc_before, replacement.wsc_after = obj.values[at].wsc_before, obj.values[at].wsc_after
            obj.values[at] = replacement
            self._expected_parent(parent_path)[name] = copy.deepcopy(value)
        else:
            anchor = _index(obj, after) if after is not None else None
            if first and obj.keys:
                _insert_first(obj, _key_node(name), _node(value, inner, self._step))
                position = 0
            elif anchor is None or anchor == len(obj.keys) - 1:
                _append(obj, _key_node(name), _node(value, inner, self._step), outer, self._step)
                position = None
            else:
                _insert_after(obj, anchor, _key_node(name), _node(value, inner, self._step))
                position = anchor + 1
            self._insert_expected(parent_path, name, value, position)
        self._verify()

    def append(self, path: KeyPath, item: Any) -> None:
        """Append ``item`` to the array at ``path``.

        Raises:
            JsoncError: If there is no array at ``path`` or the edit fails verification.
        """
        if not isinstance(self.get(path), list):
            raise JsoncError(f"There is no array at {'.'.join(path)}")
        array, outer = self._container(path)
        inner = _inner_indent(array) or outer + self._step
        _append(array, None, _node(item, inner, self._step), outer, self._step)
        self._expected_parent(path[:-1])[path[-1]].append(copy.deepcopy(item))
        self._verify()

    # --- internals ---------------------------------------------------------------------------

    def _deepest_object(self, path: KeyPath) -> KeyPath:
        """The longest prefix of ``path`` that exists as an object. Raises if one exists as something else."""
        current: Any = self._expected
        for depth, name in enumerate(path):
            if not isinstance(current, dict) or name not in current:
                return path[:depth]
            current = current[name]
            if not isinstance(current, dict):
                raise JsoncError(f"{'.'.join(path[: depth + 1])} exists but is not an object")
        return path

    @staticmethod
    def _nest(path: KeyPath, value: Any) -> Any:
        for name in reversed(path):
            value = {name: value}
        return value

    def _container(self, path: KeyPath) -> tuple[nodes.JSONObject | nodes.JSONArray, str]:
        """The node at ``path`` and the indentation of the line it starts on."""
        node: Any = self._model.value
        indent = ""
        for name in path:
            at = _index(node, name)
            if at is None:
                raise JsoncError(f"{'.'.join(path)} does not exist")
            indent = _inner_indent(node) or indent + self._step
            node = node.values[at]
        return node, indent

    def _expected_parent(self, path: KeyPath) -> dict:
        current = self._expected
        for name in path:
            current = current[name]
        return current

    def _insert_expected(self, parent_path: KeyPath, name: str, value: Any, position: int | None) -> None:
        parent = self._expected_parent(parent_path)
        items = list(parent.items())
        items.insert(len(items) if position is None else position, (name, copy.deepcopy(value)))
        parent.clear()
        parent.update(items)

    def _verify(self) -> None:
        try:
            actual = _parse_data(self.text)
        except Exception as e:
            raise JsoncError(f"The edit produced invalid JSON: {e}") from e
        if _ordered(actual) != _ordered(self._expected):
            raise JsoncError("The edit did not produce the expected result")
