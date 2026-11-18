## North-star fit

**Reuses:** the detail view's existing read-only path, `dashboard/src/components/MrDetail.jsx:265-271` (`pr.readOnly` ⇒ a "Merged … · read-only" / "closed · read-only" badge instead of `ApproveDenyActions`), already shipped and tested for the Merged/refused history view (marvin#419, `dashboard/test/mr_history_render.test.jsx:67-85`). It also reuses the exact IPC call that produces that shape for a single PR, `window.api.mr.historyDetail` → `mr:historyDetail` (`dashboard/electron/main/index.js:1031-1038`), already wired for `MrHistory`'s row-open and for `WorkshopItem.jsx:149`'s closed-PR card. And it reuses the per-repo fetch-failure signal already tracked for #422 (`prFetch.errors`, `dashboard/electron/main/index.js:262-281`, surfaced as `window.api.mr.listStatus()`), so a repo whose GitHub read failed this round is never mistaken for "the PR is gone."

Net new code is small: one pure decision function plus a thin wire-up in `OpenPrs` (`dashboard/src/components/MrReview.jsx:666-759`). No change to `MrDetail.jsx`, `ApproveDenyActions`, or the backend merge gate — the gate already refuses non-open PRs per the issue's own "Fix" note, confirmed by `webhook-server/index.js:497`'s comment that the merge queue already drops a PR that "merged or closed meanwhile."

**Why simplest sufficient:** the bug is one line — `MrReview.jsx:695`, `setSelected((cur) => (cur ? list.find((p) => p.key === cur.key) || cur : cur))` — falling back to the stale `cur` when the PR is missing from the fresh list, with no attempt to find out why it's missing. The fix is to replace that blind fallback with a three-way decision (still open / can't tell this round / genuinely gone) and, only in the last case, ask GitHub once via the already-existing `historyDetail` call. No new UI, no new backend endpoint, no new data shape.

**Token/resource cost:** one extra GitHub read (`gh pr view`) per PR, only the first refresh tick after it's confirmed gone (guarded so it doesn't repeat every tick once the view is already read-only, and deduped against overlapping in-flight refreshes). Spends a little to stop something worse: today Approve on a stale closed PR runs the full local preflight and merge gate for nothing.

**Phone-OS direction:** more reliable (a view never silently shows a dead action), which is the stated precondition for north star 2 — nothing may break silently.

**User impact:** purely corrective — removes a misleading enabled button; doesn't change what the user has to do themselves. More capable (no wasted click, no confusing "Approve failed" after the fact), not more passive.

## Files already read

- `dashboard/src/components/MrReview.jsx` (full `OpenPrs`, `ViewToggle`, `MrReview`, `PrCard`, `ApproveDenyActions`)
- `dashboard/src/components/MrDetail.jsx` (full)
- `dashboard/electron/main/pr_order.js`, `dashboard/electron/main/merge_ops.js` (the lines the issue cited)
- `dashboard/electron/main/index.js` (`mr:list`, `mr:historyDetail`, `mr:listStatus`, `fetchOpenPrs`/`prFetch`, `checkMergedElsewhere`)
- `dashboard/electron/preload/index.js` (`window.api.mr.*`)
- `dashboard/test/mr_history_render.test.jsx` (confirms the read-only rendering is already shipped/tested)
- `dashboard/webhook-server/index.js` (confirms the merge queue already drops closed/merged PRs — W5.5)

## Tests to write first

In a new `dashboard/test/selected_after_refresh.test.js` for a new pure function `selectedAfterRefresh(cur, list, fetchErrors)` (new file `dashboard/src/lib/selected_after_refresh.js`):

