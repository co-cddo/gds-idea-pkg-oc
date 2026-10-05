"""Tests for the local skill store."""

import os
import stat

import pytest

from idea_oc.github import git_blob_sha
from idea_oc.planner import PlanError, PlannedSkill, SkillFile
from idea_oc.store import Provenance, Store, StoreError, default_store_dir

PROV = Provenance(repo="co-cddo/x", source_path="skills/demo", ref="v1", commit="a" * 40)


def make_skill(files: dict[str, bytes], *, executable: frozenset[str] = frozenset(), name="demo"):
    """Return a planned skill and a fetch function serving the given file contents."""
    planned = PlannedSkill(
        name=name,
        repo="co-cddo/x",
        source_path=f"skills/{name}",
        files=tuple(SkillFile(rel, git_blob_sha(data), rel in executable) for rel, data in sorted(files.items())),
    )
    fetched: list[str] = []

    def fetch(file: SkillFile) -> bytes:
        fetched.append(file.rel_path)
        return files[file.rel_path]

    return planned, fetch, fetched


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "store")


def unlock(path):
    path.chmod(0o644)


def test_diff_of_uninstalled_skill_is_all_missing(store):
    skill, _, _ = make_skill({"SKILL.md": b"a", "references/r.md": b"b"})

    diff = store.diff(skill)

    assert diff.missing == ("SKILL.md", "references/r.md")
    assert not diff.clean


def test_install_writes_files_and_manifest(store):
    skill, fetch, _ = make_skill({"SKILL.md": b"a", "references/r.md": b"b"})

    store.install(skill, PROV, fetch)

    assert (store.root / "demo" / "SKILL.md").read_bytes() == b"a"
    assert (store.root / "demo" / "references" / "r.md").read_bytes() == b"b"
    assert store.installed() == {"demo": PROV}
    assert store.diff(skill).clean


def test_installed_files_are_read_only_and_executable_bit_is_kept(store):
    skill, fetch, _ = make_skill({"SKILL.md": b"a", "run.sh": b"#!/bin/sh"}, executable=frozenset({"run.sh"}))

    store.install(skill, PROV, fetch)

    assert stat.S_IMODE((store.root / "demo" / "SKILL.md").stat().st_mode) == 0o444
    assert stat.S_IMODE((store.root / "demo" / "run.sh").stat().st_mode) == 0o555


def test_unchanged_skill_downloads_nothing(store):
    skill, fetch, fetched = make_skill({"SKILL.md": b"a", "b.md": b"b"})
    store.install(skill, PROV, fetch)
    fetched.clear()

    diff = store.install(skill, PROV, fetch)

    assert diff.clean
    assert fetched == []


def test_only_changed_files_are_downloaded(store):
    v1, fetch1, _ = make_skill({"SKILL.md": b"a", "b.md": b"b"})
    store.install(v1, PROV, fetch1)
    v2, fetch2, fetched = make_skill({"SKILL.md": b"a", "b.md": b"b2", "c.md": b"c"})

    store.install(v2, PROV, fetch2)

    assert sorted(fetched) == ["b.md", "c.md"]
    assert (store.root / "demo" / "b.md").read_bytes() == b"b2"
    assert (store.root / "demo" / "SKILL.md").read_bytes() == b"a"


def test_files_removed_upstream_are_removed_locally(store):
    v1, fetch1, _ = make_skill({"SKILL.md": b"a", "old/x.md": b"x"})
    store.install(v1, PROV, fetch1)
    v2, fetch2, _ = make_skill({"SKILL.md": b"a"})

    store.install(v2, PROV, fetch2)

    assert not (store.root / "demo" / "old").exists()


def test_provenance_change_alone_updates_manifest_without_downloads(store):
    skill, fetch, fetched = make_skill({"SKILL.md": b"a"})
    store.install(skill, PROV, fetch)
    fetched.clear()
    newer = Provenance(PROV.repo, PROV.source_path, "v2", "b" * 40)

    store.install(skill, newer, fetch)

    assert fetched == []
    assert store.installed()["demo"].ref == "v2"


