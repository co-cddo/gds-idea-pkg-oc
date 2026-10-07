"""Bedrock application inference profiles: one per team, so each team's usage is tracked separately.

Pointing OpenCode at a profile instead of the model itself sends the same requests to the same model,
but Bedrock attributes the usage (and cost) to the profile. A profile is addressed by ARN, and OpenCode
works out what a model can do from its id, which an ARN does not describe, so this module also produces
the model settings that must be restated alongside it.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

PROVIDER = "amazon-bedrock"
_PROFILE_ID = re.compile(r"^[a-z0-9]{12}$")
_TEAM_NAME = re.compile(r"^[a-z][a-z0-9-]*$")


class ProfilesError(Exception):
    """Raised when the profiles file is invalid, or a team is not one of the configured teams."""


class Cost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: float
    output: float
    cache_read: float
    cache_write: float


class ModelSpec(BaseModel):
    """What OpenCode needs restated about the model behind a profile.

    Attributes:
        key: The name OpenCode lists the model under, before the team is added. It must contain
            ``claude`` and ``anthropic``: OpenCode decides whether to cache prompts from the key.
        efforts: The reasoning effort levels the model offers.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    family: str
    release_date: str
    context: int = Field(gt=0)
    output: int = Field(gt=0)
    input_modalities: list[str]
    output_modalities: list[str]
    reasoning: bool
    tool_call: bool
    attachment: bool
    temperature: bool
    efforts: list[str]
    cost: Cost

    @field_validator("key")
    @classmethod
    def _key_enables_caching(cls, value: str) -> str:
        if "claude" not in value or "anthropic" not in value:
            raise ValueError("key must contain 'claude' and 'anthropic', or OpenCode will not cache prompts")
        return value


class Profiles(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default_team: str
    account: str
    region: str
    teams: dict[str, str]
    model: ModelSpec

    @field_validator("account")
    @classmethod
    def _account(cls, value: str) -> str:
        if not re.fullmatch(r"\d{12}", value):
            raise ValueError("account must be a 12-digit AWS account id")
        return value

    @field_validator("teams")
    @classmethod
    def _teams(cls, value: dict[str, str]) -> dict[str, str]:
        if not value:
            raise ValueError("at least one team is required")
        for team, profile_id in value.items():
            if not _TEAM_NAME.match(team):
                raise ValueError(f"team name {team!r} must be lowercase letters, digits and hyphens")
            if not _PROFILE_ID.match(profile_id):
                raise ValueError(f"profile id {profile_id!r} for {team} must be 12 lowercase letters or digits")
        if len(set(value.values())) != len(value):
            raise ValueError("two teams share a profile id")
        return value

    @model_validator(mode="after")
    def _default_is_a_team(self) -> Profiles:
        if self.default_team not in self.teams:
            raise ValueError(f"default_team {self.default_team!r} is not one of {sorted(self.teams)}")
        return self

    def check_team(self, team: str) -> str:
        """Return ``team`` if it is configured.

        Raises:
            ProfilesError: Naming the valid teams.
        """
        if team not in self.teams:
            raise ProfilesError(f"Unknown team {team!r}. The teams are: {', '.join(sorted(self.teams))}")
        return team

    def arn(self, team: str) -> str:
        return f"arn:aws:bedrock:{self.region}:{self.account}:application-inference-profile/{self.teams[team]}"

    def model_key(self, team: str) -> str:
        """The name OpenCode lists this team's profile under."""
        return f"{self.model.key}-{team}"

    def model_ref(self, team: str) -> str:
        """The value for OpenCode's ``model`` setting."""
        return f"{PROVIDER}/{self.model_key(team)}"

    def model_entry(self, team: str) -> dict[str, Any]:
        """The ``provider.amazon-bedrock.models`` entry for ``team``, in OpenCode's config shape."""
        spec = self.model
        thinking = {"type": "adaptive", "display": "summarized"}
        return {
            "id": self.arn(team),
            "name": f"{spec.name} ({team})",
            "family": spec.family,
            "release_date": spec.release_date,
            "reasoning": spec.reasoning,
            "tool_call": spec.tool_call,
            "attachment": spec.attachment,
            "temperature": spec.temperature,
            "modalities": {"input": list(spec.input_modalities), "output": list(spec.output_modalities)},
            "limit": {"context": spec.context, "output": spec.output},
            "cost": spec.cost.model_dump(),
            "variants": {
                effort: {"reasoningConfig": {**thinking, "maxReasoningEffort": effort}} for effort in spec.efforts
            },
        }

    def team_of(self, config: dict) -> str | None:
        """The team a config already uses, judged from its ``model`` setting, or None if it uses none.

        Recognises both the key idea-oc writes and any other key whose ``id`` is a team's profile ARN.
        """
        model = config.get("model")
        if not isinstance(model, str) or not model.startswith(f"{PROVIDER}/"):
            return None
        key = model.removeprefix(f"{PROVIDER}/")
        for team in self.teams:
            if key == self.model_key(team):
                return team

        provider = config.get("provider")
        models = provider.get(PROVIDER, {}).get("models", {}) if isinstance(provider, dict) else {}
        entry = models.get(key) if isinstance(models, dict) else None
        arn = entry.get("id") if isinstance(entry, dict) else None
        return next((team for team in self.teams if arn == self.arn(team)), None)


@dataclass(frozen=True)
class TeamChoice:
    """Which team a sync is for, and how that was decided.

    Attributes:
        team: The team name.
        source: ``flag`` (--team), ``config`` (the user's model already uses it) or ``default``.
    """

    team: str
    source: str

    @property
    def explanation(self) -> str:
        return {
            "flag": "chosen with --team",
            "config": "kept from your current model",
            "default": "the default",
        }[self.source]


def load_profiles() -> Profiles:
    """Load the profiles bundled with idea-oc.

    Raises:
        ProfilesError: If the file is invalid.
    """
    text = files("idea_oc").joinpath("profiles.toml").read_text()
    try:
        return Profiles(**tomllib.loads(text))
    except (tomllib.TOMLDecodeError, ValidationError) as e:
        raise ProfilesError(f"Invalid profiles file: {e}") from e


def choose_team(profiles: Profiles, flag: str | None, config: dict) -> TeamChoice:
    """Pick the team: the ``--team`` flag, else the one the user's model already uses, else the default.

    Raises:
        ProfilesError: If ``flag`` is not a configured team.
    """
    if flag is not None:
        return TeamChoice(profiles.check_team(flag), "flag")
    if (current := profiles.team_of(config)) is not None:
        return TeamChoice(current, "config")
    return TeamChoice(profiles.default_team, "default")
