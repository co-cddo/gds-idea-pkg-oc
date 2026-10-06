"""Load and validate the skill registry."""

from __future__ import annotations

import tomllib
from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from idea_oc.models import Registry


class RegistryError(Exception):
    """Raised when the registry cannot be read or is invalid."""


def load_registry(path: Path | None = None) -> Registry:
    """Load the registry from ``path``, or the one bundled with the package.

    Args:
        path: Optional custom registry file.

    Returns:
        The validated registry.

    Raises:
        RegistryError: If the file is missing, is not valid TOML, or fails validation.
    """
    try:
        text = path.read_text() if path else files("idea_oc").joinpath("registry.toml").read_text()
    except OSError as e:
        raise RegistryError(f"Cannot read registry: {e}") from e

    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise RegistryError(f"Invalid TOML in registry: {e}") from e

    try:
        return Registry(**raw)
    except ValidationError as e:
        raise RegistryError(f"Invalid registry: {e}") from e
