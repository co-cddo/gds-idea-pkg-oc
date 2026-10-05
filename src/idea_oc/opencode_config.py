"""Register the skill store in the user's OpenCode config.

OpenCode loads extra skill folders from ``skills.paths``. That entry is the only
thing idea-oc writes to the config. It loads after the personal skills folder,
so team skills win over personal skills with the same name.
"""

from __future__ import annotations

import json
import os
import shutil
from enum import Enum
from pathlib import Path


class ConfigError(Exception):
    """Raised when the OpenCode config cannot be read or safely edited."""


class ConfigState(Enum):
    """Whether the store is registered with OpenCode."""

    REGISTERED = "registered"
    NOT_REGISTERED = "not registered"
    NO_FILE = "no config file"


def default_config_path() -> Path:
    """The user's global OpenCode config: ``opencode.json``, else ``opencode.jsonc`` if that exists.

    ``$IDEA_OC_CONFIG`` overrides the location.
    """
    if override := os.environ.get("IDEA_OC_CONFIG"):
        return Path(override).expanduser()
    config_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    plain, commented = config_home / "opencode" / "opencode.json", config_home / "opencode" / "opencode.jsonc"
    return commented if commented.exists() and not plain.exists() else plain


def manual_snippet(store_dir: Path) -> str:
    """The JSON a user can add by hand when idea-oc cannot edit their config."""
    return json.dumps({"skills": {"paths": [_as_config_value(store_dir)]}}, indent=2)


def _as_config_value(store_dir: Path) -> str:
    """Write the store path with ``~`` when it is under the home directory."""
    try:
        return f"~/{store_dir.relative_to(Path.home())}"
    except ValueError:
        return str(store_dir)


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except OSError as e:
        raise ConfigError(f"Cannot read {path}: {e}") from e
    except ValueError as e:
        raise ConfigError(
            f"{path} is not plain JSON (comments or trailing commas?), so idea-oc will not rewrite it: {e}"
        ) from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return data


def _registered_paths(config: dict, path: Path) -> list:
    """The ``skills.paths`` list from a loaded config (empty if absent)."""
    skills = config.get("skills", {})
    paths = skills.get("paths", []) if isinstance(skills, dict) else None
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
    paths = _registered_paths(_load(config_path), config_path)
    registered = any(_is_store(p, store_dir) for p in paths)
    return ConfigState.REGISTERED if registered else ConfigState.NOT_REGISTERED


def _insert_skills_block(text: str, skills: dict) -> str | None:
    """Append a ``skills`` property to a JSON object's text, leaving the rest byte-for-byte intact.

    Returns None if the text does not look like a simple object we can append to.
    """
    body = text.rstrip()
    if not body.endswith("}"):
        return None
    head = body[:-1].rstrip()
    separator = "" if head.endswith("{") else ","
    block = json.dumps({"skills": skills}, indent=2)[2:-2]  # drop the outer braces, keep the two-space indent
    return f"{head}{separator}\n{block}\n}}\n"


def _render(original: str | None, config: dict, skills: dict) -> str:
    """Produce the new file text, preferring a minimal textual edit over re-serialising everything."""
    if original is not None and "skills" not in json.loads(original):
        inserted = _insert_skills_block(original, skills)
        if inserted is not None and _parses_to(inserted, config):
            return inserted
    return json.dumps(config, indent=2) + "\n"


def _parses_to(text: str, expected: dict) -> bool:
    try:
        return json.loads(text) == expected
    except ValueError:
        return False


def ensure_skills_path(config_path: Path, store_dir: Path) -> bool:
    """Add ``store_dir`` to ``skills.paths``, leaving everything else untouched.

    The config is backed up to ``<name>.idea-oc.bak`` before it is changed, and
    written atomically. A file that is not plain JSON is never rewritten. When the
    file has no ``skills`` key the new block is appended as text, so existing
    formatting is preserved.

    Args:
        config_path: The OpenCode config file (created if missing).
        store_dir: The skill store folder.

    Returns:
        True if the file was changed, False if the store was already registered.

    Raises:
        ConfigError: If the config cannot be parsed or has an unexpected shape.
    """
    exists = config_path.exists()
    config = _load(config_path) if exists else {}
    paths = _registered_paths(config, config_path)
    if any(_is_store(p, store_dir) for p in paths):
        return False

    skills = {**(config.get("skills") or {}), "paths": [*paths, _as_config_value(store_dir)]}
    updated = {**config, "skills": skills}
    text = _render(config_path.read_text() if exists else None, updated, skills)

    if exists:
        shutil.copy2(config_path, config_path.with_name(f"{config_path.name}.idea-oc.bak"))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = config_path.with_name(f"{config_path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    tmp.replace(config_path)
    return True
