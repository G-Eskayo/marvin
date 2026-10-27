# Local Coding Spike Implementation Plan

## Overview

This document describes the implementation of a local coding assistant spike that measures whether small real-world tickets can be solved efficiently using a local open-source model (Ollama) instead of cloud Claude.

## Completed Implementation

### 1. Task Definitions (task-018 through task-022)

Created 5 real-ticket tasks from recent merged PRs:

| Task ID | PR | Title | Type |
|---------|----|----|---|
| task-018 | #655 | Flaky dashboard CI: docs test git race | sync/test fix |
| task-019 | #654 | Main is falsely red: du priority test | test fix |
| task-020 | #639 | Docs tab: find private instance | path/config fix |
| task-021 | #627 | docs: record Vitals v4 decisions | docs only |
| task-022 | #541 | Dashboard crash: electron-builder null | publish fix |

Each task includes:
- `task.json` with schema: type="real-ticket", pr_number, repo, base_sha, prompt_file
- `prompt.md` with the original PR description as the task prompt
- base_sha pointing to the commit before the fix (for checkout)

### 2. Library Modules

#### `bench/lib/build_type_measure.py`
Captures baseline and after-task code quality metrics:
- Type checking (mypy)
- Linting (pylint)
- Test results (pytest)
- Wall time for each check
- Error counts and messages

**Tests:** 7 tests covering empty dirs, syntax errors, valid code, timeouts, serialization, state preservation, consistency.

#### `bench/lib/energy_apple.py`
Measures power consumption on Apple silicon using `powermetrics`:
- Runs sampling in background thread during subprocess execution
- Parses CPU/GPU power samples
- Converts to joules and watt-hours
- Returns None with error reason if unavailable (graceful degradation)

**Tests:** 8 tests covering data structure, simple/failing commands, timeouts, working dir, robustness, error handling.

#### `bench/lib/metrics_registry.py`
Compares baseline vs after-task metrics to determine if a solution is correct:
- Type check regression: errors should not increase
- Lint regression: warnings allowed to increase by ±5%
- Test regression: if baseline passed, after-task must pass
- Build stability: no new failures

**Tests:** 8 tests covering identical metrics, regressions, improvements, multiple failures, small increases.

#### `bench/lib/evidence_capture.py`
Captures code changes before and after a task:
- Git status (modified/untracked files)
- Git diff (actual changes)
- Changed files list
- Returns None if not a git repo

**Tests:** 6 tests covering non-git dirs, clean/dirty repos, new files, serialization, truncation, robustness.

### 3. Runner Script

`bench/run_local_coding_spike.py` orchestrates the spike:

```python
for each real-ticket task:
    1. Create git worktree at base_sha
    2. measure_build() → baseline metrics
    3. Run opencode headlessly with prompt
       - With energy sampling (if available)
    4. measure_build() → after-task metrics
    5. compare_metrics() → gate verdict (passed/reason)
    6. capture_snapshot() → code evidence
    7. Collect results to JSON
    8. Clean up worktree
```

Output: `results/local-spike-<timestamp>.json` with per-task results.

### 4. Test Coverage

Total: 29 tests across 4 test modules

| Module | Tests | Coverage |
|--------|-------|----------|
| test_build_type_measure.py | 7 | baseline, error detection, state preservation |
| test_energy_apple.py | 8 | measurement, timeouts, graceful failure |
| test_metrics_registry.py | 8 | gate logic, regressions, improvements |
| test_evidence_capture.py | 6 | git snapshot, serialization, robustness |

Tests use real subprocess calls, real git operations, and real code samples. Mocking is used only where external dependencies (opencode, large models, powermetrics) genuinely can't be assumed present.

## Execution Plan

### Prerequisites

1. **Ollama model:** `ollama pull qwen2.5:7b` (or your chosen model)
2. **Optional energy measurement:** Requires `sudo` and `powermetrics` available (macOS only)
3. **Dependencies:** mypy, pylint, pytest for baseline measurement

### Running the Spike

```bash
# Basic run (no energy measurement)
python3 bench/run_local_coding_spike.py --skip-energy

# With energy measurement
python3 bench/run_local_coding_spike.py

# Custom model
python3 bench/run_local_coding_spike.py --model qwen2.5:14b

# Specific tasks
python3 bench/run_local_coding_spike.py --tasks task-018,task-020,task-022
```

### Expected Output

Results saved to `bench/results/local-spike-<timestamp>.json`:

```json
{
  "timestamp": "20261026-172500",
  "model": "qwen2.5:7b",
  "measure_energy": true,
  "results": [
    {
      "task_id": "task-018",
      "pr_number": 655,
      "passed": true/false,
      "gate_verdict": "reason...",
      "wall_s": 45.2,
      "energy": {
        "joules": 234.5,
        "wh": 0.065,
        "duration_s": 45.2
      },
      "baseline": { ... build measures ... },
      "after_task": { ... build measures ... },
      "evidence": {
        "git_status": "...",
        "git_diff": "...",
        "changed_files": [...]
      }
    }
  ]
}
```

## Expected Findings

### Viability Signals

A local model would be viable for a "small tickets go local" lane if:
- ✓ Majority of tasks pass gate verdict (correct solution by metrics)
- ✓ Majority of tasks complete within reasonable time (< 2 min for small fixes)
- ✓ Energy cost is significantly lower than cloud (< 1 Wh vs cloud ~0.5–2 Wh)
- ✓ Model size vs quality trade-off is favorable (7B fast + correct > 70B+ slow)

### Non-Viable Signals

Would argue against a local lane if:
- ✗ Most tasks fail gate verdict (incorrect solutions)
- ✗ Timeouts or crashes on half+ of tasks
- ✗ Energy cost is same or higher than cloud (no efficiency gain)
- ✗ Latency so high it offsets any other advantage

## Caveats

1. **Model size tested:** qwen2.5:7b (or specified model). Results may not generalize to other models.
2. **Single-run noise:** Each task runs once. No repeat/variance analysis (add --repeat for that).
3. **Machine-specific:** Results are specific to the host Mac (CPU, RAM, thermal state).
4. **Small sample:** 5 tasks is too small to generalize to "all small tickets." Treat as spike/proof-of-concept.
5. **Energy measurement:** Requires sudo and macOS; skipped on other platforms with --skip-energy.
6. **Gate verdict:** Compares build metrics (type check, lint, tests). Does NOT check semantic correctness or code quality beyond what tests capture.

## Related

- `bench.py`: Existing harness for cloud Claude comparison
- `select_model.py`: Model selection tool (uses same scoring as this spike)
- `RESULTS.md`: Historical results log (append spike run when executed)
