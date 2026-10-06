"""Tests for registering the store in the OpenCode config."""

import json

import pytest

from idea_oc.jsonc_doc import JsoncDocument
from idea_oc.opencode_config import (
    ConfigError,
    ConfigState,
    default_config_path,
    ensure_skills_path,
    manual_snippet,
    skills_path_state,
)


@pytest.fixture
def store(tmp_path):
    return tmp_path / "data" / "skills"


@pytest.fixture
def config(tmp_path):
    return tmp_path / "opencode" / "opencode.json"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2))


def test_creates_config_when_missing(config, store):
    assert ensure_skills_path(config, store) is True

    assert json.loads(config.read_text()) == {"skills": {"paths": [str(store)]}}
    assert config.read_text().endswith("\n")


def test_preserves_everything_else_and_key_order(config, store):
    original = {"$schema": "https://opencode.ai/config.json", "model": "m", "mcp": {"a": {"type": "local"}}}
    write(config, original)

    ensure_skills_path(config, store)

    updated = json.loads(config.read_text())
    assert list(updated) == ["$schema", "model", "mcp", "skills"]
    assert {k: v for k, v in updated.items() if k != "skills"} == original


def test_existing_formatting_is_preserved_when_adding_the_block(config, store):
    original = '{\n  "instructions": ["rules/*.md"],\n  "mcp": {\n    "a": {"command": ["npx", "-y"]}\n  }\n}\n'
    write(config, original)

    ensure_skills_path(config, store)

    text = config.read_text()
    assert text.startswith(original.rstrip().removesuffix("}").rstrip())
    assert '"instructions": ["rules/*.md"]' in text
    assert '"command": ["npx", "-y"]' in text
    assert json.loads(text)["skills"] == {"paths": [str(store)]}


def test_block_is_added_to_an_empty_object(config, store):
    write(config, "{}")

    ensure_skills_path(config, store)

    assert json.loads(config.read_text()) == {"skills": {"paths": [str(store)]}}


def test_appends_to_existing_paths_and_keeps_other_skills_keys(config, store):
    write(config, {"skills": {"paths": ["~/mine"], "urls": ["https://x/"]}})

    ensure_skills_path(config, store)

    assert json.loads(config.read_text())["skills"] == {"paths": ["~/mine", str(store)], "urls": ["https://x/"]}


def test_is_idempotent_and_does_not_touch_the_file(config, store):
    ensure_skills_path(config, store)
    before = config.stat().st_mtime_ns

    assert ensure_skills_path(config, store) is False

    assert config.stat().st_mtime_ns == before
    assert json.loads(config.read_text())["skills"]["paths"] == [str(store)]


def test_backup_is_written_before_changing_an_existing_file(config, store):
    write(config, {"model": "m"})
    original = config.read_text()

    ensure_skills_path(config, store)

    assert config.with_name("opencode.json.idea-oc.bak").read_text() == original


def test_no_backup_when_nothing_existed(config, store):
    ensure_skills_path(config, store)

    assert not config.with_name("opencode.json.idea-oc.bak").exists()


def test_home_relative_store_is_written_with_tilde(config, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    store = tmp_path / ".local" / "share" / "idea-oc" / "skills"

    ensure_skills_path(config, store)

    assert json.loads(config.read_text())["skills"]["paths"] == ["~/.local/share/idea-oc/skills"]
    assert skills_path_state(config, store) is ConfigState.REGISTERED


def test_tilde_and_absolute_forms_are_recognised_as_the_same(config, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    store = tmp_path / "s"
    write(config, {"skills": {"paths": ["~/s"]}})

    assert ensure_skills_path(config, store) is False


def test_comments_and_formatting_in_the_config_survive(config, store):
    text = (
        "{\n"
        "  // my notes\n"
        '  "model": "m", // keep this\n'
        '  "permission": {\n'
        '    "bash": { "*": "allow" } /* block */\n'
        "  }\n"
        "}\n"
    )
    write(config, text)

    assert ensure_skills_path(config, store) is True

    updated = config.read_text()
    assert updated.startswith(text.rstrip().removesuffix("}").rstrip().removesuffix("}"))  # nothing above was touched
    assert "// my notes" in updated and "// keep this" in updated and "/* block */" in updated
    assert skills_path_state(config, store) is ConfigState.REGISTERED


def test_appends_to_an_existing_commented_paths_list(config, store):
    write(config, '{\n  "skills": {\n    "paths": [\n      "~/mine" // personal\n    ]\n  }\n}\n')

    ensure_skills_path(config, store)

    text = config.read_text()
    assert "// personal" in text
    assert skills_path_state(config, store) is ConfigState.REGISTERED
    assert JsoncDocument.parse(text).get(("skills", "paths"))[0] == "~/mine"


def test_trailing_commas_are_accepted(config, store):
    write(config, '{\n  "model": "m",\n}\n')

    ensure_skills_path(config, store)

    assert skills_path_state(config, store) is ConfigState.REGISTERED


def test_unparseable_config_is_never_rewritten(config, store):
    text = '{ "model": '
    write(config, text)

    with pytest.raises(ConfigError, match="cannot edit"):
        ensure_skills_path(config, store)

    assert config.read_text() == text
    assert not config.with_name("opencode.json.idea-oc.bak").exists()


@pytest.mark.parametrize("bad", ["[]", '{"skills": []}', '{"skills": {"paths": "x"}}', '{"skills": {"paths": [1]}}'])
def test_unexpected_shapes_are_rejected(config, store, bad):
    write(config, bad)

    with pytest.raises(ConfigError):
        ensure_skills_path(config, store)


def test_state_reporting(config, store):
    assert skills_path_state(config, store) is ConfigState.NO_FILE

    write(config, {"model": "m"})
    assert skills_path_state(config, store) is ConfigState.NOT_REGISTERED

    ensure_skills_path(config, store)
    assert skills_path_state(config, store) is ConfigState.REGISTERED


def test_state_of_unparseable_config_raises(config, store):
    write(config, "{oops")

    with pytest.raises(ConfigError):
        skills_path_state(config, store)


def test_manual_snippet_is_valid_json(store):
    assert json.loads(manual_snippet(store)) == {"skills": {"paths": [str(store)]}}


def test_default_config_path_follows_opencodes_own_order(monkeypatch, tmp_path):
    monkeypatch.delenv("IDEA_OC_CONFIG", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_dir = tmp_path / "opencode"

    assert default_config_path() == config_dir / "opencode.jsonc"  # nothing exists: what OpenCode would create

    config_dir.mkdir()
    (config_dir / "config.json").write_text("{}")
    assert default_config_path() == config_dir / "config.json"

    (config_dir / "opencode.json").write_text("{}")
    assert default_config_path() == config_dir / "opencode.json"

    (config_dir / "opencode.jsonc").write_text("{}")
    assert default_config_path() == config_dir / "opencode.jsonc"  # wins when both exist

    monkeypatch.setenv("IDEA_OC_CONFIG", str(tmp_path / "x.json"))
    assert default_config_path() == tmp_path / "x.json"
