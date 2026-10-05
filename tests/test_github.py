"""Tests for the GitHub client."""

import subprocess

import httpx
import pytest

from idea_oc import github
from idea_oc.github import GitHubClient, GitHubError, IntegrityError, NotFoundError, TreeEntry, git_blob_sha

API = "https://api.github.com"
REPO = "co-cddo/example"
SHA = "a" * 40


def test_git_blob_sha_matches_git():
    # Values produced by `git hash-object`.
    assert git_blob_sha(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert git_blob_sha(b"hello\n") == "ce013625030ba8dba906f756967f9e9ca394464a"


@pytest.fixture
def client():
    with GitHubClient(token="t") as c:
        yield c


def test_resolve_latest_uses_newest_release(httpx_mock, client):
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/releases/latest", json={"tag_name": "v1.2.3"})
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/commits/v1.2.3", json={"sha": SHA})

    resolved = client.resolve_ref(REPO)

    assert (resolved.name, resolved.sha, resolved.floating) == ("v1.2.3", SHA, False)


def test_resolve_latest_falls_back_to_default_branch_without_releases(httpx_mock, client):
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/releases/latest", status_code=404)
    httpx_mock.add_response(url=f"{API}/repos/{REPO}", json={"default_branch": "main"})
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/commits/main", json={"sha": SHA})

    resolved = client.resolve_ref(REPO, "latest")

    assert (resolved.name, resolved.floating) == ("main", True)


def test_resolve_explicit_ref_skips_release_lookup(httpx_mock, client):
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/commits/release/1.0", json={"sha": SHA})

    resolved = client.resolve_ref(REPO, "release/1.0")

    assert (resolved.name, resolved.sha, resolved.floating) == ("release/1.0", SHA, False)


def test_unknown_ref_raises_not_found(httpx_mock, client):
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/commits/nope", status_code=404)

    with pytest.raises(NotFoundError):
        client.resolve_ref(REPO, "nope")


def test_not_found_hints_at_login_when_unauthenticated(httpx_mock):
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/commits/main", status_code=404)

    with GitHubClient(token=None) as anon, pytest.raises(NotFoundError, match="gh auth login"):
        anon.resolve_ref(REPO, "main")


def test_rate_limit_is_reported(httpx_mock, client):
    httpx_mock.add_response(
        url=f"{API}/repos/{REPO}/commits/main", status_code=403, headers={"x-ratelimit-remaining": "0"}
    )

    with pytest.raises(GitHubError, match="rate limit"):
        client.resolve_ref(REPO, "main")


def test_bad_credentials_are_reported(httpx_mock, client):
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/commits/main", status_code=401)

    with pytest.raises(GitHubError, match="authentication failed"):
        client.resolve_ref(REPO, "main")


def test_network_failure_is_wrapped(httpx_mock, client):
    httpx_mock.add_exception(httpx.ConnectError("boom"))

    with pytest.raises(GitHubError, match="Cannot reach GitHub"):
        client.resolve_ref(REPO, "main")


def test_get_tree_parses_entries(httpx_mock, client):
    httpx_mock.add_response(
        url=f"{API}/repos/{REPO}/git/trees/{SHA}?recursive=1",
        json={
            "truncated": False,
            "tree": [
                {"path": "skills", "mode": "040000", "type": "tree", "sha": "b" * 40},
                {"path": "skills/x/SKILL.md", "mode": "100644", "type": "blob", "sha": "c" * 40, "size": 12},
            ],
        },
    )

    tree = client.get_tree(REPO, SHA)

    assert tree[1] == TreeEntry(path="skills/x/SKILL.md", mode="100644", type="blob", sha="c" * 40, size=12)


def test_truncated_tree_is_an_error(httpx_mock, client):
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/git/trees/{SHA}?recursive=1", json={"truncated": True, "tree": []})

    with pytest.raises(GitHubError, match="too large"):
        client.get_tree(REPO, SHA)


def test_get_blob_downloads_and_verifies(httpx_mock, client):
    sha = git_blob_sha(b"hello\n")
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/git/blobs/{sha}", content=b"hello\n")

    assert client.get_blob(REPO, sha) == b"hello\n"


def test_get_blob_rejects_content_that_does_not_match_sha(httpx_mock, client):
    sha = git_blob_sha(b"hello\n")
    httpx_mock.add_response(url=f"{API}/repos/{REPO}/git/blobs/{sha}", content=b"evil\n")

    with pytest.raises(IntegrityError):
        client.get_blob(REPO, sha)


def test_token_prefers_environment(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", " abc ")

    assert github.get_token() == "abc"


def test_token_falls_back_to_gh_cli(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        github.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="cli-token\n", stderr="")
    )

    assert github.get_token() == "cli-token"


def test_token_is_none_without_gh(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    def _missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(github.subprocess, "run", _missing)

    assert github.get_token() is None
