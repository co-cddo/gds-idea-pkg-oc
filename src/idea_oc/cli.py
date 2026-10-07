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


_STAGE = click.argument("stage", type=click.Choice(["skills", "config"]), required=False)


def _check_team(ctx: click.Context, param: click.Parameter, value: str | None) -> str | None:
    """Reject a team that has no inference profile, naming the ones that do."""
    if value is None:
        return None
    from idea_oc.profiles import ProfilesError, load_profiles

    try:
        return load_profiles().check_team(value)
    except ProfilesError as e:
        raise click.BadParameter(str(e)) from e


_TEAM = click.option(
    "--team",
    callback=_check_team,
    help="Config: whose Bedrock inference profile to use, so usage is tracked per team (ds, sds or econ). "
    "Default: the team your current model already uses, else ds.",
)


@cli.command()
@_STAGE
@_TEAM
@click.option("--dry-run", is_flag=True, help="Show what would change without writing anything.")
@click.option("--prune/--no-prune", default=True, help="Skills: remove skills that are no longer approved.")
@click.option("--yes", "-y", is_flag=True, help="Config: apply changes to your OpenCode config without asking.")
@click.pass_context
def sync(ctx: click.Context, stage: str | None, team: str | None, dry_run: bool, prune: bool, yes: bool):
    """Install approved skills and update your OpenCode config.

    \b
    STAGE is optional. Without it both stages run, skills first:
      skills   install the approved skills (needs the network)
      config   compare your OpenCode config with the team's preferred one (works offline)

    The stages are independent: neither needs the other to have run.
    """
    from idea_oc.commands import run_sync

    run_sync(registry_path=ctx.obj["registry_path"], stage=stage, dry_run=dry_run, prune=prune, yes=yes, team=team)


@cli.command()
@_STAGE
@_TEAM
@click.option("--quiet", "-q", is_flag=True, help="Print only problems. The exit code still reports them.")
@click.pass_context
def status(ctx: click.Context, stage: str | None, team: str | None, quiet: bool):
    """Check skills and config against what the team expects (exits 1 if a sync is needed).

    STAGE is optional: skills or config. Without it both are checked.
    """
    from idea_oc.commands import run_status

    run_status(registry_path=ctx.obj["registry_path"], stage=stage, quiet=quiet, team=team)


@cli.command("list")
@click.pass_context
def list_skills(ctx: click.Context):
    """Show installed skills and approved sources (works offline)."""
    from idea_oc.commands import run_list

    run_list(registry_path=ctx.obj["registry_path"])
