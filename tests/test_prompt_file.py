"""The Claude prompt file that agents on an inference profile use.

OpenCode picks its instructions from the model id, and a profile's id is an ARN that does not name the
model, so the agents are pointed at a copy of the Claude instructions. OpenCode refuses to start if a
file it is told to read is missing, so these tests are mostly about never leaving that reference without
its file.
"""

import json
import os
from importlib.resources import files
from pathlib import Path

import pytest

from idea_oc.cli import cli
from idea_oc.jsonc_doc import JsoncDocument
from idea_oc.opencode_config import apply_plan, plan_config
from idea_oc.prompts import (
    AGENTS,
    PROMPT_REF,
    PromptState,
    bundled_prompt,
    prompt_path,
    prompt_state,
    references_prompt,
    write_prompt,
)
from idea_oc.team_config import desired_config, plan_changes

STORE = Path("/home/u/.local/share/idea-oc/skills")


@pytest.fixture
def config_file():
    return Path(os.environ["IDEA_OC_CONFIG"])


@pytest.fixture
def prompt_file(config_file):
    return prompt_path(config_file)


def read(config_file: Path) -> dict:
    return json.loads(config_file.read_text())


def sync(cli_runner, *args, input=None):
    return cli_runner.invoke(cli, ["sync", "config", *args], input=input)


# --- the bundled copy -------------------------------------------------------------------------


def test_the_bundled_prompt_is_the_opencode_claude_prompt():
    text = bundled_prompt().decode()

    assert text.startswith("You are OpenCode, the best coding agent on the planet.")
    assert len(text) > 5000


def test_the_copy_differs_from_upstream_only_by_the_trailing_space_the_notice_declares():
    """Fetching upstream would need the network, so check the properties that make the notice true."""
    lines = bundled_prompt().decode().splitlines()

    assert lines[71] == "-"  # upstream has "- " here: line 72
    assert not any(line != line.rstrip() for line in lines)  # so the repo's whitespace hook leaves it alone
    assert "line 72" in files("idea_oc").joinpath("prompts/NOTICE.md").read_text()


def test_the_licence_notice_that_goes_with_the_copy_ships_too():
    notice = files("idea_oc").joinpath("prompts/NOTICE.md").read_text()

    assert "MIT License" in notice and "anthropic.txt" in notice


def test_the_prompt_is_referenced_relative_to_the_config_and_lives_beside_it(config_file, prompt_file):
    assert prompt_file == config_file.parent / "prompts" / "idea-oc-anthropic.txt"
    assert PROMPT_REF == "{file:./prompts/idea-oc-anthropic.txt}"


# --- state ------------------------------------------------------------------------------------


def test_prompt_state_tells_missing_current_and_different_apart(config_file):
    assert prompt_state(config_file) is PromptState.MISSING

    write_prompt(config_file)
    assert prompt_state(config_file) is PromptState.CURRENT

    prompt_path(config_file).write_text("edited")
    assert prompt_state(config_file) is PromptState.DIFFERENT


def test_writing_the_prompt_is_atomic_and_leaves_no_temporary_files(config_file):
    write_prompt(config_file)

    assert [p.name for p in prompt_path(config_file).parent.iterdir()] == ["idea-oc-anthropic.txt"]


# --- what the preferred config asks for -------------------------------------------------------


def test_the_agents_with_no_instructions_of_their_own_are_pointed_at_the_file():
    agents = desired_config("ds")["agent"]

    assert set(agents) == {"build", "plan", "general"} == set(AGENTS)
    assert all(agent == {"prompt": PROMPT_REF} for agent in agents.values())


def test_agents_that_carry_their_own_instructions_are_not_touched():
    agents = desired_config("ds")["agent"]

    assert not {"explore", "compaction", "title", "summary"} & set(agents)


def test_each_team_gets_the_same_prompt_setting(config_file):
    assert desired_config("ds")["agent"] == desired_config("sds")["agent"] == desired_config("econ")["agent"]


