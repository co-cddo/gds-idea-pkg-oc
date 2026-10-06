# list

Show what is installed and where it came from.

```bash
idea-oc list
```

```text
Installed in ~/.local/share/idea-oc/skills:
  cdk-review          co-cddo/gds-idea-ai-reviewer  v0.1.22  (62456fe)
  readme-review       co-cddo/gds-idea-ai-reviewer  v0.1.22  (62456fe)

Approved sources:
  co-cddo/gds-idea-ai-reviewer  latest  (discover src/ai_reviewer/skills)
```

Each installed skill shows its source repository, the release it came from and the commit.
**Approved sources** are the sources in the registry built into your version of `idea-oc`.

`list` works offline and makes no network requests.
