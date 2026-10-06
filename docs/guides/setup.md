# Set up OpenCode

This guide takes you from nothing to OpenCode running against AWS Bedrock with the team's
safety settings. If OpenCode is already working for you, skip to [Check your setup](#check-your-setup).

## 1. Install OpenCode

```bash
brew install anomalyco/tap/opencode
```

Use the fully qualified tap name, `anomalyco/tap/opencode`, not just `opencode`. The `opencode`
formula in Homebrew's own repository is maintained by the Homebrew team and updates less often.

Check it worked:

```bash
opencode --version
which opencode
```

## 2. Set up AWS access

You connect to Bedrock through the `bedrockonly` AWS profile, which `awsprofile` creates as a
temporary, MFA-protected session. All Associate Data Scientists have a role in the dev account that
is scoped to Bedrock only.

Install `awsprofile` from the internal index (see [Install](../index.md#install) for the one-time
`idea-tools` setup):

```bash
idea-tools install gds-idea-pkg-awsprofile
```

Then start a session:

```bash
awsprofile bedrock
```

Run OpenCode from the same terminal afterwards, so it picks up the session.

## 3. Create your OpenCode config

By default OpenCode starts with a built-in model. The team's
[preferred config](../reference/preferred-config.md) connects it to Bedrock instead:

- the `eu-west-2` region and the `bedrockonly` profile,
- the Sonnet 5.5 model through the EU inference profile, so inference stays in EU regions,
- the direct Anthropic API disabled, so Bedrock is the only route to Claude,
- the permission rules described in the next step.

The easiest way to get it is to let `idea-oc` do it. Install it (see [Install](../index.md#install)),
then run:

```bash
idea-oc sync config
```

It shows what it would add to your config, or create if you have none, and asks before writing.
It does not add plugins: step 5 covers the one you need.

If you would rather do it by hand, download the
[preferred config](https://github.com/co-cddo/gds-idea-pkg-oc/blob/main/src/idea_oc/opencode.jsonc)
instead, which includes the plugin entries:

```bash
mkdir -p ~/.config/opencode
curl -fsSL https://raw.githubusercontent.com/co-cddo/gds-idea-pkg-oc/main/src/idea_oc/opencode.jsonc \
  -o ~/.config/opencode/opencode.jsonc
```

!!! warning
    This replaces `~/.config/opencode/opencode.jsonc` if it exists. If you already have a config,
    use `idea-oc sync config` instead, or open the preferred config alongside yours and bring across
    what you need.

## 4. Permissions

The config includes a `permission` block that protects against destructive commands and unwanted
file access. In short:

| Action | Rules |
|---|---|
| Blocked | `cdk destroy`, `git reset --hard`, `rm -rf`, `gh pr merge`, `gh pr ready`, and creating a non-draft PR |
| Asks first | `cdk deploy`, any `git push` (including a force-push after a rebase), `sudo`, other `gh pr` commands, reading or writing outside the project, and every file edit |
| Allowed | Everything else |

`edit` is set to ask, so every file write is shown to you before it happens. You may want to loosen
that later, for example to allow `**/*.md` or `**/tests/**`, once you know which file types you are
comfortable approving automatically.

Rules are read from top to bottom and the **last matching rule wins**, so the order matters. See
[Preferred config](../reference/preferred-config.md#how-rule-order-works) before you add your own.

## 5. Add the required plugin

OpenCode can sometimes run scripts that read, and potentially write, other AWS resources such as S3
buckets, even with the permissions above. The required plugin makes OpenCode's shell commands keep
to the `bedrockonly` profile instead of reaching for another profile in your AWS config.

Follow [The required plugin](plugins.md#the-required-plugin). `idea-oc sync config` does not add it
for you.

## Check your setup

From the terminal where you ran `awsprofile bedrock`:

```bash
opencode
```

Check the model shown in the status bar, and type "Hello". If everything is set up you will get a
reply from Sonnet 5.5.

Then install the team's skills:

```bash
idea-oc sync
```

## Optional plugins

A few more plugins reduce cost and stop sensitive files being read. They are recommended, not
required. See [Plugins](plugins.md#recommended-plugins).
