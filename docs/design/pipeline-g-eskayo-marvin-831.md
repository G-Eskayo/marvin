## North-star fit

**Reuses:** the dependency-injection + "live-window registry" pattern already proven in `dashboard/electron/main/show_window.js` (`createShowWindows({ BrowserWindow, ... })`, its `alive = (entry) => entry && entry.win && !entry.win.isDestroyed?.()` at `show_window.js:302`, and its practice of re-checking `alive()` immediately before every `win.webContents.send`/`win.show()` rather than trusting a reference captured earlier — see the "Closed while this show was being resolved" re-check at `show_window.js:326`). That module's own comment states the reason: *"Electron is injected so the rules are tested without launching the app."* `mockup_window.js` follows the same shape. `dashboard/electron/main/index.js` currently does **not** follow this pattern for the main window — it holds `mainWindow` as a bare module-level `let` (`index.js:356`), nulls it on `'closed'` (`index.js:398-400`, landed incidentally in PR #1029 for #715, not for this bug), and then every call site repeats its own `mainWindow?.webContents.send(...)` guard by hand (11 call sites: `index.js:47,90,314,1084,1137,1138,1404,1421,1431`, plus two `isDestroyed()` checks at `1340,1448`). That duplication is exactly why the ticket's own "Fix" text asks for "one `send()` helper."

**Why this is already partially true, corrected:** the ticket's evidence (`index.js:242-279,1156,1176-1178`) predates PR #1029 (2026-11-03), which shifted ~100 lines and already added the `'closed'` → null-out guard. Reading the current file, every existing `webContents.send` for `mainWindow` already goes through `?.`, and the two window-creation checks already call `isDestroyed()`. So the literal symptom in the bug report (dialog on every post-close trigger) is likely already gone for the call sites that existed when the ticket was filed. What is **not** done: the sends aren't routed through one helper, index.js has no unit test for this behavior (it is excluded from behavioral tests — `entry_files_load.test.js` only `--check`s that it *parses*), and three implementation attempts since have failed verification ("regressed" / "must-fix issues," most recently today) with no detail logged — consistent with reviewers repeatedly flagging missing test coverage or redundant/conflicting edits to the same scattered call sites, not a surviving crash. The honest plan is: extract the one helper the ticket asks for (collapsing 11 duplicate guards into one tested module), and write the first real regression test this behavior has ever had — because "verify fails when code changes without a test changing" cannot hold today; nothing currently breaks when the null-guard is deleted.

**Simplest sufficient approach:** a small new file, `dashboard/electron/main/main_window.js`, owning the one `mainWindow` instance and exposing `ensure()` (create-or-reuse, used by boot, Dock `activate`, and the show-in-Docs handler), `window()` (current live window or `null`), and `send(channel, ...args)` (no-ops safely if there is no window or it is destroyed, re-checked at call time — never from a value captured before an `await`). `index.js` is wired to it exactly as it already wires `show_window.js` and `mockup_window.js`. No new abstraction layer beyond what two sibling files already establish; three call sites fold into one.

**Token/compute cost:** small — one new ~40-line module plus one test file modeled directly on `show_window.test.js`'s existing fake-`BrowserWindow` harness (no new test infrastructure to invent). Net lines in `index.js` go down (11 guards become one `mainWin.send(...)` each).

**Capability:** purely a reliability fix — stops a modal dialog from interrupting Gil while the app silently keeps running; no behavior change he has to learn or adapt to. Leaves him more able (no spurious crash dialog breaking focus), not more passive.

**Machine:** this is dashboard/Electron source, built and tested wherever the ticket is picked up (no machine-specific dependency); verification runs the existing Vitest suite.

## Tests to write first (`dashboard/test/main_window.test.js`, fake `BrowserWindow` per `show_window.test.js`'s pattern)

From "How we'll try to break it":
1. **Close during boot** — `ensure()` creates a window; fire `'closed'` before `'ready-to-show'` ever fires; then call `send()` → must not throw, must no-op (no `webContents.send` call reaches the destroyed instance).
2. **Close mid-merge** — `ensure()`, then simulate an in-flight async flow: get `window()`, close it (fire `'closed'`), then call `send('mr:mergeEvent', ...)` from the still-running flow → must not throw, must no-op; confirms sends are re-resolved at call time, not from a value captured before the `await`.

