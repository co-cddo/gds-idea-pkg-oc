"""Command implementations: the layer that prints, prompts and sets exit codes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import click

from idea_oc.github import GitHubClient, get_token
from idea_oc.models import Registry
from idea_oc.opencode_config import (
    ConfigError,
    ConfigPlan,
    ConfigState,
    apply_plan,
    backup_path,
    clear_proposal,
    default_config_path,
    manual_snippet,
    plan_config,
    skills_path_state,
    write_proposal,
)
from idea_oc.planner import PlanError
from idea_oc.registry import RegistryError, load_registry
from idea_oc.status import SkillsReport, check_config, check_skills, personal_skill_dirs
from idea_oc.store import Store, default_store_dir
from idea_oc.sync import Action, SourcePlan, SyncResult, apply_plans, plan_registry
from idea_oc.team_config import Change, describe
from idea_oc.version import check_for_update

STAGES = ("skills", "config")
DOCS_SITE = "https://co-cddo.github.io/gds-idea-pkg-oc/"
DOCS_URL = f"{DOCS_SITE}commands/sync/#why-sync-skills-does-not-edit-your-config"
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


def _selected(stage: str | None) -> tuple[str, ...]:
    """The stages to run: the one named, or all of them."""
    return STAGES if stage is None else (stage,)


def _heading(name: str, stages: tuple[str, ...]) -> None:
    """Label a stage's output, but only when more than one stage is running."""
    if len(stages) > 1:
        click.echo(f"\n--- {name} ---")


def _guarded(stage: Callable[[], bool]) -> bool:
    """Run a stage so that its fatal errors are reported without stopping the other stage."""
    try:
        return stage()
    except click.ClickException as e:
        e.show()
        return False


def _sync_skills(*, registry_path: Path | None, dry_run: bool, prune: bool, advise_config: bool) -> bool:
    """Install the registry's skills into the store. Never touches the OpenCode config."""
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

    if not dry_run and (result.count(Action.ADDED) or result.count(Action.UPDATED)):
        click.echo("Restart OpenCode to pick up the changes.")
    if advise_config and result.outcomes and _registration_needed(store.root):
        _echo_registration_advice()

    if not result.ok:
        click.echo("\nSome skills could not be synced:", err=True)
        for error in result.errors:
            click.echo(f"  {error}", err=True)
    return result.ok


def _echo_registration_advice() -> None:
    click.echo(
        "\nThese skills are installed, but OpenCode will not load them yet.\n"
        'OpenCode only loads skills from folders listed under "skills.paths" in your config, and\n'
        "idea-oc keeps that edit as a separate step so it can show you the change and ask first.\n"
        "  Run:  idea-oc sync config\n"
        f"  Why:  {DOCS_URL}"
    )


def _registration_needed(store_dir: Path) -> bool:
    try:
        return skills_path_state(default_config_path(), store_dir) is not ConfigState.REGISTERED
    except ConfigError:
        return True


def _echo_changes_list(changes: list[Change]) -> None:
    rows = [describe(change) for change in changes]
    width = min(max((len(key) for _, key, _ in rows), default=0), 50)
    for verb, key, detail in rows:
        click.echo(f"  {verb:<6}  {key:<{width}}  {detail}")


def _echo_config_extras(warnings: list[str], notes: list[str]) -> None:
    for line in warnings:
        click.echo(f"Heads up: {line}")
    for line in notes:
        click.echo(f"Note: {line}")


def _confirm(prompt: str, *, yes: bool) -> bool:
    """Ask yes or no, defaulting to no. No terminal to ask on counts as no."""
    if yes:
        return True
    try:
        return click.confirm(prompt, default=False)
    except click.Abort:
        return False


def _decline(config: ConfigPlan, config_path: Path) -> None:
    """The user said no: save what would have changed next to their file and say how to use it."""
    try:
        proposal = write_proposal(config, config_path)
    except ConfigError as e:
        click.echo(f"Not changed. {e}\nMake the changes listed above yourself.")
        return
    click.echo(f"Not changed. The proposed config is saved as {_tilde(proposal)}.")
    if config.exists:
        click.echo(f"Review it and copy across what you want:\n  diff {_tilde(config_path)} {_tilde(proposal)}")
    else:
        click.echo(f"To use it as your config, rename it to {config_path.name}.")


def _accept(config: ConfigPlan, config_path: Path) -> bool:
    try:
        apply_plan(config, config_path)
    except ConfigError as e:
        click.echo(f"{e}\nMake the changes listed above yourself.", err=True)
        return True
    click.echo(f"Updated {_tilde(config_path)}.")
    if config.exists:
        click.echo(f"The original is saved as {_tilde(backup_path(config_path))}.")
    return True


