# Teams and usage tracking

OpenCode reaches Claude through Amazon Bedrock. So that each team's usage can be told apart, OpenCode
is pointed at your team's **Bedrock inference profile** instead of at the model directly. A profile
sends your requests to exactly the same model (Sonnet 5.5, in the EU regions), but Bedrock records the
usage against the profile.

There is one profile for each team:

| Team | Profile |
|---|---|
| `ds` (the default) | `ds` |
| `sds` | `sds` |
| `econ` | `econ` |

## Choosing your team

`idea-oc sync config` decides which team to use in this order:

1. **`--team <name>`**, if you give it.
2. **The team your config already uses.** If your `model` already points at a team's profile, you stay
   on that team. You only choose once.
3. **`ds`**, the default.

```bash
idea-oc sync config --team sds
```

Every `sync config` and `status config` tells you which team it used and why:

```text
Team: ds (the default). Usage is tracked per team. If you are in econ or sds, run again with --team <name>.
Team: sds (kept from your current model).
Team: econ (chosen with --team).
```

!!! warning "If you are in sds or econ, say so the first time"
    Everyone starts on a plain model, so the first sync has nothing to keep and falls back to `ds`.
    If you are not in `ds`, run `idea-oc sync config --team sds` (or `econ`) the first time. After
    that a plain `idea-oc sync` keeps your team. If you applied the default by mistake, run it again
    with the right `--team`: the model changes, and the unused profile entry is left in place for you
    to delete.

An unknown team is an error that lists the valid ones.

## What goes in your config

For your team, `sync config` adds two things, and shows them in its change list before it asks:

```text
add     provider.amazon-bedrock.models.anthropic-claude-sonnet-5-5-ds  inference profile 4niqtfvd2b0y
change  model                                                          amazon-bedrock/eu.anthropic.claude-sonnet-5-5 -> amazon-bedrock/anthropic-claude-sonnet-5-5-ds
```

- **The profile entry** holds the profile's ARN and the model's settings. The settings have to be
  written out, because OpenCode and the AI SDK work out what a model is from its id, and an ARN does
  not say which model is behind it. Without them OpenCode would think the model has no context window,
  no image input and zero cost. They are copied from the model the profile routes to (Sonnet 5.5).
- **`model`** points at it.

`small_model` is deliberately left alone. OpenCode uses a small, cheap model for background jobs such
as naming a session, and those calls are not worth tracking, so they keep going to whatever OpenCode
chooses (usually a Haiku). Nothing in `idea-oc` reads or changes that setting.

The entry's key must contain `claude` and `anthropic`: OpenCode decides whether to cache prompts from
the key, and without caching your usage and cost go up.

Your own entries under `provider.amazon-bedrock.models` are never touched, and nor are other teams'.

## Reasoning levels

Reasoning is the one place where a profile needs special handling, and getting it wrong breaks the model
rather than just degrading it.

The AI SDK decides how to ask a Bedrock model to think from its id. For a Claude model it sends the
Claude fields (`thinking` and `output_config`). For an ARN it cannot tell, assumes an Amazon Nova model
and sends `reasoningConfig`, which Bedrock rejects for Claude with `reasoningConfig: Extra inputs are
not permitted`. **Every reasoning level then fails**, though plain use without one still works. This
was found by trying it, and `modelFamily` and similar settings did not help in OpenCode 1.18.1 or
1.18.35.

So the entry sets `reasoning: false`, which stops OpenCode generating its own levels, and offers the
levels itself as raw request fields in the format Claude expects. They appear in OpenCode's variant
picker as usual (`low`, `medium`, `high`, `xhigh`, `max`) and what is sent matches what OpenCode sends
for the model directly. A side effect is that the desktop app's model tooltip says the model has no
reasoning, which is not true.

`tests/test_opencode_wire.py` points the real OpenCode at a local server and compares the requests, so
if a future OpenCode or AI SDK changes this, the test says so and the workaround can be removed.

## The prompt file

`sync config` writes `prompts/idea-oc-anthropic.txt` in the same folder as your config, and your agents
refer to it as `{file:./prompts/idea-oc-anthropic.txt}`. It is a copy of OpenCode's own Claude
instructions (OpenCode is MIT-licensed; the notice ships with `idea-oc`).

!!! danger "OpenCode will not start without it"
    If a config refers to a prompt file that does not exist, OpenCode stops with `bad file reference`.
    So `idea-oc` is careful about it:

    - the file is written **before** the config that refers to it;
    - if you say no to the changes, the file the proposed `.new` config needs is still saved (and an
      existing file is never replaced), so merging the proposal cannot break OpenCode;
    - `idea-oc status` says **"OpenCode will not start"** if your config refers to the file and it has
      gone, even with `--quiet`, and `idea-oc sync config` puts it back.

- **Your own prompts are respected.** If you already set a `prompt` for `build`, `plan` or `general`,
  it is left alone and `sync config` says so. If you set all three, the file is not installed at all.
- **Other agents are unaffected.** `explore`, `compaction`, `title` and `summary` have instructions of
  their own and do not use it.
- **It can go out of date.** The copy is OpenCode's text as of the `idea-oc` release you have. If
  OpenCode changes its instructions, `sync config` shows `update  prompts/idea-oc-anthropic.txt` after
  you upgrade `idea-oc`. OpenCode last changed this text in October 2025.

## When a profile changes

A profile cannot be edited in place. Changing the model behind it replaces it, which gives it a **new
ID**. When that happens `idea-oc` shows the ID changing the next time you sync:

```text
change  provider.amazon-bedrock.models.anthropic-claude-sonnet-5-5-ds  inference profile 4niqtfvd2b0y -> inference profile abcd1234efgh
```

The IDs are bundled with `idea-oc`, so you pick up new ones by upgrading it
(`idea-tools upgrade gds-idea-pkg-oc`). Until you do, requests through a replaced profile fail.
`idea-oc` tells you when a newer version is available each time you run `sync` or `status`.

## Things to know

- **The Claude instructions are installed for you.** OpenCode chooses its built-in instructions for a
  model from the model's id, looking for `claude`. A profile's ARN has no model name in it, so without
  help OpenCode would use its general instructions. They differ in behaviour, not just wording: the
  Claude set tells the model to plan with its todo tool and use sub-agents, while the general set tells
  it never to add code comments unless asked. So `sync config` also installs a copy of OpenCode's Claude
  instructions as `prompts/idea-oc-anthropic.txt` beside your config and points the `build`, `plan` and
  `general` agents at it. See [The prompt file](#the-prompt-file).
- **One thing is still the ARN.** OpenCode tells the model it is "powered by" the profile's ARN rather
  than by Sonnet 5.5. That cannot be changed from the config.
- **Tracking is not enforcement.** `idea-oc` points your config at your team's profile. It cannot stop
  someone calling a model directly, which only the AWS role's permissions can do.
- **Cost reports.** Each profile carries a `Team` tag. For it to appear as a column in Cost Explorer
  the tag must be activated as a cost allocation tag in the Billing console. That is set up in AWS,
  not by `idea-oc`.
- **Changing team later** adds the new team's entry and changes `model`. The old team's entry stays in
  your config until you delete it.
