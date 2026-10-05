"""Command implementations: the layer that prints, prompts and sets exit codes."""

from __future__ import annotations

from pathlib import Path

import click

from idea_oc.github import GitHubClient, get_token
from idea_oc.models import Registry
from idea_oc.opencode_config import (
    ConfigError,
    ConfigState,
    default_config_path,
    ensure_skills_path,
    manual_snippet,
    skills_path_state,
)
from idea_oc.planner import PlanError
from idea_oc.registry import RegistryError, load_registry
from idea_oc.store import Store, default_store_dir
from idea_oc.sync import Action, SourcePlan, SyncResult, apply_plans, plan_registry

_SYMBOLS = {Action.ADDED: "+", Action.UPDATED: "~"}


def _tilde(path: Path) -> str:
    """Show ``path`` relative to the home directory where possible."""
    try:
        return f"~/{path.relative_to(Path.home())}"
    except ValueError:
        return str(path)


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def load_registry_or_fail(path: Path | None) -> Registry:
    """Load the registry, turning errors into a clean CLI failure."""
    try:
        return load_registry(path)
    except RegistryError as e:
        raise click.ClickException(str(e)) from e


def _echo_plans(plans: list[SourcePlan]) -> None:
    for plan in plans:
        if plan.error:
            click.echo(f"  ! {plan.source.repo}: {plan.error}", err=True)
            continue
        resolved = plan.resolved
        note = f"  (no releases, using {resolved.name})" if resolved.floating else f"  {resolved.name}"
        click.echo(f"  {plan.source.repo}{note}  ({resolved.sha[:7]})")


def _echo_changes(result: SyncResult) -> None:
    for outcome in result.outcomes:
        if outcome.error or outcome.action is Action.UNCHANGED:
            continue
        files = _plural(outcome.files_changed, "file")
        click.echo(f"  {_SYMBOLS[outcome.action]} {outcome.name:<24} {files}")
    for name in result.removed:
        click.echo(f"  - {name:<24} removed upstream")


def _echo_summary(result: SyncResult, *, dry_run: bool) -> None:
    added, updated = result.count(Action.ADDED), result.count(Action.UPDATED)
    skills = _plural(len(result.outcomes), "skill")
    if result.ok and not (added or updated or result.removed):
        click.echo(f"Everything is up to date ({skills}).")
        return
    prefix = "Dry run, nothing written: " if dry_run else ""
    click.echo(f"{prefix}{added} installed, {updated} updated, {len(result.removed)} removed.")


def _offer_registration(store_dir: Path, *, yes: bool) -> None:
    """Make sure OpenCode is told about the store, asking first."""
    config_path = default_config_path()
    try:
        if skills_path_state(config_path, store_dir) is ConfigState.REGISTERED:
            return
    except ConfigError as e:
        click.echo(f"\n{e}\nAdd this yourself:\n{manual_snippet(store_dir)}", err=True)
        return

    click.echo(f"\nOpenCode does not load this folder yet. Add it to {_tilde(config_path)}?")
    click.echo(f"  {manual_snippet(store_dir)}".replace("\n", "\n  "))
    click.echo(f"  (a backup is saved next to the file as {config_path.name}.idea-oc.bak)")
    try:
        approved = yes or click.confirm("Register the skill folder?", default=True)
    except click.Abort:
        approved = False

    if not approved:
        click.echo(f"Not changed. To do it yourself, add:\n{manual_snippet(store_dir)}")
        return
    try:
        ensure_skills_path(config_path, store_dir)
    except ConfigError as e:
        click.echo(f"{e}\nAdd this yourself:\n{manual_snippet(store_dir)}", err=True)
        return
    click.echo("Registered.")


def run_sync(*, registry_path: Path | None, dry_run: bool, prune: bool, yes: bool) -> None:
    """Install the registry's skills into the store and register the store with OpenCode."""
    registry = load_registry_or_fail(registry_path)
    store = Store(default_store_dir())

    with GitHubClient(token=get_token()) as client:
        click.echo("Resolving sources...")
        try:
            plans = plan_registry(client, registry)
        except PlanError as e:
            raise click.ClickException(str(e)) from e
        _echo_plans(plans)

        verb = "Would install to" if dry_run else "Installing to"
        click.echo(f"\n{verb} {_tilde(store.root)}")
        result = apply_plans(client, store, plans, dry_run=dry_run, prune=prune)

    _echo_changes(result)
    _echo_summary(result, dry_run=dry_run)

    if not dry_run and result.outcomes:
        _offer_registration(store.root, yes=yes)
    if not dry_run and (result.count(Action.ADDED) or result.count(Action.UPDATED)):
        click.echo("Restart OpenCode to pick up the changes.")

    if not result.ok:
        click.echo("\nSome skills could not be synced:", err=True)
        for error in result.errors:
            click.echo(f"  {error}", err=True)
        raise click.exceptions.Exit(1)
