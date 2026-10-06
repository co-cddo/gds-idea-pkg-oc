"""The docs are part of the product: links the CLI prints, and code shown in the docs, must stay correct."""

import re
import unicodedata
from pathlib import Path

import pytest

from idea_oc.docs import ALL_LINKS, DOCS_SITE

ROOT = Path(__file__).parent.parent
DOCS = ROOT / "docs"
SOURCE = ROOT / "src" / "idea_oc"


def slugify(heading: str) -> str:
    """The anchor mkdocs (python-markdown's toc extension) gives a heading."""
    text = unicodedata.normalize("NFKD", heading).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[-\s]+", "-", re.sub(r"[^\w\s-]", "", text).strip().lower())


def anchors(page: Path) -> set[str]:
    headings = re.findall(r"^#{1,6}\s+(.*?)\s*$", page.read_text(), re.M)
    return {slugify(heading) for heading in headings}


def page_for(url_path: str) -> Path:
    """The Markdown file that mkdocs serves at ``url_path`` (relative to the site root)."""
    stem = url_path.strip("/")
    return DOCS / (f"{stem}.md" if stem else "index.md")


def printed_urls() -> list[str]:
    """Every link to the docs site that users see.

    That is the links written out in the Python source and the bundled config, plus the ones in
    ``idea_oc.docs``, which the source builds from parts and so cannot be found by reading the text.
    """
    pattern = re.escape(DOCS_SITE) + r"[^\s\"')]*"
    files = [*SOURCE.rglob("*.py"), SOURCE / "opencode.jsonc"]
    return sorted({*ALL_LINKS, *(url for file in files for url in re.findall(pattern, file.read_text()))})


def test_every_link_idea_oc_prints_is_among_those_checked():
    checked = printed_urls()

    assert set(ALL_LINKS) <= set(checked)
    assert any(url.endswith("/guides/setup/") for url in checked)  # the config header's links are found too


@pytest.mark.parametrize("url", printed_urls())
def test_every_docs_link_the_user_sees_points_at_a_real_page_and_heading(url):
    path, _, anchor = url.removeprefix(DOCS_SITE).partition("#")
    page = page_for(path)

    assert page.exists(), f"{url} points at {page.relative_to(ROOT)}, which does not exist"
    if anchor:
        assert anchor in anchors(page), f"{url}: no heading '{anchor}' in {page.relative_to(ROOT)}"


def test_every_page_in_the_nav_exists_and_every_page_is_in_the_nav():
    nav = {DOCS / name for name in re.findall(r":\s+([\w/.-]+\.md)\s*$", (ROOT / "mkdocs.yml").read_text(), re.M)}

    assert all(page.exists() for page in nav)
    assert nav == set(DOCS.rglob("*.md"))


def test_the_slug_function_matches_the_headings_the_docs_link_to():
    assert slugify("Why sync skills does not edit your config") == "why-sync-skills-does-not-edit-your-config"
    assert slugify("1. Install OpenCode") == "1-install-opencode"
    assert slugify("opencode-snip needs a separate program") == "opencode-snip-needs-a-separate-program"


def test_links_between_docs_pages_use_anchors_that_exist():
    broken = []
    for page in DOCS.rglob("*.md"):
        for target, anchor in re.findall(r"\]\(([\w./-]+\.md)#([\w-]+)\)", page.read_text()):
            linked = (page.parent / target).resolve()
            if not linked.exists() or anchor not in anchors(linked):
                broken.append(f"{page.relative_to(ROOT)} -> {target}#{anchor}")

    assert broken == []


def test_links_to_files_in_the_repo_point_at_files_that_exist():
    pattern = r"github\.com/co-cddo/gds-idea-pkg-oc/blob/main/([^\s)#]+)"
    missing = [
        f"{page.relative_to(ROOT)} -> {path}"
        for page in [*DOCS.rglob("*.md"), ROOT / "README.md"]
        for path in re.findall(pattern, page.read_text())
        if not (ROOT / path).exists()
    ]

    assert missing == []


def test_the_plugin_script_shown_in_the_docs_is_the_bundled_file():
    bundled = (SOURCE / "plugin-scripts" / "inject-env.js").read_text().strip()
    blocks = re.findall(r"```(?:\w+)?\n(.*?)```", (DOCS / "guides" / "plugins.md").read_text(), re.S)

    assert any(bundled in block for block in blocks)


def test_the_plugins_the_docs_recommend_are_the_ones_in_the_preferred_config():
    from idea_oc.jsonc_doc import JsoncDocument

    config = JsoncDocument.parse((SOURCE / "opencode.jsonc").read_text())
    listed = [p if isinstance(p, str) else p[0] for p in config.get(("plugin",))]
    docs = (DOCS / "guides" / "plugins.md").read_text()

    for plugin in listed:
        name = plugin.rsplit("@", 1)[0] if plugin.startswith("@") and plugin.count("@") > 1 else plugin
        assert Path(name).name in docs, f"{plugin} is in the preferred config but not in the plugins guide"
