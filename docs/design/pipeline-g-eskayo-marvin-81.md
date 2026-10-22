Confirmed. Now I have everything needed to write the revised plan.

## North-star fit

**Reuses before adding anything new** — verified against the actual (uncommitted) worktree state, not assumed:

- The Python-side fixes from the previous design doc are **already implemented correctly** in this worktree: `lib/marvin_launcher.py:spend_report`/`main` (null-safe `cost_usd`/`at`, `TypeError` caught, `main()` guard matching `lib/github_usage.py:main`), `lib/usage_report.py:_peer_launches` (now shells to `{AGENTS_PYTHON} ~/.agents/lib/marvin_launcher.py`, mirroring `_peer_github`), and `lib/health_checks.py:check_autonomous_share` (sums `tokens.rows` by `kind` for today, `>` boundary, registered under `CROSS_MACHINE_BUDGET_S`). These match ADR 0048's own "pipeline share" definition (`dashboard/src/components/UsageView.jsx`'s `headlessShare`) — I'm keeping all of this, not redoing it.
- What's actually broken is in the two places the previous attempt's own design doc called "the loophole" and then — checking the diff — never closed:
  - `dashboard/src/lib/usage_view.js:weeklySeries` has a real bucketing bug: after assigning each of the 4 week buckets a fixed key via `endDate - (weeks-1-i)*7`, the per-row bucketing code computes a *different* key by adding `(rowDate.getUTCDay() - endDateObj.getUTCDay() + 7) % 7` on top of the weekIndex offset. That extra term only vanishes when a row's weekday happens to match `end`'s weekday; for every other row the computed key doesn't exist in the `Map`, so `byWeek.get(weekKey)` returns `undefined` and the row is silently dropped (the `if (week)` guard was written to avoid a crash, not to avoid data loss). Six out of seven days in every week are being thrown away silently — a correctness defect, not a style nit.
  - `dashboard/test/usage_view_render.test.jsx` is the "test 20-22" file the plan called for, but it doesn't render anything: no `renderToStaticMarkup`, no import of `UsageView.jsx`/`ShareLine`/`DailyBars`. Its assertions (`expect(['day','week']).toContain('day')`) pass unconditionally. `dashboard/test/usage_view.test.js`'s new `weeklySeries` test has the exact shape the plan flagged as insufficient (`toHaveLength(4)` + `toHaveProperty('week')`, no bucket-contents assertion) — which is exactly why the bug above wasn't caught. I'm rewriting both to the `dashboard/test/github_view_render.test.jsx` pattern (real `renderToStaticMarkup`, real bucket-membership assertions) that the previous plan specified but the previous *implementation* didn't deliver.
- New finding, not in either previous plan: `lib/sandbox_orchestration.py:_launch` (the sole wrapper both `ticket-planner` and `ticket-executor` launches go through) never passes `job=` to `marvin_launcher.launch`. `dashboard/src/lib/usage_view.js:launchSpendTable` explicitly skips entries with `job === null`. Ticket work is almost certainly the single largest autonomous-spend category on this machine, and it is currently invisible in "Top autonomous spenders" — directly contradicting the ticket's own purpose for that table ("so the biggest one can be fixed first"). Fix: `_launch` defaults `kwargs.setdefault("job", "ticket-pipeline")` (one combined label for planner+executor — the existing, untouched `ticketTable` in `usage_view.js:103` already gives per-ticket granularity; a job-level split between "ticket-planner" and "ticket-executor" would just dilute the one number that matters for this table: how much of total autonomous spend is ticket work).
- `dashboard/src/components/UsageView.jsx:126` hides the entire ShareLine + Top-spenders block when `autonomousShareVal === 0`. On a day where nothing autonomous has run yet (or between hourly scans), the whole feature disappears instead of showing "0%" — which looks like the feature was never built. Acceptance criteria says the share line should be shown, not shown-only-when-nonzero. Fix: gate on `rows.length > 0` (already guaranteed above) instead, always render the line, and show "No autonomous spending in this window" in place of the table when `topSpenders` is empty — matching the existing empty-state wording pattern already used for the tickets table two sections below it.

**Why this is the simplest sufficient approach:** every fix is a correction to code that already exists and already follows the right pattern, not new machinery. No new data source, no new scan, no new file.

**Tokens:** no new per-call computation; `check_autonomous_share` still reads the already-cached `tokens` field from the hourly scan. `job="ticket-pipeline"` is one extra string written into an existing log line.

**Phone-OS fit:** unchanged — a reachable, always-current status surface.

**User capability:** shows Gil real, undistorted data (the current, buggy `weeklySeries` would have shown him a materially wrong week-over-week picture) so he can pick a cap number later with data he can trust. Nothing is paused or capped.

