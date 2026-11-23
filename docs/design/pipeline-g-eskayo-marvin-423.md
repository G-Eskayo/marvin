## North-star fit

**Reuses before adding anything new:**
- `dashboard/electron/main/mr_history.js` `buildRows`/`mergedPrArgs`/`plainReason`/`createMrHistory` — the whole feature already exists for merged+refused rows; this ticket extends it rather than building parallel machinery.
- `dashboard/electron/main/index.js` `pipelineCardFromMemory(url)` / `mrList` (coalesced open-PR builder, lines 1099‑1120) — the exact "one open PR, fully built and mergeable" accessor already used by local-first actions. Reusing it for "open row → live detail" means zero new detail-rendering code and zero new readOnly/mergeable branching logic.
- `OpenPrs`'s existing nav deep-link contract (`nav.prKey`/`nav.at`, `MrReview.jsx:730‑735`) is *not* used — `pipelineCardFromMemory` via `mr:historyDetail` is simpler and doesn't require flipping the visible tab.
- `dashboard/electron/main/mr_repos.js` `prListArgs`'s existing "full" (non‑light) field set already carries `createdAt` — switching `openPrs` from `listOpenPrs({light:true})` to `listOpenPrs()` gets "how long open" for free, with **no change** to the shared `light` contract (which two existing tests assert verbatim and which the 2‑minute status-dot poll depends on for cost).
- `dashboard/src/lib/mr_history_view.js` (`groupByDay`/`pageOf`) is already the pure, tested home for this view's display logic — new pure helpers (`openDuration`, `notesLine`) belong there, not duplicated as a third "age" formatter (one already exists in `saved_state.js` `ageText`, a second, slightly different one lives locally in `MrHistory.jsx`; neither fits "open for N days" phrasing, so a third narrow, single-purpose helper is added rather than reused/refactored — touching the other two is out of this ticket's scope).
- `lib/mr_raiser.py` `_subject()` already titles new PRs after their ticket (ticket confirms this) — **no change needed there**; only the dashboard-side fallback text changes.

**Simplest sufficient approach:** one data function (`buildRows`) gains a `closed` input and groups refusals into `notes` instead of synthesizing rows; one IPC handler (`mr:historyDetail`) gains a "is it still in the live Open list?" check before falling back to the existing read-only `gh pr view` path; one new args builder (`closedPrArgs`) mirrors `mergedPrArgs` exactly. No new storage layer, no new tab, no new IPC channel.

**Resource cost:** the only new GitHub traffic is one `gh pr list --state closed` per repo per history refresh (incremental via `--search closed:>=`, same pattern as merged), and switching `openPrs` from light to full fields (cheap scalar `createdAt`, not the expensive `files`/`statusCheckRollup` fields the light/full split exists to avoid). `mr:historyDetail` reuses the already-coalesced `mrList()` instead of a second full rebuild.

**Phone-OS direction:** neutral — this is a desktop-dashboard correctness fix, not a reachability change.

