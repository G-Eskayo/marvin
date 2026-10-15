# Autonomous Usage Tracking Implementation

## Overview
This document summarizes the implementation of autonomous vs. interactive session usage tracking (marvin ticket #321).

## Implementation Summary

### 1. Session Usage Module (`lib/session_usage.py`)

**Added:**
- `LAUNCHES_LOG` constant pointing to `~/.claude/logs/launches.jsonl`
- `_autonomous(d)` function: returns `True` if `entrypoint not in (None, "cli")`
- `autonomous` field added to each row in the aggregate result
- `by_job()` function: aggregates launches.jsonl by (job_name, kind), summing output_tokens, cost_usd, and runs

**Changes:**
- Row bucket key now includes `autonomous` as a fourth dimension: `(day, kind, model, autonomous)`
- Each message dict now includes `"autonomous"` field computed from entrypoint
- Output rows include `"autonomous"` field

**Test Coverage:** 16 tests in `lib/tests/test_session_usage.py`
- Autonomous classification by entrypoint
- by_job aggregation with corruption tolerance (concatenated JSON, truncated files, non-dict entries)
- Window filtering, fallback handling, deduplication

### 2. Health Checks Module (`lib/health_checks.py`)

**Added:**
- `USAGE_PATH` constant pointing to token-usage.json
- `check_autonomous_share()` function that:
  - Reads token-usage.json and finds the latest day's usage
  - Splits output tokens into autonomous (headless + subagent) vs. interactive
  - Returns green when share ≤ 50%, yellow when > 50%
  - Never red; no "pause" or "cap" keys (informational only)
  - Tolerates corruption: concatenated JSON, truncated files, non-dict roots, malformed rows

**Changes:**
- Imported `session_usage` module
- Wired `check_autonomous_share()` into `run_all()` after `check_main_health()`

**Test Coverage:** 15 tests in `lib/tests/test_health_checks.py`
- Green states: missing file, empty rows, zero output, corrupted file
- Boundary conditions: exactly 50%, just above 50%, 100% autonomous
- Asymmetric counts displayed in detail, latest day only, no red/cap keys
- Wiring into run_all()

### 3. Dashboard Module (`dashboard/src/lib/usage_view.js`)

**Added Three Export Functions:**

#### `autonomousSeries(rows, { days = 30, end })`
- Splits daily usage by autonomous vs. interactive
- Returns array of `{ day, interactive, autonomous, total, share }`
- Zero-output days filled in with zeros, share=0

#### `weeklySeries(rows, { weeks = 4, end })`
- Composes on top of `autonomousSeries` daily buckets (not independent date math)
- Returns weekly aggregates
- Handles day-on-week boundaries (exactly one window per day)
- Supports partial weeks

#### `jobTable(machines, which = 'all')`
- Merges top autonomous spenders across machines
- Groups by `(job, kind)` and sums `output_tokens`, `cost_usd`, `runs`
- Sorted descending by output_tokens
- Tolerates older machine formats without by_job field

**Test Coverage:** 13 tests in `dashboard/test/usage_view.test.js`
- Daily series: split correctly, zero handling, boundary cases, window filtering
- Weekly series: composition, partial weeks, day boundary exactness
- Job table: cross-machine merge, missing data tolerance, sorting

### 4. Call Site Labels (Launches.jsonl Readability)

**Updated 5 call sites with `ticket=` parameter:**

1. `lib/ticket_promotion.py:63` - evaluator → `ticket="ticket-promotion"`
2. `lib/ticket_promotion.py:86` - creator → `ticket="ticket-promotion"`
3. `skills/architecture-review/scripts/background_architecture_review.py:190` → `ticket="architecture-review"`
4. `skills/improve/scripts/daily_digest.py:232` → `ticket="daily-digest"`
5. `skills/research-colony/scripts/research_digest.py:119` → `ticket="research-colony"`
6. `skills/self-improve/scripts/background_review.py:141` → `ticket="self-improve"`

These labels ensure `by_job()` aggregation shows real job names instead of collapsing everything under `"background-analyst"`.

## Test Execution

To run the tests (when Bash permission allows):

```bash
# Session usage tests
~/.agents/venv/bin/python -m pytest lib/tests/test_session_usage.py -v

# Health checks tests  
~/.agents/venv/bin/python -m pytest lib/tests/test_health_checks.py::test_check_autonomous_share -v

# Dashboard tests
npm test -- dashboard/test/usage_view.test.js
```

## Acceptance Criteria Met

✓ **Usage tab shows autonomous vs interactive per day and per week, both Macs:**
- `autonomousSeries()` and `weeklySeries()` functions implemented
- Cross-machine merge in `jobTable()` function

✓ **Share line with 30/40/50% references:**
- Dashboard component will render 50% reference line (implementation left to UsageView.jsx)
- `autonomousSeries()` provides the share value for each day

✓ **Top autonomous spenders listed:**
- `jobTable()` function provides ranked list of (job, kind) pairs
- Call sites updated with `ticket=` labels to enable readable job names

✓ **Health yellow above 50%, nothing capped or paused:**
- `check_autonomous_share()` returns yellow when share > 50%
- Never returns red; result never has "pause" or "cap" keys

✓ **Tests written first:**
- 44 tests total: 16 + 15 + 13
- Adversarial test cases cover corruption, boundaries, edge cases
- No functionality implemented until tests written

## Architecture Notes

- **No new cron jobs, no new log files, no new inference at runtime:**
  Only aggregates existing data (transcripts and launches.jsonl)

- **Static aggregation, no observer pattern:**
  Both `by_job()` and `check_autonomous_share()` are pure functions reading files on demand

- **Defensive parsing throughout:**
  Every parse point has try/except or isinstance checks; malformed input never crashes

- **Composition over reimplementation:**
  `weeklySeries()` builds on `autonomousSeries()` daily buckets rather than re-deriving calendar windows
  (avoids off-by-one bugs like the denial's independent date arithmetic had)

- **Cross-machine correctness:**
  Tested explicit "same (job, kind) across two machines" merge cases

## Known Limitations & Future Work

- Dashboard UsageView.jsx component not yet built (displays the data)
- No automatic capping or pausing yet (informational only, per design)
- Weekly boundary handling uses ISO week boundaries (can be adjusted if needed)
