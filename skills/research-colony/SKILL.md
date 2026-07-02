---
name: research-colony
description: Autonomous research agent that monitors arXiv, GitHub, and HN daily, cross-references findings against MARVIN's knowledge base, and synthesises a digest. Use when the user wants today's research digest, what's new in AI/research, or wants the colony run/fetched manually.
tags: [intent:research, intent:monitor, intent:digest, type:agent]
---

# Research Colony Skill

Autonomous research agent that monitors arXiv, GitHub, and HN daily, cross-references findings against MARVIN's knowledge base, and synthesises a digest.

## Triggers

- "show research digest", "what's new in research", "any new papers"
- "run research colony", "fetch research", `/research-colony`
- Session-start: if `~/.claude/research-digest/YYYY-MM-DD.md` exists, mention it

## Scripts

| Script | Purpose |
|--------|---------|
| `source_monitor.py` | Fetch arXiv/GitHub/HN → ChromaDB `research-feed` + raw cache |
| `correlate.py` | Cross-reference `research-feed` against `qa-knowledge` + roadmap keywords |
| `research_digest.py` | Call claude to synthesise correlated items → `~/.claude/research-digest/` |
| `run_colony.py` | Orchestrate all three in sequence |

## Output files

- `~/.claude/research-feed/YYYY-MM-DD.json` — raw per-source fetch cache
- `~/.claude/research-digest/YYYY-MM-DD.md` — final synthesised digest

## ChromaDB collections

- `research-feed` — all fetched items; metadata includes `correlated: true/false`, `matched_topics`
- `qa-knowledge` — existing MARVIN knowledge base (read-only here)

## Correlation signals

1. **Keyword match** — title/summary contains roadmap keywords → tagged with roadmap section (e.g. `A.rag`, `C.vector-db`)
2. **Semantic similarity** — ChromaDB cosine distance < 1.1 against `qa-knowledge`

## Running manually

```bash
# Full colony run
~/.agents/venv/bin/python ~/.agents/skills/research-colony/scripts/run_colony.py

# Individual steps
~/.agents/venv/bin/python ~/.agents/skills/research-colony/scripts/source_monitor.py
~/.agents/venv/bin/python ~/.agents/skills/research-colony/scripts/correlate.py
~/.agents/venv/bin/python ~/.agents/skills/research-colony/scripts/research_digest.py
```