def _sync_config(*, dry_run: bool, yes: bool) -> bool:
    """Bring the user's OpenCode config in line with the team's preferred one. Offline; never touches the store."""
    store_dir = default_store_dir()
    config_path = default_config_path()
    try:
        config = plan_config(config_path, store_dir)
    except ConfigError as e:
        click.echo(f"{e}\nAdd this yourself to register the skills folder:\n{manual_snippet(store_dir)}", err=True)
        return True

    plan = config.plan
    if not plan.pending:
        click.echo("Config is up to date.")
        _echo_config_extras(plan.warnings, plan.notes)
        if not dry_run:
            clear_proposal(config_path)
        return True

    if dry_run:
        heading = "Would change" if config.exists else "Would create"
    else:
        heading = "Changes to" if config.exists else "New file"
    click.echo(f"{heading} {_tilde(config_path)}:")
    _echo_changes_list(plan.changes)
    _echo_config_extras(plan.warnings, plan.notes)

    if dry_run:
        click.echo("Dry run, nothing written.")
        return True

    backup = f" The original is saved as {_tilde(backup_path(config_path))}." if config.exists else ""
    if _confirm(f"\nApply these changes?{backup}", yes=yes):
        return _accept(config, config_path)
    _decline(config, config_path)
    return True


def run_sync(*, registry_path: Path | None, stage: str | None, dry_run: bool, prune: bool, yes: bool) -> None:
    """Run the skills stage, the config stage, or both. Exits 1 if any stage failed."""
    check_for_update()
    stages = _selected(stage)
    outcomes = []

    if "skills" in stages:
        _heading("skills", stages)
        outcomes.append(
            _guarded(
                lambda: _sync_skills(
                    registry_path=registry_path, dry_run=dry_run, prune=prune, advise_config="config" not in stages
                )
            )
        )
    if "config" in stages:
        _heading("config", stages)
        outcomes.append(_guarded(lambda: _sync_config(dry_run=dry_run, yes=yes)))

    if not all(outcomes):
        raise click.exceptions.Exit(1)


def _echo_skills_status(report: SkillsReport, *, quiet: bool) -> None:
    def say(line: str = "", *, problem: bool = False) -> None:
        if problem or not quiet:
            click.echo(line)

    drifted = [s for s in report.skills if not s.ok]
    say(f"Skills:  {len(report.skills)} approved, {len(drifted)} need syncing", problem=bool(drifted))
    for skill in drifted:
        say(f"  {skill.name:<24} {skill.detail}", problem=True)

    if report.stale:
        say("Stale:   no longer approved (run: idea-oc sync skills)", problem=True)
        for name in report.stale:
            say(f"  {name}", problem=True)

    if report.shadowed:
        say("\nShadowing (the team skill overrides your personal skill of the same name):")
        for shadow in report.shadowed:
            say(f"  {shadow.name:<24} {_tilde(shadow.path)}")

    for line in report.unchecked:
        click.echo(f"Could not check upstream, skipped: {line}", err=True)


def _status_skills(*, registry_path: Path | None, quiet: bool) -> bool:
    """Report skills drift. Returns True if everything is in order."""
    registry = load_registry_or_fail(registry_path)
    store = Store(default_store_dir())

    with GitHubClient(token=get_token()) as client:
        try:
            report = check_skills(client, registry, store, personal_skill_dirs(default_config_path()))
        except PlanError as e:
            raise click.ClickException(str(e)) from e

    _echo_skills_status(report, quiet=quiet)
    return not report.problems


def _status_config(*, quiet: bool) -> bool:
    """Report how the config differs from the team's preferred one. Returns True if it matches. Offline."""
    config_path = default_config_path()
    report = check_config(config_path, default_store_dir())

    if report.error:
        click.echo(f"Config:  could not be read: {report.error}")
    elif report.changes:
        count = _plural(len(report.changes), "difference")
        click.echo(
            f"Config:  {count} from the team's preferred config in {_tilde(config_path)} (run: idea-oc sync config)"
        )
        _echo_changes_list(report.changes)
    elif not quiet:
        click.echo(f"Config:  ok (matches the team's preferred config in {_tilde(config_path)})")

    if not quiet:
        _echo_config_extras(report.warnings, report.notes)
    return not report.problems


def run_status(*, registry_path: Path | None, stage: str | None, quiet: bool) -> None:
    """Report drift for the skills stage, the config stage, or both. Exits 1 if a sync is needed."""
    check_for_update(quiet=quiet)
    stages = _selected(stage)
    outcomes = []

    if "skills" in stages:
        outcomes.append(_guarded(lambda: _status_skills(registry_path=registry_path, quiet=quiet)))
    if "config" in stages:
        outcomes.append(_guarded(lambda: _status_config(quiet=quiet)))

    if not all(outcomes):
        raise click.exceptions.Exit(1)


def run_list(*, registry_path: Path | None) -> None:
    """Show the skills installed in the store and the sources the registry approves. Works offline."""
    registry = load_registry_or_fail(registry_path)
    store = Store(default_store_dir())
    installed = store.installed()

    if installed:
        width = max(len(name) for name in installed)
        click.echo(f"Installed in {_tilde(store.root)}:")
        for name, prov in installed.items():
            click.echo(f"  {name:<{width}}  {prov.repo}  {prov.ref}  ({prov.commit[:7]})")
    else:
        click.echo("No skills installed. Run: idea-oc sync")

    click.echo("\nApproved sources:")
    for source in registry.source:
        what = f"discover {source.discover}" if source.discover else f"{len(source.skills or [])} named skill(s)"
        click.echo(f"  {source.repo}  {source.ref}  ({what})")
