# list

Show what is installed and where it came from.

```bash
idea-oc list
```

```text
Installed in ~/.local/share/idea-oc/skills:
  cdk-review          co-cddo/gds-idea-ai-reviewer  v0.1.22  (62456fe)
  idea-app-usage      co-cddo/gds-idea-app-kit      v0.7.2  (a1b2c3d)
  readme-review       co-cddo/gds-idea-ai-reviewer  v0.1.22  (62456fe)

Approved sources:
  co-cddo/gds-idea-ai-reviewer  latest  (discover src/ai_reviewer/skills)
  co-cddo/gds-idea-app-kit  latest  (1 named skill(s))
  co-cddo/gds-idea-gh-kit  latest  (1 named skill(s))
```

Each installed skill shows its source repository, the release it came from and the commit.
**Approved sources** are the sources in the registry built into your version of `idea-oc`.

`list` works offline and makes no network requests.
