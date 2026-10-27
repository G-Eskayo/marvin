# Spec-Search Benchmark Harness — Implementation Status

## Overview
Benchmark-guided prompt tuning for `logic_auditor.py`'s judgment step. Teacher model (Claude Opus) proposes edits to the judgment prompt based on tuning-set misses; student (Ollama qwen2.5:3b or configurable) tests them. Keeps only edits that improve tuning accuracy without regression on a frozen holdout set.

## Completed Steps

### 1. ✅ Added `prompt_override` parameter to `logic_auditor`
- **File**: `skills/paper-dive/scripts/logic_auditor.py`
- **Changes**: 
  - `judge_extraction(..., prompt_override: str | None = None)` — accepts alternative judgment prompt
  - `judge_all(..., prompt_override: str | None = None)` — threads override through batch judging
  - When `None` (default), uses type-specific judgment prompts (backward compatible)
  - When provided, replaces the prompt entirely (for tuning/testing)
  - Override prompts are interpolated with extraction fields + fallacies list like defaults

### 2. ✅ Wrote comprehensive tests (16 new + all 78 existing pass)
- **File**: `skills/paper-dive/scripts/tests/test_logic_auditor_prompt_override.py`
- **Coverage**: 
  - Default behavior unchanged when override not provided
  - Override interpolates extraction fields correctly
  - Override works with all 4 paper types (empirical, survey, benchmark, conceptual)
  - Findings parsed identically to default prompts
  - Missing fields handled same as defaults
  - Works with both `judge_extraction` and `judge_all`
  - Can produce measurably different findings (e.g., accuracy changes)
- **Status**: 16/16 pass, 0 regressions on existing 78 tests

### 3. ✅ Created the spec-search harness skeleton
- **File**: `bench/spec_search.py`
- **Structure**:
  - Load/freeze benchmark split (tuning vs holdout)
  - Measure baseline: student accuracy on both sets
  - Loop: propose edit → test → keep if no regression
  - Final eval: on holdout only (no tuning overfitting)
  - Report results + costs to RESULTS.md
- **Status**: Script executable, infrastructure in place; helper functions stubbed with `NotImplementedError`

## Remaining Steps (Deferred — Stubs in Place)

These are marked as `NotImplementedError` to unblock the rest of the harness structure:

### 4. Benchmark-sample loader
- Load seed papers from `paper-knowledge` Chroma collection (no `discovered_via`)
- Match with `~/.claude/paper-sessions/*/state.json` state for context
- Freeze 70/30 tuning/holdout split to `bench/results/spec-search-paper-dive-judgment-sample.json`
- Reuse on subsequent runs instead of redrawing

### 5. Teacher-call helper
- Build `propose_prompt_edit()` to call Claude Opus
- Takes tuning-set misses, current prompt, paper type
- Returns one candidate edit or `None` if no further improvements
- Integrated with `_check_quota()` preflight + infra-error abort

### 6. Cost tracking & results reporting
- Sum `cost_usd` / `wall_s` across all teacher calls
- Write `## Run N` entry to `bench/RESULTS.md` (method, results table, Findings, Caveats, Next priorities)
- Write results JSON trace under `bench/results/` (mirror `select_model.py`'s convention)
- Add atomic/locked writes for split manifest + RESULTS.md append

### 7. Wire-in decision
- Update `logic_auditor.py`'s default judgment prompts (or `config/models.json`'s `local-judge-medium` capability) with final tuned spec
- **OR** file a follow-up ticket if results suggest the tuned spec is exploratory

## Test Status Summary
- Total tests passing: **192/192** ✅
  - New prompt-override tests: 16/16
  - Existing logic_auditor tests: 78/78
  - Other modules: 98/98
- Code coverage: prompt_override feature is fully tested
- Backward compatibility: default behavior unchanged

## Integration Points
- **logic_auditor.py**: judgment step is now tuneable via prompt_override
- **spec_search.py**: ready to instantiate with Chroma loaders + teacher calls
- **RESULTS.md**: waiting for results entry via Run N convention
- **bench/results/**: directory ready for manifest + trace files (create on first write)

## Next Actions (for user or follow-up work)
1. Implement `load_benchmark_split()` with Chroma + paper-sessions matching
2. Implement `propose_prompt_edit()` with Claude Opus subprocess
3. Run `spec_search.py --max-rounds 5` to tune and generate RESULTS.md entry
4. Review findings → wire in tuned spec or defer to follow-up ticket