1. **Still open:** `cur` present in `list` by key → returns the fresh list entry (`kind: 'open'`), even if other fields on it changed (e.g. new `checkedAt`).
2. **Genuinely gone, clean read:** `cur` absent from `list`, `fetchErrors` is `[]` (or has entries for *other* repos only) → `kind: 'check'` (caller must ask GitHub).
3. **Dependency failing — its own repo's read failed this round (#422):** `cur` absent, `fetchErrors` contains `{repo: cur.repo, ...}` → `kind: 'unknown'` (never guess "closed" from an absence that proves nothing).
4. **Dependency failing — fetch-status itself unknown:** `fetchErrors` is `null`/`undefined` (listStatus rejected or is unavailable) → `kind: 'unknown'`, not `'check'` — don't call GitHub on a guess.
5. **PR reopened after closing (ticket's own break-it case):** `cur.readOnly === true` (already flipped closed last tick) but `list` now contains a fresh open entry with the same key → `kind: 'open'` with the fresh (non-read-only) entry, not the stale closed one.
6. **No selection:** `cur` is `null`/`undefined` → `kind: 'none'`, no crash.
7. **Malformed/stale `cur`:** `cur` missing `.repo` (old shape) → treated as "its repo's failure status unknown" → `kind: 'unknown'`, not a throw.
8. **Empty list:** `list === []` and `cur` present → same as case 2/3 depending on `fetchErrors` (covers the "huge drop to empty" misuse case, e.g. all repos purged at once).

In `dashboard/test/mr_review.test.js` (or a new `dashboard/test/mr_review_selected_sync.test.js` if the render harness differs) — exercising the wiring, not the pure function again:

9. **End-to-end "closed while open": a mocked `window.api.mr.list()` that first returns the PR, then on the next call omits it, with `listStatus()` resolving with no errors for that repo, drives `OpenPrs`'s refresh to call `window.api.mr.historyDetail(url)` exactly once and to re-render without `>Approve<`/`>Deny<` (reusing the existing read-only assertions already proven in `mr_history_render.test.jsx`).
10. **Repeats/concurrency:** two overlapping `reload()` calls (interval tick + pushed `onRefresh` firing back-to-back) for the same just-vanished PR must call `historyDetail` at most once (dedup guard), and must not flip-flop `selected` between the stale and resolved objects.
11. **`historyDetail` itself fails (network/gh failure):** `selected` stays exactly as it was this tick (no crash, no false "closed" label); a later successful refresh tick resolves it correctly (self-heals, never retries forever on a resolved case).
12. **Decisions-submit path (`reloadKeepSelected`) hits the identical "PR vanished mid-submit" case** and resolves the same way as `reload()` — regression-proofing the second call site that had the same `list.find(...) || cur` bug pattern.

## No open decisions

Everything the ticket asks for is answerable from the existing code; no owner choice is needed. (The issue's suggested copy — "Closed on GitHub"/"Merged on GitHub" — is superseded by the already-shipped, already-tested badge copy in `MrDetail.jsx:266-268`; reusing it rather than reinventing wording is a direct application of the reuse-before-building principle, not an open question.)

## Task List

1. Add `dashboard/src/lib/selected_after_refresh.js` exporting `selectedAfterRefresh(cur, list, fetchErrors)` implementing the four-way decision (`open` / `check` / `unknown` / `none`) described above.
2. Write `dashboard/test/selected_after_refresh.test.js` covering tests 1–8; confirm they fail against a stub returning the old "find-or-keep" behavior before implementing, then pass.
3. In `dashboard/src/components/MrReview.jsx`'s `OpenPrs`, add a `selectedRef` (mirroring the existing `prsRef`/`lastSelected` idiom at lines 768-771) and an in-flight dedup ref (e.g. `fetchingDetailFor`).
4. Extract a shared `applyFreshList(list, status)` helper inside `OpenPrs` that: calls `setPrs(list)`; computes `selectedAfterRefresh(selectedRef.current, list, status?.errors)`; on `'open'` sets `selected` to the fresh entry; on `'check'` (and no in-flight call for that url) calls `window.api.mr.historyDetail(cur.url)` and sets `selected` to the result if still the same `cur.key`, swallowing/self-healing on failure; on `'unknown'`/`'none'` does nothing.
5. Rewire `reload()` (lines 685-709) to call `applyFreshList(list, status)` once both `mr.list()` and `mr.listStatus()` have resolved (or `listStatus` rejected → pass `null`), replacing the current line 695 fallback.
6. Rewire `reloadKeepSelected()` (lines 747-759) to call the same `applyFreshList` after its own `mr.list()` resolves, replacing its identical `list.find(...) || cur` fallback.
7. Write the wiring tests (9–12) against `OpenPrs`/`MrReview` with a mocked `window.api.mr` (list/listStatus/historyDetail/markSeen/onRefresh), confirming they fail first against the current code, then pass.
8. Run the full dashboard test suite (not just the touched files) before considering this done, per the "full suites before a hand-merge" rule.
9. Manually drive the app (or a scripted repro): open a PR's detail, close it on github.com, wait for the next refresh tick, confirm Approve/Deny disappear and the read-only badge shows; reopen it and confirm Approve/Deny return.
10. Capture screenshots at 900px and 1440px of the detail view showing the read-only state (and, if feasible, the restored Approve/Deny after reopening) and pin them to the PR, per the acceptance criteria and the screenshot/PR-image rules.
11. Open the PR naming this ticket ("Closes #810"), noting in the description which existing pattern was reused (MrDetail's read-only rendering, `mr:historyDetail`, and the `prFetch.errors`/`listStatus` dependency-failure gate).