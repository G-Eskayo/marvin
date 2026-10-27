# Local Coding Spike Implementation Summary

## Completion Status: ✅ COMPLETE AND READY FOR EXECUTION

All infrastructure for the local coding assistant spike has been implemented, tested, and documented. The system is ready to run on a Mac mini with Ollama + powermetrics.

## Deliverables

### 1. Real-Ticket Task Definitions (5 tasks)
- **task-018-docs-test-race** (PR #655) — Flaky CI race condition fix
- **task-019-du-priority-nice** (PR #654) — Test priority measurement fix  
- **task-020-docs-tab-instance** (PR #639) — Path resolution fix
- **task-021-vitals-v4-docs** (PR #627) — Documentation task
- **task-022-dashboard-crash-fix** (PR #541) — Publish error handling

Each task includes:
- `task.json` with schema: type="real-ticket", pr_number, repo, base_sha
- `prompt.md` with original PR description as task prompt
- Base SHA pointing to state before the fix

### 2. Library Modules (4 modules)

#### `bench/lib/build_type_measure.py` (BuildMeasure class)
Captures baseline and after-task code quality metrics:
- Type checking via mypy
- Linting via pylint  
- Test results via pytest
- Wall time tracking
- Serialization to dict

#### `bench/lib/energy_apple.py` (EnergyMeasure class)
Measures power consumption on Apple silicon:
- Background powermetrics sampling during subprocess execution
- CPU/GPU power data parsing
- Energy conversion (joules ↔ watt-hours)
- Graceful degradation if powermetrics unavailable

#### `bench/lib/metrics_registry.py` (GateVerdict class)
Compares baseline vs after-task metrics:
- Type check regression detection
- Lint warning threshold (±5% allowed)
- Test regression detection
- Build stability checks
- Pass/fail verdict with detailed reason

#### `bench/lib/evidence_capture.py` (CodeSnapshot class)
Captures code changes before and after:
- Git status (modified/untracked files)
- Git diff (actual code changes, truncated to 10KB)
- Changed files list
- Returns None for non-git repos (graceful)

### 3. Comprehensive Test Suite (29 tests)

| Module | Tests | Scenarios |
|--------|-------|-----------|
| test_build_type_measure.py | 7 | Empty dirs, syntax errors, valid code, timeouts, serialization, state preservation |
| test_energy_apple.py | 8 | Data structure, command execution, timeouts, working dirs, robustness, error handling |
| test_metrics_registry.py | 8 | Identical metrics, regressions, improvements, multiple failures, threshold logic |
| test_evidence_capture.py | 6 | Non-git dirs, clean/dirty repos, new files, serialization, truncation |

All tests use real subprocess calls, real git operations, and real code samples. External dependencies (opencode, models, powermetrics) are mocked where they can't be assumed present.

### 4. Runner Script: `bench/run_local_coding_spike.py`

Orchestrates the end-to-end spike execution:

```
For each real-ticket task:
  1. Create git worktree at base_sha
  2. Measure baseline (build metrics)
  3. Run opencode headlessly with task prompt
     - Optional energy sampling via powermetrics
     - Configurable timeout (default 600s)
  4. Measure after-task (build metrics)
  5. Compare metrics → gate verdict (passed/reason)
  6. Capture code evidence (git snapshot)
  7. Collect results to JSON
  8. Clean up worktree
```

Output: `results/local-spike-<timestamp>.json` containing:
- Per-task gate verdict (pass/fail + reason)
- Wall time and energy consumption
- Baseline and after-task metrics
- Code evidence (git status/diff)

Summary table printed to stdout showing:
- Task ID, PR number, pass/fail, wall time, energy

### 5. Documentation

- **SPIKE_PLAN.md** — Complete implementation plan with execution instructions
- **RESULTS.md** — Appended spike section explaining status and how to run
- **This file** — High-level summary

## Execution Instructions

### Prerequisites
```bash
# Install Ollama and pull a model
ollama pull qwen2.5:7b

# Optional: verify build tools available
which mypy pylint pytest
```

### Run the Spike
```bash
cd bench

# Basic run (no energy measurement)
python3 run_local_coding_spike.py --skip-energy

# With energy measurement (requires sudo)
python3 run_local_coding_spike.py

# Custom model
python3 run_local_coding_spike.py --model qwen2.5:14b

# Specific tasks only
python3 run_local_coding_spike.py --tasks task-018,task-020
```

### Expected Output
Results JSON:
```
results/local-spike-20261026-173500.json
```

Summary printed to console:
```
Task                  PR     Pass   Wall   Energy
task-018-docs-test-race 655    True   42.3s  0.065Wh
task-019-du-priority-nice 654    True   35.1s  0.052Wh
...
Passed: 5/5
```

## Success Criteria

### Viable for "Small Tickets Go Local" Lane
- ✓ Majority of tasks pass gate verdict (correct solutions)
- ✓ Complete within reasonable time (< 2 min for small fixes)
- ✓ Energy cost significantly lower than cloud (< 1 Wh)

### Not Viable
- ✗ Most tasks fail gate verdict
- ✗ Timeouts or crashes on many tasks
- ✗ Energy same/higher than cloud
- ✗ Latency erases efficiency gains

## Important Caveats

1. **Model-specific** — Results for qwen2.5:7b; other models may differ
2. **Single-run** — No variance analysis; add `--repeat` for statistical rigor
3. **Host-specific** — Results bound to Mac mini's hardware/thermal state
4. **Small sample** — 5 tasks insufficient to generalize; proof-of-concept only
5. **Energy requires sudo** — Skipped if powermetrics unavailable
6. **Gate checks build, not semantics** — Measures type/lint/tests only

## Technical Debt & Extensions

### Possible Improvements
- Add `--repeat N` for variance analysis (requires repeat runs)
- Add semantic correctness grading (LLM judge on code quality)
- Extend to more task types (docs, architecture, refactoring)
- Compare energy against cloud Claude baseline
- Profile memory consumption alongside power
- Test with different model sizes/architectures

### Known Limitations
- No offline mode detection (assumes Ollama available)
- Mypy/pylint/pytest required but not installed by default
- Energy measurement macOS-only
- Git worktree cleanup may fail on permission issues (checked but not fatal)

## Related Files

- `bench/SPIKE_PLAN.md` — Full implementation details and plan
- `bench/RESULTS.md` — Historical results log (appended spike section)
- `bench/run_local_coding_spike.py` — Main runner script
- `bench/lib/*.py` — Library modules
- `bench/lib/tests/test_*.py` — Comprehensive test suite
- `bench/tasks/task-0{18,19,20,21,22}/` — Real-ticket task definitions

## Next Steps

1. **Mac mini setup:** Install Ollama, pull qwen2.5:7b model
2. **Run the spike:** Execute `python3 bench/run_local_coding_spike.py`
3. **Analyze results:** Review JSON output and summary table
4. **Interpret findings:** Check gate verdicts, wall times, energy consumption
5. **Document findings:** Append results to `bench/RESULTS.md` with findings/caveats

All infrastructure is complete and ready. The spike can run immediately on a properly configured Mac mini.
