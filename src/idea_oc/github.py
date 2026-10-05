"""Minimal GitHub API client for reading files from a repository at a fixed commit."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from urllib.parse import quote

import httpx

GITHUB_API_BASE = "https://api.github.com"


class GitHubError(Exception):
    """Raised when a GitHub API call fails."""


class NotFoundError(GitHubError):
    """Raised when a repository, ref or object does not exist (or is not visible)."""


class IntegrityError(GitHubError):
    """Raised when downloaded content does not match its git blob SHA."""


def git_blob_sha(data: bytes) -> str:
    """Return the git object id of ``data`` stored as a blob.

    Args:
        data: Raw file content.

    Returns:
        The 40-character hex SHA-1 that git assigns to this content.
    """
    header = f"blob {len(data)}\0".encode()
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def get_token() -> str | None:
    """Find a GitHub token, or None if none is available.

    Checks ``GH_TOKEN`` and ``GITHUB_TOKEN``, then asks the gh CLI. Public repos
    work without a token, but at a much lower rate limit.
    """
    for var in ("GH_TOKEN", "GITHUB_TOKEN"):
        token = os.environ.get(var, "").strip()
        if token:
            return token
    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True, timeout=10)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


@dataclass(frozen=True)
class ResolvedRef:
    """A ref resolved to an immutable commit.

    Attributes:
        repo: Repository as ``owner/name``.
        name: Human-readable ref (release tag, branch name or the ref given).
        sha: Commit SHA that ``name`` pointed to.
        floating: True when ``latest`` fell back to the default branch because
            the repo has no releases, so the content is not a tagged release.
    """

    repo: str
    name: str
    sha: str
    floating: bool = False


@dataclass(frozen=True)
class TreeEntry:
    """One entry in a git tree."""

    path: str
    mode: str
    type: str
    sha: str
    size: int = 0


class GitHubClient:
    """Thin wrapper around the GitHub REST API using httpx."""

    def __init__(self, token: str | None = None, *, base_url: str = GITHUB_API_BASE):
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.authenticated = bool(token)
        self._client = httpx.Client(base_url=base_url, headers=headers, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def _get(self, path: str, *, accept: str | None = None, missing_ok: bool = False) -> httpx.Response | None:
        headers = {"Accept": accept} if accept else None
        try:
            response = self._client.get(path, headers=headers)
        except httpx.HTTPError as e:
            raise GitHubError(f"Cannot reach GitHub: {e}") from e

        if response.status_code == 404:
            if missing_ok:
                return None
            hint = "" if self.authenticated else " (private repos need 'gh auth login')"
            raise NotFoundError(f"Not found on GitHub: {path}{hint}")
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            hint = "" if self.authenticated else " Run 'gh auth login' for a higher limit."
            raise GitHubError(f"GitHub API rate limit exceeded.{hint}")
        if response.status_code == 401:
            raise GitHubError("GitHub authentication failed. Run 'gh auth login'.")
        if response.status_code >= 400:
            raise GitHubError(f"GitHub API error {response.status_code} for {path}")
        return response

    def resolve_ref(self, repo: str, ref: str = "latest") -> ResolvedRef:
        """Resolve a registry ref to a commit.

        Args:
            repo: Repository as ``owner/name``.
            ref: ``latest`` for the newest release (default branch if there are no releases),
                or any tag, branch or commit SHA.

        Returns:
            The resolved ref.

        Raises:
            NotFoundError: If the repo or ref does not exist.
        """
        floating = False
        if ref == "latest":
            release = self._get(f"/repos/{repo}/releases/latest", missing_ok=True)
            if release is not None:
                name = release.json()["tag_name"]
            else:
                name = self._get(f"/repos/{repo}").json()["default_branch"]  # type: ignore[union-attr]
                floating = True
        else:
            name = ref

        commit = self._get(f"/repos/{repo}/commits/{quote(name, safe='/')}")
        return ResolvedRef(repo=repo, name=name, sha=commit.json()["sha"], floating=floating)  # type: ignore[union-attr]

    def get_tree(self, repo: str, sha: str) -> list[TreeEntry]:
        """List every entry in the repo at commit ``sha``.

        Raises:
            GitHubError: If GitHub truncated the listing (repo too large).
        """
        data = self._get(f"/repos/{repo}/git/trees/{sha}?recursive=1").json()  # type: ignore[union-attr]
        if data.get("truncated"):
            raise GitHubError(f"Tree for {repo}@{sha[:7]} is too large to list in one request")
        return [
            TreeEntry(path=e["path"], mode=e["mode"], type=e["type"], sha=e["sha"], size=e.get("size", 0))
            for e in data["tree"]
        ]

    def get_blob(self, repo: str, sha: str) -> bytes:
        """Download a blob and verify it against its git SHA.

        Raises:
            IntegrityError: If the downloaded bytes do not hash to ``sha``.
        """
        response = self._get(f"/repos/{repo}/git/blobs/{sha}", accept="application/vnd.github.raw+json")
        data = response.content  # type: ignore[union-attr]
        if git_blob_sha(data) != sha:
            raise IntegrityError(f"Downloaded content for blob {sha[:7]} in {repo} does not match its hash")
        return data
