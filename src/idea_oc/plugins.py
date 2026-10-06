"""Advise on OpenCode plugins. idea-oc only checks what is listed and never changes plugins.

The recommended plugins are the ones in the bundled preferred config. A plugin counts as listed if
the user's config names it, whatever version is pinned, or if it is a file plugin with the same file
name. A test keeps the table below in step with the preferred config.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from idea_oc.jsonc_doc import JsoncDocument, JsoncError

SNIP_PLUGIN = "opencode-snip"
SNIP_PROGRAM = "snip"
SNIP_INSTALL = "brew install edouard-claude/tap/snip"
# OpenCode merges these three files from its config folder; a later file's `plugin` list replaces an earlier one's.
GLOBAL_CONFIG_FILES = ("config.json", "opencode.json", "opencode.jsonc")


@dataclass(frozen=True)
class PluginInfo:
    """A plugin the team recommends.

    Attributes:
        identity: The package name (without version), or the file name for a file plugin.
        required: Whether the team needs everyone to have it.
        why: One line on what it does.
    """

    identity: str
    required: bool
    why: str


RECOMMENDED: tuple[PluginInfo, ...] = (
    PluginInfo("inject-env.js", True, "keeps OpenCode's shell commands on the bedrockonly AWS profile"),
    PluginInfo("@tarquinen/opencode-dcp", False, "prunes the conversation to cut token use"),
    PluginInfo("envsitter-guard", False, "blocks raw reads of .env files"),
    PluginInfo(SNIP_PLUGIN, False, "filters noisy command output to cut token use"),
    PluginInfo("cc-safety-net", False, "blocks destructive commands (it also blocks force-push)"),
)


def identity(spec: Any) -> str | None:
    """The name a plugin is known by, from a ``plugin`` entry: a string or ``[string, options]``.

    Versions are ignored (``name@latest`` is ``name``), and a file path is known by its file name.
    """
    if isinstance(spec, list) and spec:
        spec = spec[0]
    if not isinstance(spec, str) or not spec:
        return None
    is_scoped_package = spec.startswith("@")
    is_path = spec.startswith(("file:", ".", "~")) or ("/" in spec and not is_scoped_package)
    if is_path:
        return PurePosixPath(spec.removeprefix("file://")).name
    at = spec.rfind("@")
    return spec[:at] if at > 0 else spec


@dataclass(frozen=True)
class PluginStatus:
    """A recommended plugin and whether the user lists it."""

    info: PluginInfo
    listed: bool


@dataclass
class PluginReport:
    """What the plugin check found.

    Attributes:
        plugins: Every recommended plugin and whether it is listed.
        snip_missing: ``opencode-snip`` is listed but the program it needs is not installed.
        error: Why the config could not be read, if it could not.
    """

    plugins: list[PluginStatus] = field(default_factory=list)
    snip_missing: bool = False
    error: str | None = None

    @property
    def missing_required(self) -> list[PluginInfo]:
        return [p.info for p in self.plugins if p.info.required and not p.listed]

    @property
    def missing_recommended(self) -> list[PluginInfo]:
        return [p.info for p in self.plugins if not p.info.required and not p.listed]

    @property
    def all_good(self) -> bool:
        return not (self.error or self.missing_required or self.missing_recommended or self.snip_missing)


def _config_files(config_path: Path) -> list[Path]:
    """Config files to read, lowest priority first: OpenCode's three global files, then ``config_path``."""
    files = [config_path.parent / name for name in GLOBAL_CONFIG_FILES]
    return [*(f for f in files if f != config_path), config_path]


def listed_plugins(config_path: Path) -> set[str]:
    """The plugins the user's global config lists. Raises ``JsoncError``/``OSError`` if a file can't be read."""
    plugins: list = []
    for path in _config_files(config_path):
        if not path.exists():
            continue
        value = JsoncDocument.parse(path.read_text()).get(("plugin",))
        if isinstance(value, list):  # a later file's list replaces an earlier one's, as in OpenCode
            plugins = value
    return {name for spec in plugins if (name := identity(spec))}


def check_plugins(config_path: Path) -> PluginReport:
    """Check the user's config for the recommended plugins. Works offline and changes nothing."""
    try:
        listed = listed_plugins(config_path)
    except (JsoncError, OSError) as e:
        return PluginReport(error=str(e))
    plugins = [PluginStatus(info, info.identity in listed) for info in RECOMMENDED]
    return PluginReport(plugins, snip_missing=SNIP_PLUGIN in listed and shutil.which(SNIP_PROGRAM) is None)
