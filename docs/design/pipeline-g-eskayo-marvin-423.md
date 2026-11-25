## North-star fit

**Reuses, before adding anything new:**
- `prKey(repo, number)` (`dashboard/electron/main/mr_repos.js:9`) for row identity — the exact key format `OpenPrs`'s existing deep-link effect already matches against (`MrReview.jsx:731-735`, built for Activity-board → PR jumps). Routing a clicked "open" row through that effect (switch to the Open tab, feed it a `{prKey, at}` nav object) needs zero new navigation code.
- The incremental "fetch everything once, then only since the newest known date" loop already written for merged PRs (`mr_history.js:70-77`) — generalized into one helper and reused for the new closed-PR fetch instead of copy-pasting it.
- `ViewToggle`'s `aria-pressed` button styling (`MrReview.jsx:593-602`) for the new All/Merged/Still open/Dropped chips.
- `groupByDay`/`pageOf` (`mr_history_view.js`) as the home for a new pure `filterByKind` helper — same file, same shape.
- The "extract branching logic as a plain exported function instead of simulating clicks" convention this codebase already uses (`statusFromOp`, `displayTitle`) — the new open-vs-read-only click decision becomes `historyRowTarget(row)`, not new click-simulation test infra (there isn't any in this codebase).
- `MrDetail.jsx`'s existing single `pr.refusal` box is reused unchanged — a merged/dropped row's notes feed it just the latest note; **no change needed to `MrDetail.jsx` at all**.

**Simplest sufficient approach:** everything above means the only files that actually change are `mr_history.js`, `mr_repos.js` (one field), `MrHistory.jsx`, and the thin `openRow` wiring in `MrReview.jsx`. No new shared module, no new IPC channel, no change to `MrDetail.jsx` or the merge gate.

**One deliberate deviation from the ticket's literal text:** it names the function `buildRows(merged, history, openPrs)`, but "dropped" rows need a closed-PR list from somewhere — I'm extending it to `buildRows(merged, history, openPrs, closedPrs)`. Mechanical necessity, not a design fork, so it's not a Decision.

**Where it spends vs. saves:** adding `createdAt` to the *light* open-PR fields (`mr_repos.js:53`) costs a few bytes on a call that's already polled every minute — but it's cheaper than the alternative (a brand-new `gh pr list` round trip just for the Merged tab's "open" rows). The new closed-PR fetch is a genuinely new GitHub call, but it only happens when the Merged tab does a fresh read, not on a poll, and it's incremental after the first read, exactly like the merged list.

**Phone-OS fit:** none directly — this is a dashboard-only reliability/clarity fix.

**More capable or more passive:** more capable — Gil currently can't tell a stuck-open PR from an abandoned one without opening each row; this makes the three outcomes (and which still need him) visible at a glance, and lets him act on the stuck one directly instead of going to GitHub.

No north star argues against this work.

**No Decisions section** — every fork below resolves against an existing pattern or documented convention (see reuses above); nothing is a genuine open choice for Gil.

## Tests first

In `dashboard/test/mr_history.test.js` (the old `kind:'refused'`/`(title unknown)` tests get replaced, not kept — the whole point of this ticket is that those are gone):

**From "How we'll try to break it":**
1. A refusal whose `pr_url` doesn't match `PR_RE` → dropped, no row, no throw.
2. A refusal whose PR is in neither merged, open, nor closed → dropped silently (no row at all — not even a bare-number placeholder).
3. Same PR present in `merged` and in a **stale** `closedPrs`/cache-closed entry (closed, reopened, then merged) → exactly one row, `kind:'merged'`.
4. 500 refusals on one PR → exactly one row, `notes` capped to a small count, with the total preserved somewhere on the row (not silently lost).

**Generic adversarial checklist (bad/empty/huge/malformed, dependency failures, repeats/concurrency, stale state, person's mistakes):**
5. Empty everything: `buildRows([], {merges:[],refusals:[]}, [], [])` → `[]`, no throw.
6. A merged/open/closed PR entry with a falsy/empty `title` → row title is `#<n> in <repo>`, never blank or bare.
7. Closed-PR fetch throws for one repo → `errors` names it; merged and open rows still render from cache (mirrors the existing "a repo that fails is skipped and named" test, extended to the new fetcher).
8. `openPrs()` throws entirely → refresh doesn't crash; no `open`-kind rows (nothing to match refusals against), merged/closed still render.
9. Concurrent `fresh:true` reads share one in-flight fetch, and the closed-PR fetcher is called exactly once too (extend the existing "simultaneous refreshes share one fetch" test).
10. Refusals arrive out of chronological order in `history.refusals` → the row's latest note (and an `open` row's displayed reason) is picked by timestamp, not by array order.
11. A refusal entry missing `t` (malformed/partial write) → doesn't crash the sort, sorts last.
12. Stale `closed` cache entry for a PR that's currently **open** (closed → reopened, never merged) with refusals against it → renders as `kind:'open'`, not `'dropped'` (precedence: merged > open > dropped, tested as its own case distinct from #3).
13. Wrong permissions/machine: not applicable — no new privileged action, same `gh`/webhook reads as today; stated rather than faked.

**`mr_repos.js` / `pr_list_args.test.js`:**
14. Update the two tests pinned to the light field list (`'number,title,url'`) to expect `createdAt` added, with an explicit comment why (status-dot payload still has no `body`/`files`/`labels`/`isDraft`).

**`MrHistory.jsx` / `mr_history_view.js` rendering:**
15. `filterByKind(rows, 'open')` etc. — pure filter, each chip returns only its kind, `'all'` returns everything.
16. `HistoryRow` for a `dropped` row renders ✗ and a dropped label, never crashes on a row with no `by`.
17. `HistoryRow` for an `open` row renders its latest reason and how long it's been open, plus a "refused N×" notes line when N > 1.
18. `historyRowTarget(row)` — the extracted pure decision: `kind:'open'` → `{jump: prKey}`, `kind:'merged'|'dropped'` → `{detail: url, refusal: latestNote}`.

**Real-app check (not a unit test):** screenshots of the Merged tab (All/Merged/Still open/Dropped chips, light and dark) via the `run` skill, attached to the PR per the acceptance criteria — can't be faked by a passing suite.

## Task List

1. `mr_repos.js`: add `createdAt` to `prListArgs`'s light field list; update `pr_list_args.test.js` and the one `mr_actions.test.js` assertion that pins the light field string.
2. `mr_history.js`: add `closedPrArgs(repo, since)` mirroring `mergedPrArgs`; factor the existing per-repo incremental-accumulate loop into a small shared helper, call it for both merged and closed.
3. `mr_history.js`: rewrite `buildRows(merged, history, openPrs, closedPrs)` — build the four row kinds with the precedence rules (merged > open > dropped), title fallback `#<n> in <repo>`, notes capped-with-total, latest-note-first sorting, orphan-refusal dropping.
4. `mr_history.js`: extend `createMrHistory`'s `refresh()` to accept and persist a `closedPrs` fetcher, add `cache.closed` alongside `cache.merged`, update `next.open`'s saved shape to carry `number`, `repo`, `createdAt` (not just `url`/`title`).
5. `electron/main/index.js`: wire `closedPrs: async (repo, since) => JSON.parse((await ghOut(closedPrArgs(repo, since))) || '[]')` into the existing `createMrHistory({...})` call; filter out any entry with a non-null `mergedAt` defensively.
6. `mr_history_view.js`: add `filterByKind(rows, kind)`.
7. `MrHistory.jsx`: add filter chips (reusing `ViewToggle`'s button styling), local `age`-style "open for" helper, update `HistoryRow` for the three kinds and the notes line.
8. `MrReview.jsx`: extract `historyRowTarget(row)`; rewire `openRow` to either jump into the Open tab via the existing `nav.prKey` deep-link (reusing `OpenPrs`'s effect untouched) or call `historyDetail` and attach only the latest note as `pr.refusal` (no `MrDetail.jsx` change).
9. Update `mr_history_render.test.jsx` for the new row shapes/kinds; add the new unit tests from the list above to `mr_history.test.js`.
10. Run the full dashboard test suite; launch the real app via the `run` skill, exercise all three outcomes and the filter chips in light and dark, capture screenshots, attach via `marvin-show`/PR images per the repo's PR-image rule.
11. Open the PR against #423, naming it as the closing ticket.