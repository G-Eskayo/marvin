Now I have everything needed. Here's the plan.

## North-star fit

**Reuses:** the factory-with-injected-`BrowserWindow` pattern already used for `createShowWindows` (`dashboard/electron/main/show_window.js:302`, `alive = (entry) => entry && entry.win && !entry.win.isDestroyed?.()`) and `createMockupWindows` (`dashboard/electron/main/mockup_window.js:36,70`): a small factory module, Electron injected so it's unit-tested without launching the app, holding its own `isDestroyed()` guard. `dashboard/test/show_window.test.js:45-68`'s fake `BrowserWindow` (EventEmitter, `isDestroyed()`, `webContents.send` as a spy, `close()` emits `'closed'`) is the fake I'll reuse for the new test.

**Correction to the ticket's stated fit:** half the "Fix" is already shipped. PR #1029 (`marvin#715`, landed 2026-11-03) added exactly "Null `mainWindow` on `closed`" as a side effect — `dashboard/electron/main/index.js:395-400`, comment: *"must find no window, not a destroyed one"*. `app.on('activate', ...)` at `index.js:1446-1449` and the `show:openInDocs` handler at `index.js:1340` already do "Dock click reopens a working window" (AC2 is already satisfied). What's missing is only the second half of the Fix: **the one `send()` helper that checks `isDestroyed()`**. Right now ~13 call sites still do `mainWindow?.webContents.send(...)` — optional-chaining only guards against `mainWindow === null`, not against a non-null `mainWindow` whose `webContents` is already destroyed (the exact race the ticket's "close during boot" / "close mid-merge" break-attempts target: an async callback — a merge push, a 300 ms-debounced file trigger, a check-watch probe — resolving between native destroy and the `'closed'` JS event, or after a window has been torn down out of band).

**Why this is the simplest sufficient approach:** `index.js` has no tests and can't be imported in tests (`dashboard/test/entry_files_load.test.js` only `node --check`-parses it — it runs `app.whenReady()` at module load). Every piece of this bug that needs a test must live outside it, in a small injectable module, same as `show_window.js`/`mockup_window.js` already do. Rather than leaving `let mainWindow` as untested raw state with a helper bolted on top (two sources of truth, which is the same class of bug this ticket reports), I'll extract one tiny module that *owns* the window reference, the `'closed'`-nulling, and the `send()` guard together, and make `index.js` read/write through it everywhere `mainWindow` currently appears. That removes the duplicated `!mainWindow || mainWindow.isDestroyed()` check (currently copy-pasted at `index.js:1340` and `:1448`) into one named, tested predicate.

**Tokens:** small, surgical — one new ~20-line module, one new test file, and a mechanical find-replace of `mainWindow` in `index.js` (no behavior change to anything else: createWindow's webPreferences, loadURL/loadFile, dialogs, chat-sender identity check are all unchanged, just read through `get()`).

**Phone-OS fit:** reliability precondition (north star 2) — "nothing may break silently." A silent main-process crash dialog on close is exactly the kind of silent break that direction forbids.

**User capability:** purely a robustness fix; no behavior Gil sees change (no new UI, nothing visible), so no screenshots needed per AC3's "if anything visible changes."

## Tests (written first)

New file `dashboard/test/main_window.test.js`, fake window = the same EventEmitter-based fake `BrowserWindow` instance shape as `show_window.test.js` (`isDestroyed()`, `webContents.send` as `vi.fn()`, `.on`/`.emit('closed')`).

From the ticket's "How we'll try to break it":
1. **Close during boot** — window is non-null but `isDestroyed()` already returns `true` *before* `'closed'` has fired (simulates destruction racing ahead of the JS event): `send()` must not throw and must not call `webContents.send`.
2. **Close mid-merge** — window set, then emits `'closed'` (nulling it), then an async caller (standing in for a merge-push/trigger callback that was already in flight) calls `send()`: must not throw, must not call `webContents.send`.

Additional misuse coverage (bad/empty input, repeats, stale state, wrong order):
3. `send()` called before any window was ever `set()` (wrong order) — no throw.
4. `send()` on a live window forwards the channel and every arg exactly once, unmutated — including zero extra args and a non-string channel (malformed input).
5. Stale-reference / re-entrancy: `set(A)`, `A` emits `'closed'` (nulls to `null`), `set(B)` (dock reopen), then `A` emits `'closed'` **again** (duplicate/out-of-order event) — `get()`/`isAlive()` must still report `B`, not be nulled by the stale `A` listener.
6. Rapid/concurrent `send()` calls while the window transitions from alive → destroyed mid-burst — never throws; only the calls made while alive reach `webContents.send`.
7. `isAlive()`/`get()` correctness through the plain lifecycle: `null` initially → `set()` → alive → `'closed'` → `null` again.

`index.js` itself gets no new tests (consistent with the existing convention: it's never imported in tests, only parse-checked by `entry_files_load.test.js`, which will keep covering syntax regressions from the edit).

No decisions needed — every choice above (module boundary, reuse of the existing fake-window test pattern, no UI screenshots) is ordinary engineering discretion, not an open design question for the owner.

## Task List

1. Write `dashboard/test/main_window.test.js` with the 7 cases above against a not-yet-existing `createMainWindowTracker` (red).
2. Add `dashboard/electron/main/main_window.js` exporting `createMainWindowTracker()` → `{ set(win), get(), isAlive(), send(channel, ...args) }`: `set` wires the existing closed-nulling pattern (guard against a stale window nulling a newer one, copied from `index.js:396-400`); `send` guards `win && !win.isDestroyed()` before `win.webContents.send(...)`. Get tests green.
3. In `dashboard/electron/main/index.js`: import and instantiate `mainWindowTracker`; remove `let mainWindow = null` and the inline `'closed'`-nulling block (now owned by the tracker).
4. In `createWindow()`: build the window into a local `win`, call `mainWindowTracker.set(win)`, keep all the existing internal setup (`ready-to-show`, `setWindowOpenHandler`, `loadURL`/`loadFile`) against `win` directly.
5. Replace every remaining `mainWindow` read site with `mainWindowTracker.get()` (dialog-parent args at lines ~75, 482, 531, 541, 561, 571, 1257; the chat-sender identity check at ~441; `mainWindow?.show()` at ~1403) and collapse the duplicated `if (!mainWindow || mainWindow.isDestroyed()) createWindow()` guards at ~1340 and ~1448 into `if (!mainWindowTracker.isAlive()) createWindow()`.
6. Replace every `mainWindow?.webContents.send(...)` call site (lines ~47, 90, 314, 1084, 1137-1138, 1404, 1421, 1431) with `mainWindowTracker.send(...)`.
7. Run `npm run test` in `dashboard/` (full suite, per the "full suites before a hand-merge" rule) and `node --check electron/main/index.js` to confirm the parse-check test still passes.
8. Manual verification pass (can't be automated without a real display): launch the dashboard, close the window with the red button, touch a watched file (e.g. touch a `.claude/logs` JSON under `STAGES_DIR`) and confirm no "A JavaScript error occurred" dialog; click the Dock icon and confirm a working window reopens.