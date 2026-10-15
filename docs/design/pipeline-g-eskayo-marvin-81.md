## North-star fit

**Reuses before adding anything new — re-verified against the code, not the previous design doc's claims.** I read every file this ticket touches, fresh, in this pass:
- `lib/session_usage.py`, `dashboard/src/lib/usage_view.js`, `dashboard/src/components/UsageView.jsx`: the full feature — `autonomousSeries`/`weeklySeries`/`jobTable`, the day/week split, the 30/40/50% dashed reference lines, the top-spenders table — is **already built and correct** in this worktree's uncommitted diff. All acceptance criteria (day/week split both Macs, share line with references, top spenders, tests-first) are already met by code I just read end-to-end.
- `lib/health_checks.py`'s `check_autonomous_share()`: already fixed to split by the `autonomous` field (not re-derived from `kind`), never red, no cap key — correct.
- `lib/ticket_promotion.py` + `lib/tests/test_ticket_promotion.py`: the `ticket="ticket-promotion"` label and its regression test already exist (lines 64/87 and 166-202).

**Correction to the previous design doc, not to the ticket:** that doc is stale. It describes three bugs — a `write_text(mode="a")` `TypeError` in `test_session_usage.py`, a self-defeating `"100" not in detail` assertion in `test_health_checks.py`, and a missing `autonomousSeries`/`weeklySeries`/`jobTable` import in `usage_view.test.js` — as the current state of the worktree. **I read all three files directly: none of these bugs exist anymore.** `test_session_usage.py`'s `by_job` fixtures all use a single `write_text("\n".join(lines) + "\n")` call, no `mode=` kwarg, anywhere. `usage_view.test.js` line 2 already imports all three new functions. `test_check_autonomous_share_uses_latest_day_only` already asserts `"0 interactive" in result["detail"]`, not the broken substring check. These were fixed in a later iteration than the one that produced the regression metrics I was handed (which, per the issue's own comment thread, is the iteration that preceded "Verification passed… PR #359" — a *later* denial, for a *different* reason). Repeating that doc's plan would mean re-fixing bugs that don't exist — pure wasted tokens, the opposite of north star 1.

