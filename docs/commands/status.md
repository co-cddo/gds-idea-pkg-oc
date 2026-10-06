# status

Check your setup against what the team expects, without changing anything.

```bash
idea-oc status            # both stages
idea-oc status skills
idea-oc status config
idea-oc status --quiet    # print only problems
```

`status` exits with **1** if a sync is needed and **0** if everything is in order, so it can run from
a hook or CI.

## What it reports

**Skills** (needs the network, but downloads no files)

- Each approved skill that is not installed, or whose files differ from the source: changed,
  missing or extra files.
- Skills in the skill folder that are no longer approved.
- **Shadowing**: personal skills, found in `~/.config/opencode/skills`, `~/.claude/skills` and
  `~/.agents/skills`, that have the same name as a team skill. The team skill overrides yours.
  This is shown for information and does not make `status` fail.
- Sources that could not be reached are reported and skipped, not counted as drift.

**Config** (works offline)

- The differences between your OpenCode config and the team's
  [preferred config](../reference/preferred-config.md), listed as `sync config` would show them. Run
  `idea-oc sync config` to review and apply them.
- Whether the config can be read.
- **Heads up** lines for team permission rules that a rule in your own config stops from working.
  These are shown for information and do not make `status` fail.
- **Plugin advice**: which of the [recommended plugins](../guides/plugins.md) your config does not
  list, and a warning if `opencode-snip` is listed without the `snip` program. This is advice only.
  It never makes `status` fail, and `--quiet` leaves it out.

## Options

| Option | Effect |
|---|---|
| `-q`, `--quiet` | Print only problems, so a healthy machine prints nothing. The exit code still reports them. |

Like `sync`, `status` first checks the package index for a newer `idea-oc` and prints one line to
say how to upgrade. With `--quiet` that notice is a single line.
