"""Where the published docs live, and the pages idea-oc links to from its output."""

DOCS_SITE = "https://co-cddo.github.io/gds-idea-pkg-oc/"

SYNC_WHY_URL = f"{DOCS_SITE}commands/sync/#why-sync-skills-does-not-edit-your-config"
PLUGINS_REQUIRED_URL = f"{DOCS_SITE}guides/plugins/#the-required-plugin"
PLUGINS_RECOMMENDED_URL = f"{DOCS_SITE}guides/plugins/#recommended-plugins"
PLUGINS_SNIP_URL = f"{DOCS_SITE}guides/plugins/#opencode-snip-needs-a-separate-program"

# Every link built here is checked against the docs by tests/test_docs.py.
ALL_LINKS = (SYNC_WHY_URL, PLUGINS_REQUIRED_URL, PLUGINS_RECOMMENDED_URL, PLUGINS_SNIP_URL)