def test_a_prompt_of_the_users_own_is_never_replaced_and_they_are_told():
    user = JsoncDocument.parse('{"agent": {"build": {"prompt": "{file:./mine.txt}"}}}\n')

    plan = plan_changes(user, STORE, "~/s", desired_config("ds"))

    assert not any(change.path == ("agent", "build", "prompt") for change in plan.changes)
    assert any("agent.build.prompt is already set to a prompt of your own" in note for note in plan.notes)
    assert {change.path for change in plan.changes} >= {("agent", "plan", "prompt"), ("agent", "general", "prompt")}


def test_other_settings_on_an_agent_are_kept_when_the_prompt_is_added():
    user = JsoncDocument.parse('{"agent": {"build": {"temperature": 0.2}}}\n')
    apply = plan_changes(user, STORE, "~/s", desired_config("ds"))
    from idea_oc.team_config import apply_changes

    apply_changes(user, apply.changes)

    assert user.get(("agent", "build")) == {"temperature": 0.2, "prompt": PROMPT_REF}


def test_the_plan_knows_whether_the_config_will_refer_to_the_file():
    refers = plan_changes(JsoncDocument.empty(), STORE, "~/s", desired_config("ds"))
    own = JsoncDocument.parse(
        '{"agent": {"build": {"prompt": "x"}, "plan": {"prompt": "x"}, "general": {"prompt": "x"}}}\n'
    )
    does_not = plan_changes(own, STORE, "~/s", desired_config("ds"))

    assert refers.uses_prompt_file is True
    assert does_not.uses_prompt_file is False  # all three are the user's own, so nothing refers to the file


def test_references_prompt_only_matches_our_file():
    assert references_prompt({"agent": {"build": {"prompt": PROMPT_REF}}})
    assert not references_prompt({"agent": {"build": {"prompt": "{file:./other.txt}"}}})
    assert not references_prompt({"agent": "nope"})
    assert not references_prompt({})


# --- applying: the file always arrives before the references to it -----------------------------


def test_applying_writes_the_file_and_the_config_that_refers_to_it(cli_runner, config_file, prompt_file):
    result = sync(cli_runner, "--yes")

    assert result.exit_code == 0, result.output
    assert prompt_file.read_bytes() == bundled_prompt()
    assert read(config_file)["agent"]["build"]["prompt"] == PROMPT_REF
    assert "add     prompts/idea-oc-anthropic.txt" in result.output


def test_a_failed_config_edit_does_not_leave_a_prompt_file_behind(config_file, prompt_file, monkeypatch):
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}\n")
    config = plan_config(config_file, STORE)

    def broken(*args, **kwargs):
        raise RuntimeError("disk full while writing the config")

    monkeypatch.setattr("idea_oc.opencode_config._write_atomically", broken)

    with pytest.raises(RuntimeError):
        apply_plan(config, config_file)

    assert config_file.read_text() == "{}\n"  # untouched
    # the prompt file was written first and that is the safe order: a file nobody refers to is harmless
    assert not references_prompt(read(config_file))


def test_an_edit_that_cannot_be_made_writes_nothing_at_all(config_file, prompt_file, monkeypatch):
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}\n")
    config = plan_config(config_file, STORE)
    from idea_oc.jsonc_doc import JsoncError

    def refuse(document, changes):
        raise JsoncError("nope")

    monkeypatch.setattr("idea_oc.opencode_config.apply_changes", refuse)

    with pytest.raises(Exception, match="cannot edit"):
        apply_plan(config, config_file)

    assert not prompt_file.exists()


def test_a_second_sync_has_nothing_to_do(cli_runner, config_file):
    sync(cli_runner, "--yes")

    result = sync(cli_runner, "--yes")

    assert "Config is up to date." in result.output
    assert "prompts/" not in result.output


