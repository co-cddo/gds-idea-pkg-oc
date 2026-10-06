"""Tests for the idea-oc CLI entry point."""

from idea_oc import __version__
from idea_oc.cli import cli


def test_version_flag(cli_runner):
    result = cli_runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert "idea-oc" in result.output
    assert __version__ in result.output


def test_help_lists_description(cli_runner):
    result = cli_runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "OpenCode" in result.output
