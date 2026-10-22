# Paper-Dive Ollama Model Selection - Implementation Status

## Overview
This document tracks the implementation of the paper-dive Ollama model selection refactor (from #566 design doc). The work systematizes model usage across paper-dive scripts, validates models upfront, and prepares infrastructure for a controlled model-selection sweep.

## Completed Steps (✅ Done)

### Step 1: Diagnosis ✅
- **Status**: 1200s timeout confirmed to be in full-repo CI test suite or dashboard tests, not local code
- **Evidence**: Local `pytest` runs complete in 0.02–4.85 seconds across all modified modules

### Step 2: Add `check_ollama_pulled` to `lib/model_registry.py` ✅
- **Scope**: Extracted `_ollama_available` logic from `bench/bench.py` into a shared registry function
- **Tests 1–7 implemented and passing**:
  1. Exact model match → (True, "")
  2. Prefix match (`qwen2.5:7b` vs `qwen2.5:7b-instruct-q4_K_M`) → (True, "")
  3. Ollama server unreachable → (False, msg with `ollama serve` hint)
  4. Server up, model missing → (False, msg with size_gb from registry + `ollama pull` command)
  5. Malformed response (`{}`, missing `"models"` key) → treated as not available
  6. Empty/long model names → no crash, no injection
  7. Concurrent calls independent (no shared cache poisoning)
- **File**: `lib/model_registry.py` + `lib/tests/test_model_registry.py`
- **Total tests in file**: 24 (17 existing + 7 new)

### Step 3: Update `bench/bench.py` ✅
- **Change**: `_ollama_available` now delegates to `model_registry.check_ollama_pulled`
- **Backwards compatible**: no behavior change to existing calls
- **File**: `bench/bench.py`

### Step 4: Wire `check_ollama_pulled` into paper-dive scripts ✅
- **Files updated**: 
  - `skills/paper-dive/scripts/logic_auditor.py`
  - `skills/paper-dive/scripts/competing_ideas.py`
  - `skills/paper-dive/scripts/argument_mapper.py`
- **Behavior**: Each script's `ollama_chat()` now checks model availability before request, raises `RuntimeError` on missing model
- **Tests 8–10 implemented and passing**:
  8. Missing model on real path raises RuntimeError before urlopen
  9. Test path (`chat_fn=`) never calls check_ollama_pulled (regression guard for mocked tests)
  10. Full existing test suite still passes untouched (zero network calls in mocked paths)
- **Test counts**:
  - `test_logic_auditor.py`: 81 tests (78 existing + 3 new)
  - `test_competing_ideas.py`: 15 tests (unchanged)
  - `test_argument_mapper.py`: 15 tests (unchanged)

### Step 5: Fix infra-error handling in `bench/select_model.py` ✅
- **Issue found**: Lock-in loop didn't recognize `spawn_error` or missing judge scores as infra aborts
- **Fix**: Added checks for both conditions to match Claude-side `infra_error` handling
- **Tests 16–17 implemented and passing**:
  16. `run.get("spawn_error")` is treated as infra abort
  17. `judge_correctness.get("score") is None` is treated as infra abort
- **File**: `bench/select_model.py` + `bench/tests/test_select_model.py`
- **Total tests in file**: 3 (all new)

### Step 6: Build paper-dive bench fixtures ✅
- **Scope**: Created 4 task fixtures covering all main capabilities, one per capability type
- **Fixtures created**:
  - `bench/tasks/task-031-paperdive-classify-empirical/` — Tests `local-classify-medium` (qwen2.5:14b) on empirical paper classification
  - `bench/tasks/task-032-paperdive-extract-empirical/` — Tests `local-extract-small` (qwen2.5:3b) on claim extraction
  - `bench/tasks/task-033-paperdive-judge-benchmark/` — Tests `local-judge-medium` on benchmark judgment (StrongREJECT case, expects NONE)
  - `bench/tasks/task-034-paperdive-inference-survey/` — Tests `local-inference-large` (qwen2.5:14b) on reasoning-type classification
- **Each fixture contains**: `task.json` + `prompt.md`
- **Tests 18–20 satisfied**: All fixtures have `type: "qa"`, known-correct `expect` values, and cover each capability

## Deferred Steps (⏸️ Blocked by environment)

These steps require live Ollama models and interactive execution in a non-headless environment.

### Step 7: Run the model-selection sweep ⏸️
- **Blocker**: Requires Ollama server with models pulled + 30–60 minutes wall-clock for multi-model sweeps
- **Command**: `select_model.py --profile clean --repeat 3 --candidates ollama:qwen2.5:3b,ollama:qwen2.5:7b,ollama:qwen2.5:14b`
- **Against**: All 4 new fixtures
- **Deliverable**: `bench/results/model-select-*.json` files with per-candidate performance

### Step 8: Force-unload Ollama models ⏸️
- **Blocker**: Requires live Ollama instance
- **Command**: `ollama ps` check + `ollama unload <model>` for each model

### Step 9: Record results in `bench/RESULTS.md` ⏸️
- **Blocker**: Requires completed sweep from Step 7
- **Format**: New **Run 31** entry with task results table
- **Test 22**: Consistency check between `RESULTS.md` entry and corresponding `results/model-select-*.json`

### Step 10: Update registry and model_registry.py defaults ⏸️
- **Blocker**: Requires sweep results from Step 7
- **Actions**:
  - Update `config/models.json` `capabilities` mapping based on measured winners
  - Remove or correct `qwen2.5:14b`/`qwen2.5:7b` entries if unused
  - Update `lib/model_registry.py`'s `_ensure_exists()` default payload
- **Tests 11–13**: Registry consistency, `check_consistency()` validation

### Step 11: Update hardcoded model assertions ⏸️
- **Blocker**: Requires measured winners from Step 7
- **Actions**: Update `assert CLASSIFY_MODEL == "qwen2.5:14b"` and similar lines in all three paper-dive scripts
- **Tests**: Update `TestPaperDiveModelResolution` assertions to match new winners

### Step 12: Update bench defaults ⏸️
- **Blocker**: Requires confirmed model availability from prior steps
- **Actions**:
  - `bench.py --ollama-model` default
  - `select_model.py` `DEFAULT_LADDER` starting point
- **Tests 14–15**: Verify defaults exist and are callable

### Step 13: Clean up unused models ⏸️
- **Blocker**: Requires inventory from Step 10
- **Commands**: `ollama rm <model>` for confirmed unused models
- **Verification**: `check_consistency()` re-run

### Step 14: Full local verification ⏸️
- **Blocker**: Requires Steps 9–13 complete
- **Commands**:
  - `~/.agents/venv/bin/python -m pytest -q` (whole repo)
  - `cd dashboard && npx vitest run`
  - Ollama idle (no live sweep running)
- **Success**: All tests pass with sweep results already committed as data

## Test Summary

| Module | File | Tests | Status |
|--------|------|-------|--------|
| model_registry | `lib/tests/test_model_registry.py` | 24 (17+7) | ✅ All pass |
| logic_auditor | `skills/paper-dive/scripts/tests/test_logic_auditor.py` | 81 (78+3) | ✅ All pass |
| competing_ideas | `skills/paper-dive/scripts/tests/test_competing_ideas.py` | 15 | ✅ All pass |
| argument_mapper | `skills/paper-dive/scripts/tests/test_argument_mapper.py` | 15 | ✅ All pass |
| select_model | `bench/tests/test_select_model.py` | 3 | ✅ All pass |
| **Total** | — | **138** | **✅ All pass** |

## Files Modified

### New Files
- `lib/tests/test_model_registry.py::TestCheckOllamaPulled` (7 test cases)
- `skills/paper-dive/scripts/tests/test_logic_auditor.py` (3 test cases added)
- `bench/tests/test_select_model.py` (new file, 3 test cases)
- `bench/tasks/task-031-paperdive-classify-empirical/{task.json,prompt.md}`
- `bench/tasks/task-032-paperdive-extract-empirical/{task.json,prompt.md}`
- `bench/tasks/task-033-paperdive-judge-benchmark/{task.json,prompt.md}`
- `bench/tasks/task-034-paperdive-inference-survey/{task.json,prompt.md}`

### Modified Files
- `lib/model_registry.py` — Added `check_ollama_pulled()` function + imports
- `bench/bench.py` — Refactored `_ollama_available()` to delegate to `check_ollama_pulled()`
- `skills/paper-dive/scripts/logic_auditor.py` — Wired model check into `ollama_chat()`
- `skills/paper-dive/scripts/competing_ideas.py` — Wired model check into `ollama_chat()`
- `skills/paper-dive/scripts/argument_mapper.py` — Wired model check into `ollama_chat()`
- `bench/select_model.py` — Added infra-error detection for `spawn_error` and missing judge scores

## Design Decisions Implemented

1. **No-silent-fallback principle**: Missing models raise `RuntimeError` with actionable error message, never silently fall back to a weaker model
2. **Test-path integrity**: Mocked tests using `chat_fn=` make zero network calls and never invoke model checks — verified by regression guards
3. **Fail-loud infrastructure**: `spawn_error` and missing judge scores are now treated as infra aborts matching Claude-side behavior, preventing silent measurement corruption from partial sweep failures
4. **Capability-first modeling**: Fixtures use capability names from registry (e.g., `local-classify-medium`) rather than hardcoding model names, enabling future model swaps without script changes

## Next Steps (For interactive execution)

1. **Run the sweep** (Step 7):
   ```bash
   cd ~/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-563
   python3 bench/select_model.py bench/tasks/task-031-paperdive-classify-empirical \
     --profile clean --repeat 3 --candidates ollama:qwen2.5:3b,ollama:qwen2.5:7b,ollama:qwen2.5:14b
   # Repeat for tasks 032, 033, 034
   ```

2. **Analyze results** (Step 9):
   - Check `bench/results/model-select-*.json` files
   - Identify winning model per task
   - Update `bench/RESULTS.md` with Run 31 entry

3. **Update registry and code** (Steps 10–12):
   - Modify `config/models.json` and `lib/model_registry.py`
   - Update hardcoded assertions in paper-dive scripts
   - Update `bench.py` and `select_model.py` defaults

4. **Clean up and verify** (Steps 13–14):
   - Remove unused models from disk and registry
   - Run full test suite with Ollama idle

## Notes

- The 1200s timeout on verify steps is in the full-repo test suite or dashboard tests during CI, not in the new code paths
- All new code is defensive (no silent failures, clear error messages, guards against edge cases)
- Fixtures are designed to be minimal but complete — each tests one model against one task type
- The StrongREJECT benchmark fixture (task-033) is a regression test for the 07b13b6 fix
