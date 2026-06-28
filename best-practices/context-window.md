---
name: context-window-best-practices
description: Rules for maximising what can be accessed in a context window while minimising token spend. Reference whenever designing skills, memory files, or knowledge architecture.
tags: [domain:context, domain:tokens, intent:optimize, type:best-practices]
---

# Context Window Best Practices

## The Five-Level Loading Hierarchy

Load only what the current task needs. Nothing else.

| Level | What | When loaded | Target size |
|-------|------|-------------|-------------|
| 0 | CLAUDE.md + MEMORY.md | Always | < 150 lines each |
| 1 | lexicon.md + active handoff | Session start | < 100 lines |
| 2 | Matched skill SKILL.md | On task match | < 100 lines |
| 3 | Skill support files, best-practices.md | On demand within skill | < 80 lines each |
| 4 | retrospective.md, full ADRs, large docs | By explicit reference only | Unbounded |

**Never preload Level 3+ speculatively.** The cost of one unnecessary load is paid on every task that doesn't need it.

## Indexing Over Inlining

- Store content at its canonical path; store a pointer everywhere else.
- MEMORY.md is an index — one line per memory, never content.
- manifest.json is the unified tag index — match keywords, pull paths, read only what matched.
- A file that says "see X for details" is correct. A file that copies X inline is a context leak.

## Skill File Discipline

- SKILL.md hard limit: 100 lines.
- Supporting content (examples, edge cases, format specs) → separate files referenced by name.
- If trimming to 100 lines means losing nuance, the nuance belongs in a `best-practices.md` or `examples.md`, not inline.
- Description field must be specific enough to match relevant tasks and reject irrelevant ones. Vague descriptions cause over-loading.

## Handoff Before Context Switch

Run the `handoff` skill before switching topics or projects. A handoff doc + resume prompt costs ~200 tokens to write and saves a full cold-start reconstruction next session.

## Compression Signals

When any of these are true, compress before continuing:
- CLAUDE.md exceeds 80 lines
- Routing table has 20+ entries  
- A skill file exceeds 100 lines
- The same concept appears in 3+ places verbatim

Compression rule: **pointer beats copy**. Replace inline content with a path reference.

## Anti-Patterns

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| Loading all skills at session start | Wastes tokens on every task that uses only 1-2 skills | Use `index` to match and load selectively |
| Copying best practices into CLAUDE.md | CLAUDE.md bloats; same content duplicated | Keep in domain file, add manifest entry |
| Writing retrospective inline in SKILL.md | Grows unbounded, gets loaded on every skill use | Write to `retrospective.md` at Level 4 |
| Preloading docs "just in case" | Consumes context before the task starts | Load on first reference |
| Long commit-style comments in skill files | Context noise, rots fast | No "added for X" comments in skills |
