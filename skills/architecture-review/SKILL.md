---
name: architecture-review
description: Autonomously reviews the WHOLE agent system (not just meta-config — every skill, script, hook, and cron job under ~/.agents and ~/.claude) and generates actionable optimization suggestions queued for user authorization in priority order. Run regularly — after every 3–5 sessions, when CLAUDE.md grows significantly, when a skill feels slow or redundant, or when routing table gets noisy. Never implements without approval. Focuses on: token reduction, retrieval speed, file organization, pipeline logic, reliability, robustness.
tags: [intent:optimize, intent:review, intent:meta, type:skill]
---

# Architecture Review

Architectural review of the whole agent system. Generate suggestions → queue in priority order → wait for authorization → implement.

**Never implement without explicit approval.**

## Scope

**Whole system, expanded 2026-07-09** (was previously a named subset — CLAUDE.md, lexicon, skills, commands, one script — scope had drifted narrower than the skill's own stated purpose). Review everything under:
- `~/.agents/` — every skill's `SKILL.md` and its scripts, every `lib/` utility, every ADR/CONTEXT.md, `bench/`, `brain-map/` — not just a hand-picked subset
- `~/.claude/` — `CLAUDE.md`, `lexicon.md`, `commands/`, `handoffs/`, `suggestions.md` itself, launchd job configs, hook wiring in `settings.local.json`
- Cross-machine infra (`marvin-network.json`, `task_dispatch.py`, `cross_machine_merge.py`) where it affects reliability or organization, same as anything else

Still bounded by the review process below (token reduction, retrieval speed, organization, pipeline logic, reliability, robustness) — "whole system" means no arbitrary exclusion list, not "review everything exhaustively every single pass."

## Review Process

### 1. Audit the system

Read each component. For each, ask:
- **Tokens**: is this longer than it needs to be? Redundant with another file?
- **Speed**: would reorganizing make retrieval/matching faster?
- **Reliability**: any single points of failure? Scripts that could break silently?
- **Organization**: does the file structure reflect how things are actually used?
- **Robustness**: what happens when something is missing or malformed?
- **Maintenance burden** (added 2026-07-09, Gil's direction): does two-or-more scripts implement the same *shape* of logic on different data (not necessarily copy-pasted — a duplicated pattern counts)? Every new script is something to maintain going forward; growing that count without checking for reuse first is itself a cost. Flag genuine duplication; don't force consolidation for its own sake at 2 call sites (see the `priority_rank.py` entry in `suggestions.md` for the calibration — noted, not force-extracted).

### 2. Generate suggestions

For each finding that passes the bar (see below), write a suggestion entry with an explicit priority — this file is a priority-ordered, reorderable backlog (added 2026-07-09), not a chronological log. Score priority using the same compounding-leverage lens as everywhere else in this system (`~/.claude/marvin-roadmap.md`'s north-star section): does this unlock or cheapen multiple future items, not just its own standalone value.

Entry format:

```
## [Title]
**Priority**: [1-10, 10 = highest — see scoring guidance below]
**Status**: pending
**Impact**: [token-reduction | speed | reliability | organization | robustness]
**Effort**: [low | medium | high]
**Why**: [one line — the problem]
**What**: [exact change]
**How**:
- step 1
- step 2
**Added**: [YYYY-MM-DD]
```

**Priority scoring**: weight compounding leverage above standalone impact — an item that makes several future items cheaper/faster/possible outranks a bigger one-off win. Within that, break ties by Impact (token-reduction/speed rank above organization/robustness per `## Optimization Priorities` below) then Effort (lower effort wins at equal impact).

After writing the entry, run the sorter so the file actually reflects current priority order, not insertion order:
```
~/.agents/venv/bin/python ~/.agents/skills/architecture-review/scripts/sort_suggestions.py
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
- Read `~/.claude/suggestions.md` — already in priority order (highest first), since the file is kept sorted
- Show all `pending` items in compact form, in that order
- Ask: "Approve any? (by title or 'all')" — also accept reprioritization requests ("bump X", "this is more important than Y"): update the entry's **Priority** field and re-run `sort_suggestions.py`

## Optimization Priorities

Ranked by value:

1. **Token reduction** — shorter SKILL.md files, compressed routing descriptions, deduplicated instructions
2. **Retrieval speed** — routing table accuracy (fewer false positives), skill descriptions that match faster
3. **Organization** — related skills grouped, dead files removed, naming consistent
4. **Pipeline logic** — background_review.py robustness, handoff flow, session-start checks
5. **Reliability** — hardcoded/stale counts, scripts referenced but not present, scripts that fail silently
6. **Robustness** — graceful degradation when files missing, fallback behavior documented
