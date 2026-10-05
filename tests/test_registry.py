"""Tests for registry loading and validation."""

import pytest

from idea_oc.registry import RegistryError, load_registry


@pytest.fixture
def write_registry(tmp_path):
    def _write(text: str):
        path = tmp_path / "registry.toml"
        path.write_text(text)
        return path

    return _write


def test_bundled_registry_loads():
    registry = load_registry()

    assert registry.source
    assert all(src.owner in registry.allowed_owners for src in registry.source)


def test_bundled_registry_discovers_ai_reviewer_skills():
    registry = load_registry()

    reviewer = next(s for s in registry.source if s.repo == "co-cddo/gds-idea-ai-reviewer")
    assert reviewer.discover == "src/ai_reviewer/skills"
    assert reviewer.ref == "latest"


def test_multiple_skills_from_one_repo(write_registry):
    path = write_registry(
        """
        [[source]]
        repo = "co-cddo/gds-idea-app-kit"
        skills = ["skills/idea-app-usage/", "/skills/other/SKILL.md"]
        """
    )

    source = load_registry(path).source[0]

    assert source.skills == ["skills/idea-app-usage", "skills/other/SKILL.md"]
    assert source.ref == "latest"


def test_discover_with_exclude(write_registry):
    path = write_registry(
        """
        [[source]]
        repo = "co-cddo/x"
        discover = "skills"
        exclude = ["draft"]
        """
    )

    assert load_registry(path).source[0].exclude == ["draft"]


@pytest.mark.parametrize(
    "body",
    [
        'repo = "co-cddo/x"',
        'repo = "co-cddo/x"\ndiscover = "a"\nskills = ["b"]',
        'repo = "co-cddo/x"\nskills = []',
        'repo = "co-cddo/x"\nskills = ["../etc"]',
        'repo = "co-cddo/x"\ndiscover = "/"',
        'repo = "co-cddo/x"\nskills = ["a"]\nexclude = ["b"]',
        'repo = "not-a-repo"\ndiscover = "a"',
        'repo = "co-cddo/x"\ndiscover = "a"\nunknown = 1',
        'repo = "someone-else/x"\ndiscover = "a"',
    ],
)
def test_invalid_source_is_rejected(write_registry, body):
    path = write_registry(f"[[source]]\n{body}\n")

    with pytest.raises(RegistryError):
        load_registry(path)


def test_unknown_top_level_key_is_rejected(write_registry):
    path = write_registry("bogus = 1\n")

    with pytest.raises(RegistryError):
        load_registry(path)


def test_invalid_toml_is_rejected(write_registry):
    path = write_registry("[[source\n")

    with pytest.raises(RegistryError, match="Invalid TOML"):
        load_registry(path)


def test_missing_file_is_rejected(tmp_path):
    with pytest.raises(RegistryError, match="Cannot read"):
        load_registry(tmp_path / "nope.toml")


def test_custom_allowed_owner(write_registry):
    path = write_registry(
        """
        allowed_owners = ["co-cddo", "other-org"]
        [[source]]
        repo = "other-org/x"
        discover = "a"
        """
    )

    assert load_registry(path).source[0].owner == "other-org"
