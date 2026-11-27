## North-star fit

**Reuses, before adding anything new:**
- The cause codes already exist and are already recorded on every refused merge: `MAIN_RED`, `RATE_LIMITED`, `GITHUB_OUTAGE`, `MEMORY_PRESSURE` (`dashboard/src/lib/stage_strip.js:60-84` `REMEDIATION_BY_CODE`; `dashboard/electron/main/mr_history.js:17-23` `REASONS`/`plainReason`). `MAIN_RED` refusals already flow end to end into `history.refusals` → `buildRows()` (`dashboard/electron/main/mr_history.js:27-38`) with `{code, at, number, title, repo, url}` — no new recording plumbing is needed for the two acceptance-criteria roots (main red, GitHub rate limit).
- The real, shipped place this noise is visible today is `MrHistory.jsx`'s "Merged" view (now inside Workshop, per `[[Workshop...]]` in the lexicon): every merge and every refused Approve, newest first, ungrouped (`dashboard/src/components/MrHistory.jsx:36-62`, fed by `dashboard/src/lib/mr_history_view.js:groupByDay`). That is where "15 builds failing on MAIN_RED" would otherwise sit as 15 identical lines. The Vitals tab itself (`#873`/`#878`) is still an unapproved mock-up, so this ticket has to land against the surface that actually exists, in a shape the eventual Vitals "what needs you" column can absorb later (per the re-home table in `vitals-v5-2026-10-30.md`).
- The fold-with-count UI pattern already exists twice: `ProjectBoard.jsx:460-488` (`OtherProjects`, folded row with a count) and `AccountsCard.jsx:66-74` (grouped rows under one header). The new folded history row reuses that shape rather than inventing one.
- The "how far apart is still the same incident" judgment reuses `lib/failure_breaker.py`'s existing `WINDOW_HOURS = 2` rationale, instead of making up a new threshold.

**Why this is the simplest sufficient approach:** folding is driven only by each row's own already-recorded `code`, through a static `code → root` table (`MAIN_RED→MAIN_RED`, `RATE_LIMITED/GITHUB_OUTAGE→GITHUB`, `MEMORY_PRESSURE→MEMORY_PRESSURE`). Nothing is inferred from timing except *splitting two separate incidents of the same code* that are hours apart — never used to *merge* two different codes. That is exactly what "never guess a root from timing alone" requires, with no extra machinery. `MAC_UNREACHABLE` and `BUDGET_HARD_LINE` are named in the issue but have no live refusal code yet (`#898` peer watch and `#872` budget governor are both still open) — I'm reserving their slot in the root table (one line to wire later) rather than building detection for systems that don't exist yet.

**Where it saves/spends:** zero new runtime calls, timers or polling — a pure in-memory transform of data the Merged view already fetches, same O(n log n) cost class as the `groupByDay` step it sits beside.

**User impact:** turns a wall of 15 identical "refused: main was failing" lines into one actionable line ("main is red · 15 builds blocked") with the individual builds still inspectable underneath — less noise to read through, not less information; nothing is hidden, so it leaves Gil more able to spot the one real problem, not more passive.

**Machine:** pure dashboard (Electron/React) source change; no machine-specific behavior, runs wherever the dashboard runs.

No Decisions section — the ticket is concretely specified and I didn't find a genuine fork needing Gil's choice; the two judgment calls above (reserving unbuilt roots, folding threshold of 2+) are ordinary implementation details, not product ambiguity.

## Tests to write first

In a new `dashboard/test/common_cause.test.js` against a new pure module `dashboard/src/lib/common_cause.js`:

