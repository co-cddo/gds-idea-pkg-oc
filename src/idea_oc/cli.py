"""CLI entry point for idea-oc."""

from __future__ import annotations

from pathlib import Path

import click

from idea_oc import __version__


@click.group()
@click.version_option(version=__version__, prog_name="idea-oc")
@click.option(
    "--registry",
    "registry_path",
    type=click.Path(path_type=Path, dir_okay=False),
    default=None,
    help="Use a custom registry file instead of the built-in one.",
)
@click.pass_context
def cli(ctx: click.Context, registry_path: Path | None):
    """Sync approved OpenCode agent skills to your machine."""
    ctx.ensure_object(dict)
    ctx.obj["registry_path"] = registry_path


@cli.command()
@click.option("--dry-run", is_flag=True, help="Show what would change without writing anything.")
@click.option("--prune/--no-prune", default=True, help="Remove skills that are no longer approved (default: prune).")
@click.option("--yes", "-y", is_flag=True, help="Register the skill folder in opencode.json without asking.")
@click.pass_context
def sync(ctx: click.Context, dry_run: bool, prune: bool, yes: bool):
    """Install the approved skills and register them with OpenCode."""
    from idea_oc.commands import run_sync

    run_sync(registry_path=ctx.obj["registry_path"], dry_run=dry_run, prune=prune, yes=yes)