**What's actually still broken, found by reading forward from the PR #359 denial comment, not by re-deriving the old doc's analysis:** the denial's failing test (`test_run_all_includes_autonomous_share_check`, now renamed `test_check_autonomous_share_wired_into_run_all`) crashed with `json.decoder.JSONDecodeError: Extra data`, preceded by `[ticket-pipeline] gh issue list failed: gh is disabled in tests`. I traced this to a real, still-present gap:
- `lib/health_checks.py:run_all()` unconditionally calls `record_anomaly_metrics(results)` (line 1427), which calls `mr.latest("health-monitor")`, `mr.record("health-monitor", numeric)`, `mr.compare(...)` — i.e. `metrics_registry.py`'s real `~/.agents/bench/metrics/health-monitor.<machine>.json`.
- `lib/tests/conftest.py` has an autouse isolation fixture for **every other** side-effecting module (`failure_breaker`, `board_registry`, `job_events`, `marvin_launcher`, `project_profile`, `ticket_stages`) — but **none for `metrics_registry`**. The one existing test that calls `hc.run_all()` (`test_run_all_includes_parallel_dispatch_check`) only survives because it happens to manually mock `hc.mr.latest/record/compare`. The ticket #81 test added for `check_autonomous_share` does **not** follow that convention — it only mocks `USAGE_PATH`/`session_usage.OUT_PATH` — so it hits the real metrics file.
- `metrics_registry._load_snapshots()` does `json.loads(path.read_text())` with **no exception handling**, and `record()` writes via plain `write_text()` (not the tmp-file-then-`.replace()` atomic pattern `session_usage.refresh()` already uses in this same codebase) — so a second concurrent writer (the hourly health-check cron, another test run, the merge gate re-running the suite on every main move per conftest's own docstring) racing a `record()` call can leave the file with two concatenated JSON documents. That's exactly `"Extra data"`.

This is the real, still-live defect behind the denial — not anything in the stale doc. Fixing it is small, general (benefits every future test that calls `run_all()`, not just this one), and directly addresses "a person's mistake" + "stale state" + "each dependency failing" from the north stars' adversarial checklist.

**Where this spends tokens vs. the last plan:** almost nothing on re-implementing the feature (it's done); the spend is entirely on this one newly-diagnosed isolation/atomicity gap plus running the real suites to completion, which is cheaper than another blind rewrite.

**More capable, not more passive:** unchanged — visibility only, no cap, Gil decides the threshold once he sees real data.

---

## Tests to write first

The ticket has no "How we'll try to break it" section (confirmed again). All of the following are **new**, targeting the metrics_registry gap. The feature's own adversarial tests (session_usage aggregation edge cases, health-check JSON-corruption tolerance, usage_view.js day/week/job-table edge cases, call-site label test) are **already present and verified correct by reading the code** — no action needed there, and re-writing them would violate "research efficiency: don't re-derive settled ground."

**`lib/tests/conftest.py`**
1. `test_metrics_registry_isolated_by_default` (or equivalent smoke-check): a test calling `metrics_registry.record(...)` never writes under the real `~/.agents/bench/metrics/` — i.e. the new autouse fixture redirects `METRICS_DIR` to a tmp path, same style as the existing 6 isolation fixtures.

**`lib/tests/test_metrics_registry.py`** (new coverage for the two production hardening fixes)
2. `_load_snapshots` tolerates two concatenated JSON documents (the exact denial shape) → treated as empty history, no raise.
3. `_load_snapshots` tolerates truncated JSON (file cut off mid-write) → empty, no raise.
4. `_load_snapshots` tolerates a non-list JSON root (e.g. a dict) → empty, no raise.
5. `_load_snapshots` tolerates an empty (0-byte) file → empty, no raise.
6. On detecting corruption, the corrupted file is preserved as `<path>.corrupted-<timestamp>` before being treated as empty — never silently discarded (Gil's standing "never lose anything" rule).
7. Unreadable file (chmod 000) → empty, no raise; permissions restored in `finally`.
8. `record()` writes atomically: monkeypatch the final write step to raise partway through → the pre-existing file on disk is still intact and still valid JSON afterward (proves the tmp-write-then-replace fix, mirroring `session_usage.refresh()`'s own pattern).
9. Two sequential `record()` calls to the same subsystem/machine both land — no snapshot lost, file stays parseable (closest a deterministic unit test gets to the concurrent-writer case; the atomic-rename fix from #8 is what actually makes concurrent crash-safety structural, not this test).

**`lib/tests/test_health_checks.py`**
10. `test_run_all_tolerates_corrupted_metrics_registry_file`: seed the (now-isolated) `METRICS_DIR` with a concatenated-JSON `health-monitor.<machine>.json`, call `hc.run_all()` for real (minimal additional mocking only where other checks need it), assert it completes without raising and returns a normal result — this is the direct regression test for the PR #359 denial.

---

## Implementation plan

1. **`lib/metrics_registry.py`**: harden `_load_snapshots()` to catch `(json.JSONDecodeError, OSError)`, back up the corrupted file to `<path>.corrupted-<isoformat timestamp>`, and return `[]`. Change `record()`'s write to the tmp-write-then-`Path.replace()` pattern already established in `lib/session_usage.py:refresh()` (reuse, not reinvent).
2. **`lib/tests/conftest.py`**: add `_isolate_metrics_registry` autouse fixture redirecting `metrics_registry.METRICS_DIR` to `tmp_path_factory.mktemp(...)`, matching the existing six fixtures' exact style and placement.
3. **`lib/tests/test_metrics_registry.py`**: new file, tests 2-9 above.
4. **`lib/tests/test_health_checks.py`**: add test 10.
5. Leave `lib/session_usage.py`, `dashboard/src/lib/usage_view.js`, `dashboard/src/components/UsageView.jsx`, `lib/ticket_promotion.py`, and their existing tests untouched — verified correct, nothing to change.
6. **Run both full suites for real and compare total counts against baseline** (not just "no error on the file I touched"):
   - `~/.agents/venv/bin/python -m pytest lib/ -q` — compare total passed/failed against the 2402-passed/0-failed baseline (expect ≥2402 passed, 0 failed, given only additions).
   - `npm --prefix dashboard run test -- --run` — compare total passed/failed against the 1146-passed/0-failed baseline (expect unchanged, since no vitest file is touched by this plan).
   - Treat a shortfall in either total count as a blocking failure, not a pass, exactly as the last two attempts' failures should have been caught.

**Acceptance criteria → coverage:** all four UI/health criteria are already satisfied by existing code (verified by reading it, not assumed). The only remaining work is the isolation/atomicity/defensive-parsing fix and its tests, which satisfy "tests first" for the actual delta this attempt makes.