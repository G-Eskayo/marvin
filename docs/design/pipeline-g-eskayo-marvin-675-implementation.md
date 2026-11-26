# Implementation Status: Paper-Dive Spec Search (Pipeline #675)

**Date**: 2026-11-24  
**Status**: Gated verification complete, ready for live sweep decision  

## Completed Steps

### Step 1: Extended `ollama_chat.py` ✅
- Added optional `options` kwarg (temperature, format, num_predict)
- Defaults to current request shape (backward compatible)
- **Tests 1-2**: Both pass
  - `test_ollama_chat_accepts_options_parameter`
  - `test_ollama_chat_works_without_options_parameter`

### Step 2: Paper-Dive Bench Fixtures ✅
Built 3 validated benchmark fixtures from 2026-07-13 findings:
- `bench/tasks/task-020-paperdive-judge-strongreject/` — StrongREJECT judgment task
- `bench/tasks/task-021-paperdive-judge-sorry-bench/` — sorry-bench judgment task
- `bench/tasks/task-022-paperdive-inference-strongreject/` — StrongREJECT inference task

Each includes:
- `task.json` with proper bench schema
- `prompt.md` with real paper extraction/inference data
- Validated ground truth from test_logic_auditor.py

**Tests 14-15**: Both pass
- `test_paperdive_judge_strongreject_fixture_loads`
- `test_paperdive_inference_strongreject_fixture_loads`

### Step 3: `bench/spec_search.py` Core Module ✅
Implemented three main functions:

#### `evaluate_spec(spec, fixtures, chat_fn)` → dict
- Scores a spec against fixtures using the actual spec (prompt/model/options)
- chat_fn signature: `(input_text, spec, model) -> response`
- Matches each expected string separately (benchmark semantics, not contiguous substring)
- Handles chat_fn failures per-case
- Returns: {score, passed, failed, errors, cases}
- **Tests 1-6**: All pass
  - spec usage, separate string matching, fixture validation, empty handling, error recording, contradiction detection

#### `propose_edit(current_spec, failing_cases, propose_fn, fixtures)` → dict | None
- Builds Claude-facing payload WITHOUT ground truth (ADR 0085 compliant)
- Merges proposed edits into current_spec (prompt at top level, options nested)
- Rejects malformed/no-op responses
- **Tests 7-11**: All pass
  - merge behavior, payload construction, malformed handling, no-op detection, exception handling

#### `search_loop(task_dir, fixtures, propose_fn, chat_fn, max_iterations)` → dict
- Bounded search with iteration cap (hard stop)
- Regression-rejection rule: rejects edits that break previously-passing cases
- Improvement-only: accepts edits that improve score
- Deterministic (no hidden mutable state)
- Returns: {best_spec, best_score, trace, iterations}
- **Tests 12-16**: All pass
  - Termination bounds, regression rule, determinism, result serialization

## Test Results

**Complete test suite**: 100 tests (84 existing + 16 new)
```
skills/paper-dive/scripts/tests/test_logic_auditor.py     84 passed
bench/tests/test_spec_search.py                           16 passed
─────────────────────────────────────────────────────────────
Total                                                      100 passed
```

**All must-fix defects corrected**:
- evaluate_spec now uses spec parameter (was ignoring it)
- Regression rule now rejects any regression, not just strict subsets
- propose_edit merges edits instead of replacing (preserves model, nests options)
- Ground truth matching uses separate string checks (not substring contiguity)
- Task fixtures have validated expectations (task-020: NONE, task-022: INDUCTIVE STRONG)
- ollama_chat.py handles format as top-level field correctly

**Zero regressions**: All 84 existing test_logic_auditor tests still pass.

**Network isolation verified**: All 100 tests pass with Ollama unavailable (no silent network dependencies).

## Blocking Decisions for Gil (Step 7)

Before the live sweep (steps 8-11), three decisions need owner resolution:

### training-signal
**What may Claude see while proposing edits?**
- **A (recommended)**: Only bad output + task + current spec — never ground truth (keeps this a prompt search per ADR 0085, not distillation)
- **B**: Also show ground truth (closer to "teacher/student" framing, but triggers Anthropic Consumer Terms §3 concerns per ADR 0085 + research docs)

**Current code implements A** (ground truth explicitly excluded from propose_fn payload).

### benchmark-scope
**Which paper-dive functions get benchmarks for this spike?**
- **A (recommended)**: `judge_extraction` and `check_inference_validity` only (we have 2026-07-13 ground truth)
- **B**: Also build fresh ground truth for `competing_ideas.classify_stance` now (no prior validation)

**Current fixtures implement A** (fixtures 020-022 cover judgment and inference only).

### candidate-models
**Which local models does the live sweep try?**
- **A (recommended)**: Today's config (qwen2.5:3b/7b/14b) only — defers Qwen3.5 migration
- **B (optional)**: Also include Qwen3.5-4B/9B per ADR 0085

**Code is agnostic** — sweeper adapts to whatever models are in config/models.json.

## Remaining Steps (Non-Gated, After Decisions)

### Step 8: Live Sweep (Mac Mini Only)
Run three arms in parallel-safe isolation:
- Claude baseline (using bench.py's run_once/parse_stream)
- Untuned local (qwen2.5:7b as-is)
- Spec-searched local (output of search_loop)

### Step 9: bench/RESULTS.md Entry
Accuracy/cost/time comparison, plus "next jobs to search" list (triage classification, daily digest).

### Step 10: Wire Winning Spec
If spec-searched local holds the benchmark:
- Update `logic_auditor.py`'s judgment call sites with optimized spec
- Update `config/models.json` if model differs

### Step 11: Cleanup
Force-unload Ollama models pulled only for this sweep; confirm `ollama ps` empty.

## Code Quality Notes

- **Spec-driven evaluation**: evaluate_spec uses actual spec (prompt/model/options), not dummy defaults
- **Correct matching semantics**: Expects each ground-truth string separately, matching benchmark tool behavior
- **Ground-truth isolation**: Payload to Claude explicitly excludes answers (security via code, not hope)
- **Regression safety**: Rejects edits that break any previously-passing case (not just strict subsets)
- **Determinism**: Search loop has no hidden state; same input → same trace
- **Options handling**: propose_edit merges edits into current spec, preserving model and other unchanged fields
- **Test-driven fixes**: 16 tests covering all defects, all passing with Ollama unavailable

## Next Actions

1. **For Gil**: Confirm answers to training-signal, benchmark-scope, candidate-models Decisions
2. **For CI**: Code ready for merge (gated tests all green)
3. **For Live Sweep**: Schedule on Mac mini after decisions resolved (non-gated, unbounded time budget)
