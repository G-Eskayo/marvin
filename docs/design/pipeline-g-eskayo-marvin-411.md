Write access is blocked in this session, so here's the full revised plan as text instead of a file.

## North-star fit

**Reuses, confirmed by re-reading the code just now, not assumed from the last doc:** the ranked backend (#330/#371), the full renderer wiring (`ActivityBoard.jsx` → `DashboardHome.jsx` → `<NeedsYouList>`), and `usage_view.js`'s `agoText` are all in place and unchanged. More importantly: **`relations_service.js`'s count-parity fix from the last attempt is already correct and already tested** — `build()` computes `needsYouByRepo[repo] = rankNeedsYou(repoTickets).length` inside the per-repo loop (line 26), `overview()` reads only that map (no card-based tally, no `Math.max`), and `relations_service.test.js` has three passing tests pinning exactly the `pinned`+`ready-for-human` inflation case the old must-fix #1/#2 pointed at. **This attempt does not touch `relations_service.js` or its test file** — re-fixing something already shipped would waste tokens.

The ticket carries no self-stated north-star fit to correct.

**Simplest sufficient approach:** the 3 remaining must-fix defects are all in `needs_you_view.js` (`readCache`) and `NeedsYouList.jsx` (empty/error state):
- Structural cache fields (`unblocks.count`, `unblocks.items` — both drive sort and the "Unblocks N" line) keep rejecting the whole row, same severity as the existing `number`/`repo` checks.
- Cosmetic cache fields (`priority` — sort/display only) normalize to the existing "no value" sentinel (`null`) instead of discarding a real waiting-on-you row over a corrupted pill — matching this file's own existing precedent for `project` ("cosmetic, not a validity requirement").
- The error-vs-empty text bug in `NeedsYouList.jsx` gets pulled out as named pure functions in `needs_you_view.js`, next to `pillStyle`/`kindLabel`, which already do exactly this job. This isn't scope creep — it's the only way to get a deterministic regression test: this project's `*.test.jsx` files render with `react-dom/server` (`renderToStaticMarkup`), which never runs `useEffect`, so a bug that only shows up after a fetch rejects is untestable as JSX unless the decision logic is extracted first.

**Tokens:** two files touched, no backend change, no new modules/IPC/UI. Each new function is a few lines paired with 1-4 direct unit tests — the cheapest test shape this codebase has.

**User capability:** unchanged (pure surfacing), but correctness here *is* a north-star-3 point: telling Gil "Nothing needs you right now" when the real answer is "the fetch failed, I don't know" is a false reassurance that would make him check less, not more.

No north star argues against finishing this fix pass.

---

## What's still broken (confirmed by reading the current working tree)

| File:line | Bug |
|---|---|
| `NeedsYouList.jsx:115-119` | Empty-state text when `status === 'error'` and `rows.length === 0` falls into the `else` branch → "Nothing needs you right now." (false negative). |
| `NeedsYouList.jsx:84` `freshness()` | Same path: `lastUpdated` is `null`, so the ternary's `else` picks the literal `'earlier'` → "update failed — showing data from earlier" when there's no earlier data at all. |
| `needs_you_view.js:86` `readCache` | Filter checks `Array.isArray(r.unblocks.items)` but never `r.unblocks.count`. A row with a missing/non-numeric `count` passes, making `sortRows(..., 'unblocks', ...)`'s `b.unblocks.count - a.unblocks.count` go `NaN` for that pair, and rendering `undefined` in the "Unblocks N" line. |
| `needs_you_view.js:86` `readCache` | No check on `priority` at all. A value not shaped `p[0-3]` (the only backend guarantee, from `needs_you.js:142`'s `getPriority`) passes through, and `sortRows(..., 'priority', ...)`'s `parseInt(a.priority[1])` goes `NaN`. |

Also still missing — not code-review items, but Gil's own comment feedback, which counts as a requirement for this attempt: tests for "the saved list renders before the refresh resolves" and "a refresh failure keeps the saved list and shows its age." Both are true in the running app already, just untested, for the same reason as above (logic is inline, effects don't run in tests). Fixed by the same extraction.

**Deliberately not touched this round** (real but not must-fix, not re-promised after the last doc/diff mismatch): `resolveProject` always-truthy blank "Project:" line; dead `latestReqId` state; unused third arg on `writeCache(...)`; `refresh()` sorting with a stale `sortKey` closure; prev/next clamping against `prev.page`. Listed so they aren't silently lost, but out of scope here.

---

## The fix

**`dashboard/src/lib/needs_you_view.js`**

```js
export function readCache(storage) {
  try {
    const stored = storage?.getItem?.('needsYouCache')
    if (!stored) return []
    const data = JSON.parse(stored)
    if (!Array.isArray(data)) return []
    return data
      .filter((r) => r && typeof r.number === 'number' && typeof r.repo === 'string' &&
        r.unblocks && typeof r.unblocks.count === 'number' && Array.isArray(r.unblocks.items))
      .map((r) => (/^p[0-3]$/.test(r.priority) ? r : { ...r, priority: null }))
  } catch {
    return []
  }
}

export function initialViewState(storage) {
  const cached = readCache(storage)
  return {
    rows: cached,
    sortKey: readSortPref(storage),
    lastUpdated: null,
    status: cached.length > 0 ? 'ok' : 'loading',
    error: null,
    page: 1,
    latestReqId: 0
  }
}

export function applyFetchError(prevState, message) {
  return { ...prevState, status: 'error', error: message }
}

export function emptyStateText(status) {
  if (status === 'loading') return 'Loading…'
  if (status === 'error') return "Couldn't check what's waiting on you — try again shortly."
  return 'Nothing needs you right now.'
}

export function freshnessText({ status, error, lastUpdated, now = Date.now() }) {
  if (error) return lastUpdated ? `update failed — showing data from ${agoText(now - lastUpdated)}` : 'update failed'
  if (status === 'loading') return 'updating…'
  if (lastUpdated) return `updated ${agoText(now - lastUpdated)}`
  return 'loading…'
}
```

Adds `import { agoText } from './usage_view.js'` to this file.

**`dashboard/src/components/NeedsYouList.jsx`**
- `useState(() => initialViewState(storage))` replaces the inline initializer.
- `catch (e) { ... setState((prev) => applyFetchError(prev, String(e.message || e))) }`.
- Empty-state paragraph → `{emptyStateText(status)}`.
- `freshness()` body → `freshnessText({ status, error, lastUpdated })`; drops its now-unused local `agoText` import.

No other line in either file changes.

---

## Tests to write FIRST (all in `dashboard/test/needs_you_view.test.js`)

**Regressions for the 3 must-fix defects:**
1. `readCache` drops a row with missing `unblocks.count`.
2. `readCache` drops a row with non-numeric `unblocks.count` (e.g. `'3'`).
3. `readCache` normalizes malformed `priority` (`'urgent'`, `'p9'`, `'P0'`, `5`, `{}`) to `null`, keeps the row.
4. `readCache` leaves valid `priority` (`'p0'`..`'p3'`) unchanged.
5. `readCache` normalizes a row with no `priority` field to `null` (parity with the existing "missing `project`" test).
6. `emptyStateText('error')` ≠ `'Nothing needs you right now.'`.
7. `emptyStateText('loading')` / `emptyStateText('ok')` unchanged.
8. `freshnessText({status:'error', error:'boom', lastUpdated:null})` === `'update failed'` exactly — the literal quoted bug.
9. `freshnessText({status:'error', error:'boom', lastUpdated:<ts>})` still shows `"...showing data from Xs ago"`.
10. `freshnessText` loading/ok branches unchanged.

**Comment-mandated cases now testable via extraction:**
11. `initialViewState` on empty cache → `status:'loading'`, `rows:[]`.
12. `initialViewState` on cache with 2 valid rows → `status:'ok'`, `rows` = cached ("saved list renders before refresh resolves").
13. `applyFetchError(prevState, 'boom')` leaves `rows`/`lastUpdated` untouched, only flips `status`/`error` ("refresh failure keeps the saved list and shows its age").

**Already covered, re-verified by reading the suite, not re-derived:** pagination edges, all 4 sorts incl. no-board-name crash guard, sort-pref round-trip/fallback, `shouldApply`, existing `readCache` null/corrupt/wrong-shape/missing-number/repo/unblocks/project cases (`needs_you_view.test.js`); `rankNeedsYou`/`missingFor`/`blocksGraph`/`transitiveUnblocks` misuse cases (`needs_you.test.js`); `relations_service.js` count-parity incl. `pinned` case across 1 and 2 repos (`relations_service.test.js`). Nothing to add there.

**Verify gate:** any future change to `readCache`'s normalization rules or to `emptyStateText`/`freshnessText`'s branches must move at least one of the above assertions — none depend on incidental formatting.