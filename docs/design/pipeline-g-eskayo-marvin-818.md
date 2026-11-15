## North-star fit

**Reuses before adding anything new:**
- `dashboard/electron/main/mr_seen.js` (`readSeenNumbers`/`markSeen`) — the exact shape of this problem already solved: a per-viewer, local-only "I've dealt with this" flag persisted as a small JSON file under `app.getPath('userData')`, explicitly reasoned as local-only because cross-device sync of dashboard UI state is "a separate, harder, undesigned problem" (marvin#74). I'll clone that pattern for a `helpers-dismissed.json` file rather than inventing a new persistence mechanism or a cross-Mac write endpoint.
- `dashboard/electron/main/chat_helpers.js`'s `createHelpersReader`/`sortHelpers` pipeline — extended with one more filtering step (dismissed + 24h-crash-expiry + cap), not rebuilt. The merge-then-sort-then-filter happens once, in the main process, so the renderer (`ChatHelpers.jsx`) stays a dumb consumer of an already-correct list, same as today.
- `dashboard/src/components/MrReview.jsx`'s `CorrectionNotice`/`onDismiss` button as the visual/interaction precedent for a one-click dismiss affordance, and `AgentsPanel.jsx`'s existing `bad` status grouping as where the "crashed" check already lives.
- CONTEXT.md's existing "Dismiss and mute" decision for the map (`dismissing... clears that one occurrence`) confirms dismiss-as-per-occurrence (not permanent silencing) is already this codebase's convention — I'm following it, not choosing it fresh.

**Simplest sufficient approach:** no change to `lib/chat_helpers.py` (its `KEEP=30`/`prune()` retention is cited in the ticket only as root-cause evidence, not something to alter) and no new webhook-server write endpoint. All new logic is a display-layer filter in the Electron main process plus one small local JSON file, both direct clones of code already reviewed and merged.

**Tokens:** cheap — reuses two existing, already-tested modules' shape; the only genuinely new code is a ~20-line filter function and a ~15-line persistence module, both pure and easy to unit test, avoiding a slow multi-iteration build/verify cycle (this ticket has already failed 3 verify iterations on "must-fix issues" with no detail left on the issue — most likely scope creep or a missed edge case, which this plan keeps narrow and testable against).

**Phone-OS direction:** neutral-to-positive — one more place where "it just works and gets out of your way" instead of accumulating noise, consistent with a proactive, trustworthy OS-shaped dashboard.

**User capability:** more capable, not more passive — removes a persistent irritant (crashed cards blocking real work) without taking away any information (the full run history is never deleted, only hidden from the home strip).

## Tests to write first

**`dashboard/test/helpers_dismissed.test.js`** (new, mirrors `mr_seen.test.js`):
1. `readDismissed` returns `[]` when the file doesn't exist.
2. `readDismissed` returns `[]` when the file is corrupt JSON.
3. `dismissHelper` persists a key so a later read sees it.
4. Accumulates across calls instead of overwriting.
5. Does not duplicate a key dismissed twice.
6. Creates parent directories that don't exist yet.
7. **Misuse:** a non-string, empty, or absurdly long key is ignored (not written, doesn't throw, doesn't corrupt the file for other keys already stored) — malformed input.

**`dashboard/test/chat_helpers.test.jsx`** (extend, new `filterForHome`-style export in `electron/main/chat_helpers.js`):
8. A crashed helper whose last sign of life is >24h old is dropped; one at 23h59m is kept (boundary).
9. `done` and `failed` helpers are **not** auto-expired at 24h — only `crashed` is (matches the literal acceptance criterion).
10. A dismissed helper (composite key in the dismissed set) is dropped regardless of status or age.
11. **Break it — "crashes, restarts, crashes again":** two crashes from the same chat get distinct composite keys (different agent ids); dismissing the first does not hide the second.
12. **Cap:** 15 finished (crashed/failed/done) helpers → only 10 shown; a card count above 10 running helpers is never trimmed by the cap (running is never hidden).
13. **Clock skew:** a crashed helper with a timestamp in the future (negative age) or outright garbage doesn't throw and is handled deterministically (clamped, not expired).
14. **Dependency failure:** a corrupt/unreadable dismissed-file doesn't break `readHelpers()` — treated as "nothing dismissed," matching `readSeenNumbers`'s existing contract.
15. End-to-end: `createHelpersReader` composes local + remote + dismissed-filter + expiry + cap in one pass (extend the existing "the other Mac" describe block).

**`dashboard/test/chat_helpers.test.jsx`** (`ChatHelpersView` rendering):
16. A `crashed` card renders a Dismiss button; `running`/`done`/`failed` cards do not.
17. Clicking Dismiss calls the handler with the right `${machine}:${id}` key and does not also toggle the card's history-open state (click must not bubble into the card's own `onClick`).
18. **Empty/huge input:** zero helpers, and a list of 100 helpers, both render without error (existing "nothing to show is nothing at all" test extended, plus a cap-boundary render check).

