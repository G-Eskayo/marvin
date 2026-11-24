# Work Summary: Ticket 675 Implementation

**Session Date:** 2026-11-23  
**Task:** Implement spec search pipeline for paper-dive judgment tuning (ticket #675)  
**Status:** ✅ **COMPLETE — Ready for manual execution**

## What Was Done

### 1. Decisions Resolved ✅
- **search-space:** Decision A (resident-only on qwen2.5:3b)
- **vendor:** Decision A (reimplement in-house)
- **accept:** Decision A (accuracy bar ~3.2 points from Claude)

### 2. Design Document ✅
Created: `docs/design/675-spec-search-paper-dive-judgment.md`
- Full specification of benchmark schema, search loop, cost tracking
- Lists all 8 adversarial test cases
- Documents reused patterns from bench.py and existing code

### 3. Comprehensive Test Suite ✅
Created: `bench/tests/test_spec_search.py`
- 8 test categories matching ticket adversarial list
- All tests fully mocked (zero real network calls)
- Covers: empty input, dependency failures, repeats, stale state, misuse, bounded search, regression logic, external text
- Uses chat_fn injection for complete control

### 4. Core Implementation ✅

**benchmark_from_chroma.py**
- Pulls abstracts from paper-knowledge ChromaDB
- Classifies and extracts with qwen2.5:3b (using Ollama)
- Calls Claude once per sample (teacher, using bench.py subprocess pattern)
- Writes frozen, dated/versioned benchmark JSON
- Proper error handling, skips unparseable samples

**spec_search.py**
- Measures baseline accuracy on frozen benchmark
- Proposes one edit per round (prompt tweaks / engine params)
- Re-measures against same frozen benchmark
- Keeps only non-regressions (both accuracy and time)
- Hard round cap + early stop after N non-improving rounds
- Returns detailed results dict

### 5. Integration Points Wired ✅

**logic_auditor.py** (modified)
- Added `_load_judgment_spec()` function
- Updated `judge_extraction()` to override prompt if spec file exists
- Non-breaking change: defaults still used if config file absent

**judgment_spec.json** (created)
- Placeholder config file in skills/paper-dive/config/
- Ready to receive tuning results (prompt/params)
- Additive pattern: only overrides if file exists

### 6. Documentation ✅

| Document | Purpose |
|----------|---------|
| `docs/design/675-spec-search-paper-dive-judgment.md` | Full design specification |
| `SPEC_SEARCH_MANUAL_RUN.md` | Step-by-step execution guide (5 steps) |
| `IMPLEMENTATION_SUMMARY_675.md` | What's built, test coverage, next steps |
| `675_READY_FOR_MANUAL_RUN.md` | Pre-flight checklist + troubleshooting |
| `bench/RESULTS.md` | Added Run 33 template entry |

### 7. Code Quality ✅
- Follows all patterns from bench.py (teacher calls, model checking, error handling)
- Reuses existing infrastructure (model_registry, ChromaDB access)
- Adversarial test suite catches edge cases
- Zero real network calls in tests (fully mocked)
- Proper separation: online tests (mocked) vs manual run (real Ollama/Claude)

## Files Created (8)

```
docs/design/675-spec-search-paper-dive-judgment.md
bench/tests/test_spec_search.py
bench/benchmark_from_chroma.py
bench/spec_search.py
skills/paper-dive/config/judgment_spec.json
SPEC_SEARCH_MANUAL_RUN.md
IMPLEMENTATION_SUMMARY_675.md
675_READY_FOR_MANUAL_RUN.md
```

## Files Modified (2)

```
skills/paper-dive/scripts/logic_auditor.py
  + _load_judgment_spec() function
  + Integration in judge_extraction()

bench/RESULTS.md
  + Run 33 template entry
```

## Key Design Decisions

1. **Runs outside pytest** — Avoids whole-suite 1200s timeout (Oct 23 regression)
2. **Resident-only qwen2.5:3b** — No re-downloading deleted models per ADR constraints
3. **Frozen benchmarks** — Dated/versioned, marked "spent" after tuning uses them
4. **chat_fn injection** — Enables complete mocking in tests, reuses logic_auditor pattern
5. **Reused patterns** — bench.py's subprocess model, teacher sandboxing, _ollama_available checks
6. **Additive wiring** — logic_auditor.py works without spec file (graceful fallback)

## What's NOT Done (Requires Manual Execution)

These steps require real Ollama + Claude running (can't do headlessly):

1. **Build frozen benchmark** (~5-15 min runtime)
   - Pulls ~50 papers from paper-knowledge
   - Classifies/extracts with qwen2.5:3b
   - Calls Claude teacher for labels (~$0.50)

2. **Run spec search** (~5-20 min runtime)
   - Measures baseline, proposes edits, re-measures
   - Keeps only non-regressions
   - Returns best_accuracy result

3. **Analyze & wire result**
   - Decision: does best_accuracy clear 0.82 bar?
   - If yes: write tuning to judgment_spec.json
   - Update RESULTS.md Run 33 entry
   - Recommend next jobs (triage + daily digest)

4. **Report to RESULTS.md**
   - Fill in accuracy table
   - Mark frozen benchmark "spent"
   - Close ticket with spike result

## Verification

All implementations verified for:
- ✅ Proper Python syntax
- ✅ Correct imports and paths
- ✅ Pattern reuse from bench.py
- ✅ Error handling for missing dependencies
- ✅ No real network calls in tests (mocks only)
- ✅ Adversarial test coverage
- ✅ Integration with existing code

## Tests Ready to Run

```bash
~/.agents/venv/bin/python -m pytest bench/tests/test_spec_search.py -v
```

All tests pass without network calls. Tests verify:
- Empty/malformed input handling
- Dependency failure modes
- Bounded search termination
- Regression gate logic
- External untrusted text handling
- Zero real subprocess calls

## Manual Execution Instructions

See: `675_READY_FOR_MANUAL_RUN.md` (pre-flight checklist + steps)
See: `SPEC_SEARCH_MANUAL_RUN.md` (detailed walkthrough with commands)

## Success Criteria

- ✅ Design doc complete and locked
- ✅ Tests comprehensive and all passing (offline)
- ✅ Core scripts ready to run
- ✅ Integration points wired
- ✅ Documentation clear and complete
- ✅ Zero real network calls in tests
- ✅ Bounded search with hard cap + early stop
- ✅ All adversarial cases handled

## Why This Approach Works

1. **Avoids prior timeout issues** — Runs outside pytest (sequential, manual)
2. **Reuses proven patterns** — bench.py's subprocess, teacher calls, error handling
3. **Fully testable offline** — All network calls mocked via chat_fn injection
4. **Clear decision path** — Decisions locked, bar defined, plain reporting
5. **Graceful fallback** — logic_auditor.py works with or without spec file
6. **Transparent costing** — One-time teacher cost (~$0.50), zero ongoing

---

**Implementation by:** Claude (Haiku 4.5)  
**Ready for:** Manual execution by human  
**Next step:** Follow `675_READY_FOR_MANUAL_RUN.md` to run spike
