## North-star fit

**Existing patterns reused, by file and function (re-checked against the code just now, not assumed):**
- `dashboard/src/components/MetricsPage.jsx:35-37` (`useState(() => readSaved(storage(), SAVED_KEY))`) — already copied correctly into `DashboardHome.jsx:102` and `MrReview.jsx:559`. Confirmed: both now use a lazy `useState` initializer, not a per-render call. Nothing to redo here.
- `MetricsPage.jsx:45,52,91` (stale-survives-error: `setData((prev) => ({ report: prev?.report ?? null, error: ... }))`, rendered as `{data.error && <p>{data.error}{data.report ? ' Showing the last good result.' : ''}</p>}`) — already copied into `DashboardHome.jsx` (`error && !boards` / `error && <p>{error} Showing the last good result.</p>` at line 185) and `MrReview.jsx` `OpenPrs` (`error && prs === null` / `{error && <p>{error} Showing the last good result.</p>}` at line 681). Confirmed by reading both files end to end.
- `dashboard/src/lib/saved_state.js` (`readSaved`/`writeSaved`/`ageText`) — unchanged, third/fourth reuse.
- CONTEXT.md:613-634 ("render the true result locally at once, confirm in the background") — same principle, applied to reads.
- `approve_stream.js` + `MergeProgress.jsx` (#568) — confirmed still present (`dashboard/electron/main/approve_stream.js`, `dashboard/src/components/MergeProgress.jsx`, `dashboard/test/merge_progress_view.test.jsx` all exist). Criterion 4 is satisfied; nothing to build.

**What's actually left, after re-reading the real files (not the previous session's self-report):**

The previous round's *design* was largely right and most of its *code* landed correctly — the four component-side fixes (shape validation, stale-survives-error, lazy init, writing on success) are genuinely in `DashboardHome.jsx` and `MrReview.jsx` right now. What code review flagged and is still true today:

1. **`IMPLEMENTATION_REPORT.md`** is still sitting at the repo root, uncommitted, still making the false claims code review already called out (a non-existent call-order test, stale counts). Not a planning gap — a "didn't do task 1" gap.
2. **The window-leak test is fake.** `mr_review_open_prs.test.jsx:100-107`'s "globals do not leak" test never captures what `global.window` was *before* the suite ran, so `afterEach` can't restore it, and the test itself only asserts a fresh render still works — it would pass even with the leak fully present.
3. **`PR_DESCRIPTION.md`'s Decisions section is pre-answered** (`**Resolved: A**` prose under each heading, no `- [ ]` options at all) and is missing the `criterion-1-metric` question entirely — this is exactly the "too vague" / "don't pre-tick an answer the owner didn't give" violation `docs/agents/decisions-format.md` exists to prevent. Gil cannot click buttons he already finds checked.
4. **`docs/design/pipeline-g-eskayo-marvin-236-pr-summary.md:33`** marks criterion 1 ✅ with no measurement and no explanation — the exact misreport the previous design doc itself warned against, repeated anyway in the written artifact.

