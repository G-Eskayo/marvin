---
name: architecture-review
description: Autonomously reviews the agent system architecture (skills, CLAUDE.md, lexicon, handoffs, scripts) and generates actionable optimization suggestions queued for user authorization. Run regularly — after every 3–5 sessions, when CLAUDE.md grows significantly, when a skill feels slow or redundant, or when routing table gets noisy. Never implements without approval. Focuses on: token reduction, retrieval speed, file organization, pipeline logic, reliability, robustness.
tags: [intent:optimize, intent:review, intent:meta, type:skill]
---

# Architecture Review

Architectural review of the agent system itself. Generate suggestions → queue → wait for authorization → implement.

**Never implement without explicit approval.**

## Scope

Review these systems:
- `~/.claude/CLAUDE.md` — routing table, instructions, verbosity
- `~/.claude/lexicon.md` — term drift, redundancy, coverage
- `~/.agents/skills/*/SKILL.md` — size, clarity, overlap between skills
- `~/.claude/commands/` — broken symlinks, stale entries
- `~/.agents/skills/self-improve/scripts/wire-skill.sh` — reliability, edge cases
- `~/.claude/handoffs/` — old handoffs to archive or prune
- `~/.claude/suggestions.md` — stale pending items to flag

## Review Process

### 1. Audit the system

Read each component. For each, ask:
- **Tokens**: is this longer than it needs to be? Redundant with another file?
- **Speed**: would reorganizing make retrieval/matching faster?
- **Reliability**: any single points of failure? Scripts that could break silently?
- **Organization**: does the file structure reflect how things are actually used?
- **Robustness**: what happens when something is missing or malformed?

### 2. Generate suggestions

For each finding that passes the bar (see below), write a suggestion entry.

Append to `~/.claude/suggestions.md`:

```
## [YYYY-MM-DD] [Title]
**Status**: pending
**Impact**: [token-reduction | speed | reliability | organization | robustness]
**Effort**: [low | medium | high]
**Why**: [one line — the problem]
**What**: [exact change]
**How**:
- step 1
- step 2
```

### 3. Present to user

After writing to the queue, surface new suggestions:

> **[N] new optimization suggestion(s) queued.**
> Run `/architecture-review review` to see them, or I'll show them now.

Don't dump the full list unprompted — respect caveman mode.

### 4. On approval

When user approves a suggestion (by name or number):
1. Read the suggestion's **How** steps
2. Implement exactly as specified
3. Update status to `done` in `~/.claude/suggestions.md`
4. Confirm what changed

On rejection: update status to `rejected`. Don't re-raise.

## Suggestion Bar

Only queue suggestions that pass all three:
- **Concrete**: exact file + change specified, not vague ("improve clarity")
- **Measurable**: tokens saved, files reduced, steps eliminated — quantify if possible
- **Net positive**: improvement outweighs risk of breaking something

Do not queue:
- Stylistic preferences with no functional impact
- Changes that increase complexity for marginal gain
- Anything that would alter behavior in non-obvious ways without flagging it clearly

## Review Subcommand

When invoked as `/architecture-review review`:
- Read `~/.claude/suggestions.md`
- Show all `pending` items in compact form
- Ask: "Approve any? (by title or 'all')"

## Optimization Priorities

Ranked by value:

1. **Token reduction** — shorter SKILL.md files, compressed routing descriptions, deduplicated instructions
2. **Retrieval speed** — routing table accuracy (fewer false positives), skill descriptions that match faster
3. **Organization** — related skills grouped, dead files removed, naming consistent
4. **Pipeline logic** — wire-skill.sh robustness, handoff flow, session-start checks
5. **Reliability** — broken symlinks, missing dirs, scripts that fail silently
6. **Robustness** — graceful degradation when files missing, fallback behavior documented
