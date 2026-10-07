"""Read, plan and write the user's OpenCode config.

The config stage compares the user's config with the team's preferred one (see ``team_config``),
shows what would change, and either applies the changes (with a backup) or saves them as a
``.new`` file for the user to merge by hand. Edits keep the user's comments and formatting.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from idea_oc.jsonc_doc import JsoncDocument, JsoncError
from idea_oc.profiles import ProfilesError, TeamChoice, choose_team, load_profiles
from idea_oc.team_config import SKILLS_PATH, Plan, apply_changes, desired_config, plan_changes

# The order OpenCode itself looks for the global config in: the first one that exists is its "main" file.
CONFIG_FILENAMES = ("opencode.jsonc", "opencode.json", "config.json")
BACKUP_SUFFIX = ".idea-oc.bak"
PROPOSAL_SUFFIX = ".new"


class ConfigError(Exception):
    """Raised when the OpenCode config cannot be read or safely edited."""


class ConfigState(Enum):
    """Whether the skill store is registered with OpenCode."""

    REGISTERED = "registered"
    NOT_REGISTERED = "not registered"
    NO_FILE = "no config file"


@dataclass
class ConfigPlan:
    """The user's config and the changes needed to bring it in line with the team's.

    Attributes:
        document: The user's config as read (an empty document if the file does not exist).
        plan: The changes needed.
        exists: Whether the config file exists.
        team: Which team's inference profile the config is being compared against, and why.
    """

    document: JsoncDocument
    plan: Plan
    exists: bool
    team: TeamChoice


def default_config_path() -> Path:
    """The global OpenCode config file that OpenCode itself treats as the main one.

    That is the first of ``opencode.jsonc``, ``opencode.json`` and ``config.json`` to exist, or
    ``opencode.jsonc`` if none do. ``$IDEA_OC_CONFIG`` overrides the location.
    """
    if override := os.environ.get("IDEA_OC_CONFIG"):
        return Path(override).expanduser()
    config_dir = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "opencode"
    candidates = [config_dir / name for name in CONFIG_FILENAMES]
    return next((path for path in candidates if path.exists()), candidates[0])


def store_config_value(store_dir: Path) -> str:
    """Write the store path with ``~`` when it is under the home directory."""
    try:
        return f"~/{store_dir.relative_to(Path.home())}"
    except ValueError:
        return str(store_dir)


def manual_snippet(store_dir: Path) -> str:
    """The JSON a user can add by hand to register the skill store."""
    return json.dumps({"skills": {"paths": [store_config_value(store_dir)]}}, indent=2)


def backup_path(config_path: Path) -> Path:
    return config_path.with_name(config_path.name + BACKUP_SUFFIX)


def proposal_path(config_path: Path) -> Path:
    return config_path.with_name(config_path.name + PROPOSAL_SUFFIX)


def _open(path: Path) -> JsoncDocument:
    """Read ``path`` as an editable document, or an empty one if the file does not exist."""
    if not path.exists():
        return JsoncDocument.empty()
    try:
        return JsoncDocument.parse(path.read_text())
    except OSError as e:
        raise ConfigError(f"Cannot read {path}: {e}") from e
    except JsoncError as e:
        raise ConfigError(f"idea-oc cannot edit {path}: {e}") from e


def skills_path_state(config_path: Path, store_dir: Path) -> ConfigState:
    """Report whether ``store_dir`` is registered in ``skills.paths``.

    Raises:
        ConfigError: If the config exists but cannot be parsed.
    """
    if not config_path.exists():
        return ConfigState.NO_FILE
    paths = _open(config_path).get(SKILLS_PATH, [])
    if not isinstance(paths, list):
        return ConfigState.NOT_REGISTERED
    registered = any(isinstance(p, str) and Path(p).expanduser() == store_dir for p in paths)
    return ConfigState.REGISTERED if registered else ConfigState.NOT_REGISTERED


def plan_config(config_path: Path, store_dir: Path, team: str | None = None) -> ConfigPlan:
    """Work out what the team's preferred config would change in the user's config.

    Args:
        config_path: The OpenCode config file (it need not exist).
        store_dir: The skill store.
        team: The team to use, from ``--team``. By default the team the config's model already uses,
            else the default team.

    Raises:
        ConfigError: If the config cannot be read, parsed or compared, or the team is unknown.
    """
    document = _open(config_path)
    try:
        profiles = load_profiles()
        choice = choose_team(profiles, team, document.data)
        desired = desired_config(choice.team, profiles)
        plan = plan_changes(document, store_dir, store_config_value(store_dir), desired)
    except (JsoncError, ProfilesError) as e:
        raise ConfigError(f"{config_path}: {e}") from e
    return ConfigPlan(document, plan, config_path.exists(), choice)


def _render(config: ConfigPlan, config_path: Path) -> str:
    try:
        apply_changes(config.document, config.plan.changes)
    except JsoncError as e:
        raise ConfigError(f"idea-oc cannot edit {config_path}: {e}") from e
    return config.document.text


def _write_atomically(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(path)


def apply_plan(config: ConfigPlan, config_path: Path) -> None:
    """Apply the changes to the config file, saving a backup of the original first.

    Any earlier proposal (``.new`` file) is removed, since it is now out of date.

    Raises:
        ConfigError: If the edits cannot be made safely. The file is not touched in that case.
    """
    text = _render(config, config_path)
    if config.exists:
        shutil.copy2(config_path, backup_path(config_path))
    _write_atomically(config_path, text)
    clear_proposal(config_path)


def write_proposal(config: ConfigPlan, config_path: Path) -> Path:
    """Save the config with the changes applied next to the original, for the user to merge by hand.

    Raises:
        ConfigError: If the edits cannot be made safely.
    """
    path = proposal_path(config_path)
    _write_atomically(path, _render(config, config_path))
    return path


def clear_proposal(config_path: Path) -> None:
    """Remove an out-of-date proposal."""
    proposal_path(config_path).unlink(missing_ok=True)