Misuse the ticket's list didn't name, per the north-star checklist:
3. **Empty/no window yet** — `send()` called before any `ensure()`/`createWindow` has ever run → no-op, no throw.
4. **Stale-but-non-null window** — window object remains assigned but `isDestroyed()` flips `true` without `'closed'` firing (defends the guard itself, not just the null-out convention) → `send()` still no-ops.
5. **Dock reopen (`activate`) after close** — `ensure()` after `'closed'` fired must create a **new** window distinct from the destroyed one; `window()` then returns the new instance.
6. **Repeated close/reopen cycles** — close → `ensure()` → close → `ensure()`, several times — no leaked reference to an old destroyed window, no growing listener count (`closed` handler added each `ensure()` but doesn't double-fire for the same window).
7. **Concurrent `ensure()` calls in the same tick** (two triggers — e.g. Dock `activate` racing the show-in-Docs handler — both call `ensure()` before either yields) → exactly one window is created, both callers observe the same instance. (Mirrors `show_window.js:310`'s "Two shows racing... window made once.")
8. **Malformed call** — `send()` with an empty channel string / no extra args does not throw (defensive, since this becomes the one chokepoint every call site now shares).

Integration/manual (can't run headless, so these stay manual steps in the PR description, not CI):
9. Launch the real app, close the window with the red button, touch a file under the watched dirs (`STAGES_DIR`/`JOBS_DIR`/`registry.json`/`support/state.json`) — confirm no "A JavaScript error occurred" dialog and the process is still alive.
10. Click the Dock icon — confirm a working window reopens and renders.
11. Screenshots at 900 px and 1440 px, pinned to the PR via `marvin-show` (not a file card), only if anything visible changed (it shouldn't — this is main-process-only).

**Verify gate:** these tests must fail against today's `main_window.js`-less code (there is nothing to import yet) and pass only once the extraction lands — giving this ticket, for the first time, a test that actually breaks if the guard is removed.

## Decisions
<!-- marvin:decisions -->
### safety-net: Add a main-process `uncaughtException`/`unhandledRejection` logger (log-only, not dialog-suppressing) in normal mode as a defense-in-depth backstop, alongside the root-cause fix?
- [ ] A: No — root-cause fix only (one guarded `send()` helper). Matches "fix the cause, not the symptom"; a future miss would still surface loudly, which north star 2 ("nothing may break silently") argues for.
- [ ] B: Yes — also log (never suppress the dialog) any future main-process exception, the way `capture_mode.js` already does for the unattended evidence-capture copy, so a *different* future bug still gets recorded even if it still shows the dialog.

## Task List

1. Add `dashboard/electron/main/main_window.js`: `createMainWindow({ BrowserWindow, preload, loadPage, webPreferencesExtra? })` returning `{ ensure(), window(), send(channel, ...args) }`, modeled on `show_window.js`'s `alive()`/DI pattern; `'closed'` nulls the held reference exactly once per instance (guard against double-handling via an identity check, as `index.js:398-399` already does).
2. Write `dashboard/test/main_window.test.js` covering tests 1–8 above with a fake `BrowserWindow` (same fake shape as `show_window.test.js`'s).
3. Wire `index.js`: replace `createWindow()`/`mainWindow` (`index.js:356,373-411`) with `main_window.js`'s `ensure()`/`window()`; replace all 11 `mainWindow?.webContents.send(...)` call sites (`index.js:47,90,314,1084,1137,1138,1404,1421,1431`, and the guarded ones at `1340-1348`) with the module's `send(...)`; replace `dialog.showMessageBox(mainWindow, ...)` call sites (`75,482,531,541,561,571,1257`) with `dialog.showMessageBox(mainWin.window(), ...)`.
4. Update the two `isDestroyed()` recreate checks (`index.js:1340,1448`, in the show-in-Docs handler and `app.on('activate')`) to call `ensure()` instead of duplicating the check.
5. Run the full Vitest suite (`dashboard/test`) plus `entry_files_load.test.js` to confirm `index.js` still parses and nothing else regresses.
6. Apply the owner's `safety-net` decision (above) — add or skip the log-only `uncaughtException`/`unhandledRejection` listener in normal (non-capture) mode.
7. Manual verification steps 9–11 (close + file-touch, Dock reopen, screenshots at 900/1440 px) — pin results via `marvin-show`, not a file card.
8. Open the PR naming `Closes #831`, carrying the Decisions block above.