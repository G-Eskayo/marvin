# Stale Decision Check System (marvin#XXX)

## Overview

Implemented a system to detect and flag when documented claims (in memory, CONTEXT.md, ADRs, README) contradict current system state, surfacing "stale decisions" that intent-reality gaps created.

## Architecture

### Core Modules

**`lib/stale_decision_check.py`** — Pure logic for finding and judging contradictions:
- `find_candidates(text)` — Token-based search for relevant docs/ADRs/memory in matched project
- `judge_contradiction(claim, state)` — Uses Judge (clean model) to decide if they contradict
- `check_claim(file_path, text)` — Entry point: checks one memory file against repo docs
- `sweep()` — Scans all memory files for stale decisions (report-only)
- `open_flags()` — Reads unresolved contradictions from `~/.claude/contradictions.md`
- `Flag` dataclass — Structured representation of a flagged contradiction

**`lib/stale_decision_hook.py`** — PostToolUse hook (mirrors `background_review.py` pattern):
- Triggers on Write/Edit to memory, CONTEXT.md, docs/adr/, CLAUDE.md
- Detached subprocess pattern to avoid stalling interactive session
- 5-minute cooldown to collapse repeated writes
- Spawns with `--run-check` flag to run check synchronously

**`~/.claude/contradictions.md`** — Quarantine-style flagged queue:
- Append-only file (like `quarantine.md`)
- Checkboxes: approve / update / contradiction
- Never auto-modified by tools (design review gates all changes)

### Integration Points

**`lib/marvin_hooks.py`** — Registered PostToolUse hook on `Write|Edit` for:
- Memory files (any .md under `~/.agents/projects/-*-/memory/`)
- CONTEXT.md, docs/adr/*.md (project repo docs)
- CLAUDE.md (global rules)

**`skills/handoff/SKILL.md`** — Added rule:
- Before writing handoff, check `contradictions.md` for open flags related to the work
- Fold unresolved contradictions into "Key decisions made" or "Open questions"

**`skills/self-improve/SKILL.md`** — Added gate:
- Before codifying a pattern, check `contradictions.md` for flags that would contradict it
- Prevents locking in disputed intent

## Decisions Needed

### 1. **judge-trigger**: When should the Judge run?

**Current implementation**: Runs on every `check_claim()` call (whenever a memory file is written).

**Trade-off**: 
- Always running: catches contradictions early, but expensive (one Judge call per memory edit = ~5s + tokens)
- On-demand only: cheaper, but contradictions go unnoticed until `sweep` runs

**Options**:
A. **Always** (current): Judge every check_claim, even for small edits. Cost: one Judge call per memory write.
B. **Selective**: Only judge if the check_claim snippet is >N tokens or matches a high-confidence heuristic.
C. **On-demand only**: Remove auto-judge from hook; `check_claim()` only runs heuristic checks. Judge only on explicit `sweep` or user request.
D. **Tiered**: Heuristic check in hook (fast), full Judge only on `sweep` or flag review.

**Recommendation**: Start with **B (Selective)** — judge only if the snippet is substantial (>50 tokens) or high-risk keywords ("always", "never", "must") appear. This catches material contradictions early without stalling every write.

### 2. **sweep-cadence**: How often should sweep run?

**Current implementation**: Not wired to any schedule; must be triggered manually or via `marvin_launcher.launch("background-analyst", ...)`.

**Options**:
A. **Daily cron** (launchd): Run `sweep()` once per day (e.g., 2 AM), write to contradictions.md, let handoff prompt surface any unresolved ones.
B. **Weekly cron**: Run once per week, less churn.
C. **On-demand only**: No automation; sweep runs manually when needed (e.g., before a release).
D. **Session-start hook**: Run lightweight heuristic check at session start; full sweep only once per day.

**Recommendation**: Start with **A (Daily cron)** — `sweep()` runs once daily (low cost, long-lived contradictions won't age silently), write findings to contradictions.md. Handoff skill will surface unresolved ones. If daily is too noisy, dial back to weekly (**B**).

### 3. **judge-model**: Which model should the Judge use?

**Current implementation**: `claude-haiku-4-5-20251001` (same as `fit_check.py`).

**Rationale**: Haiku is fast and cheap for this task (comparing two texts, not complex reasoning). The judge's job is straightforward: do these contradict? Not "is this the optimal design", which would need more reasoning.

**Confirm**: Haiku is sufficient. If contradictions are being missed or over-flagged, escalate to Sonnet. No change planned.

### 4. **Flag Resolution Workflow**: How should Gil review contradictions?

**Current implementation**: Manual checkbox in `contradictions.md` + optional handoff integration.

**Workflow** (implied by design):
1. Hook finds a contradiction, appends to contradictions.md with `[ ]` checkboxes
2. Handoff skill notifies Gil about unresolved flags (if any in the session)
3. Gil manually checks one of:
   - `[x] approve` — claim is dated but acceptable, no action needed
   - `[x] update` — update the memory file with current truth
   - `[x] contradiction` — real disagreement, blocks shipping related code
4. Once Gil marks an entry, the flag is resolved (stays in the file for history)

**Confirm**: This is a manual review loop, not auto-remediation. MARVIN may surface and categorize contradictions, but only Gil decides which matter.

## Testing

Comprehensive test suite in `lib/tests/test_stale_decision_check.py`:
- Token extraction and filtering ✅
- Snippet extraction with context ✅
- Candidate matching against catalogs ✅
- Judge verdict parsing ✅
- Flag parsing and resolution checking ✅
- Check_claim and contradiction detection ✅

All 19 tests pass.

## Next Steps

1. **Confirm decisions** (above) in PR review — especially judge-trigger (A/B/C/D) and sweep-cadence.
2. **Implement `sweep` scheduling** once cadence is decided (likely via a launchd job, mirroring `daily_digest`).
3. **Optional: Judge-trigger refinement** — if sweep-cadence is "on-demand", could flip judge-trigger to "selective" to catch contradictions even without daily sweep.
4. **Monitor** — track how many flags are found in first week, whether they're real vs. noise. Adjust judge model or trigger if needed.

## Files Changed

- `lib/stale_decision_check.py` — new module (pure logic)
- `lib/stale_decision_hook.py` — new module (PostToolUse hook)
- `lib/marvin_hooks.py` — register new hook
- `lib/tests/test_stale_decision_check.py` — test suite
- `skills/handoff/SKILL.md` — added contradictions check rule
- `skills/self-improve/SKILL.md` — added gate against flagged patterns

## Known Gaps / Deferred

- **sweep scheduling** — depends on decision #2; not wired until decision is made
- **Auto-remediation** — deliberately not included; Gil reviews and decides which contradictions matter
- **AI-to-code mapping** — currently text-only (memory vs. docs). Could extend to check claims against actual code via AST (deferred)
- **Judge context** — Judge runs clean (no MARVIN layers) intentionally, to avoid biasing it; if contradictions are being missed due to insufficient context, would need to add carefully
