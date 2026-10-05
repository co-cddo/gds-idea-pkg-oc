"""Shared test configuration and fixtures."""

import pytest
from click.testing import CliRunner


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: tests that require external services")


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()
