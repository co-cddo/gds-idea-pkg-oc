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
  written out, because OpenCode works out what a model can do from its id, and an ARN does not say
  which model is behind it. Without them OpenCode would think the model has no context window and no
  reasoning, and would use the wrong thinking settings. The restated settings make the profile behave
  exactly like the model it routes to.
- **`model`** points at it.

`small_model` is deliberately left alone. OpenCode uses a small, cheap model for background jobs such
as naming a session, and those calls are not worth tracking, so they keep going to whatever OpenCode
chooses (usually a Haiku). Nothing in `idea-oc` reads or changes that setting.

The entry's key must contain `claude` and `anthropic`: OpenCode decides whether to cache prompts from
the key, and without caching your usage and cost go up.

Your own entries under `provider.amazon-bedrock.models` are never touched, and nor are other teams'.

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

- **A different system prompt.** OpenCode chooses its built-in instructions for the model from the
  model's id, looking for `claude`. A profile's ARN has no model name in it, so OpenCode falls back to
  its general instructions instead of the Claude-specific ones. They are not the same: the Claude set
  tells the model to plan with its todo tool and to use sub-agents, while the general set does not, and
  the general set tells it never to add code comments unless asked and to run lint and type checks
  when it finishes. OpenCode also tells the model it is "powered by" the ARN rather than by
  Sonnet 5.5. We have not measured whether this changes results in practice, so say if the agent
  behaves differently from before. It is a limit of how OpenCode picks its instructions, and cannot be
  fixed in the config.
- **Tracking is not enforcement.** `idea-oc` points your config at your team's profile. It cannot stop
  someone calling a model directly, which only the AWS role's permissions can do.
- **Cost reports.** Each profile carries a `Team` tag. For it to appear as a column in Cost Explorer
  the tag must be activated as a cost allocation tag in the Billing console. That is set up in AWS,
  not by `idea-oc`.
- **Changing team later** adds the new team's entry and changes `model`. The old team's entry stays in
  your config until you delete it.
