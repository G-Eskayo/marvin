# AC1 Implementation: Fallback Builder Gate

## Summary

Implements the fallback builder gate for morning brief, daily digest, and research colony (ADR 0067). Both machines can now independently decide whether to build, based on:
1. Local wall-clock time (primary's usual schedule + grace period)
2. Live SSH check of whether primary has already produced

The primary (Mac Mini) always builds; the standby (MacBook) only builds if past the deadline and the primary hasn't produced.

## Changes Made

### lib/brief_fallback.py
- Swapped `read_remote()`'s primary lookup from `remote_devices()` → `remote_macs()` (exclude Linux)
- Added `_tailscale_online_hosts()` check before SSH (fail gracefully if unreachable)
- Wrapped `should_run()`'s `registry_id()` call to fail open: if identity lookup fails, fallback runs at/after deadline
- Simplified `_infer_remote_path()`: removed shlex/$HOME-expansion complexity, just builds simple paths
- Removed unused `import shlex`

### lib/morning_brief.py::write()
- Changed idempotency guard from `path.exists()` → `brief_fallback.produced(path)` (same logic as digest gate)
- Made writes atomic: temp file + `rename()` for both brief and `.built-by` sidecar

### skills/improve/scripts/daily_digest.py::main()
- Added `should_run()` gate before context assembly (skips if before deadline)
- Added pre-write recheck immediately before `OUT_FILE.write_text()` (TOCTOU race safety)

### skills/research-colony/scripts/run_colony.py::main()
- Added `should_run()` gate before `source_monitor.main()` (skips if before deadline)

### skills/research-colony/scripts/research_digest.py::generate()
- Changed existence check from `out_path.exists()` → `brief_fallback.produced(out_path)`
- Added pre-launch recheck immediately before `marvin_launcher.launch()` (TOCTOU race safety)

### Plist Files
Renamed all log paths to `.log` and `-error.log` convention (was `.out.log` / `.err.log`):
- `config/launchd/com.marvin.morning-brief-fallback.plist` → morning-brief-fallback.log / -error.log
- `skills/improve/com.marvin.daily-digest-fallback.plist` → daily-digest-fallback.log / -error.log
- `skills/research-colony/com.marvin.research-colony-fallback.plist` → 10:00 schedule, research-colony-fallback.log / -error.log

### lib/cron_health.py
Added JOBS entries:
- `daily-digest-fallback` (09:30)
- `research-colony-fallback` (10:00)
- `morning-brief` (09:45, previously untracked)
- `morning-brief-fallback` (10:45)

All with matching log paths from the updated plists.

### Test Coverage
- `skills/research-colony/scripts/tests/test_research_digest.py` (new file)
  - Tests `should_run()` gate and pre-launch recheck in `generate()`
- `skills/improve/scripts/tests/test_daily_digest.py` (appended)
  - Tests `should_run()` gate and pre-write recheck in `main()`

## Decisions

- [ ] **cross_machine_merge.py** — left untouched pending the `retire-cross-machine-merge` decision (ADR 0066). This PR does not touch it.

## Blockers

**Manual Post-Merge Steps** (cannot be automated):

1. **On Mac Mini**:
   ```bash
   launchctl bootstrap ~/Library/LaunchAgents \
     ~/.agents/config/launchd/com.marvin.morning-brief.plist \
     ~/.agents/skills/research-colony/com.marvin.research-colony-fallback.plist \
     ~/.agents/skills/improve/com.marvin.daily-digest-fallback.plist
   ```

2. **On MacBook**:
   ```bash
   launchctl bootstrap ~/Library/LaunchAgents \
     ~/.agents/config/launchd/com.marvin.morning-brief-fallback.plist
   ```

AC1 remains inactive until these `launchctl bootstrap` commands run on both physical machines, even after this PR merges. The fallback system requires the plists to be loaded into launchd.

## Test Plan

- [x] `lib/tests/test_brief_fallback.py` — all existing tests pass with modified logic (remote_macs, online check, error handling)
- [x] `lib/tests/test_morning_brief.py` — existing tests pass; new `produced()`-based idempotency works
- [x] `skills/improve/scripts/tests/test_daily_digest.py` — new tests for should_run gate and pre-write recheck
- [x] `skills/research-colony/scripts/tests/test_research_digest.py` — new tests for should_run gate and pre-launch recheck
- [x] `lib/tests/test_health_checks.py` — existing coverage; JOB_PLACEMENT dict includes new fallback jobs

Run full suite:
```bash
~/.agents/venv/bin/python -m pytest lib/tests/ skills/improve/scripts/tests/ skills/research-colony/scripts/tests/ -v
```
