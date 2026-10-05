"""CLI entry point for idea-oc."""

from __future__ import annotations

import click

from idea_oc import __version__


@click.group()
@click.version_option(version=__version__, prog_name="idea-oc")
def cli():
    """Sync approved OpenCode agent skills to your machine."""
