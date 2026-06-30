---
name: improve
description: Continuous improvement agent. Post-completion code sweep + daily brainstorm digest. Surfaces queued improvements at session start; generates daily ideas digest via launchd cron.
tags: [intent:improve, intent:quality, intent:digest, type:system]
---

# Improve Skill

Two capabilities:

1. **Post-completion sweep** (automatic) — fires on every handoff write. Scans the session's project through `qa_scan`, picks the top 5 issues by priority (logic > naming > verbosity > style > complexity > comment), and appends them to `~/.claude/improvement-queue.md`.

2. **Daily digest** (cron) — runs at 08:30 daily via launchd. Assembles context from the roadmap, recent handoffs, QA KB, and bench results, then calls `claude` to brainstorm: feature combinations, trim candidates, a wild idea, and a quick win. Writes to `~/.claude/daily-digest/YYYY-MM-DD.md`.

---

## Manual invocation

```bash
# Run today's digest immediately (skips if already exists)
~/.agents/venv/bin/python ~/.agents/skills/improve/scripts/daily_digest.py

# Force regenerate today's digest
rm ~/.claude/daily-digest/$(date +%Y-%m-%d).md
~/.agents/venv/bin/python ~/.agents/skills/improve/scripts/daily_digest.py

# Show improvement queue
cat ~/.claude/improvement-queue.md

# Run sweep manually against a project
~/.agents/venv/bin/python ~/.agents/skills/improve/scripts/improvement_sweep.py
```

## Install cron

```bash
bash ~/.agents/skills/improve/install.sh
```

---

## Session start integration

At session start, MARVIN checks:
- `~/.claude/improvement-queue.md` — mentions count if new items
- `~/.claude/daily-digest/` — mentions if today's digest exists

## Triggers (manual invocation)
- "show improvement queue", "what should I fix", "show digest", "/improve"
- "run daily digest", "brainstorm improvements"
