"""Tests for the upgrade advice."""

import httpx
import pytest
from packaging.version import Version

from idea_oc import version
from idea_oc.cli import cli
from tests.conftest import skill_md

INDEX = f"{version.INDEX_URL}{version.PACKAGE}/"


def index_page(*versions: str) -> str:
    links = [f"gds_idea_pkg_oc-{v}-py3-none-any.whl\ngds_idea_pkg_oc-{v}.tar.gz" for v in versions]
    return "Links for gds-idea-pkg-oc\n" + "\n".join(links)


@pytest.fixture
def check_enabled(monkeypatch):
    monkeypatch.delenv("IDEA_OC_NO_VERSION_CHECK")
    monkeypatch.setattr(version, "__version__", "0.3.0")


def test_index_is_the_internal_pypi_page_for_this_package():
    assert INDEX == "https://co-cddo.github.io/gds-idea-pypi/simple/gds-idea-pkg-oc/"


def test_latest_is_the_highest_version_not_the_last_listed(httpx_mock):
    httpx_mock.add_response(url=INDEX, text=index_page("0.9.0", "0.10.0", "0.2.0"))

    assert version.fetch_latest_version() == Version("0.10.0")


def test_prereleases_are_ignored(httpx_mock):
    httpx_mock.add_response(url=INDEX, text=index_page("0.4.0", "0.5.0rc1", "0.5.0.dev2"))

    assert version.fetch_latest_version() == Version("0.4.0")


@pytest.mark.parametrize(
    "response",
    [
        {"status_code": 404},
        {"status_code": 500},
        {"text": "no links here"},
        {"exception": httpx.ConnectError("offline")},
        {"exception": httpx.ReadTimeout("slow")},
    ],
)
def test_unavailable_index_gives_none(httpx_mock, response):
    if "exception" in response:
        httpx_mock.add_exception(response["exception"])
    else:
        httpx_mock.add_response(url=INDEX, **response)

    assert version.fetch_latest_version() is None


def test_notice_only_when_newer():
    assert version.upgrade_notice(Version("0.3.0"), Version("0.3.0")) is None
    assert version.upgrade_notice(Version("0.4.0"), Version("0.3.0")) is None

    notice = version.upgrade_notice(Version("0.3.0"), Version("0.4.1"))

    assert "0.4.1" in notice
    assert "you have 0.3.0" in notice
    assert "idea-tools upgrade gds-idea-pkg-oc" in notice


def test_short_notice_is_one_line():
    notice = version.upgrade_notice(Version("0.3.0"), Version("0.4.1"), short=True)

    assert "\n" not in notice
    assert "idea-tools upgrade gds-idea-pkg-oc" in notice


def test_check_prints_advice_to_stderr(httpx_mock, check_enabled, capsys):
    httpx_mock.add_response(url=INDEX, text=index_page("0.4.1"))

    version.check_for_update()

    captured = capsys.readouterr()
    assert "idea-tools upgrade gds-idea-pkg-oc" in captured.err
    assert captured.out == ""


def test_check_is_silent_when_current_or_offline(httpx_mock, check_enabled, capsys):
    httpx_mock.add_response(url=INDEX, text=index_page("0.3.0"))
    version.check_for_update()
    httpx_mock.add_exception(httpx.ConnectError("offline"))
    version.check_for_update()

    assert capsys.readouterr().err == ""


def test_development_builds_are_never_checked(httpx_mock, monkeypatch):
    monkeypatch.delenv("IDEA_OC_NO_VERSION_CHECK")
    monkeypatch.setattr(version, "__version__", "0.1.dev1+g7370cf5")

    version.check_for_update()  # any request would fail: nothing is mocked

    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("value", ["1", "yes"])
def test_opt_out_variable_skips_the_request(httpx_mock, monkeypatch, value):
    monkeypatch.setattr(version, "__version__", "0.3.0")
    monkeypatch.setenv("IDEA_OC_NO_VERSION_CHECK", value)

    version.check_for_update()

    assert httpx_mock.get_requests() == []


def test_sync_advises_before_doing_any_work(cli_runner, github, monkeypatch):
    monkeypatch.setattr(version, "fetch_latest_version", lambda: Version("9.0.0"))
    monkeypatch.delenv("IDEA_OC_NO_VERSION_CHECK")
    monkeypatch.setattr(version, "__version__", "0.3.0")
    github.add_repo("co-cddo/gds-idea-ai-reviewer", {"src/ai_reviewer/skills/a/SKILL.md": skill_md("a")})

    result = cli_runner.invoke(cli, ["sync", "--yes"])

    assert result.exit_code == 0
    assert result.output.index("idea-tools upgrade") < result.output.index("Resolving sources")


def test_status_advises_but_does_not_change_the_exit_code(cli_runner, github, monkeypatch):
    monkeypatch.setattr(version, "fetch_latest_version", lambda: Version("9.0.0"))
    monkeypatch.delenv("IDEA_OC_NO_VERSION_CHECK")
    monkeypatch.setattr(version, "__version__", "0.3.0")
    github.add_repo("co-cddo/gds-idea-ai-reviewer", {"src/ai_reviewer/skills/a/SKILL.md": skill_md("a")})
    cli_runner.invoke(cli, ["sync", "--yes"])

    result = cli_runner.invoke(cli, ["status"])

    assert result.exit_code == 0
    assert "idea-tools upgrade" in result.output


def test_quiet_status_prints_a_single_line_notice_only(cli_runner, github, monkeypatch):
    monkeypatch.setattr(version, "fetch_latest_version", lambda: Version("9.0.0"))
    monkeypatch.delenv("IDEA_OC_NO_VERSION_CHECK")
    monkeypatch.setattr(version, "__version__", "0.3.0")
    github.add_repo("co-cddo/gds-idea-ai-reviewer", {"src/ai_reviewer/skills/a/SKILL.md": skill_md("a")})
    cli_runner.invoke(cli, ["sync", "--yes"])

    result = cli_runner.invoke(cli, ["status", "--quiet"])

    assert result.exit_code == 0
    assert len(result.output.strip().splitlines()) == 1
    assert "9.0.0" in result.output


def test_list_never_checks(cli_runner, httpx_mock, monkeypatch):
    monkeypatch.delenv("IDEA_OC_NO_VERSION_CHECK")
    monkeypatch.setattr(version, "__version__", "0.3.0")

    cli_runner.invoke(cli, ["list"])

    assert httpx_mock.get_requests() == []