# --- declining --------------------------------------------------------------------------------


def test_declining_saves_the_file_the_proposal_needs_but_leaves_the_config_alone(cli_runner, config_file, prompt_file):
    config_file.parent.mkdir(parents=True)
    config_file.write_text('{"model": "old"}\n')

    result = sync(cli_runner, input="n\n")

    assert config_file.read_text() == '{"model": "old"}\n'
    proposal = JsoncDocument.parse(config_file.with_name(f"{config_file.name}.new").read_text())
    assert proposal.get(("agent", "build", "prompt")) == PROMPT_REF
    assert prompt_file.read_bytes() == bundled_prompt()  # so merging the proposal cannot break OpenCode
    assert "OpenCode will not start without it" in result.output


def test_declining_never_replaces_a_prompt_file_that_is_already_there(cli_runner, config_file, prompt_file):
    config_file.parent.mkdir(parents=True)
    config_file.write_text("{}\n")
    prompt_file.parent.mkdir(parents=True)
    prompt_file.write_text("the user's version")

    sync(cli_runner, input="n\n")

    assert prompt_file.read_text() == "the user's version"


def test_a_dry_run_lists_the_file_but_writes_nothing(cli_runner, config_file, prompt_file):
    result = sync(cli_runner, "--dry-run")

    assert "add     prompts/idea-oc-anthropic.txt" in result.output
    assert not prompt_file.exists() and not config_file.exists()


# --- an out-of-date file ----------------------------------------------------------------------


def test_a_different_prompt_file_is_offered_as_an_update_and_replaced_when_accepted(
    cli_runner, config_file, prompt_file
):
    sync(cli_runner, "--yes")
    prompt_file.write_text("an older copy")

    shown = sync(cli_runner, "--dry-run")
    applied = sync(cli_runner, "--yes")

    assert "update  prompts/idea-oc-anthropic.txt" in shown.output
    assert prompt_file.read_bytes() == bundled_prompt()
    assert "Updated" in applied.output


# --- a config that refers to a missing file ---------------------------------------------------


def test_status_says_loudly_when_the_config_refers_to_a_file_that_is_gone(cli_runner, config_file, prompt_file):
    sync(cli_runner, "--yes")
    prompt_file.unlink()

    result = cli_runner.invoke(cli, ["status", "config"])

    assert result.exit_code == 1
    assert "OpenCode will not start" in result.output
    assert "add     prompts/idea-oc-anthropic.txt" in result.output


def test_the_missing_file_warning_survives_quiet_mode(cli_runner, config_file, prompt_file):
    sync(cli_runner, "--yes")
    prompt_file.unlink()

    result = cli_runner.invoke(cli, ["status", "config", "--quiet"])

    assert "OpenCode will not start" in result.output


def test_sync_puts_a_deleted_file_back_and_says_why(cli_runner, config_file, prompt_file):
    sync(cli_runner, "--yes")
    prompt_file.unlink()

    result = sync(cli_runner, "--yes")

    assert "OpenCode will not start" in result.output
    assert prompt_file.read_bytes() == bundled_prompt()
    assert cli_runner.invoke(cli, ["status", "config", "--quiet"]).output == ""


def test_a_healthy_setup_has_no_warning(cli_runner, config_file):
    sync(cli_runner, "--yes")

    result = cli_runner.invoke(cli, ["status", "config"])

    assert result.exit_code == 0
    assert "will not start" not in result.output


def test_a_user_with_prompts_of_their_own_is_not_given_the_file(cli_runner, config_file, prompt_file):
    config_file.parent.mkdir(parents=True)
    own = {a: {"prompt": "x"} for a in AGENTS}
    config_file.write_text(json.dumps({"agent": own}))

    result = sync(cli_runner, "--yes")

    assert not prompt_file.exists()
    assert "prompts/idea-oc-anthropic.txt" not in result.output
    assert read(config_file)["agent"] == own
