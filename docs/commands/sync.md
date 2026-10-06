# sync

Install the approved skills and register them with OpenCode.

```bash
idea-oc sync            # both stages: skills, then config
idea-oc sync skills     # install the approved skills (needs the network)
idea-oc sync config     # update your OpenCode config (works offline)
```

## The two stages

| Stage | What it does | Needs the network | Writes to |
|---|---|---|---|
| `skills` | Installs the approved skills into the skill folder, and removes ones that are no longer approved | Yes | The skill folder only |
| `config` | Registers the skill folder in your OpenCode config | No | Your OpenCode config only |

The stages are independent. Either can be run, skipped or fail without affecting the other, and
neither needs the other to have run first. If you run both and `skills` fails, `config` still runs.
The command exits with status 1 if any stage failed.

## Options

| Option | Applies to | Effect |
|---|---|---|
| `--dry-run` | both | Show what would change and write nothing. Never prompts. |
| `--prune` / `--no-prune` | skills | Remove skills that are no longer approved (the default), or keep them. |
| `-y`, `--yes` | config | Apply changes to your OpenCode config without asking. |
| `--registry FILE` | both | Use a custom registry file instead of the built-in one. Goes before the command. |

## The skills stage

Skills come from the sources in the built-in registry. For each source `idea-oc` reads the latest
release of the repository and installs only the files that differ from what you already have, so a
second run downloads nothing.

- A source can **discover** every skill in a folder, so skills added upstream appear on your next
  sync with no change to `idea-oc`, or name particular skills, from several repositories.
- Each skill is checked before it is installed: its `SKILL.md` must have a `name` that matches its
  folder and a `description`.
- Skills are installed read-only into `~/.local/share/idea-oc/skills`. If you edit a file there,
  the next sync restores it.
- If a source cannot be reached, the skills already installed from it are kept. Nothing is removed
  while any source is failing.

## The config stage

OpenCode only loads skills from folders listed under `skills.paths` in its config. This stage adds
the skill folder to that list. It shows you the change, asks yes or no, and saves a backup next to
the file as `opencode.jsonc.idea-oc.bak` before it writes.

Comments and formatting in your config are kept. If the file cannot be edited safely, for example
because it is not valid, `idea-oc` leaves it alone and prints the snippet to add yourself.

## Why sync skills does not edit your config

OpenCode only loads skills from folders it has been told about. `idea-oc` installs team skills into
its own folder, separate from your personal skills, and OpenCode finds that folder through the
`skills.paths` entry in your `opencode.jsonc` or `opencode.json`.

That entry is a change to a file you own, so it belongs to the config stage: `idea-oc sync config`
shows exactly what it will change, asks you yes or no, and saves a backup first.
`idea-oc sync skills` never writes to your config, so it is safe to run from hooks and CI.

If you only run `sync skills`, the skills are installed but OpenCode will not see them until you
run `idea-oc sync config` once. Plain `idea-oc sync` runs both stages for you.
