---
name: context-sweep
description: Autonomously reviews all context/documentation files for contradictions, redundancy, and QA gaps — run regularly like architecture-review (same cadence, different scope). Findings queued to suggestions.md. Never edits swept files; only writes findings to the shared bucket with Source:context-sweep tag for traceability.
tags: [intent:optimize, intent:review, intent:meta, type:skill]
---

# Context Sweep

Autonomously reviews all documentation, context files, and skill references for contradictions, redundancy, and QA gaps. Runs unattended with findings queued alongside architecture-review suggestions.

**Never implements without explicit approval.**

## Scope

Everything under:
- `~/.agents/skills/**/*.md` — all SKILL.md and supporting docs
- `~/.agents/docs/**/*.md` — all ADRs, handbooks, and guidance
- `~/.agents/CONTEXT.md` — central context document
- Project `CLAUDE.md` (repo-checked-in)
- Project `README.md`, `retrospective-log.md`
- `~/.claude/CLAUDE.md` — global user config
- `~/.claude/lexicon.md` — defined terms
- `~/.claude/handoffs/*.md` — saved context switches
- `~/.claude/projects/*/memory/*.md` — persistent per-project memory

**Exclusions**: `suggestions.md` and `improvement-queue.md` (don't let the sweep review its own output bucket).

Chunked by file count (not directory size like architecture-review): ~5 files per chunk, cycling through the full inventory over multiple runs.

## Review Checklist

For each file or cluster of files in the chunk, ask:

- **Contradictions**: Do different files give conflicting guidance on the same topic? (e.g., CLAUDE.md says "use Haiku" but lexicon says "never use Haiku")
- **Redundancy**: Is the same instruction/definition repeated in multiple places? Could it be centralized?
- **QA gaps**: Are claims made (e.g., "SKILL X does Y") but never verified against actual code? Are references stale (file paths, function names that no longer exist)?
- **Clarity**: Do related entries use consistent terminology? Are there orphaned references (e.g., handoff mentions "the sync-log" which doesn't exist)?
- **Currency**: When was each file last edited? Any section that looks obviously outdated (e.g., "coming soon" that's been sitting for 6 months)?

## Suggestion Entry Format

Reuse suggestions.md format exactly (from architecture-review/SKILL.md), with one addition:

```
## [Title]
**Priority**: [1-10, 10 = highest]
**Status**: pending
**Impact**: [token-reduction | speed | reliability | organization | robustness]
**Effort**: [low | medium | high]
**Why**: [one line — the problem]
**What**: [exact change]
**How**:
- step 1
- step 2
**Source**: context-sweep
**Added**: [YYYY-MM-DD]
```

**Source: context-sweep** is added for provenance — sort_suggestions.py ignores unknown fields, so this is safe.

## Suggestion Bar (Reuse from architecture-review)

Only queue suggestions that pass all three:
- **Concrete**: exact file + change specified
- **Measurable**: quantify if possible (lines consolidated, files deduplicated, etc.)
- **Net positive**: improvement outweighs risk

Do not queue:
- Stylistic preferences with no functional impact
- Vague observations ("this is confusing")
- Anything without a clear action

## Example Findings (Calibration)

**Good**: "CLAUDE.md lists 'grill-me' under Skills but grill-me has been merged into grill-with-docs (only grill-with-docs/SKILL.md exists). Remove the now-broken reference."

**Good**: "Contradiction: ~/.claude/lexicon.md defines 'chunk' as 'N files per pass' but architecture-review/SKILL.md chunk description treats chunks as 'skills or meta-clusters'. Clarify which is canonical."

**Skip**: "This sentence is a bit long" (stylistic, not actionable).

**Skip**: "CONTEXT.md feels outdated" (vague; would need specifics like "line X references Y which no longer exists").
