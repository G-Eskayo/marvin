# Security Policy

## What must never be committed

| File / pattern | Why |
|---|---|
| `.credentials.json` | Claude Code OAuth tokens |
| `.claude.json` | Account identity, onboarding state |
| `settings.local.json` | May contain personal file paths in hooks |
| `projects/` | Session memory — contains personal conversation context |
| `history.jsonl` | Full conversation history |
| `chroma/` | Embedded vectors built from personal sessions |
| `handoffs/` | Session handoff docs with personal context |
| `.env` / `*.env` | Environment variables, API keys |
| Any file matching `*_token*`, `*_secret*`, `*_key*` | Credentials |

The `.gitignore` blocks all of the above. Before opening a PR, run:

```bash
git diff --cached --name-only | xargs -I{} grep -l "sk-ant\|Bearer\|password\|secret\|token" {} 2>/dev/null
```

If that prints anything, **do not push**.

## Pre-push checklist

- [ ] No hardcoded usernames, email addresses, or personal file paths
- [ ] No API keys or tokens in any file
- [ ] `git status` shows no untracked `.credentials.json` or `.claude.json`
- [ ] Skills reference `Path.home()` for home-relative paths, not `/Users/<you>/`

## Reporting a vulnerability

Open a GitHub issue with the title prefix `[SECURITY]`. Do not include the
sensitive content itself — describe the exposure type and we will follow up
privately.
