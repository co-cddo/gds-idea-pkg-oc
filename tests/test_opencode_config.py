"""Tests for reading, planning and writing the user's OpenCode config."""

import json
from pathlib import Path

import pytest

from idea_oc.jsonc_doc import JsoncDocument
from idea_oc.opencode_config import (
    ConfigError,
    ConfigState,
    apply_plan,
    backup_path,
    clear_proposal,
    default_config_path,
    manual_snippet,
    plan_config,
    proposal_path,
    skills_path_state,
    store_config_value,
    write_proposal,
)
from idea_oc.team_config import team_config


@pytest.fixture
def store(tmp_path):
    return tmp_path / "data" / "skills"


@pytest.fixture
def config(tmp_path):
    return tmp_path / "opencode" / "opencode.jsonc"


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data, indent=2))


def team_data() -> dict:
    data = team_config().data
    data.pop("plugin")
    data.pop("$schema")
    return data


# --- planning -------------------------------------------------------------------------------


def test_a_missing_file_is_planned_as_a_new_config(config, store):
    result = plan_config(config, store)

    assert result.exists is False
    assert result.plan.pending


def test_a_config_that_matches_the_team_has_nothing_to_do(config, store):
    ready = team_config().text
    ready = JsoncDocument.parse(ready)
    ready.set(("skills", "paths"), [str(store)])
    write(config, ready.text)

    assert plan_config(config, store).plan.pending is False


def test_unparseable_config_is_an_error_naming_the_file(config, store):
    write(config, '{ "model": ')

    with pytest.raises(ConfigError, match="cannot edit"):
        plan_config(config, store)


def test_malformed_skill_paths_are_an_error(config, store):
    write(config, {"skills": {"paths": "x"}})

    with pytest.raises(ConfigError, match="skills.paths"):
        plan_config(config, store)


def test_planning_never_writes_anything(config, store):
    write(config, '{"model": "old"}\n')
    before = config.read_text()

    plan_config(config, store)

    assert config.read_text() == before
    assert not backup_path(config).exists() and not proposal_path(config).exists()


# --- applying -------------------------------------------------------------------------------


def test_applying_changes_the_file_and_saves_a_backup_of_the_original(config, store):
    original = '{\n  // my notes\n  "model": "old" // keep\n}\n'
    write(config, original)

    apply_plan(plan_config(config, store), config)

    updated = config.read_text()
    assert "// my notes" in updated and "// keep" in updated
    assert JsoncDocument.parse(updated).get(("model",)) == team_data()["model"]
    assert backup_path(config).read_text() == original


def test_applying_to_a_missing_file_creates_it_without_a_backup(config, store):
    apply_plan(plan_config(config, store), config)

    document = JsoncDocument.parse(config.read_text())
    assert document.get(("permission", "bash", "gh pr merge *")) == "deny"
    assert document.get(("skills", "paths")) == [store_config_value(store)]
    assert not backup_path(config).exists()


def test_applying_makes_the_config_match_so_a_second_plan_is_empty(config, store):
    write(config, '{"model": "old"}\n')

    apply_plan(plan_config(config, store), config)

    assert plan_config(config, store).plan.pending is False
    assert skills_path_state(config, store) is ConfigState.REGISTERED


def test_applying_removes_an_out_of_date_proposal(config, store):
    write(config, '{"model": "old"}\n')
    stale = proposal_path(config)
    stale.write_text("stale")

    apply_plan(plan_config(config, store), config)

    assert not stale.exists()


def test_a_failed_edit_leaves_the_file_and_backup_alone(config, store, monkeypatch):
    write(config, '{"model": "old"}\n')
    original = config.read_text()
    from idea_oc import team_config as module

    def broken(document, changes):
        raise module.JsoncError("nope")

    monkeypatch.setattr("idea_oc.opencode_config.apply_changes", broken)

    with pytest.raises(ConfigError, match="cannot edit"):
        apply_plan(plan_config(config, store), config)

    assert config.read_text() == original
    assert not backup_path(config).exists()


# --- proposals ------------------------------------------------------------------------------


def test_a_proposal_is_the_config_with_the_changes_applied_and_the_original_is_untouched(config, store):
    original = '{\n  "model": "old" // keep\n}\n'
    write(config, original)

    path, _ = write_proposal(plan_config(config, store), config)

    assert path == proposal_path(config) == config.with_name("opencode.jsonc.new")
    assert config.read_text() == original
    assert "// keep" in path.read_text()
    assert JsoncDocument.parse(path.read_text()).get(("model",)) == team_data()["model"]
    assert not backup_path(config).exists()


def test_a_proposal_for_a_missing_config_is_a_complete_new_config(config, store):
    path, _ = write_proposal(plan_config(config, store), config)

    assert not config.exists()
    assert JsoncDocument.parse(path.read_text()).get(("model",)) == team_data()["model"]


def test_a_new_proposal_replaces_the_previous_one(config, store):
    write(config, '{"model": "old"}\n')
    proposal_path(config).write_text("stale")

    write_proposal(plan_config(config, store), config)

    assert proposal_path(config).read_text() != "stale"


def test_clearing_a_missing_proposal_is_fine(config):
    clear_proposal(config)


# --- state and paths ------------------------------------------------------------------------


def test_state_reporting(config, store):
    assert skills_path_state(config, store) is ConfigState.NO_FILE

    write(config, {"model": "m"})
    assert skills_path_state(config, store) is ConfigState.NOT_REGISTERED

    write(config, {"skills": {"paths": [str(store)]}})
    assert skills_path_state(config, store) is ConfigState.REGISTERED


def test_state_of_unparseable_config_raises(config, store):
    write(config, "{oops")

    with pytest.raises(ConfigError):
        skills_path_state(config, store)


def test_tilde_and_absolute_forms_of_the_store_both_count_as_registered(config, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    store = tmp_path / ".local" / "share" / "idea-oc" / "skills"
    write(config, {"skills": {"paths": ["~/.local/share/idea-oc/skills"]}})

    assert skills_path_state(config, store) is ConfigState.REGISTERED


def test_the_store_is_written_with_a_tilde_when_under_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    assert store_config_value(tmp_path / ".local" / "share" / "idea-oc" / "skills") == "~/.local/share/idea-oc/skills"
    assert store_config_value(Path("/opt/elsewhere/skills")) == "/opt/elsewhere/skills"


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
