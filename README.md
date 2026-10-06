# idea-oc

Installs the GDS IDEA team's approved [OpenCode](https://opencode.ai) agent skills on your machine
and registers them with OpenCode, so everyone works from the same set.

**Documentation: <https://co-cddo.github.io/gds-idea-pkg-oc/>**

## Install

```bash
idea-tools install gds-idea-pkg-oc
idea-oc sync
```

New to OpenCode? Start with the [setup guide](docs/guides/setup.md).

## Documentation

The docs live in [`docs/`](docs/) and are published with mkdocs.

| | |
|---|---|
| [Set up OpenCode](docs/guides/setup.md) | From install to running against Bedrock |
| [Plugins](docs/guides/plugins.md) | The required plugin and the recommended ones |
| [sync](docs/commands/sync.md), [status](docs/commands/status.md), [list](docs/commands/list.md) | The commands |
| [Preferred config](docs/reference/preferred-config.md) | The team's OpenCode config and how permission rules work |

The preferred config itself is [`src/idea_oc/opencode.jsonc`](src/idea_oc/opencode.jsonc).

## Prerequisites for development

- [uv](https://docs.astral.sh/uv/) for Python package management
- [git](https://git-scm.com/)
- [gitleaks](https://github.com/gitleaks/gitleaks) for pre-commit secret scanning (`brew install gitleaks`)

## Getting started

1. Clone the repository:

   ```bash
   git clone git@github.com:co-cddo/gds-idea-pkg-oc.git
   cd gds-idea-pkg-oc
   ```

2. Install dependencies:

   ```bash
   uv sync
   ```

3. Set up pre-commit hooks:

   ```bash
   uv run pre-commit install
   ```

   This is done automatically when the project is first scaffolded.
   Pre-commit runs [ruff](https://docs.astral.sh/ruff/) on every commit
   to auto-fix lint issues and enforce formatting.

## Development

### Running tests

```bash
uv run pytest
```

### Running linting manually

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

### Working on the docs

```bash
uv sync --group docs
uv run mkdocs serve
```

`uv run mkdocs build --strict` fails on broken links, as the docs workflow does on pull requests.

### Pre-commit hooks

Pre-commit hooks run automatically on `git commit`. They will:

- **Auto-fix** lint issues detected by `ruff check --fix`
- **Auto-format** code with `ruff format`
- **Check** YAML/TOML syntax, trailing whitespace, merge conflicts
- **Scan** for leaked secrets with gitleaks
- **Prevent** direct commits to `main`

If files are modified by the hooks, the commit will be aborted.
Review the changes, `git add` them, and commit again.

To run hooks against all files manually:

```bash
uv run pre-commit run --all-files
```

## Versioning

This project uses [hatch-vcs](https://github.com/ofek/hatch-vcs) for
automatic versioning from git tags. Versions are never set manually.

On merge to `main`, the auto-release workflow creates a new tag based on
PR labels:

- `bump:major` — major version bump
- `bump:minor` — minor version bump
- (default) — patch version bump

## Licence

[MIT License](LICENCE)
