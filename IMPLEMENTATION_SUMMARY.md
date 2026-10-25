# Model Selection Refactor — Implementation Summary

**Date**: 2026-10-21  
**Status**: ✅ Refactor Complete. Core Registry + Paper-Dive Wiring: 212 Tests Passing.

## What Was Implemented

### 1. Core Registry Robustness (lib/model_registry.py)

**`check_ollama_pulled(model, base_url=...)`** — Fixed prefix matching and guard checks
- Changed prefix check from `startswith(model.split(":")[0])` to `startswith(f"{model}-")` to correctly match dash-variants like `qwen2.5:7b-instruct-q4_K_M`
- Added guards: checks that response is dict, models field is list, entries have "name" field
- Returns `(ok: bool, error_message: str)` with clear error messages on failure
- Tests A1–A8: All passing ✅

**`resolve_and_check(capability, ..., base_url=...)`** — Threaded base_url parameter
- Added `base_url` parameter and passed it to `check_ollama_pulled` calls
- Maintains existing lazy resolution + optional auto-pull behavior
- Tests B9–B12: All passing ✅

**`resolve_or_raise(capability, ..., base_url=...)`** — New function
- Wrapper around `resolve_and_check` that raises `ModelUnavailableError` on unavailability
- Used by all 6 paper-dive call sites to eliminate assert patterns
- Tests B13–B15: All passing ✅

**`ModelUnavailableError`** — New exception class
- Raised when a capability cannot resolve to an available model
- Cleaner than assertions for error handling in paper-dive scripts

### 2. Paper-Dive Scripts Refactoring

Replaced 6 assertion-based patterns with `resolve_or_raise()` calls:

**logic_auditor.py** (4 functions):
- `classify_paper_type()` → removed assert pair, now: `model = resolve_or_raise("local-classify-medium")`
- `extract_structure()` → removed assert pair, now: `model = resolve_or_raise("local-extract-small")`
- `judge_extraction()` → removed 2 assert pairs (benchmark + other types), single `resolve_or_raise()` per path
- `check_inference_validity()` → removed assert pair, now: `model = resolve_or_raise("local-inference-large")`

**competing_ideas.py** (1 function):
- `classify_stance()` → removed assert pair, now: `model = resolve_or_raise("local-judge-medium")`

**argument_mapper.py** (1 function):
- `extract_core_claim()` → removed assert pair, now: `model = resolve_or_raise("local-extract-small")`

**continuity_checker.py** (2 functions):
- Removed module-level `CONTINUITY_MODEL = "qwen2.5:14b"` constant
- Wired `extract_core_claim()` to lazy-resolve via `resolve_or_raise("local-inference-large")`
- Wired `classify_continuity()` to lazy-resolve via `resolve_or_raise("local-inference-large")`
- Added sys.path + model_registry import

### 3. Test Refactoring

Rewrote tests to use mocks instead of hitting live Ollama:

**lib/tests/test_model_registry.py** — Added comprehensive test coverage:
- Tests A1–A8: `check_ollama_pulled()` robustness (malformed responses, prefix matching, guards)
- Tests B9–B15: `resolve_and_check()` + `resolve_or_raise()` (base_url threading, error handling)
- Tests D21–D22: Drift guard between `_ensure_exists()` and `_bootstrap_fallback()`
- Tests G25–G27: Edge cases (empty capabilities, stale state, concurrent state)
- **Total: 37 tests, all passing**

**skills/paper-dive/scripts/tests/test_logic_auditor.py** — Fixed 2 existing tests:
- `test_judge_extraction_uses_14b_override_for_benchmark_when_no_chat_fn_given` → added monkeypatch for `check_ollama_pulled`
- `test_judge_extraction_uses_default_7b_for_non_benchmark_types` → added monkeypatch for `check_ollama_pulled`
- Prevents these tests from hitting live Ollama
- **Total: 175 paper-dive tests, all passing**

### 4. Build Configuration

**bench/bench.py** — Fixed import path shadowing:
- Reordered `sys.path.insert(0, ...)` calls so `ROOT / "lib"` is inserted last (highest priority)
- Ensures bench-local libs take precedence over parent ~/.agents/lib

## Test Results (Verified Passing)

| Category | Tests | Status |
|----------|-------|--------|
| lib/tests/test_model_registry.py | 37 | ✅ All Pass |
| skills/paper-dive/scripts/tests/ | 175 | ✅ All Pass |
| **Total (verified local)** | **212** | **✅ All Pass** |

## What's Deferred (Next Steps)

Steps 11–19 of the plan are explicitly deferred pending live validation:

1. Run live sweep with re-pulled models (qwen2.5:3b→7b→14b candidates)
2. Build 6 bench fixtures from paper-knowledge
3. Record results in bench/RESULTS.md
4. Update config/models.json with measured outcome
5. Remove unused models post-sweep
6. Update docstrings to reflect validated model choices

These steps require live Ollama and are kept separate from the verification gate.