No Python tests are added — `lib/chat_helpers.py` isn't touched; `lib/tests/test_chat_helpers.py`'s existing retention tests stand unchanged.

## Task List

1. **`dashboard/electron/main/helpers_dismissed.js`** (new): `readDismissed(path)` / `dismissHelper(path, key)`, cloned from `mr_seen.js`'s `readSeenNumbers`/`markSeen`, with input validation on `key` (non-empty string, bounded length).
2. **`dashboard/test/helpers_dismissed.test.js`** (new): tests 1–7 above.
3. **`dashboard/electron/main/chat_helpers.js`**: add an exported filter (e.g. `filterForHome(helpers, { dismissed, now, maxAgeMs = 24h, cap = 10 })`) that drops dismissed keys, drops `crashed` helpers older than `maxAgeMs` (clamped against clock skew/garbage timestamps), then caps the non-running remainder to `cap` while never dropping `running` helpers. Wire it into `createHelpersReader` so `readHelpers()` returns an already-filtered list (same `{ helpers, unreachable }` shape — no breaking change to consumers).
4. **`dashboard/test/chat_helpers.test.jsx`**: tests 8–15 above (reader/filter level).
5. **`dashboard/src/components/AgentsPanel.jsx`**: add an optional `onDismiss` prop to `AgentCard`; render a small "Dismiss" button (styled like `MrReview.jsx`'s `CorrectionNotice`) only when `onDismiss` is provided and `agent.status === 'crashed'`; clicking it calls `onDismiss(agent)` with `stopPropagation` so it doesn't toggle the history expander.
6. **`dashboard/src/components/ChatHelpers.jsx`**: pass `onDismiss={(h) => dismiss(h)}` into each `AgentCard`; `dismiss` calls `window.api.activity.dismissHelper(`${h.machine}:${h.id}`)` and replaces local `data` with the IPC's returned fresh (already-filtered) result.
7. **`dashboard/test/chat_helpers.test.jsx`**: tests 16–18 above (`ChatHelpersView` rendering + dismiss click).
8. **`dashboard/electron/main/index.js`**: in `registerActivityHandlers()`, create `dismissedPath = join(app.getPath('userData'), 'helpers-dismissed.json')`, pass it into `createHelpersReader`, and add `ipcMain.handle('activity:dismissHelper', (_e, key) => { dismissHelper(dismissedPath, key); return readHelpers() })`.
9. **`dashboard/electron/preload/index.js`**: add `dismissHelper: (key) => ipcRenderer.invoke('activity:dismissHelper', key)` to the `activity` block.
10. **`dashboard/scripts/chat_helpers_evidence.mjs`** or a new sibling script: capture screenshots at **900px and 1440px** showing a crashed card with its Dismiss button (and, if easy, a capped 10-card list), following the same sandboxed-HOME/fixture-jobs pattern already used for `#612`'s evidence. Pin via `marvin-show`.
11. **`CONTEXT.md`**: short addition under "Chat helpers in Activity" noting the home-list filter (dismiss is per-viewer/local-only, by the same reasoning as `mr_seen.js`'s #74 precedent; crashed cards auto-expire at 24h; cap is 10 pending #625's helpers decision).
12. Run the full JS (vitest) and Python test suites before opening the PR (per the main-green rule), then open the PR naming `Closes #818`.