def test_local_edit_is_detected_and_restored(store):
    skill, fetch, fetched = make_skill({"SKILL.md": b"a", "b.md": b"b"})
    store.install(skill, PROV, fetch)
    edited = store.root / "demo" / "b.md"
    unlock(edited)
    edited.write_bytes(b"tampered")

    assert store.diff(skill).changed == ("b.md",)
    fetched.clear()
    store.install(skill, PROV, fetch)

    assert fetched == ["b.md"]
    assert edited.read_bytes() == b"b"


def test_extra_and_missing_files_are_detected(store):
    skill, fetch, _ = make_skill({"SKILL.md": b"a", "b.md": b"b"})
    store.install(skill, PROV, fetch)
    (store.root / "demo" / "b.md").unlink()
    (store.root / "demo" / "notes.txt").write_text("mine")

    diff = store.diff(skill)

    assert (diff.missing, diff.extra) == (("b.md",), ("notes.txt",))


def test_executable_bit_change_is_detected(store):
    skill, fetch, _ = make_skill({"SKILL.md": b"a", "run.sh": b"x"}, executable=frozenset({"run.sh"}))
    store.install(skill, PROV, fetch)
    (store.root / "demo" / "run.sh").chmod(0o444)

    assert store.diff(skill).changed == ("run.sh",)


def test_symlink_in_place_of_a_file_is_detected(store, tmp_path):
    skill, fetch, _ = make_skill({"SKILL.md": b"a"})
    store.install(skill, PROV, fetch)
    target = tmp_path / "elsewhere.md"
    target.write_bytes(b"a")
    (store.root / "demo" / "SKILL.md").unlink()
    os.symlink(target, store.root / "demo" / "SKILL.md")

    assert store.diff(skill).changed == ("SKILL.md",)


def test_failed_fetch_leaves_existing_skill_intact_and_cleans_up(store):
    v1, fetch1, _ = make_skill({"SKILL.md": b"a", "b.md": b"b"})
    store.install(v1, PROV, fetch1)
    v2, _, _ = make_skill({"SKILL.md": b"a2", "b.md": b"b2"})

    def failing(file):
        raise RuntimeError("network down")

    with pytest.raises(RuntimeError):
        store.install(v2, PROV, failing)

    assert (store.root / "demo" / "SKILL.md").read_bytes() == b"a"
    assert not list((store.root / ".staging").glob("*"))
    assert store.diff(v1).clean


def test_path_traversal_in_file_path_is_refused(store):
    bad = PlannedSkill("demo", "co-cddo/x", "p", (SkillFile("../../evil", git_blob_sha(b"x")),))

    with pytest.raises(StoreError, match="outside"):
        store.install(bad, PROV, lambda f: b"x")

    assert not (store.root.parent / "evil").exists()


def test_invalid_skill_name_is_refused(store):
    with pytest.raises(PlanError):
        store.skill_dir("../escape")


def test_stale_lists_only_unexpected_skill_folders(store):
    skill, fetch, _ = make_skill({"SKILL.md": b"a"})
    store.install(skill, PROV, fetch)
    (store.root / "gone").mkdir()
    (store.root / ".staging").mkdir(exist_ok=True)

    assert store.stale({"demo"}) == ["gone"]
    assert store.stale({"demo", "gone"}) == []


def test_stale_on_missing_store_is_empty(store):
    assert store.stale(set()) == []


def test_remove_deletes_folder_and_manifest_entry(store):
    skill, fetch, _ = make_skill({"SKILL.md": b"a"})
    store.install(skill, PROV, fetch)

    store.remove("demo")

    assert not (store.root / "demo").exists()
    assert store.installed() == {}


def test_corrupt_manifest_counts_as_empty_and_is_repaired(store):
    skill, fetch, _ = make_skill({"SKILL.md": b"a"})
    store.install(skill, PROV, fetch)
    store.manifest_path.write_text("{not json")

    assert store.installed() == {}
    store.install(skill, PROV, fetch)

    assert store.installed() == {"demo": PROV}


def test_default_store_dir_honours_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("IDEA_OC_STORE", str(tmp_path / "custom"))
    assert default_store_dir() == tmp_path / "custom"

    monkeypatch.delenv("IDEA_OC_STORE")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert default_store_dir() == tmp_path / "xdg" / "idea-oc" / "skills"
