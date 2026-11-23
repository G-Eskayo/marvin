## North-star fit

**Reuses:** `mergedPrArgs(repo, since)` (`dashboard/electron/main/mr_history.js:10`) as the direct template for a new `closedPrArgs(repo, since)` — same incremental-since-newest-known pattern, same `gh pr list --json` shape. `createMrHistory`'s existing per-repo incremental-fetch-and-cache loop (`mr_history.js:70-77`) is reused verbatim for the new closed-list source, not reinvented. The merge/open/refused row-building already lives in `buildRows`; it's extended, not replaced. Filter chips reuse the `ViewToggle` button/`aria-pressed` pattern already in `MrReview.jsx:593-602`. Day-grouping/paging (`groupByDay`/`pageOf` in `mr_history_view.js`) is untouched and still runs on the (now filtered) row list. For the "live, approvable detail" requirement, I reuse the exact options object `mrList` already builds for the Open tab (`canMergeHere`/`canMergeFromDashboard`, `sentBackTickets`, `reworkStatus`, etc., `index.js:1117`) rather than inventing a second mergeability path.

**Simplest sufficient approach:** one more data source (closed-unmerged PRs) feeding the same `buildRows` keyed-by-url map that already exists for merged+refusals; no new storage mechanism, no new cache file, no new IPC surface — `mr:history` and `mr:historyDetail` keep their existing shapes.

**Resources:** the `openPrs` fetch currently requested in *light* mode (`number,title,url` only) for history, duplicating a second GitHub list call/cache key (`'prs-light'`) alongside the Open tab's own non-light `'prs'` fetch. Switching history's `openPrs` to the same non-light call reuses the Open tab's existing cache entry in the common case (zero extra GitHub calls) and gains the `createdAt` field the ticket needs for "how long it has been open" — a net resource win, not a cost. The new closed-list fetch is a genuine new GitHub call, but incremental (since-newest-known) like the merged list, so it costs one call per repo per fresh read, not per PR.

**Correcting the ticket's stated fit:** `buildRows`'s given signature (`merged, history, openPrs`) is one argument short — "dropped" rows need their own data source (closed-unmerged PRs), explicitly called out as a separate list in the "how we'll try to break it" line ("in neither the merged, open nor closed list"). I'm adding a fourth `closedPrs` parameter rather than overloading `openPrs`, since conflating open and closed PRs in one array would make the kind-assignment logic ambiguous and harder to test. This is a correction to an AI-triaged ticket's shorthand, not a deviation from its intent.

**Leaves the user more capable:** yes — Gil can tell at a glance which of his own PRs are actually stuck-and-waiting-on-him versus just finished history, which was the entire point of filing #423 (#359/#368/#400 misread as dropped).

**Machine:** none specified by the ticket; this is a pure dashboard-code change, runs wherever the dashboard build/tests run (no machine-specific concern).

## Tests (first, before any implementation)

