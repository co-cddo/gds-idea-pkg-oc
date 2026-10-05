"""Shared test configuration and fixtures."""

from __future__ import annotations

import hashlib
import re

import httpx
import pytest
from click.testing import CliRunner

from idea_oc.github import git_blob_sha


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: tests that require external services")


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """Keep every test away from the real home directory, store, OpenCode config and gh login."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("IDEA_OC_STORE", str(home / ".local" / "share" / "idea-oc" / "skills"))
    monkeypatch.setenv("IDEA_OC_CONFIG", str(home / ".config" / "opencode" / "opencode.json"))
    monkeypatch.setenv("GH_TOKEN", "test-token")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return home


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


class FakeGitHub:
    """An in-memory GitHub serving the few endpoints idea-oc uses, and recording requests."""

    def __init__(self):
        self.repos: dict[str, dict] = {}
        self.requests: list[str] = []

    def add_repo(self, repo: str, files: dict[str, bytes | str], *, tag: str | None = "v1.0.0", modes=None):
        """Create or update a repo. ``tag=None`` makes a repo with no releases (default branch only)."""
        files = {path: data.encode() if isinstance(data, str) else data for path, data in files.items()}
        self.repos[repo] = {"files": files, "tag": tag, "modes": modes or {}}

    def commit_sha(self, repo: str) -> str:
        info = self.repos[repo]
        return hashlib.sha1(f"{repo}@{info['tag'] or 'main'}:{sorted(info['files'])}".encode()).hexdigest()  # noqa: S324

    def blob_requests(self) -> list[str]:
        return [r for r in self.requests if "/git/blobs/" in r]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append(path)
        match = re.fullmatch(r"/repos/([^/]+/[^/]+)(/.*)?", path)
        if not match or match.group(1) not in self.repos:
            return httpx.Response(404, json={"message": "Not Found"})
        repo, rest = match.group(1), match.group(2) or ""
        info = self.repos[repo]

        if rest == "":
            return httpx.Response(200, json={"default_branch": "main"})
        if rest == "/releases/latest":
            if info["tag"] is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"tag_name": info["tag"]})
        if rest.startswith("/commits/"):
            ref = rest.removeprefix("/commits/")
            if ref not in {info["tag"], "main"}:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"sha": self.commit_sha(repo)})
        if rest.startswith("/git/trees/"):
            return httpx.Response(200, json=self._tree(info))
        if rest.startswith("/git/blobs/"):
            sha = rest.removeprefix("/git/blobs/")
            for data in info["files"].values():
                if git_blob_sha(data) == sha:
                    return httpx.Response(200, content=data)
        return httpx.Response(404, json={})

    @staticmethod
    def _tree(info: dict) -> dict:
        folders = {"/".join(p.split("/")[:i]) for p in info["files"] for i in range(1, len(p.split("/")))}
        tree = [{"path": f, "mode": "040000", "type": "tree", "sha": "0" * 40} for f in sorted(folders)]
        tree += [
            {
                "path": path,
                "mode": info["modes"].get(path, "100644"),
                "type": "blob",
                "sha": git_blob_sha(data),
                "size": len(data),
            }
            for path, data in sorted(info["files"].items())
        ]
        return {"truncated": False, "tree": tree}


@pytest.fixture
def github(httpx_mock) -> FakeGitHub:
    """A fake GitHub wired into every httpx client for the duration of the test."""
    fake = FakeGitHub()
    httpx_mock.add_callback(fake, is_reusable=True)
    return fake


def skill_md(name: str, description: str = "A test skill", body: str = "Body") -> str:
    """Return valid ``SKILL.md`` text for a skill called ``name``."""
    return f"---\nname: {name}\ndescription: {description}\n---\n{body}\n"
