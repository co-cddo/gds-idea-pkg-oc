"""Advise the user when a newer idea-oc is available on the internal index.

The index is the source of truth for what ``idea-tools upgrade`` can install. A
GitHub release appears before its wheel is built and the index rebuilt, so
checking the repo would sometimes advise an upgrade that cannot happen yet.
"""

from __future__ import annotations

import os
import re

import click
import httpx
from packaging.version import InvalidVersion, Version

from idea_oc import __version__

INDEX_URL = "https://co-cddo.github.io/gds-idea-pypi/simple/"
PACKAGE = "gds-idea-pkg-oc"
TIMEOUT_SECONDS = 2.0
OPT_OUT_VARIABLE = "IDEA_OC_NO_VERSION_CHECK"

_FILENAME = re.compile(r"gds[_-]idea[_-]pkg[_-]oc-(\d[^\s\"'<>/-]*?)(?:-py\d|\.tar\.gz|\.zip)")


def _opted_out() -> bool:
    return os.environ.get(OPT_OUT_VARIABLE, "") not in ("", "0")


def _parse(text: str) -> Version | None:
    try:
        return Version(text)
    except InvalidVersion:
        return None


def installed_version() -> Version | None:
    """The running version, or None if it cannot be compared (for example a development build).

    Development builds always sort below real releases, so they would be told to upgrade forever.
    """
    version = _parse(__version__)
    return None if version is None or version.is_devrelease else version


def fetch_latest_version() -> Version | None:
    """The newest final release listed on the index, or None if it cannot be determined.

    Offline, slow, missing or unparseable responses all return None rather than raising.
    """
    try:
        response = httpx.get(f"{INDEX_URL}{PACKAGE}/", timeout=TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None

    versions = (_parse(match) for match in _FILENAME.findall(response.text))
    finals = [v for v in versions if v is not None and not v.is_prerelease]
    return max(finals, default=None)


def upgrade_notice(installed: Version, latest: Version, *, short: bool = False) -> str | None:
    """The advice to show, or None if ``installed`` is current."""
    if latest <= installed:
        return None
    if short:
        return f"idea-oc {latest} is available (you have {installed}): idea-tools upgrade {PACKAGE}"
    return (
        f"A newer idea-oc is available ({latest}; you have {installed}). The approved sources and team\n"
        f"config bundled in this version may be out of date. Upgrade with:\n"
        f"  idea-tools upgrade {PACKAGE}\n"
    )


def check_for_update(*, quiet: bool = False) -> None:
    """Print upgrade advice to stderr if a newer version is on the index. Never raises or blocks."""
    installed = installed_version()
    if installed is None or _opted_out():
        return
    latest = fetch_latest_version()
    if latest is None:
        return
    if notice := upgrade_notice(installed, latest, short=quiet):
        click.echo(notice, err=True)