In `dashboard/test/mr_history.test.js` (extending `buildRows`'s existing describe block) and `dashboard/test/mr_history_render.test.jsx`:

1. A refusal whose `pr_url` doesn't match `PR_RE` is dropped, never a crash (existing test, kept).
2. A refusal whose PR is in neither the merged, open, nor closed list is dropped, never a crash (new: refusal for a URL absent from all three source arrays produces no row).
3. The same PR appearing in both the closed-unmerged list and the merged list (closed-then-reopened-then-merged) yields exactly one row, `kind: 'merged'` — merged wins over dropped.
4. A PR closed without merging (`closedPrs` entry with no `mergedAt`) is one `dropped` row.
5. An open PR that has a refusal is one `open` row carrying the latest refusal's `plainReason` and a how-long-open value derived from its `createdAt`.
6. A PR refused twice then merged is one `merged` row with both refusals folded into `notes` (length 2), never two separate rows.
7. 500 refusals on one PR collapse to one row: `notes` holds only the last few, plus a total count field, never 500 entries.
8. A row whose title can't be resolved from any list shows `#<n> in <repo>` — never a bare number, never `(title unknown)`.
9. `createMrHistory`: the closed-list fetch is incremental — first read asks for everything, a later read asks only since the newest closed PR already cached (mirrors the existing merged-list test at `mr_history.test.js:132`).
10. `createMrHistory`: the closed-list GitHub call failing for one repo still renders merged and open rows from the saved cache, and names the failing repo in `errors` (mirrors the existing "repo that fails is skipped and named" test at `mr_history.test.js:158`, extended to the new source).
11. `createMrHistory`: the saved cache after a refresh with many refusals/closed PRs stays bounded — `JSON.stringify(cache)` size tracks PR count, not refusal count (extends the existing "cache stays small" assertion style at `mr_history.test.js:185`).
12. A corrupt cache rebuilds cleanly with the new `closed` field present (extends the existing corrupt-cache test).
13. `mr_history_view.js`: a new `filterRows(rows, kind)` helper — `'all'`/undefined returns everything; `'merged'`/`'open'`/`'dropped'` returns only that kind; empty input never throws.
14. `MrHistory.jsx` render test: filter chips render all four options; clicking (asserted via the resulting filtered row set, since these are static-markup renders) each chip leaves only rows of that `kind` in the output.
15. `MrHistory.jsx` render test: an `open`-kind row renders its `plainReason` and open-duration text, styled distinctly (amber/⏳) from merged (emerald/✓) and dropped (red/✗).
16. `MrHistory.jsx` render test: a row's notes line renders as "Approve refused Nx: reason1, reason2" when `notes` is present, and nothing extra when absent.

Not unit-testable (no existing coverage for `index.js`'s IPC-handler bodies anywhere in this codebase — confirmed by grep; `error_log.test.jsx` only tests the generic error-wrapper, never real handler logic): the `mr:historyDetail` branch that gives an `OPEN`-state PR the live, approvable card (real `canMerge`) versus forcing `merged`/`closed` PRs read-only. This will be verified by hand — opening a real still-open history row with a refusal and confirming Approve/Deny render, then opening a merged and a dropped row and confirming both show the read-only badge — alongside the required light/dark screenshots.

No Decisions section: every open question in the ticket (collapse threshold, exact open-duration wording, which file literally hosts the filter chips) is a cosmetic implementation detail with no user-facing fork worth asking Gil about; nothing here blocks on his input.

## Task List

1. `mr_history.js`: add `closedPrArgs(repo, since)`, mirroring `mergedPrArgs` (`--state closed`, `number,title,url,closedAt,mergedAt`, same since/day math).
2. `mr_history.js`: rewrite `buildRows(merged, history, openPrs, closedPrs = [])` to build a `Map` keyed by PR url — dropped rows from `closedPrs` (no `mergedAt`), then open rows from `openPrs` entries that have at least one refusal, then merged rows from `merged` (overwriting any dropped/open entry for the same url) — then fold every refusal into its matching row's `notes` (collapsing beyond a display limit into a count + last few), setting `plainReason` from the latest refusal only on `open`-kind rows. Title fallback becomes `#<n> in <repo>`.
3. `mr_history.js`: extend `createMrHistory` to accept a closed-list fetcher, maintain `cache.closed` with the same incremental-since-newest pattern as `cache.merged`, include it in `saveCache`, and pass it into `buildRows`.
4. `index.js`: wire the new closed-list fetcher (`ghOut(closedPrArgs(...))`) into `createMrHistory`; switch its `openPrs` source from `listOpenPrs({ light: true })` to `listOpenPrs()` so `createdAt` is available and the fetch is shared with the Open tab's existing cache.
5. `index.js`: factor the Open tab's `listPipelinePrs` options object (currently inlined at `mrList`, `index.js:1117`) into a shared value; reuse it in `mr:historyDetail` when the live PR's `state === 'OPEN'` (real `canMerge`, `readOnly: false`), keeping the current forced-read-only path for `MERGED`/`CLOSED`.
6. `mr_history_view.js`: add `filterRows(rows, kind)`.
7. `MrHistory.jsx`: add filter chips (All/Merged/Still open/Dropped) driving `filterRows` ahead of `groupByDay`; update `HistoryRow` to branch styling/icon on `kind` (merged ✓ emerald, open ⏳ amber, dropped ✗ red), render the notes line, and render `plainReason` + open-duration for `open` rows.
8. `MrReview.jsx`: update `openRow` so an `open`-kind row's refusal banner data (`pr.refusal`) is built from the row's latest note/`plainReason` instead of the now-removed `'refused'` kind.
9. Run the full dashboard test suite; add/confirm the tests listed above pass.
10. Manually run the dashboard, exercise a real (or fixture-backed) still-open PR with a refusal, a merged PR, and a dropped PR through the Merged view and each filter chip; capture light and dark screenshots per the acceptance criterion.