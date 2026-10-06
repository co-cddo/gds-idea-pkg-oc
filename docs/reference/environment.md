# Environment variables

| Variable | Effect |
|---|---|
| `IDEA_OC_STORE` | Where skills are installed. Defaults to `~/.local/share/idea-oc/skills` (or under `$XDG_DATA_HOME`). |
| `IDEA_OC_CONFIG` | The OpenCode config file to read and edit. Defaults to the file OpenCode itself treats as the main one: the first of `opencode.jsonc`, `opencode.json` and `config.json` in `~/.config/opencode` (or under `$XDG_CONFIG_HOME`) that exists, or `opencode.jsonc` if none do. |
| `IDEA_OC_NO_VERSION_CHECK` | Set to `1` to skip the check for a newer `idea-oc`. |
| `GH_TOKEN`, `GITHUB_TOKEN` | A GitHub token used to read skill sources. If neither is set, `idea-oc` asks the `gh` CLI (`gh auth login`). Public sources work without one, with a lower rate limit. |
