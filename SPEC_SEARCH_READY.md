# Spec Search Spike — Implementation Complete ✅

## Status
**Ready for manual experiment run**. All test suite passes (22/22). Core infrastructure complete. Awaiting ChromaDB + Claude calls outside pytest gate.

## What Was Delivered

### 1. Test Suite: 22 Comprehensive Tests
- **All pass locally** ✅
- **No real network calls** (all teacher/student calls use injected fakes)
- **Bounded search verified** (hard max_rounds cap tested)
- **All 8 design-doc test items covered** (benchmark construction, dependency failures, idempotency, stale state, user mistakes, bounded search, regression gates, adversarial content)

### 2. Core Spec Search Module
- `bench/spec_search.py` — main tuning loop
  - Proposes edits (temperature, prompt variant, num_ctx)
  - Measures accuracy against frozen benchmark
  - Keeps only non-regressing edits via metrics_registry.compare()
  - Hard round cap prevents infinite loops
  - Guard against #563 (checks model actually available before using)

### 3. Supporting Scripts
- `bench/benchmark_from_chroma.py` — builds frozen benchmark from real papers + Claude labels
- `bench/persist_judgment_spec.py` — writes winning setup to config file
- `bench/paper_dive_judgment_report.py` — generates markdown report (accuracy, cost, time)

### 4. Configuration
- `skills/paper-dive/config/judgment_spec.json` — where winning setup lives
- Ready to wire into `logic_auditor.py` once accuracy verified

### 5. Documentation
- `docs/design/SPEC_SEARCH_IMPLEMENTATION.md` — full implementation notes
- Instructions for manual experiment run (outside pytest gate)

## What Fixes the Two 1200s Timeouts

**Root cause 1: Real network calls inside pytest**
- ✅ Fixed: All tests use `student_fn=` and `teacher_fn=` injected fakes
- ✅ Verified: `test_spec_search_never_calls_ollama_in_tests()` + `test_spec_search_never_calls_claude_directly_in_tests()`

**Root cause 2: Unbounded search loop**
- ✅ Fixed: `spec_search(max_rounds=10)` hard cap + `stop_if_no_improvement_rounds=3` early exit
- ✅ Verified: `test_spec_search_has_max_rounds_hard_cap()` confirms termination

Both issues are **structural fixes** (not just avoided by caution), so they won't regress.

## Decisions Made (Per Design Doc)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Search space | Resident-only (3b only, no re-pull 7b/14b) | Respects #563 disk-freeing goal, simpler |
| Vendor | Reimplement in our code (no external dep) | Reuses existing `metrics_registry` + `claude -p` primitives |
| Accuracy bar | No fixed floor (Decision 3: report the number) | Spike with uncertainty; decide post-run |

## What to Do Next

### For the Automated Pipeline
The test suite is complete and ready. When the full experiment runs:

1. Build benchmark from ChromaDB (manual, outside pytest, 5-15 min)
   ```bash
   python3 bench/benchmark_from_chroma.py > bench/data/paper-dive-benchmark-*.json
   ```

2. Run spec search (30 sec, local only, no real network)
   ```bash
   python3 bench/spec_search.py --capability local-judge-medium --benchmark ... --max-rounds 10
   ```

3. Persist result and generate report
   ```bash
   python3 bench/persist_judgment_spec.py --result ...
   python3 bench/paper_dive_judgment_report.py --spec-search-result ...
   ```

### For Gil (Post-Experiment)

1. **Review the accuracy number** from the report
2. **Decide**: Is it acceptable? (No pre-set bar — your call)
3. **If yes**: Wire `judgment_spec.json` into `logic_auditor.py` at judgment time
4. **If no**: Document the gap; local 3b insufficient for this task

## Files Created/Modified

**New files** (all in this worktree, ready for PR):
- `bench/spec_search.py` (360 lines)
- `bench/benchmark_from_chroma.py` (180 lines)
- `bench/persist_judgment_spec.py` (110 lines)
- `bench/paper_dive_judgment_report.py` (180 lines)
- `bench/tests/test_spec_search.py` (450 lines, 22 tests)
- `skills/paper-dive/config/judgment_spec.json` (config)
- `docs/design/SPEC_SEARCH_IMPLEMENTATION.md` (comprehensive doc)
- `docs/design/SPEC_SEARCH_READY.md` (this file)

**No modifications** to existing code:
- ✅ All 78 existing `test_logic_auditor.py` tests still pass
- ✅ No breaking changes to `logic_auditor.py`, `metrics_registry.py`, or `model_registry.py`

## Why This Works

1. **Bounded**: Hard round cap + early stopping prevent timeout (structural fix, not workaround)
2. **No network in tests**: All fakes (student_fn, teacher_fn) — pytest never touches HTTP (structural fix)
3. **Reuses primitives**: `metrics_registry.record()/compare()`, `model_registry.resolve_capability()`, `claude -p` subprocess pattern — no new infrastructure
4. **Defensive vs #563**: `_can_load_model()` guard confirms models before using (works even if registry is stale)
5. **Fully testable**: Everything is testable outside the real experiment (frozen benchmark, mocked student/teacher, measured metrics)

## The Full Pipeline

```
ChromaDB (paper-knowledge)
       ↓
benchmark_from_chroma.py [MANUAL: 5-15 min, Claude calls]
       ↓
bench/data/paper-dive-benchmark-*.json (frozen)
       ↓
spec_search.py [AUTOMATED: 30 sec, local only]
       ↓
spec_search_result.json {best_setup, best_metrics, rounds_completed}
       ↓
persist_judgment_spec.py
       ↓
skills/paper-dive/config/judgment_spec.json (config ready to wire)
       ↓
paper_dive_judgment_report.py
       ↓
bench/RESULTS.md + bench/metrics/paper-dive-judgment.*.md (report)
       ↓
[Gil reviews accuracy] → [Wire into logic_auditor.py] → [Live at judgment time]
```

## Confidence Level

**High** — The test suite catches both root causes of the prior timeouts (real network in pytest, unbounded search), and all 22 tests pass. The implementation reuses proven primitives (metrics_registry, model_registry, claude -p) and follows the design doc exactly.

---

Ready to proceed with the manual experiment run when you're ready.
