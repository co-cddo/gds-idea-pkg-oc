"""Pydantic models for the skill registry."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_REPO_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")


def _normalise_path(value: str) -> str:
    """Validate a repo-relative path and return it without leading or trailing slashes."""
    path = PurePosixPath(value.strip("/"))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid repo path: {value!r}")
    return str(path)


class Source(BaseModel):
    """A GitHub repository that provides one or more skills.

    Exactly one of ``discover`` or ``skills`` must be set.

    Attributes:
        repo: Repository as ``owner/name``.
        ref: ``latest`` (newest release, else default branch) or a tag, branch or commit SHA.
        discover: Folder whose subfolders containing ``SKILL.md`` are all installed.
        skills: Explicit paths, each a skill folder or a ``SKILL.md`` file.
        exclude: Skill folder names to skip when using ``discover``.
    """

    model_config = ConfigDict(extra="forbid")

    repo: str
    ref: str = "latest"
    discover: str | None = None
    skills: list[str] | None = None
    exclude: list[str] = Field(default_factory=list)

    @field_validator("repo")
    @classmethod
    def _check_repo(cls, value: str) -> str:
        if not _REPO_PATTERN.match(value):
            raise ValueError(f"repo must be 'owner/name', got {value!r}")
        return value

    @field_validator("discover")
    @classmethod
    def _check_discover(cls, value: str | None) -> str | None:
        return None if value is None else _normalise_path(value)

    @field_validator("skills")
    @classmethod
    def _check_skills(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if not value:
            raise ValueError("skills must not be empty")
        return [_normalise_path(item) for item in value]

    @model_validator(mode="after")
    def _check_mode(self) -> Source:
        if (self.discover is None) == (self.skills is None):
            raise ValueError("set exactly one of 'discover' or 'skills'")
        if self.exclude and self.discover is None:
            raise ValueError("'exclude' can only be used with 'discover'")
        return self

    @property
    def owner(self) -> str:
        return self.repo.split("/", 1)[0]


class Registry(BaseModel):
    """The approved set of skill sources.

    Attributes:
        allowed_owners: GitHub owners that sources may come from.
        source: Approved sources, declared as ``[[source]]`` tables in TOML.
    """

    model_config = ConfigDict(extra="forbid")

    allowed_owners: list[str] = Field(default_factory=lambda: ["co-cddo"])
    source: list[Source] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_owners(self) -> Registry:
        for src in self.source:
            if src.owner not in self.allowed_owners:
                raise ValueError(f"source {src.repo!r} is not from an allowed owner ({', '.join(self.allowed_owners)})")
        return self
