# Plugins

OpenCode plugins are listed in the `plugin` array of your config. `idea-oc` does not install or
change plugins: it only checks which of the plugins below are listed and tells you what is missing.

Add plugins to your config file directly. OpenCode installs them the next time it starts.

`idea-oc sync config` and `idea-oc status config` print what is missing, with a link to the right
section below. The advice never changes the exit code, so it will not fail a hook or a CI check.

## The required plugin

OpenCode can sometimes run scripts that read, and potentially write, to resources such as S3
buckets, even with the [permission rules](../reference/preferred-config.md) in place. This plugin
makes OpenCode's shell commands use the `bedrockonly` profile, rather than reaching for another
profile in your AWS config or credentials as a workaround.

**1. Add the plugin file.** Put it in a folder called `plugin-scripts`:

```bash
mkdir -p ~/.config/opencode/plugin-scripts

cat > ~/.config/opencode/plugin-scripts/inject-env.js << 'EOF'
export const InjectEnvPlugin = async (ctx, options = {}) => {
  return {
    "shell.env": async (input, output) => {
      for (const [key, value] of Object.entries(options)) {
        output.env[key] = value
      }
    },
  }
}
EOF
```

!!! warning
    Do not call the folder `plugins`. OpenCode loads that folder itself during startup, which
    makes it ignore the AWS profile you give it in the config file.

**2. List it in your config.** It is the first entry of the `plugin` array:

```jsonc
"plugin": [
  ["./plugin-scripts/inject-env.js", { "AWS_PROFILE": "bedrockonly" }]
]
```

The [preferred config](../reference/preferred-config.md) file already has this entry. If you used
`idea-oc sync config` to create your config instead, add it yourself: that command never changes
plugins.

## Recommended plugins

These save cost and stop sensitive information being stored by accident. Add them to the same
`plugin` array, one at a time, restarting OpenCode between each. That makes it much easier to see
which one caused a problem if something breaks.

| Plugin | What it does |
|---|---|
| `@tarquinen/opencode-dcp` | Prunes the conversation context to reduce token use. Works silently. |
| `envsitter-guard` | Blocks raw reads of `.env`-style files and offers safe alternatives (listing keys, not values), so secrets are not stored in an `AGENTS.md` or other output. |
| `opencode-snip` | Filters noisy command output (npm installs, git logs, test runs) before it reaches the model, which cuts token use a lot on verbose commands. You can still ask for the output verbatim when you need to debug. |
| `cc-safety-net` | Blocks destructive commands (`git reset --hard`, `rm -rf`, force-push) before they run, and cites the rule that fired. |

Some of what `cc-safety-net` blocks overlaps with the permission rules. That is intentional: two
independent layers.

!!! note "cc-safety-net and force-push"
    `cc-safety-net` blocks force-pushes outright. The preferred permission rules only ask before a
    force-push, so you can push after a rebase once you have confirmed. With `cc-safety-net`
    installed you will not be able to.

### opencode-snip needs a separate program

`opencode-snip` calls a program called `snip`. Without it the plugin loads without any error and
does nothing, so you get none of the saving. Install it separately:

```bash
brew install edouard-claude/tap/snip
which snip
```

`idea-oc` warns you when `opencode-snip` is listed but `snip` is not installed.

## Known issues

- Do not install plugins with `opencode plugin <name> --global`. That command currently fails with
  a dependency error (`@opencode-ai/plugin@local`). Add the plugin to the config file instead.
- To check a plugin really installed, look for a folder per plugin here once OpenCode has started:

  ```bash
  ls -la ~/.cache/opencode/packages/
  ```
