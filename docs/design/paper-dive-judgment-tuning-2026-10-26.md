# Paper-Dive Judgment Tuning Implementation — 2026-10-26

## Summary

Completed implementation of specification search infrastructure for optimizing judgment extraction in paper-dive. Enables data-driven tuning of prompt templates and model parameters against real gold-standard reliability judgments.

## Completed Work

### 1. Logic auditor parameter (additive, backward compatible)

**File**: `skills/paper-dive/scripts/logic_auditor.py`

Added optional `prompt_template: str | None = None` parameter to `judge_extraction()`. Allows callers to override the type-specific judgment prompt while maintaining exact backward compatibility — existing calls continue to use defaults.

**Tests**: All 78 existing logic_auditor tests pass unchanged.

### 2–3. Specification search primitive

**Files**: 
- `lib/spec_search.py` (implementation, 130 LOC)
- `lib/tests/test_spec_search.py` (9 tests, all passing)

Implements the core teacher/student loop:

- `evaluate(spec, samples, student_fn, score_fn)`: runs student once per sample, returns accuracy
- `propose_edit(spec, failing_samples, teacher_fn)`: asks teacher for spec improvements, validates JSON
- `search(initial_spec, samples, student_fn, teacher_fn, score_fn, max_iterations)`: iterative loop with non-regressing-edits strategy, early stop on perfect score

Keep-only-non-regressing pattern: proposed changes kept only if they improve or maintain accuracy.

### 4–5. Judgment benchmark

**Files**:
- `skills/paper-dive/scripts/judgment_benchmark.py` (implementation, 250 LOC)
- `skills/paper-dive/scripts/tests/test_judgment_benchmark.py` (test stubs for tests #10–17)

Implements benchmark harness:

- `build_benchmark_samples(n, collection, teacher_fn, cache_path)`: pulls empirical papers from Chroma, runs real `extract_structure`, gets gold standard via `marvin_launcher`, caches to disk
- `student_fn(extraction, spec)`: applies spec (temperature, prompt_template) to judge an extraction via `judge_extraction()`
- `score_fn(prediction, sample)`: binary match on reliability level
- `teacher_fn(failing_samples, current_spec)`: calls `marvin_launcher` to propose spec edits
- `main()`: wires everything together, records baseline/final metrics via `metrics_registry`

## Testing Status

- **spec_search tests**: 9 tests, all passing ✓
- **logic_auditor tests**: 78 tests (unchanged), all passing ✓
- **judgment_benchmark tests**: stubs written (tests #10–17), ready for implementation details

## Remaining Work

### Step 6: Live Benchmark Run (manual)

On mac-mini with models available:

```bash
cd ~/.agents
./venv/bin/python skills/paper-dive/scripts/judgment_benchmark.py
```

Expected output:
- Baseline accuracy (current defaults)
- Final accuracy (after search)
- Improvement % and iteration count
- Metrics recorded via `metrics_registry`
- Results appended to research report at `docs/research/paper-dive-judgment-spec-search-2026-10-26.md`

**Estimated time**: ~5–10 minutes (8–10 samples, max 4 iterations, 2–3 sec per evaluation)

### Step 7: Research Report (in progress)

**File**: `docs/research/paper-dive-judgment-spec-search-2026-10-26.md`

Template created. To be populated with actual results from step 6.

Includes sections on:
- Experimental setup
- Baseline vs. final accuracy
- Number of iterations and convergence
- Recommended next steps (expand scope, cross-paper-type searches, threshold calibration)
- Wire-in decision deferred

### Step 8: CONTEXT.md (done)

Added glossary entry documenting:
- What specification search is (teacher/student pattern, keep-only-non-regressing loop)
- Use case (judgment extraction tuning)
- Tier (manual/optional, never required by merge gate)

### Step 9: Wire-in Decision (deferred)

**Two options, user to choose**:

**Option A (Ship into defaults)**
- Results show significant accuracy gain
- Update `judge_extraction` calls in logic_auditor.py to use optimized spec
- Include optimized spec in next release
- Document in release notes as improved judgment accuracy

**Option B (Leave as recommendation)**
- Results are marginal or need further validation
- Document optimized spec in `docs/adr/` or `suggestions.md`
- Reference for future #563-shaped work (judgment tuning infrastructure)
- User can opt-in manually by passing `prompt_template=spec[...]` to judge_extraction

**Implementation**: Once user answers, either:
- A: Update `_JUDGMENT_PROMPTS` dict and/or default params in logic_auditor.py
- B: Write ADR entry, no code changes needed (spec is already in the codebase)

## Code Quality

- **No breaking changes**: all modifications additive or parameter-optional
- **Backward compatible**: existing tests unchanged, all pass
- **Composable**: spec_search is a general primitive usable beyond judgment tuning
- **Instrumented**: metrics recorded via `metrics_registry`, caching for reproducibility
- **Documented**: docstrings, CONTEXT.md entry, research template

## Next Ticket

After #563 wire-in decision is made:
- #564 (or similar): expand benchmark to other paper types (survey, benchmark, conceptual)
- Investigate reliability level threshold calibration
- Consider cross-paper-type parameter optimization