**More capable, not more passive:** directly serves it — today a stuck-but-open PR (#359/#368/#400) is indistinguishable from an abandoned one, so Gil can't tell what needs him. One row per PR, with an honest outcome and a live Approve/Deny on the ones still waiting on him, puts the decision back in his hands instead of hiding it in noise.

No open decisions for the owner — every choice below (note ordering, duration wording, no chip-state persistence) is a cosmetic internal call resolvable from the ticket text and existing conventions, not a design fork.

## Tests to write first

In `dashboard/test/mr_history.test.js` (extends/rewrites existing `buildRows`/`createMrHistory` suites — the signature change is intentional per this ticket):
1. A refusal whose `pr_url` fails `PR_RE`, or whose PR is in none of merged/open/closed → produces no row at all (replaces the old "orphan refusal still gets a row" test, which the new spec explicitly forbids).
2. A PR present in both `merged` and `closed` (closed-then-reopened-then-merged) → exactly one row, `kind:'merged'`.
3. `ghListClosed` throwing for one repo → that repo's error is recorded, merged/open rows for other repos still render (mirrors the existing `ghList`-fails test).
4. The webhook (refusals/merges) unreachable → merged and open rows still render from the saved cache (extends the existing "webhook unreachable" test to also assert closed/open survive).
5. A PR refused twice then merged → one `merged` row, `notes.length === 2`.
6. A PR closed without merging and never refused → one `dropped` row with no notes.
7. An open PR refused once → one `open` row, `reason`/`notes[0].reason` is the latest refusal's plain reason, `createdAt` carried through.
8. 500 refusals on one PR → `buildRows` still returns exactly one row with `notes.length === 500` (no crash, no row explosion); a separate `notesLine` test confirms the *display* string collapses to a count plus the last 3.
9. Missing/malformed refusal fields (`null` `t`, missing `code`, non-string `pr_url`) → skipped, never throws (extends existing malformed-refusal coverage).
10. Title fallback: a merged/open/dropped PR with no readable title → `#<n> in <repo>`, never a bare number or `(title unknown)`.
11. Simultaneous `refresh()` calls (merged + closed + webhook) → one shared fetch per dependency, cache not corrupted (extends existing "simultaneous refreshes share one fetch" test to also cover the new closed-list fetch).
12. A corrupt or missing cache → rebuilt cleanly with the new `closed` key present and an empty array, not a crash.
13. `closedPrArgs(repo, since)`: first read asks for everything; a later read asks only `closed:>=<day>` (mirrors the existing `mergedPrArgs` test).

In a new/extended pure-logic test file for `dashboard/src/lib/mr_history_view.js`:
14. `openDuration(createdAt, now)`: correct "N h"/"N day(s)" text; `null`/unparseable `createdAt` → `null`, never `NaN` or a throw.
15. `notesLine(notes, max)`: `null`/empty `notes` → `null`; ≤3 notes → all shown; >3 → count + last 3 + "+N more", never throws on a huge array.
16. A `filter` of `'open'`/`'dropped'`/`'merged'`/`'all'` applied to a mixed row list → only matching rows pass through; a filter with zero matches → the existing "nothing yet" empty state, not a crash.

In `dashboard/test/mr_history_render.test.jsx`:
17. `HistoryRow` renders ⏳ for `kind:'open'` and ✗ for `kind:'dropped'` (✓ stays for `merged`), and the notes line under a row with notes.
18. Filter chips (All/Merged/Still open/Dropped) render, and clicking one narrows `HistoryList`'s visible rows.

In `dashboard/test/mr_actions.test.js` or a new `mr_history_detail.test.js` (whichever already exercises `index.js`'s IPC wiring — read it once to confirm the right home before adding):
19. `mr:historyDetail` for a PR still in the live open-PR set → returns the normal mergeable card (no `readOnly`), unaffected by which `row.kind` the renderer thought it was.
20. `mr:historyDetail` for a PR no longer in the live open set (merged/closed, or raced away between the history read and the click — "a person's mistake"/stale state) → falls back to the existing read-only `gh pr view` path, never throws.
21. `mr:historyDetail` called for a url `repoFromPrUrl` can't parse → still throws the existing `'not a PR url'` error (unchanged behavior, regression-guard).

In `MrReview.jsx`'s render test (extend #17/#18's file or a new one):
22. Clicking an `open` row shows live `ApproveDenyActions` (not the read-only badge); clicking a `merged`/`dropped` row still shows `data-readonly="1"`.
23. Submitting Decisions from an open row opened this way updates the shown PR in place (via `onChanged`), same contract `reloadKeepSelected` already uses elsewhere.

## Task List

1. `mr_history.js`: add `closedPrArgs(repo, since)` (mirrors `mergedPrArgs`, fields `number,title,url,closedAt,mergedAt`).
2. `mr_history.js`: rewrite `buildRows` to accept `{ merged, closed, openPrs, history }` and produce `kind: 'merged'|'open'|'dropped'` rows, grouping every matched refusal into that PR's `notes: [{at, reason}]` (newest first), with the merged-wins-over-closed dedupe and the "no match anywhere → dropped from the view" rule.
3. `mr_history.js`: update the title fallback everywhere to `#<n> in <repo>` (drop `(title unknown)`).
4. `mr_history.js`: `createMrHistory` — add an optional `ghListClosed` dependency (default no-op), fetch per-repo incrementally like the merged list, catch per-repo errors into `errors`, persist `cache.closed`, and call the new `buildRows` shape in both `refresh()` and the non-fresh cache-read path.
5. `dashboard/src/lib/mr_history_view.js`: add `openDuration(createdAt, now)` and `notesLine(notes, max=3)`, plus a small `filterRows(rows, filter)` (or equivalent) for the chip filter.
6. `dashboard/electron/main/index.js`: wire `closedPrArgs`/`ghListClosed` into the `createMrHistory({...})` call; switch its `openPrs` dependency from `listOpenPrs({ light: true })` to `listOpenPrs()` (full fields, for `createdAt`); update `createMrHistory`'s `refresh()` open-map to also carry `createdAt`.
7. `dashboard/electron/main/index.js`: change `mr:historyDetail` to first check whether the url is in the live, already-coalesced `mrList()` result and return that (mergeable, not `readOnly`) before falling back to today's `gh pr view` read-only path.
8. `dashboard/src/components/MrHistory.jsx`: update `HistoryRow` for the three kinds (✓/⏳/✗, trailing column text, notes line via `notesLine`), add the All/Merged/Still open/Dropped filter chips wired to `filterRows`.
9. `dashboard/src/components/MrReview.jsx`: update `openRow` to drop the old `kind === 'refused'` branch; for `kind === 'open'` attach the latest note as `pr.refusal` for the existing red banner. Wire `onApproved`/`onDenied`/`onChanged` on the `historyPr` `<MrDetail>` render (no-ops for the read-only merged/dropped case, real behavior for `open`).
10. Run the full dashboard test suite; take light/dark screenshots of the Merged view (All chip, Still open chip showing an open-with-reason row, and the live detail opened from an open row) via `marvin-show` for the PR, per the acceptance criteria.