1. **Two roots at once** — a mix of `MAIN_RED` and `RATE_LIMITED`/`GITHUB_OUTAGE` refused rows produces two separate folded rows, each with its own correct count; items never cross groups.
2. **Missing/unknown cause code never folds by guess** — a refused row with `code: undefined`, `code: null`, or an unrecognized code stays its own individual row, even when it sits right next to a real incident in time.
3. **Root clears, one build still fails for its own reason** — 15 `MAIN_RED` rows plus one later row for the *same PR* with a different code (e.g. `GATE_TESTS_FAILED`) after main recovers: the fold shows 15 (or 14, if that PR's own retry is excluded — assert the exact expected count), and that PR's own red row stays separate and visible.
4. **Unrelated failure in the same minute stays its own row** — one `MAIN_RED` row and one `GATE_TESTS_FAILED`/`OUT_OF_ORDER` row at the identical timestamp never fold together.
5. **Empty/absent input** — `[]`, `null`, `undefined` → returns `[]`, never throws.
6. **Malformed rows** — missing `url`, missing `at`, non-string `code`, a row that isn't `kind: 'refused'` at all → never crash; non-`refused` rows pass through untouched; refused rows missing the fields needed to fold safely fall back to their own row.
7. **Dedup by build, not by event** — the same PR refused twice for the same code (retried, failed again) counts once in the fold, keeping only its latest occurrence.
8. **Two separate incidents of the same code, far apart in time** — two `MAIN_RED` clusters separated by more than the gap window fold into *two* rows, not one, so unrelated incidents weeks apart never merge.
9. **A merged row sharing a `url` with an earlier refused row** — the `kind: 'merged'` row is never pulled into the fold group or altered; it stays its own row (this is how "fixing main clears the row... as retries pass" actually happens — the item simply stops being a refused row).
10. **Out-of-order input** — rows not sorted by `at` still group and dedupe correctly (sort internally; don't trust caller order).
11. **A lone row with a known root code (count 1)** — stays an individual row; folding only kicks in at 2+.
12. **Large input (thousands of rows)** — completes without quadratic blow-up (guards `O(n log n)` behavior, not just correctness).
13. **Idempotence** — calling `foldCommonCause` twice on the same data (simulating a re-render/data refresh) yields the same output; it's a pure function with no hidden state.
14. **Injectable root table** — passing a different `rootByCode` map folds a different code set, proving the function isn't hardcoded to only the merge-history codes (reusability check, not over-building a cross-feed aggregator now).

In `dashboard/test/mr_history_render.test.jsx` (or a new `mr_history_render_folded.test.jsx` if that file is already large):

15. **Rendering** — a folded row shows the `"<label> · N builds blocked"` summary collapsed by default; clicking expands to list every blocked PR (number, title, repo) without breaking the existing `onOpen` behavior for `merged`/individual `refused` rows.
16. **Misuse via repeated clicks** — rapid expand/collapse clicking a folded row never duplicates its item list or desyncs from a data refresh arriving mid-toggle.

## Task List

1. Create `dashboard/src/lib/common_cause.js`: static `ROOT_BY_CODE` (`MAIN_RED`, `RATE_LIMITED`→`GITHUB`, `GITHUB_OUTAGE`→`GITHUB`, `MEMORY_PRESSURE`), `ROOT_LABEL` (`"main is red"`, `"GitHub is down"`, `"memory pressure"`), and `foldCommonCause(rows, { rootByCode = ROOT_BY_CODE, gapHours = 2 } = {})`: sorts refused rows by `at`, groups by mapped root, splits groups into incidents on the gap window, dedupes by `url` keeping the latest per build, folds incidents of 2+ builds into a `{kind: 'folded', root, label, at, count, items}` row, and leaves every other row (merged, unknown-code, singleton) untouched.
2. Write `dashboard/test/common_cause.test.js` covering tests 1–14 above, before touching any rendering code.
3. Wire the fold into `dashboard/src/components/MrHistory.jsx`: call `foldCommonCause(data.rows)` before `groupByDay` in `HistoryList`, so folded rows are grouped by day using their own (latest) `at` like any other row.
4. Extend `HistoryRow` (or add a small `FoldedHistoryRow`) in `MrHistory.jsx` to render `kind === 'folded'` rows: collapsed summary line (`"<label> · N builds blocked"`), click toggles an expanded sub-list of `items` (each still clickable via the existing `onOpen`), following the `AccountsCard`/`ProjectBoard` grouped-row pattern already in the codebase.
5. Write/extend the render test(s) (tests 15–16) against the updated `MrHistory.jsx`.
6. Run the full dashboard test suite (not just the new files) and the Python suite untouched, to confirm nothing in `mr_history`, `stage_strip`, or `merge_queue` tests regressed from the new call in `HistoryList`.