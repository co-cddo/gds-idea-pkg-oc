# idea-oc

`idea-oc` installs the GDS IDEA team's approved [OpenCode](https://opencode.ai) agent skills on your
machine, and checks your OpenCode config against the team's preferred setup, so everyone works from
the same set.

It keeps your own setup out of the way:

- Team skills go in their own folder, separate from your personal skills.
- Your personal skills are never touched. If you have one with the same name as a team skill, the
  team skill wins, and `idea-oc status` tells you.
- Nothing is written to your OpenCode config without showing you the change first and asking. If
  you say no, it saves what it would have changed as a `.new` file for you to merge yourself.

## Install

You need `uv` and the `idea-tools` shell function. Both are set up once, following the
[index instructions](https://co-cddo.github.io/gds-idea-pypi/).

```bash
idea-tools install gds-idea-pkg-oc
idea-oc --version
```

## First run

```bash
idea-oc sync
```

This installs the approved skills, then shows how your OpenCode config differs from the team's
preferred config and asks before changing anything. Restart OpenCode afterwards to pick the skills up.

See [`sync`](commands/sync.md) for the two stages it runs and how to run either on its own.

## Staying up to date

Every time you run `sync` or `status`, `idea-oc` checks the index for a newer version and tells you
how to upgrade:

```bash
idea-tools upgrade gds-idea-pkg-oc
```

The approved skill sources are built into each version, so upgrading is how you receive changes to
the list.

## New to OpenCode?

Start with [Set up OpenCode](guides/setup.md).
