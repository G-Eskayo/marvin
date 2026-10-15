**Backend (already correct in this worktree — keep, no changes)**
1. `dashboard/electron/main/needs_you.js`: `projectFor` + `rankNeedsYou(projects)` — keep as-is.
2. `dashboard/electron/main/relations_service.js`: `overview()`/`needsYou()` passing `getProjects()` through — keep as-is.
3. `dashboard/test/needs_you.test.js`, `dashboard/test/relations_service.test.js`: keep the already-added cases; add the 0/11-item pagination edge case noted in item 5 above to `needs_you_view.test.js` instead (it's a frontend pure-function concern).

**Frontend — pure helpers (`dashboard/src/lib/needs_you_view.js`, already mostly correct — keep, extend)**
4. Keep `paginate`, `sortRows`, `pillFor`, `projectName`, `readSortChoice`, `writeSortChoice` as-is (already correct and tested).
5. Rewrite `mergeNeedsYouResult` to accept and track a request sequence so overlapping resolutions can be adjudicated purely: `mergeNeedsYouResult(prev, result, { now, seq, latestSeq })` (or equivalent) — stale (`seq < latestSeq`) results are dropped entirely, not merged.
6. `dashboard/test/needs_you_view.test.js`: keep existing coverage; add the 0/11-row pagination cases (item 5) and the overlap-guard cases (item 13) for the revised `mergeNeedsYouResult`.

**Frontend — component (`dashboard/src/components/NeedsYouList.jsx` — fix the three bugs, do not just re-skip)**
7. Fix the saved-state read: `saved ? { rows: saved.value?.rows ?? [], error: null } : { rows: [], error: null }`, matching `MetricsPage.jsx`'s pattern exactly.
8. Fix the trigger subscription to the real one-argument API: `useEffect(() => window.api.triggers.on((t) => (t.topic === 'activity' || t.topic === 'mr') && load()), [])` — delete the invented `{ cancelled }` option and the second `triggers.on` call.
9. Add a request-sequence `useRef` counter in `load()`: increment on each call, pass the captured token through to the new `mergeNeedsYouResult` signature, so a stale response is dropped instead of overwriting newer state.
10. Keep the `setInterval` "keeps 'updated X ago' honest" tick — this matches the established convention identical in `MetricsPage.jsx:57` and `ProjectBoard.jsx:80`; it is not a defect, and the prior design doc's instinct to treat it as a hang risk was wrong (confirmed: no test exercises a mount, so it's never created during the test run either way).
11. Keep pagination (5/page), sort control (4 options), empty state, row click → `onOpenTicket(row.repo, row.number)` — unchanged from the prior attempt's design, which was correct here.

**Frontend — component tests (`dashboard/test/needs_you_list.test.jsx` — remove every `.skip`, fix the wrong assertions underneath them)**
12. Replace the file's skipped tests with real, passing ones asserting only synchronously-reachable states (no effect required): no saved data → "Reading what needs you…" (not "Nothing needs you" — the prior attempt's skipped assertion was actually wrong, which is likely why it got skipped instead of fixed); saved data with populated rows → pill/title/project/ask/unblocks render (direct Bug A regression test); saved data with an empty rows array → "Nothing needs you"; saved envelope present but `value.rows` missing (Bug A regression, item 9); malformed JSON → same as no-saved-data case; `triggers.on` called with a single-argument predicate (Bug C regression, item 12).

**Wiring (already correct in this worktree — keep)**
13. `dashboard/src/components/DashboardHome.jsx`: `onOpenTicket` prop + `<NeedsYouList boards={cards} onOpenTicket={onOpenTicket} />` placement above "Project Boards" — keep as-is.
14. `dashboard/src/components/ActivityBoard.jsx`: pass `onOpenTicket` through to `DashboardHome` — keep as-is.

**Done-when evidence (not automatable, listed so it isn't dropped)**
15. Simulator/app screenshots in the PR: list populated, list empty, a ticket opened from a row, and the sort control actually changing the order and resetting to page 0 on click (item 18, verified manually since it can't run under this test harness).