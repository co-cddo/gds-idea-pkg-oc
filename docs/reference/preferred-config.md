# Preferred config

The team's preferred OpenCode configuration is kept in the repository as
[`opencode.jsonc`](https://github.com/co-cddo/gds-idea-pkg-oc/blob/main/src/idea_oc/opencode.jsonc).
It is the single source for these values, so this page explains them instead of repeating them.

To set it up from scratch, follow [Set up OpenCode](../guides/setup.md).

## What it sets

| Section | Purpose |
|---|---|
| `provider.amazon-bedrock.options` | The `eu-west-2` region and the `bedrockonly` AWS profile that `awsprofile bedrock` creates. |
| `model` | Sonnet 5.5 through the **EU** inference profile (`eu.anthropic.claude-sonnet-5-5`), so inference stays in EU regions. The `global.` profile may route requests to other regions. |
| `disabled_providers` | Turns off the direct Anthropic API, so Bedrock is the only route to Claude. |
| `plugin` | The [required plugin](../guides/plugins.md#the-required-plugin) and the [recommended ones](../guides/plugins.md#recommended-plugins). |
| `permission` | What OpenCode may do without asking: see below. |

## Permissions

The `permission` block has three parts:

- `bash` decides what happens for each shell command: `allow`, `ask` or `deny`.
- `external_directory` asks before OpenCode reads or writes anything outside the project.
- `edit` asks before every file write, so nothing lands without you seeing it.

Each `bash` rule has a comment in the file saying why it exists.

## How rule order works

OpenCode reads the rules in a section from top to bottom and uses the **last rule that matches** the
command. If no rule matches it asks. A rule's position therefore decides whether it works.

In patterns, `*` matches anything, and a trailing ` *` also matches the bare command, so
`git push *` matches both `git push` and `git push origin main`. A pattern must match the whole
command.

Two consequences:

1. **Keep the `"*"` catch-all first.** It matches every command, so anything above it is overridden.
2. **Put specific rules below the general ones they refine.** For example `gh pr *` asks for any pull
   request command, and `gh pr merge *` below it denies merging. If they were the other way round,
   `gh pr *` would match merges last and turn the deny into an ask.

!!! example "A rule that does nothing"
    ```jsonc
    "git push --force*": "deny",   // listed first...
    "git push *": "ask"            // ...but this matches the same command later, and wins
    ```
    `git push --force origin main` is asked, not denied, because the later rule wins. The deny rule
    can never take effect. Swapping the two lines would make it work. The team chose to *ask*
    before a force-push, so that pushing after a rebase is possible, and the preferred config has no
    separate force-push rule.

The repository's tests check every rule in the preferred config for this: each rule must be the one
that actually applies to the command it describes.

## Making your own changes

You are free to change your own config. Add your own rules **below** the team's rules in the same
section so they take effect, and keep the `"*"` catch-all first. A rule you add for a command that
a team rule already covers needs to come after it to override it.
