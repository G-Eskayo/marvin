---
name: context-sweep
description: Autonomously checks MARVIN's own knowledge store for contradictions, redundancy, and QA gaps — distinct lens from architecture-review (design quality) and audit (intent-vs-reality). Continuous, chunked background process. Never implements without approval.
tags: [intent:quality, intent:review, intent:meta, type:skill]
---

# Context Sweep

Continuous integrity checks on MARVIN's own knowledge: docstrings, memory, skills, configuration, and code — checking for contradictions, redundancy, and QA gaps. A dedicated, automated background sweep that complements human-driven code review and the design-focused `architecture-review` skill.

**Never implement without explicit approval.**

## Epistemic Stance

This is a **local consistency checker**, not a complete contradiction detector:

- **Can detect**: within a single chunk or against the small canonical-index files (CLAUDE.md, lexicon.md, marvin-roadmap.md, MEMORY.md), contradictions and redundancy visible in that scope.
- **Cannot detect**: a contradiction between two arbitrary skill files that never land in the same chunk. The canonical-index injection mitigates this for the most common cross-file references (meta-config, design decisions, lexicon), but is not a complete solution. Mitigation: every file is rotated through regularly, so contradictions *within* each file's component are caught; the gap is only across components that don't share canonical references.
- **Will miss**: very subtle semantic redundancy (e.g., two different-looking workarounds for the same underlying issue, neither explicitly named). The checker looks for explicit naming/documentation of the concept.

This is acceptable because:
1. Chunks rotate regularly (full-DB coverage over weeks)
2. The canonical-index injection covers the highest-risk cross-component references
3. Human review (code review, architecture-review, audit) catches the remainder
4. The goal is passive risk reduction, not a bulletproof verification system

## Scope

Everything under `~/.agents` and `~/.claude`:
- Skill code and documentation (SKILL.md, scripts, tests)
- lib/ utilities and helper scripts
- CLAUDE.md, lexicon.md, marvin-roadmap.md, memory files
- Configuration, hooks, launchd jobs
- Commands and handoff summaries
- Cross-machine infrastructure config (where it affects knowledge state)

**Not** in scope:
- The marvin codebase itself (design/architecture issues) — use `architecture-review` for that
- Unattended behavior gaps — use `audit` for intent-vs-reality mismatches
- Standalone optimization suggestions — queue those to `architecture-review`

## Review Process

### 1. Chunk enumeration

Files are exhaustively enumerated from `~/.agents` and `~/.claude`, batched into fixed-size chunks (~10 files per chunk). Enumeration is fresh each run — added/removed files are automatically reflected on the next run.

Exclusions:
- Build artifacts: `__pycache__`, `.pytest_cache`, `node_modules`, venvs
- Binary files and large assets (>1MB)
- `.git`, `.DS_Store`, IDE configs

### 2. Canonical-index injection

Every chunk's review context includes a small fixed canonical set:
- `~/.claude/CLAUDE.md` — meta-routing, skill triggers
- `~/.claude/lexicon.md` — shared terminology definitions
- `~/.claude/marvin-roadmap.md` — design decisions, north-stars
- `~/.claude/MEMORY.md` — facts about the user and system

This injection enables cross-component contradiction detection (e.g., "this skill's docstring says it's triggered by X, but CLAUDE.md says Y").

### 3. Check for findings

For each chunk, ask:
- **Contradictions**: A fact stated one way in one file conflicts with how it's stated elsewhere
  - Example: "this script runs weekly" vs. a comment saying "monthly"
  - Example: skill docstring says "runs on demand" but cron config triggers it daily
- **Redundancy**: The same pattern/concept/rule is documented in multiple places
  - Example: memory.md and CLAUDE.md both explain the same term
  - Example: two skill files implement identical state-machine logic separately
  - Example: three scripts all export the same utility function (maintenance burden — should consolidate)
- **QA gaps**: A documented feature/process has no verification
  - Example: "the pipeline verifies X" but there's no test for X
  - Example: "cooldown prevents double-runs" but no test exercises the cooldown
  - Example: a function's docstring claims it handles missing files, but no test passes a missing file

### 4. Generate findings

For each finding that passes the bar (below), write a finding entry:

```
## [Title]
**Priority**: [1-10, 10 = highest]
**Status**: pending
**Impact**: [contradiction | redundancy | qa-gap]
**Effort**: [low | medium | high]
**Why**: [one line — the problem]
**What**: [exact change]
**How**:
- step 1
- step 2
**Added**: [YYYY-MM-DD]
```

**Priority scoring**: Same as `architecture-review` — weight compounding leverage above standalone impact. Within that, break ties by Impact (contradiction/redundancy rank above qa-gap), then Effort (low wins).

After writing findings, the `sort_context_sweep_findings.py` script runs automatically to keep the file sorted.

### 5. Present to user

When findings are queued, surface them:

> **[N] new context-sweep finding(s) queued.**
> Run `/context-sweep findings` to see them, or I'll show them now.

### 6. On approval

When user approves (by name/number):
1. Read the finding's **How** steps
2. Implement exactly as specified
3. Update status to `done` in `~/.claude/context-sweep-findings.md`
4. Confirm what changed

On rejection: update status to `rejected`.

## Finding Bar

Only queue findings that pass all three:
- **Concrete**: exact file + change specified, not vague ("improve readability")
- **Measurable**: items consolidated, lines removed, tests added — quantify if possible
- **Net positive**: fix outweighs risk of breaking something; not a stylistic preference

Do not queue:
- Redundancy where the two implementations serve genuinely different purposes (e.g., two different CLI argparse setups for different tools)
- QA gaps for internal/private utilities not exposed to real error cases
- Contradictions that are actually allowed variants ("this script *can* run weekly or on-demand")

## Running manually

Trigger a fresh sweep:
```
~/.agents/venv/bin/python ~/.agents/skills/context-sweep/scripts/background_context_sweep.py
```

View pending findings:
```
/context-sweep findings
```

## Automation

Wired to a launchd cron (weekly by default) via the same pattern as `architecture-review`. Full database coverage completes over N weeks depending on file count. Run log visible in dashboard Health tab.

## Output and storage

Findings are stored in `~/.claude/context-sweep-findings.md`, separate from:
- `~/.claude/suggestions.md` — architecture quality findings (design/organization)
- `~/.agents/CONTEXT.md` — intent-vs-reality audit findings (docs vs. code)
- Retrospective logs (improvement feedback)

This separation keeps the three review surfaces focused and easy to scan.

## Verifier integration

The automated pipeline verifier runs `pytest` on the included `test_background_context_sweep.py` suite. Tests verify:
- Chunk enumeration correctness (full rotation, no skips/duplication)
- State management (load/save, cooldown)
- Error handling (missing claude, malformed bucket, unreadable files)
- Idempotency (same chunk twice doesn't duplicate findings)
- File rendering for the reviewer

For new findings that should be caught, write a test first that would fail without the fix, then implement.
