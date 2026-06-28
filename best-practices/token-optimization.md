---
name: token-optimization-best-practices
description: Techniques for reducing token spend without degrading capability. Covers model routing, caching, prompt design, and output discipline.
tags: [domain:tokens, domain:cost, intent:optimize, type:best-practices]
---

# Token Optimization Best Practices

## Model Routing (highest leverage)

Route tasks to the cheapest model that can do the job reliably.

| Task type | Target model | Signal |
|-----------|-------------|--------|
| Simple retrieval, formatting, classification | Haiku 4.5 | Single-step, no reasoning chain |
| Code generation, analysis, multi-step logic | Sonnet 4.6 | Moderate complexity |
| Architecture, novel reasoning, hard reverse engineering | Opus 4.8 | Requires deep inference |

Never default to Opus for everything. Most tasks don't need it.

## Caching

- Identical or near-identical prompts → semantic cache hits via FastMCP (once integrated).
- Static context (skill files, best-practices docs) changes rarely — cache aggressively.
- Dynamic context (user input, live code) — never cache.
- Cache warm window = 5 minutes in Anthropic's prompt cache. Structure work to stay inside it.

## Prompt Design

- State the constraint first: "In one sentence…", "List only the file paths…"
- Don't narrate intent before tool calls — output text is tokens the model must generate and the user must read.
- Fragments over sentences where meaning is preserved (caveman mode always active).
- No trailing summaries — the diff is visible; restating it burns tokens and adds no value.

## Output Discipline

- Return only what was asked. Struct when bool sufficient = wasteful.
- Skill files: omit examples unless concept non-obvious without one.
- Handoff summaries: compress to decisions + blockers. Discard process.

> For human-facing response compression, see `~/.agents/skills/caveman/SKILL.md`. Separate concern — does not affect system-level token spend.

## Context Reuse

- Structure prompts so the static prefix is longest — Anthropic caches the prefix.
- Skill files loaded multiple times in a session = prefix cache hits. Keep them stable.
- Avoid appending to a growing prompt mid-session — start fresh with a focused context instead.

## Chunking for Large Inputs

- Process large corpora in chunks, not as a single monolithic input.
- Chunk size target: 2,000–4,000 tokens per chunk (leaves room for reasoning + output).
- Overlap chunks by ~10% to avoid boundary misses on semantic content.
- Use a map-reduce pattern: chunk → process → aggregate results, not chunk → accumulate → process.

## Anti-Patterns

| Anti-pattern | Token cost | Fix |
|---|---|---|
| Loading full file when only a function is needed | 2–10x | Read with offset+limit or grep first |
| Re-reading files after editing | Wasted read | Trust the edit tool's confirmation |
| Defaulting to Opus for all tasks | 5–15x vs Haiku | Use routing rules above |
| Prose explanations before every tool call | +50–200 tokens/call | One sentence max, or none |
| Asking "does this look right?" after every step | Extra round trip | Batch confirmation to end of logical unit |
