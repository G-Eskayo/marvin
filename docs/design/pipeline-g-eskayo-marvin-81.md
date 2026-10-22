I have everything needed. No open decisions arise here — this is a narrow, well-defined test fix. Writing the revised plan now.

## North-star fit

**Existing-code check (confirmed by reading the live files, not assumed):** every piece of production and backend/JS-lib code from the prior design doc is **already correctly implemented and committed to the working tree** — verified directly:
- `lib/session_usage.py`: `_autonomous()` keys off `entrypoint` correctly, `isinstance(d, dict)` guards are in both loops, `by_job` aggregation from the launch log works, `TOP_JOBS` cap exists. Matches tests in `lib/tests/test_session_usage.py` (`test_autonomous_detection_based_on_entrypoint`, `test_by_job_*`, `test_*_ignores_malformed_lines`), all present.
- `lib/health_checks.py`: `check_autonomous_share()` is a single `try`/`except Exception` degrading to green, filters to the latest day, registered as `"usage:autonomous-share"` in `default_checks()`. Matches `lib/tests/test_health_checks.py`'s six tests, all present, including `test_run_all_includes_autonomous_share_check` — which now (correctly) asserts only that `default_checks()` lists the id, not a full `run_all()` call, which is what avoided the real-file `JSONDecodeError` the denial's `GATE_TESTS_FAILED` was about.
- `dashboard/src/lib/usage_view.js`: `weeklySeries` rebuilds on `dayList(weeks*7, end)`, so today's data lands in week 0. Matches `dashboard/test/usage_view.test.js`'s rewritten `weekly series` tests.
- The 7 `marvin_launcher.launch(..., ticket=<job>)` call sites and `lib/purpose_metrics.py`'s `ticket="purpose-metrics"` change are present and correct.

So the only thing left broken is exactly what this round's code review found: two assertions in `dashboard/test/usage_view_render.test.jsx` that pass regardless of whether the feature they claim to cover is actually working. This is a **test-only repair**, not a feature or production-code change.

**Reuses:** `dashboard/test/github_view_render.test.jsx`'s pattern (`LowPointBars`/`CallBars` describe blocks, lines 9-30) of asserting on specific rendered markup (`data-tone="green"`, text counts) rather than a static heading string — the exact discipline missing from the two flagged tests. `UsageView.jsx` doesn't export its internal `ShareBars`/job-table JSX as named exports (unlike `GithubView.jsx`'s `LowPointBars`/`CallBars`), so the fix renders the default `UsageView` export with fixture data chosen so the specific text can only appear if the real feature renders — no new exports needed, no production code touched.

**Why simplest sufficient:** two one-line assertion changes (plus one net-new test for the inverse case each, so the fix is provably tied to real rendered content and not to a lucky string match). No new machinery, no new component API.

**Tokens:** negligible — this is strengthening two existing test bodies, not writing new product logic.

**User capability:** unchanged from the already-landed feature (pure visibility, north star 3, Gil's 2026-10-09 "show it first" decision). This pass doesn't add or remove any user-facing capability; it closes a gap where the test suite could silently stop proving the feature works.

**Out of scope, confirmed still correctly out of scope:** the reference-line label clipping (`UsageView.jsx:28`, `x={W + 2}` sits outside the `viewBox` width) and the 4-bar weekly `i % 5 === 0` labeling are "notes," not in this round's `fix_these`, and the prior design doc already explicitly deferred them. Re-confirmed: this round's review again didn't put them in `fix_these`. Not touching them keeps this pass narrowly scoped to what was actually denied.

## Decisions

None. Nothing here requires the owner to choose between options — both fixes have one correct answer (assert on content that only renders when the real feature renders).

## Tests (written first — these ARE the fix)

**`dashboard/test/usage_view_render.test.jsx`:**

1. Rewrite `'renders a job table with top autonomous spenders'` (currently line 28, only asserts the section title, which also renders in the empty-jobs branch): assert `expect(html).toContain('daily-digest')` (the higher-output job in the fixture, sorted first by `jobTable`) in addition to the title — this fails if job rows stop rendering, which the current test does not.
2. New: `'shows the empty-jobs message when there are no job rows'` — call `UsageView` with `jobs: []` (job table empty, other data present) and assert `expect(html).toContain('No autonomous jobs')` and `expect(html).not.toContain('daily-digest')` — the inverse case, so test 1's fixture-specific string isn't just coincidentally true for any input.
3. Rewrite `'renders reference lines at 0% share for autonomous/interactive charts'` (currently line 63, only asserts the chart section heading, which renders unconditionally): assert all three reference percentages render — `expect(html).toContain('30%')`, `expect(html).toContain('40%')`, `expect(html).toContain('50%')` — in addition to the existing heading check. This fails if the reference lines are removed or gated behind `share > 0`, which the current test does not.
4. New: `'still renders reference lines when autonomous share is 100%'` — same shape as test 3 but with `autonomous: 'autonomous'` on every row, confirming the reference lines aren't accidentally gated on the opposite extreme either (guards against a future "only show at low/high share" regression the current single fixture can't catch).
5. (Existing, keep unchanged, re-verify passing) `'renders autonomous/interactive share bars'`, `'shows empty state when there is no data'`, `'renders both per-day and per-week share bars'` — none of these were flagged and none need new assertions.

**Covered without new tests:** every other acceptance criterion (per-day/per-week split both Macs, health yellow above 50%, top spenders listed, tests-first) is already covered by the existing, verified-correct test suites in `lib/tests/test_session_usage.py`, `lib/tests/test_health_checks.py`, and `dashboard/test/usage_view.test.js` (confirmed by reading them directly above) — this pass does not touch or need to touch those.

## Task List

1. `dashboard/test/usage_view_render.test.jsx`: rewrite the job-table test to assert a real job name renders (test 1), add the empty-jobs inverse test (test 2).
2. `dashboard/test/usage_view_render.test.jsx`: rewrite the reference-line test to assert all three percentage labels render (test 3), add the 100%-share inverse test (test 4).
3. Run `npx vitest run dashboard/test/usage_view_render.test.jsx`; temporarily revert each of `UsageView.jsx`'s job-table rendering and reference-line rendering in turn (locally, not committed) and confirm tests 1 and 3 each fail without the corresponding code — this is the check that the new assertions actually catch the regression the code review described — then restore and confirm green.
4. Run the full `pytest -q` and `npx vitest run` suites once more to confirm no count regression against the last comparison baseline (pytest 3218/0, vitest 2080/0) — no production code changes are expected to move these numbers.