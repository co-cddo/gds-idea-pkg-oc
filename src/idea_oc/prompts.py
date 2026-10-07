"""OpenCode's Claude system prompt, installed next to the user's config for agents on an inference profile.

OpenCode chooses its built-in instructions for a model from the model's id, looking for ``claude``. A
Bedrock inference profile's id is an ARN, which does not name the model, so OpenCode falls back to its
general instructions. An agent's ``prompt`` setting replaces the built-in choice, so pointing the agents
at a copy of the Claude instructions gives profile users the same instructions as everyone else.

The agents' ``prompt`` setting is a ``{file:...}`` reference, and OpenCode refuses to start if the file it
names is missing. So the file and the references to it must always arrive together, and every function
here is written so that a failure leaves the user's setup working.
"""

from __future__ import annotations

import os
from enum import Enum
from importlib.resources import files
from pathlib import Path
from typing import Any

PROMPT_DIR = "prompts"
PROMPT_FILENAME = "idea-oc-anthropic.txt"
PROMPT_REF = f"{{file:./{PROMPT_DIR}/{PROMPT_FILENAME}}}"
# The agents that have no instructions of their own and so use the ones chosen from the model id. The
# others (explore, compaction, title, summary) carry their own and are not affected.
AGENTS = ("build", "plan", "general")


class PromptState(Enum):
    """How the prompt file next to the user's config compares with the bundled one."""

    CURRENT = "current"
    MISSING = "missing"
    DIFFERENT = "different"


def bundled_prompt() -> bytes:
    """OpenCode's Claude prompt, as shipped with idea-oc."""
    return files("idea_oc").joinpath("prompts/anthropic.txt").read_bytes()


def prompt_path(config_path: Path) -> Path:
    """Where the prompt file lives: in a ``prompts`` folder next to the config, where ``./prompts/...`` resolves."""
    return config_path.parent / PROMPT_DIR / PROMPT_FILENAME


def prompt_state(config_path: Path) -> PromptState:
    """Whether the prompt file is there and matches the bundled one."""
    path = prompt_path(config_path)
    if not path.is_file():
        return PromptState.MISSING
    return PromptState.CURRENT if path.read_bytes() == bundled_prompt() else PromptState.DIFFERENT


def write_prompt(config_path: Path) -> Path:
    """Write the bundled prompt next to the config, atomically, and return its path."""
    path = prompt_path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(bundled_prompt())
    tmp.replace(path)
    return path


def is_agent_prompt(path: tuple[str, ...]) -> bool:
    """Whether a config key path is the ``prompt`` of one of the agents we set."""
    return len(path) == 3 and path[0] == "agent" and path[1] in AGENTS and path[2] == "prompt"


def references_prompt(config: dict[str, Any]) -> bool:
    """Whether any agent in ``config`` uses the prompt file, in which case the file must exist."""
    agents = config.get("agent")
    if not isinstance(agents, dict):
        return False
    return any(isinstance(agent, dict) and agent.get("prompt") == PROMPT_REF for agent in agents.values())