**Three more real, cheap-to-fix defects turned up by reading the current code line by line** (not required by code review's four `fix_these`, but they're in the same lines already being touched, are concrete misuse-category failures the ticket's own test mandate requires covering, and fixing them now avoids a third round of "found but not fixed" for the exact same files):

5. `DashboardHome.jsx:103` — `typeof saved.value?.overview === 'object'` is `true` for `overview: null` and for an array. A hand-edited or corrupted cache with `overview: null` passes validation, then `overview[board.repo]` inside `buildProjectCards` throws on a `null`. This is the "a person's mistake" misuse category the ticket requires testing.
6. `DashboardHome.jsx:163,171` — with a cached **empty** `boards` array (`[]`, a real state for a new project with zero boards), `error && !boards` is `false` (`![]` is `false`), so a background failure falls through to "No project boards yet" and the error is silently swallowed instead of shown. This is the "dependency fails after success" category, missed for the one case where cached data is an empty-but-valid array.
7. `MrReview.jsx` `OpenPrs` — when seeded from saved state, the tab's open-count badge (`onCount`) isn't called until `mr.list()` resolves, so the instant-paint promise ("no blank or spinner-first renders") is broken for the badge even though the list body paints immediately. Direct miss against the ticket's own acceptance bar.

**Simplest sufficient approach:** no new file, no new abstraction, no new caching layer. Delete the stray report, fix the two doc files to use real unanswered Decisions per the existing format spec, fix the fake test and the three line-level bugs in place, and add the handful of tests that were twice now flagged as claimed-but-missing.

**Token/compute cost:** spends tokens re-reading actual file contents end to end (confirmed — not assumed — that the four `fix_these` component bugs are already fixed) rather than re-deriving a plan from the stale self-report. Saves tokens by not re-touching anything already correct.

**Phone-OS direction:** unchanged — instant-paint, non-blocking, "show what you have, confirm quietly."

**User capability:** infrastructural; strictly more capable (an honest view of true state, including diagnosed-not-blank staleness), never more passive. If this task's own Decisions-format violation is left unfixed, it actively *reduces* Gil's agency (he can't exercise his own stated choice), which is a direct north-star violation — fixing it is non-optional, not a nice-to-have.

## Decisions
<!-- marvin:decisions -->
### criterion-1-metric: How should "the slowest user-facing call is 50% faster" be satisfied for a UI-blocking fix that doesn't touch backend call time?
- [ ] A: Accept that `timing_report.mjs`'s backend ms is unchanged by this PR and use the criterion's own escape clause — state plainly why a saved-state/instant-paint fix cannot move `ipcMain.handle` execution time, post the current ranked table as the honest baseline, and argue the user-facing wait is cut by the saved-state mechanism instead, which the existing log doesn't capture
- [ ] B: Add a small new client-side metric (ms from mount to first meaningful paint, logged per screen) so "faster" can be measured directly for this mechanism, and compare that before/after instead of the backend table
- [ ] C: Expand this PR's scope to also cut backend call time for one of the top entries (e.g. trim the `files` field on `mr:list`), so the existing table genuinely moves

### scope: Which cold-start screens get saved-state wiring in this round?
- [ ] A: Just the two already wired — Activity home (`DashboardHome.jsx`) and MR Review's PR list (`MrReview.jsx` `OpenPrs`)
- [ ] B: Also the Queue widgets (`NextUpQueue.jsx`, `ActivityHover.jsx`, `ParallelToggle.jsx`, all calling `queue:list`)
- [ ] C: Every remaining GitHub-backed view dashboard-wide in one pass

### health-refresh-progress: Does Health's "Refresh" button need stage-by-stage progress this round?
- [ ] A: Leave as-is — the acceptance criterion names Approve specifically, and Refresh is an explicit, already-labelled action
- [ ] B: Extend the same stage-progress pattern used for Approve (#568) to `health:refresh`

### es-module-suspect: Pursue the dashboard/package.json "type":"module" suspect in this PR?
- [ ] A: Drop it from this ticket — the timing log only measures handler/route execution, not module-parse time, and it isn't among the top 5 ranked calls; file a separate low-priority ticket if it matters
- [ ] B: Investigate and fix it here too

None of these are pre-ticked — Gil hasn't answered any of them yet, so the boxes stay empty. For `criterion-1-metric`, since this session is headless and can't wait on an answer, the implementation below proceeds on option A's *behavior* (post the honest current table, change nothing backend) as the null/no-op default, without checking the box — if Gil picks B or C instead, that's a follow-up, not a block on merging an honest baseline.

## Tests first

One item per case already in the code's reach, plus the ticket's standard misuse categories. Items 1–4 characterize behavior that's already implemented but still untested (twice now flagged as claimed-but-missing); items 5–7 are the three newly found bugs; item 8 is the fake test that needs to become real.

1. **Stale-content-survives-error** (`DashboardHome.jsx`, `MrReview.jsx` `OpenPrs`) — with valid cached data already painted, a background refresh failure keeps the cached cards/list on screen with the inline "...Showing the last good result" note, never the full-page error. Regression guard: with **no** cached state and a failed first load, the full-page error view is unchanged.
2. **Lazy read** — `storage.getItem` is called at most once per mount of `DashboardHome`/`OpenPrs`, not once per render (assert via a mock storage counting calls across a couple of re-renders triggered by an unrelated prop/state change).
3. **`reload()` call order** (`OpenPrs`) — on mount, `mr.parity()`, `mr.autoMergeReport()` and `mr.list()` fire synchronously in that order; `mr.listStatus()` and `mr.markSeen()` fire only after `mr.list()` resolves. Recorded via one shared call-order array across all five mocks; asserted both with and without a seeded saved state, proving the seed path doesn't change call order.
4. **Approve progress regression guard** — re-run `test/merge_progress_view.test.jsx` unchanged; no new test needed, criterion 4 is already satisfied.
5. **Malformed `overview` (a person's mistake)** — a cached blob with `overview: null` or `overview: []` must be treated as invalid saved state (same as today's `boards`-not-array case): `loading` stays `true`, not a crash inside `buildProjectCards`.
6. **Empty-but-valid cached `boards` + background failure** — with `boards: []` cached (a real "zero project boards" state) and a background `boards.list()`/`activity.overview()` failure, the amber "...Showing the last good result" note still renders next to "No project boards yet" — it must not be silently swallowed.
7. **Instant count badge** (`OpenPrs`) — mounting with a valid seeded PR list calls `onCount(savedPrs.length)` synchronously on first render, before `mr.list()` resolves (assert with a `mr.list()` mock that returns a promise that never resolves in the test).
8. **Window-leak regression, made real** — fix `beforeEach`/`afterEach` in both `render_smoke.test.jsx`'s `DashboardHome` block and `mr_review_open_prs.test.jsx` to capture whatever `global.window` was *before* the suite touches it (present object or `undefined`) and restore exactly that in `afterEach`, not just `.api`/`.localStorage`. Then add one test, run last in each suite, asserting `global.window` is back to that original value/absence. Verify this test actually catches the bug: temporarily reintroduce the current broken cleanup and confirm the new test fails, then put the fix back — this is the "verify fails when code changes without a test changing" check for this specific item.

Misuse categories covered: a person's mistake / malformed input (5, and the pre-existing shape-validation tests), a dependency failing after a successful cache (1, 6), repeated/ordered calls on mount (3), stale state shown honestly rather than silently or blockingly (1, 6), test-order dependence from a leaked global (8), and the instant-paint promise applying to every visible element, not just the list body (7). Concurrency and permissions don't apply — no new write path or privilege boundary.

## Task List

1. [ ] Delete `IMPLEMENTATION_REPORT.md` for real this time (duplicate of `docs/design/pipeline-g-eskayo-marvin-236-pr-summary.md`, contains false claims).
2. [ ] `DashboardHome.jsx`: tighten `validSaved`'s overview check to `typeof saved.value?.overview === 'object' && saved.value.overview !== null && !Array.isArray(saved.value.overview)`. Add test-first item 5's `overview: null`/`overview: []` cases to `render_smoke.test.jsx`.
3. [ ] `DashboardHome.jsx`: move the inline error note into the "No project boards yet" branch so a background failure with a cached empty `boards: []` still shows it (reuse the exact phrasing/placement already used in the main render, don't invent new copy). Add test-first item 6.
4. [ ] `MrReview.jsx` `OpenPrs`: add a mount-only effect calling `onCount?.(prs.length)` when `prs` is non-null from the seed, so the tab badge paints instantly too. Add test-first item 7.
5. [ ] Add test-first items 1–3 (stale-survives-error for both components, lazy-read call count, `reload()` call order) — these characterize code already in place; no component changes needed for them, only tests.
6. [ ] Fix `render_smoke.test.jsx`'s `DashboardHome` block and `mr_review_open_prs.test.jsx`'s `beforeEach`/`afterEach` to capture and restore the true pre-existing `global.window` (present vs. absent), not just its `.api`/`.localStorage`. Replace the fake "test order independence" test with the real regression test from test-first item 8, and confirm it fails against the current broken cleanup before putting the fix in.
7. [ ] Run the full dashboard test suite (`vitest`) and the Python suite; confirm no regressions beyond this change.
8. [ ] Run `node dashboard/scripts/timing_report.mjs 24 ~/.claude/logs/dashboard-timing.jsonl` (and a longer window if useful) to get the current ranked table, dated at implementation time — not the 2026-10-13 comment's numbers, which are 12 days stale.
9. [ ] Rewrite `PR_DESCRIPTION.md` and `docs/design/pipeline-g-eskayo-marvin-236-pr-summary.md` from scratch (not edited in place, since both currently contain false claims): honest criterion-by-criterion status (criterion 1 explained per the no-op default under Decision `criterion-1-metric`, never marked ✅ without a real measurement that supports it), the fresh ranked table from step 8 labeled plainly as current state, and all four Decisions above reproduced verbatim as real unticked `- [ ]` options — no pre-filled "Resolved" answers, and `criterion-1-metric` included this time.
10. [ ] If Decision `scope` is later answered B or C, repeat the same pattern for the named queue widgets in a follow-up — out of scope for this PR's task list.