## Decisions
<!-- marvin:decisions -->
None required. The weekly-bucketing fix, the fake-test rewrite, and the zero-share display fix are bug fixes with one correct answer. The `job="ticket-pipeline"` labeling choice follows directly from the existing, untouched per-ticket table already covering the per-ticket dimension — not a real tradeoff for the owner.

## Tests first

**`dashboard/src/lib/usage_view.js` — `weeklySeries` (real bug, currently masked by a shallow test)**
1. A row whose weekday differs from `end`'s weekday is still bucketed into the correct week (the must-fix: reproduces the silent-drop bug directly — fails on current code, passes after the fix).
2. Four buckets, each with a deterministic key, covering exactly the last 4 weeks ending at `end`; a week with no rows is present with all-zero values, not omitted.
3. A row exactly on the boundary between two weeks lands in the week containing its own day (no double-count, no drop).
4. `autonomousShare(rows, end)`: `0`, not `NaN`, when that day's total is 0 (regression, already specified, keep).

**`lib/sandbox_orchestration.py` — `_launch` job tagging (new gap)**
5. A `ticket-planner` launch through `_launch` records `job: "ticket-pipeline"` in the launch log.
6. A `ticket-executor` launch through `_launch` records the same `job: "ticket-pipeline"` (so `spend_report` sums them together, not split).
7. A caller that explicitly passes its own `job=` through `**kwargs` is not overridden (misuse case: a future caller opts out of the default — `setdefault` must not clobber it).

**`dashboard/src/lib/usage_view.js` / `UsageView.jsx` — zero-share display (new gap)**
8. `autonomousShareVal === 0` with `rows.length > 0` still renders the `ShareLine` section at 0%, not hidden.
9. `topSpenders` empty (no job-tagged launches yet) renders "No autonomous spending in this window", not nothing.
10. `topSpenders` non-empty still renders the table, unchanged (regression).

**`dashboard/test/usage_view_render.test.jsx` — rewritten to actually render (closing the fake-test gap)**
11. `renderToStaticMarkup(<ShareLine share={0.75} />)` contains a `75%` label and three reference lines, regardless of share value (0, 0.3, 1.0 — label never renders past the SVG viewBox at 100%).
12. `renderToStaticMarkup(<DailyBars series={weeklySeries(rows, end)} metric="output" bucketKey="week" />)` renders 4 bars keyed by `week`, not `day` — the actual Day/Week toggle behavior, not an assertion about array literals.
13. `renderToStaticMarkup(<UsageView machines={[...]} which="all" />)` with no token rows at all still renders the existing "No token usage scan…" message (regression; `UsageView.jsx` has no render test today at all).

**Carried over from the already-correct Python side (gap-fill only, not redone)**
14. `check_autonomous_share`: a row from yesterday with a huge headless share is excluded from today's figure (day-filtering exists in code at `lib/health_checks.py` but has no dedicated test today — closes that coverage gap).
15. `check_autonomous_share`'s result dict never contains a field a caller could read as a pause/cap signal (`set(result.keys()) <= {"id","label","severity","detail","checked_at","value"}` — guards the "no cap yet" decision against silent scope creep; cheap to add, currently untested).
16. `default_checks()` registers `check_autonomous_share` specifically under `CROSS_MACHINE_BUDGET_S`, not merely "present" (today's test only checks the id is present, not which budget tier it runs under — a regression could silently move it back to `CHECK_BUDGET_S` and time out against a stale peer without any test catching it).

## Task List

1. `dashboard/src/lib/usage_view.js`: write tests 1–3, then fix `weeklySeries`'s per-row bucketing to use the same fixed `weekIndex`-derived key the buckets were initialized with (drop the weekday-alignment term entirely — the buckets are already aligned to `end`, not to each row's weekday).
2. `lib/sandbox_orchestration.py`: write tests 5–7, then change `_launch` to `kwargs.setdefault("job", "ticket-pipeline")` before calling `marvin_launcher.launch`.
3. `dashboard/src/components/UsageView.jsx` + `usage_view.js`: write tests 8–10, then change the ShareLine/top-spenders gate from `autonomousShareVal > 0` to always-rendered (guarded only by the existing `rows.length === 0` early return), and render an explicit empty-state line when `topSpenders.length === 0`.
4. `dashboard/test/usage_view_render.test.jsx`: delete the current placeholder content, write tests 11–13 using `renderToStaticMarkup` against real exports (`ShareLine`, `DailyBars`, default `UsageView`), matching `dashboard/test/github_view_render.test.jsx`'s pattern.
5. `lib/tests/test_health_checks.py`: add tests 14–16 (day-filter exclusion, no-cap-field guard, budget-tier-specific registration check) — gap-fill only, no production code change expected here.
6. Run the full pytest + vitest suite; confirm each test above fails if its corresponding fix (or, for 14–16, the already-existing behavior) is reverted, then confirm the full suite is green with no count regression against the baseline (vitest ~2070 passed, pytest ~3203+ passed).