---
name: context-sweep
description: Systematic sweep of contradiction, redundancy, and QA gaps across the entire context database (~/.agents + ~/.claude). Runs as a recurring background task that chunks the full database and rotates through it over time, rather than trying to audit everything at once.
tags: [intent:audit, intent:meta, domain:reliability, type:skill, cadence:automated]
---

# Context Sweep

Complementary to `architecture-review` (which finds optimization/design opportunities within skills) and `audit` (which is reactive, triggered by a specific suspicion). This skill is **systematic and full-coverage**: it rotates through the entire context database — documentation, config, commands, skills, handoffs, lexicon — and flags only three categories of genuine problems:

## Finding categories

1. **Contradiction**: this file states something an ADR, CONTEXT.md, another skill's docs, or config states differently. A real divergence in intent/design, not just "different writing style." Carries the same judgment-call weight as architecture-review findings.

2. **Redundancy**: near-duplicate content across files that should consolidate or cross-reference instead. A maintenance burden (when docs drift and end up saying different things) disguised as multiple resources.

3. **QA gap**: a docstring, comment, or file header makes a claim about a mechanism, caller, dependency, or behavior that doesn't exist or is handled differently than described. Same shape as `audit`'s intent-vs-reality mismatch, but discovered systematically rather than reactively.

## What NOT to flag (self-poisoning guard)

Adapted from background_review.py's DO-NOT-capture clause: never flag something as a contradiction/redundancy/gap if it falls into these categories:

- **Genuinely scoped-but-different**: two skills covering adjacent cases intentionally (e.g., `grill-me` for abstract conceptual work, `grill-with-docs` for repo-attached grilling — both exist for valid reasons).
- **Environment-specific details**: a file's statement about "this tool only works on macOS" or "launchd won't run this on CI" reflects real conditional behavior, not a contradiction.
- **One-off narrative**: "this attempted fix in 2025 didn't work" is a historical note, not a QA gap if the current mechanism is correct.
- **Transient state**: "the cache was poisoned on that one run" isn't a gap in the design; the design is fine.

When in doubt: if it's genuinely separable concerns or historical artifact, skip it. Only flag things that would confuse future readers or cause maintenance problems.

## Acceptance criteria

| Criterion | How it's met |
|---|---|
| Full sweep covers every file at least once | Flat sorted file list from `~/.agents/` + `~/.claude/` (minus binaries/cache), cursor rotation, and `coverage-log.md` records cycle completion auditably |
| Findings in a dedicated bucket, not ad hoc | New `~/.claude/context-sweep-findings.md`, separate from `suggestions.md` (keeps architecture/optimization and contradiction/QA findings from mixing) |
| Re-runnable, consistent cadence | Standalone script with chunk/cursor/cooldown identical to `background_architecture_review.py`, safe to wire into launchd or trigger from session-start hook |

## Implementation

Not a user-facing skill (no manual `/context-sweep` trigger). Implemented as:

- `background_context_sweep.py` — same subprocess fork + chunk/cursor pattern as `background_architecture_review.py`, enumerates files fresh each run from the two roots, writes findings to `~/.claude/context-sweep-findings.md` with file pointers injected into offending files.
- `coverage-log.md` — auditable record of when a full rotation cycle completes.
- Tests in `tests/test_background_context_sweep.py`, mirroring `background_architecture_review`'s test shape (cursor advance, wraparound, cycle-completion logging, pointer rendering, exit-code branches).
