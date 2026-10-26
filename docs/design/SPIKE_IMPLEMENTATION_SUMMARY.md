# Local Coding Spike — Implementation Summary

**Status:** Code complete and tested. Ready for Mac Mini execution.

**Time to spike run:** ~5 minutes setup + ~15 minutes measurement (10 runs @ 1–2 min each)

## What Was Built

### 1. Tests (14 adversarial, all passing)
- **File:** `bench/lib/tests/test_local_coding_spike.py`
- **Coverage:** Ollama availability, opencode in PATH, sudo degradation, PR selection, worktree cleanup, token tracking, empty/large diffs, concurrent safety
- **Status:** ✅ All 14 tests pass

### 2. Core Modules

#### `bench/lib/energy_apple.py`
- **Purpose:** Measure CPU/GPU power via `powermetrics` subprocess
- **Key:** Degrades gracefully to None + reason if sudo unavailable
- **Tests:** Tests 1, 3, 12 covered

#### `bench/local_coding_spike.py` (main)
- **Functions:**
  - `_ollama_available()` / `_opencode_available()` — Preflight checks
  - `preflight_checks()` — Combined dependency check
  - `select_tickets()` — Query GitHub for small PRs (docs:/fix:/test: prefix)
  - `create_historical_worktree()` — Context manager for git worktree at base_sha
  - `run_opencode()` — Execute opencode, apply diff, track tokens
  - `run_gates()` — Run real gate sequence (measure + metrics + test_change + review)
  - `run_spike()` — Orchestrate full sweep, save JSON, append RESULTS.md
  - `append_run_summary()` — Format and append Run 31 to RESULTS.md

### 3. Gate Sequence (Matching Production)

The spike runs the exact gate logic from `sandbox_orchestration.execute_ticket`:

```python
1. build_type_measure.measure() + metrics_registry.compare()  # Tests pass?
2. test_change_rule.check_worktree()                          # Code changed ⟹ test changed?
3. code_review_gate.review_worktree()                         # Review clean?
```

Each produces: `gate_verdict: "PASS"|"FAIL"` + `gate_reason: str`

### 4. Data Model (JSON output)

Per run:
```json
{
  "ticket_number": 123,
  "ticket_title": "fix: handle edge case",
  "model": "qwen2.5:7b",
  "timestamp": 1729978800.123,
  "opencode": {
    "gate_verdict": "FAIL",
    "gate_reason": "no changes produced",
    "tokens": 0,
    "tokens_approx": true,
    "wall_s": 1.5,
    "error": null
  },
  "gates": {
    "gate_verdict": "PASS",
    "gate_reason": "all gates passed",
    "metrics": {...},
    "tests": {...},
    "review": {...}
  },
  "energy": {
    "energy_j": 45.2,
    "reason": null
  }
}
```

Saved to: `bench/results/local-coding-spike-<timestamp>.json`

### 5. Documentation

- **`docs/design/pipeline-g-eskayo-marvin-674.md`** — Full design (north-star fit, tests, decision)
- **`docs/design/pipeline-g-eskayo-marvin-674-tasks.md`** — Task tracking and implementation status
- **`bench/SPIKE_SETUP.md`** — Step-by-step setup guide for Mac Mini
- **`bench/RESULTS.md`** — Will be appended with Run 31 after execution

## Critical Design Decisions

1. **Reuses, not reinvented:** Calls the real gate functions directly, not a fake proxy
2. **Graceful degradation:** Every dependency loss (Ollama, opencode, sudo) becomes a logged reason, not a crash
3. **Historical git worktrees:** Separate `create_historical_worktree()` from live ticket branches (sandbox_orchestration's path)
4. **Token approximation:** Falls back to diff-length heuristic with explicit `tokens_approx: true` flag
5. **Atomic RESULTS.md:** Single append at the very end of the sweep, no partial writes

## What's NOT Implemented

- Actual sweep execution (blocked on Mac Mini setup)
- Energy sampling during opencode (EnergySampler is built but requires passwordless sudo setup)
- Interaction with real tickets (PR fetch, etc. are mocked in tests; spike uses real `gh` API)

## Setup Required (Mac Mini only)

1. `pip install anthropic` → opencode binary
2. `ollama pull qwen2.5:7b && ollama pull qwen2.5:14b`
3. `echo "$(whoami) ALL=(ALL) NOPASSWD: /usr/bin/powermetrics" | sudo tee /etc/sudoers.d/powermetrics`

See `bench/SPIKE_SETUP.md` for detailed steps.

## Next: Execution Plan

Once setup is done on the Mini:

```bash
cd ~/.agents
python3 bench/local_coding_spike.py
```

This will:
- Take ~15 minutes (5 tickets × 2 models × 1–2 min per run)
- Output: `bench/results/local-coding-spike-<stamp>.json` + `bench/RESULTS.md` "## Run 31" section
- Produce findings on which ticket kinds (docs/fix/test) pass the real gate with local models

## Verification Checklist (post-spike)

- [ ] Results file created in `bench/results/`
- [ ] RESULTS.md appended with Run 31 section
- [ ] No real tickets had labels/comments/claims touched
- [ ] All worktrees cleaned up (no orphaned paths)
- [ ] Energy measurements captured or reason logged
- [ ] Tokens tracked (approx labeled if fallback used)

---

**Built by:** MARVIN (Claude Code)
**Date:** 2026-10-26
**Commit:** Will be auto-merged by pipeline after spike runs
