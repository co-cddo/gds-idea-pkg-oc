# sync

Install the approved skills, and bring your OpenCode config in line with the team's preferred one.

```bash
idea-oc sync            # both stages: skills, then config
idea-oc sync skills     # install the approved skills (needs the network)
idea-oc sync config     # compare your OpenCode config with the team's (works offline)
```

## The two stages

| Stage | What it does | Needs the network | Writes to |
|---|---|---|---|
| `skills` | Installs the approved skills into the skill folder, and removes ones that are no longer approved | Yes | The skill folder only |
| `config` | Compares your OpenCode config with the team's preferred config and applies the differences you approve | No | Your OpenCode config only |

The stages are independent. Either can be run, skipped or fail without affecting the other, and
neither needs the other to have run first. If you run both and `skills` fails, `config` still runs.
The command exits with status 1 if any stage failed.

## Options

| Option | Applies to | Effect |
|---|---|---|
| `--dry-run` | both | Show what would change and write nothing. Never prompts. |
| `--prune` / `--no-prune` | skills | Remove skills that are no longer approved (the default), or keep them. |
| `-y`, `--yes` | config | Apply the changes to your OpenCode config without asking. |
| `--team NAME` | config | Whose inference profile to use: `ds`, `sds` or `econ`. By default the team your config already uses, else `ds`. |
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

This stage compares your OpenCode config with the team's
[preferred config](../reference/preferred-config.md), shows you what would change, and asks whether to
apply it.

```text
Changes to ~/.config/opencode/opencode.jsonc:
  append  skills.paths                              ~/.local/share/idea-oc/skills
  add     provider.amazon-bedrock.models.anthropic-claude-sonnet-5-5-ds  inference profile 4niqtfvd2b0y
  change  model                                     amazon-bedrock/eu.anthropic.claude-sonnet-5-5 -> amazon-bedrock/anthropic-claude-sonnet-5-5-ds
  add     permission.bash["rm -rf*"]                deny

Apply these changes? The original is saved as ~/.config/opencode/opencode.jsonc.idea-oc.bak. [y/N]:
```

**What it looks at**

- the skill folder, which must be listed under `skills.paths` so OpenCode loads your skills,
- the Bedrock provider settings, `disabled_providers`, and the `model`, which points at your team's
  inference profile (see [Teams and usage tracking](../reference/teams.md)),
- the `permission` rules.

**What it never touches.** Plugins are not changed. Nothing else in your config is touched either,
so your own settings, rules and comments stay as they are.

**Plugin advice.** After the config changes, `sync config` checks which of the team's
[recommended plugins](../guides/plugins.md) your config lists and tells you what is missing. It never
installs or edits plugins, and the advice has no effect on the exit code.

```text
Plugins (idea-oc does not install or change these):
  missing (REQUIRED)  inject-env.js  keeps OpenCode's shell commands on the bedrockonly AWS profile
  missing             cc-safety-net  blocks destructive commands (it also blocks force-push)
  How to add the required plugin: https://co-cddo.github.io/gds-idea-pkg-oc/guides/plugins/#the-required-plugin
```

A plugin counts as listed whatever version you pin, and a plugin that is a file counts by its file
name. If `opencode-snip` is listed but the `snip` program it needs is not installed, you get a
warning, because without it the plugin does nothing and gives no error. When everything is listed
you see one line: `Plugins: all the recommended plugins are listed.`

**Three kinds of change**

| Change | Meaning |
|---|---|
| `add` | The setting or rule is missing |
| `change` | The setting is there with a different value. Both values are shown. |
| `append` | Items are missing from a list. Items you already have are kept: lists are only added to. |

**Your answer**

- **Yes** applies the changes and saves your original next to it as `opencode.jsonc.idea-oc.bak`.
  Comments and formatting are kept.
- **No**, which is the default, leaves your config exactly as it was and saves what it would have
  looked like as `opencode.jsonc.new`. Compare the two and copy across what you want:

  ```bash
  diff ~/.config/opencode/opencode.jsonc ~/.config/opencode/opencode.jsonc.new
  ```

  Running `sync config` again asks again. The `.new` file is replaced each time, and removed once
  your config matches or you accept the changes.
- With `--yes` it applies without asking. With no terminal to ask on, it counts as no. With
  `--dry-run` it shows the changes and writes nothing, not even a `.new` file.

**Where new permission rules go.** Rules are read top to bottom and the last matching rule wins, so
position matters. A missing rule goes after the team rules that should come before it and before the
specific rules it refines. Your own rules stay where they are, so a more specific rule of yours below
the team's still wins. If a rule in your config would stop a team rule from working, `sync config`
says so:

```text
Heads up: permission.bash["rm -rf*"] (deny) is overridden by '*' (allow) and will have no effect.
```

If the config cannot be edited safely, for example because it is not valid, `idea-oc` leaves it alone
and prints what you need to add yourself.

## Why sync skills does not edit your config

OpenCode only loads skills from folders it has been told about. `idea-oc` installs team skills into
its own folder, separate from your personal skills, and OpenCode finds that folder through the
`skills.paths` entry in your `opencode.jsonc` or `opencode.json`.

That entry is a change to a file you own, so it belongs to the config stage: `idea-oc sync config`
shows exactly what it will change, asks you yes or no, and saves a backup first.
`idea-oc sync skills` never writes to your config, so it is safe to run from hooks and CI.

If you only run `sync skills`, the skills are installed but OpenCode will not see them until you
run `idea-oc sync config` once. Plain `idea-oc sync` runs both stages for you.
