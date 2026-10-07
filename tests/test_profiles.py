"""Tests for the per-team Bedrock inference profiles."""

import copy

import pytest

from idea_oc.profiles import (
    ModelSpec,
    Profiles,
    ProfilesError,
    TeamChoice,
    choose_team,
    load_profiles,
)
from idea_oc.team_config import desired_config, team_config


@pytest.fixture(scope="module")
def profiles() -> Profiles:
    return load_profiles()


def raw(profiles: Profiles) -> dict:
    return profiles.model_dump()


# --- the bundled data -------------------------------------------------------------------------


def test_the_bundled_profiles_cover_the_three_teams_with_ds_as_the_default(profiles):
    assert set(profiles.teams) == {"ds", "sds", "econ"}
    assert profiles.default_team == "ds"


def test_every_team_has_its_own_profile(profiles):
    assert len(set(profiles.teams.values())) == len(profiles.teams)
    assert len({profiles.arn(team) for team in profiles.teams}) == len(profiles.teams)


def test_an_arn_is_built_from_the_account_region_and_profile_id(profiles):
    assert profiles.arn("ds") == ("arn:aws:bedrock:eu-west-2:992382722318:application-inference-profile/4niqtfvd2b0y")


def test_each_team_gets_its_own_model_key_that_keeps_prompt_caching_on(profiles):
    keys = {team: profiles.model_key(team) for team in profiles.teams}

    assert len(set(keys.values())) == len(keys)
    # OpenCode decides whether to cache prompts from the key, not from the ARN
    assert all("claude" in key and "anthropic" in key for key in keys.values())


def test_the_model_reference_names_the_bedrock_provider_and_the_key(profiles):
    assert profiles.model_ref("sds") == "amazon-bedrock/anthropic-claude-sonnet-5-5-sds"


# --- the model entry written to a user's config ----------------------------------------------


def test_the_entry_points_at_the_profile_and_restates_what_the_arn_cannot_say(profiles):
    entry = profiles.model_entry("econ")

    assert entry["id"] == profiles.arn("econ")
    assert entry["limit"] == {"context": 1_000_000, "output": 128_000}
    assert (entry["tool_call"], entry["attachment"], entry["temperature"]) == (True, True, False)
    assert entry["modalities"] == {"input": ["text", "image", "pdf"], "output": ["text"]}
    assert entry["cost"] == {"input": 2.2, "output": 11.0, "cache_read": 0.22, "cache_write": 2.75}


def test_the_entry_names_the_team_so_it_shows_in_opencodes_model_list(profiles):
    assert profiles.model_entry("sds")["name"] == "Claude Sonnet 5.5 (sds)"


def test_reasoning_is_switched_off_so_opencode_adds_no_reasoning_settings_of_its_own(profiles):
    """With it on, OpenCode treats an ARN as an Amazon Nova model and adds ``reasoningConfig``, which Bedrock
    rejects for Claude ("Extra inputs are not permitted"), so every reasoning level fails."""
    assert profiles.model_entry("ds")["reasoning"] is False


def test_every_reasoning_level_is_offered_as_raw_claude_request_fields(profiles):
    variants = profiles.model_entry("ds")["variants"]

    assert list(variants) == ["low", "medium", "high", "xhigh", "max"]
    for effort, variant in variants.items():
        assert variant == {
            "additionalModelRequestFields": {
                "thinking": {"type": "adaptive", "display": "summarized"},
                "output_config": {"effort": effort},
            }
        }


def test_no_variant_carries_the_amazon_nova_field_bedrock_rejects_for_claude(profiles):
    assert "reasoningConfig" not in str(profiles.model_entry("ds")["variants"])


def test_the_entry_is_independent_between_calls(profiles):
    entry = profiles.model_entry("ds")
    entry["limit"]["context"] = 1
    entry["modalities"]["input"].append("audio")
    entry["cost"]["input"] = 99

    fresh = profiles.model_entry("ds")
    assert fresh["limit"]["context"] == 1_000_000
    assert fresh["modalities"]["input"] == ["text", "image", "pdf"]
    assert fresh["cost"]["input"] == 2.2


# --- validation -------------------------------------------------------------------------------


def broken(profiles: Profiles, **changes) -> dict:
    data = copy.deepcopy(raw(profiles))
    for key, value in changes.items():
        data[key] = value
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"teams": {}}, "at least one team"),
        ({"teams": {"ds": "short"}}, "12 lowercase"),
        ({"teams": {"ds": "UPPERCASE123"}}, "12 lowercase"),
        ({"teams": {"ds": "4niqtfvd2b0y", "sds": "4niqtfvd2b0y"}}, "share a profile id"),
        ({"teams": {"Bad Team": "4niqtfvd2b0y"}, "default_team": "Bad Team"}, "lowercase letters"),
        ({"default_team": "nobody"}, "not one of"),
        ({"account": "123"}, "12-digit"),
    ],
)
def test_invalid_profiles_are_rejected(profiles, change, message):
    with pytest.raises(ValueError, match=message):
        Profiles(**broken(profiles, **change))


