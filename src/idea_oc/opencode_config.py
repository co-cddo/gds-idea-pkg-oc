"""Register the skill store in the user's OpenCode config.

OpenCode loads extra skill folders from ``skills.paths``. That entry is the only
thing idea-oc writes to the config. It loads after the personal skills folder,
so team skills win over personal skills with the same name.

Edits go through ``JsoncDocument``, so the comments and formatting in a hand-written
``opencode.jsonc`` survive.
"""

from __future__ import annotations

import json
import os
import shutil
from enum import Enum
from pathlib import Path

from idea_oc.jsonc_doc import JsoncDocument, JsoncError

SKILLS_PATH = ("skills", "paths")
# The order OpenCode itself looks for the global config in: the first one that exists is its "main" file.
CONFIG_FILENAMES = ("opencode.jsonc", "opencode.json", "config.json")


class ConfigError(Exception):
    """Raised when the OpenCode config cannot be read or safely edited."""


class ConfigState(Enum):
    """Whether the store is registered with OpenCode."""

    REGISTERED = "registered"
    NOT_REGISTERED = "not registered"
    NO_FILE = "no config file"


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


def manual_snippet(store_dir: Path) -> str:
    """The JSON a user can add by hand when idea-oc cannot edit their config."""
    return json.dumps({"skills": {"paths": [_as_config_value(store_dir)]}}, indent=2)


def _as_config_value(store_dir: Path) -> str:
    """Write the store path with ``~`` when it is under the home directory."""
    try:
        return f"~/{store_dir.relative_to(Path.home())}"
    except ValueError:
        return str(store_dir)


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


def _registered_paths(document: JsoncDocument, path: Path) -> list:
    """The ``skills.paths`` list (empty if absent)."""
    skills = document.get(("skills",), {})
    if not isinstance(skills, dict):
        raise ConfigError(f"'skills' in {path} must be an object")
    paths = skills.get("paths", [])
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        raise ConfigError(f"'skills.paths' in {path} must be a list of strings")
    return paths


def _is_store(entry: str, store_dir: Path) -> bool:
    return Path(entry).expanduser() == store_dir


def skills_path_state(config_path: Path, store_dir: Path) -> ConfigState:
    """Report whether ``store_dir`` is registered in ``skills.paths``.

    Raises:
        ConfigError: If the config exists but cannot be parsed.
    """
    if not config_path.exists():
        return ConfigState.NO_FILE
    paths = _registered_paths(_open(config_path), config_path)
    registered = any(_is_store(p, store_dir) for p in paths)
    return ConfigState.REGISTERED if registered else ConfigState.NOT_REGISTERED


def ensure_skills_path(config_path: Path, store_dir: Path) -> bool:
    """Add ``store_dir`` to ``skills.paths``, leaving everything else untouched.

    The config is backed up to ``<name>.idea-oc.bak`` before it is changed, and
    written atomically. Comments and formatting are preserved.

    Args:
        config_path: The OpenCode config file (created if missing).
        store_dir: The skill store folder.

    Returns:
        True if the file was changed, False if the store was already registered.

    Raises:
        ConfigError: If the config cannot be parsed or has an unexpected shape.
    """
    document = _open(config_path)
    paths = _registered_paths(document, config_path)
    if any(_is_store(p, store_dir) for p in paths):
        return False

    value = _as_config_value(store_dir)
    try:
        if paths or document.get(SKILLS_PATH) is not None:
            document.append(SKILLS_PATH, value)
        else:
            document.set(SKILLS_PATH, [value])
    except JsoncError as e:
        raise ConfigError(f"idea-oc cannot edit {config_path}: {e}") from e

    if config_path.exists():
        shutil.copy2(config_path, config_path.with_name(f"{config_path.name}.idea-oc.bak"))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_name(f"{config_path.name}.{os.getpid()}.tmp")
    tmp.write_text(document.text)
    tmp.replace(config_path)
    return True
