# gds-idea-pkg-oc

_Brief description of your package._

## Usage

`idea-oc sync` has two independent stages. Run both, or either on its own:

```bash
idea-oc sync            # skills, then config
idea-oc sync skills     # install the approved skills (needs the network)
idea-oc sync config     # update your OpenCode config (works offline)
```

`idea-oc status [skills|config]` checks the same stages without changing anything and
exits 1 if a sync is needed.

### Why sync skills does not edit your config

OpenCode only loads skills from folders it has been told about. idea-oc installs team
skills into its own folder (`~/.local/share/idea-oc/skills`), separate from your personal
skills, and OpenCode finds that folder through the `skills.paths` entry in your
`opencode.json` or `opencode.jsonc`.

That entry is a change to a file you own, so it belongs to the config stage: `idea-oc sync
config` shows exactly what it will change, asks you yes or no, and saves a backup first.
`idea-oc sync skills` never writes to your config, so it is safe to run from hooks and CI.

If you only run `sync skills`, the skills are installed but OpenCode will not see them until
you run `idea-oc sync config` once. Plain `idea-oc sync` runs both stages for you.

## Preferred OpenCode config

The team's preferred OpenCode configuration is kept in
[`src/idea_oc/opencode.jsonc`](src/idea_oc/opencode.jsonc): the Bedrock provider and model, the
recommended plugins, and the `permission` rules that guard commands such as `gh pr merge`,
`git push` and `rm -rf`. Use it as the reference when setting up OpenCode, or compare it with
your own `~/.config/opencode/opencode.jsonc`.

Permission rules are read top to bottom and the **last matching rule wins**, so the order of the
`bash` rules matters: keep the `"*"` catch-all first and put more specific rules below the
general ones they refine.

## Prerequisites

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
