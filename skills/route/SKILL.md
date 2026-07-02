---
name: route
description: Classify a task and surface the optimal Claude profile + model routing decision
tags: [domain:meta, intent:routing, type:skill]
---

# Route Skill

Auto-routes tasks to the optimal profile + model combination based on bench-validated cost/capability data.

## Routing table (bench-validated)

| Intent | Profile | Model | Savings | When to use |
|--------|---------|-------|---------|-------------|
| recall | marvin | claude-haiku-4-5-20251001 | ~60% | Memory/session history retrieval |
| research | marvin | claude-haiku-4-5-20251001 | ~60% | arXiv, papers, synthesis, ChromaDB queries |
| coding | lean | default (Sonnet) | ~9% on simple tasks; unreliable on hard tasks (Run 15) | Self-contained coding tasks with no memory dependency |
| architecture | marvin | default (Sonnet) | baseline | Design decisions, planning, trade-off analysis |

## Triggers

Load this skill when the user asks:
- "which profile should I use for X"
- "should I use haiku for this"
- "route this task"
- "which model is best for"
- "how should I launch"

When triggered, run the classifier and print the routing recommendation:
```bash
~/.agents/venv/bin/python ~/.agents/skills/route/scripts/route.py "<task description>"
```

For **in-session auto-routing** (session start only): if the user's first message clearly signals a specific task type (≥2 keyword matches from the routing table), surface the routing suggestion briefly:
> "This looks like a **recall** task — `claude-recall` (marvin + haiku) handles it at ~60% of this session's cost."

Only say this once, at the top of the session. Don't repeat it mid-session.

## CLI usage

```bash
# After running install.sh:
route "what were the bench results?"      # classify + print
route "fix the bug" --launch              # classify + exec claude
route --recall --launch                   # explicit mode + launch
route --table                             # full routing table
route --aliases                           # print alias definitions

# Aliases (after install):
claude-recall       # marvin profile + Haiku
claude-research     # marvin profile + Haiku
claude-code         # lean profile + Sonnet
claude-arch         # marvin profile + Sonnet (default)
```

## Install

```bash
bash ~/.agents/skills/route/install.sh
source ~/.zshrc
```

## Evidence base

| Finding | Source |
|---------|--------|
| MARVIN wins recall (1.00 vs 0.00) at ~+600 token overhead | bench Run 7, task-002 + task-011 |
| MARVIN + Haiku wins recall identically, 60% cheaper | bench Run 8, Haiku cross-model |
| Lean saves 9–10% on SIMPLE coding tasks with zero quality gap | bench Runs 2–6, tasks 001/003/005/006 |
| On HARD coding tasks lean is NOT reliably cheaper than marvin — flips per task, high variance; clean is cheapest on both but lacks lean's TDD/grill quality benefit | bench Run 15 (N=3), tasks 012/013 |
| Haiku fails navigational recall without MARVIN | bench Run 8, task-007 |
| Haiku matches Sonnet on recall independently confirmed via a second method | bench Run 15, `select_model.py` sweep on task-002-recall |