@pytest.mark.parametrize("key", ["sonnet-5-5", "anthropic-sonnet", "claude-sonnet", "gpt"])
def test_a_model_key_that_would_switch_off_prompt_caching_is_rejected(profiles, key):
    spec = {**raw(profiles)["model"], "key": key}

    with pytest.raises(ValueError, match="claude' and 'anthropic"):
        ModelSpec(**spec)


def test_unknown_team_names_the_valid_ones(profiles):
    with pytest.raises(ProfilesError, match="Unknown team 'nobody'. The teams are: ds, econ, sds"):
        profiles.check_team("nobody")


# --- working out a user's current team --------------------------------------------------------


def config_with_model(profiles: Profiles, team: str, *, key: str | None = None) -> dict:
    key = key or profiles.model_key(team)
    return {
        "model": f"amazon-bedrock/{key}",
        "provider": {"amazon-bedrock": {"models": {key: {"id": profiles.arn(team)}}}},
    }


@pytest.mark.parametrize("team", ["ds", "sds", "econ"])
def test_the_team_is_recognised_from_the_key_idea_oc_writes(profiles, team):
    assert profiles.team_of({"model": profiles.model_ref(team)}) == team


def test_the_team_is_recognised_when_the_user_renamed_the_key_but_kept_the_arn(profiles):
    assert profiles.team_of(config_with_model(profiles, "econ", key="my-claude")) == "econ"


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"model": "amazon-bedrock/eu.anthropic.claude-sonnet-5-5"},
        {"model": "anthropic/claude-sonnet-4-5"},
        {"model": 42},
        {"model": "amazon-bedrock/unknown-key"},
        {"model": "amazon-bedrock/my-claude", "provider": {"amazon-bedrock": {"models": {"my-claude": {"id": "x"}}}}},
        {"model": "amazon-bedrock/my-claude", "provider": "not an object"},
    ],
)
def test_a_config_not_using_a_team_profile_has_no_team(profiles, config):
    assert profiles.team_of(config) is None


# --- choosing the team ------------------------------------------------------------------------


def test_the_flag_wins_over_everything(profiles):
    choice = choose_team(profiles, "econ", {"model": profiles.model_ref("sds")})

    assert choice == TeamChoice("econ", "flag")


def test_without_a_flag_the_current_teams_is_kept(profiles):
    assert choose_team(profiles, None, {"model": profiles.model_ref("sds")}) == TeamChoice("sds", "config")


def test_otherwise_the_default_team_is_used(profiles):
    assert choose_team(profiles, None, {}) == TeamChoice("ds", "default")
    assert choose_team(profiles, None, {"model": "amazon-bedrock/eu.anthropic.claude-sonnet-5-5"}).source == "default"


def test_an_unknown_flag_is_an_error_even_when_the_config_has_a_team(profiles):
    with pytest.raises(ProfilesError):
        choose_team(profiles, "nobody", {"model": profiles.model_ref("sds")})


@pytest.mark.parametrize(("source", "text"), [("flag", "--team"), ("config", "current model"), ("default", "default")])
def test_each_choice_explains_itself(source, text):
    assert text in TeamChoice("ds", source).explanation


# --- the generated config ---------------------------------------------------------------------


def test_the_bundled_preferred_config_is_exactly_the_default_teams_variant(profiles):
    """The file people copy by hand and the config the tool writes must be the same thing."""
    assert team_config().data == desired_config(profiles.default_team)


@pytest.mark.parametrize("team", ["ds", "sds", "econ"])
def test_a_teams_config_uses_only_its_own_profile(profiles, team):
    data = desired_config(team)

    assert data["model"] == profiles.model_ref(team)
    assert list(data["provider"]["amazon-bedrock"]["models"]) == [profiles.model_key(team)]
    others = [profiles.teams[t] for t in profiles.teams if t != team]
    assert not any(other in str(data) for other in others), "another team's profile leaked into this config"


def test_teams_differ_only_in_their_profile(profiles):
    ds, sds = desired_config("ds"), desired_config("sds")
    for data in (ds, sds):
        data["model"] = "x"
        data["provider"]["amazon-bedrock"]["models"] = {}

    assert ds == sds


def test_the_small_model_is_left_to_opencode(profiles):
    """Titles and other background calls are not worth tracking, so the config does not set small_model."""
    assert all("small_model" not in desired_config(team) for team in profiles.teams)


def test_an_unknown_team_cannot_be_generated():
    with pytest.raises(ProfilesError):
        desired_config("nobody")
