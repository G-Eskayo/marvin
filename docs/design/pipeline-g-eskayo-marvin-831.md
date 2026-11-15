Nothing CONTEXT.md-specific on window-close lifecycle — the governing decision here is just the existing #715-slice-1 fix itself. I have enough to write the plan.

## North-star fit

**Reuses:** the window-lifecycle fix already in `dashboard/electron/main/index.js:392-400,1446-1448` (landed in PR #1029 for #715 slice-1, 2026-11-03: *"The main window is now cleared when closed, so later sends never hit a destroyed window."*) and the regression-test pattern in `dashboard/test/polling_guard.test.js:192-202` / `dashboard/test/github_feed.test.js:192-217` — static source-text assertions on `electron/main/index.js`, the established way this repo locks in invariants inside the Electron entry file, which cannot be imported/executed in tests (only syntax-checked, see `entry_files_load.test.js:17-19`) because it runs `app.whenReady()` at module load.

**Verification (no edit needed for the fix itself):** I read every call site in `index.js` that touches `mainWindow` (9 `webContents.send` sites, `.show()`, `.focus()`, the `activate` handler, the `show:openInDocs` handler) and the `marvin show` window module (`show_window.js`, already covered by `show_window.test.js`). All of them are correct today:
- `createWindow()` (`index.js:397-400`) captures `created = mainWindow` and nulls `mainWindow` on `'closed'`, only if it's still the current window — this already defeats the exact failure the ticket describes ("Object has been destroyed" from a stale `webContents.send`).
- Every send on `mainWindow` uses `mainWindow?.webContents.send(...)` (lines 47, 90, 314, 1084, 1137, 1138, 1404, 1421, 1431) — none can throw once `mainWindow` is null.
- `app.on('activate', ...)` (`index.js:1446-1448`) and `show:openInDocs` (`index.js:1340`) both recreate the window with `if (!mainWindow || mainWindow.isDestroyed()) createWindow()` — so a Dock click after close reopens a working window.
- Close during boot and close mid-merge are both covered by the same mechanism: the `'closed'` handler fires regardless of load state or in-flight merge pushes, and every later send is guarded.

So **this ticket's acceptance criteria are already met by code on this branch** — the fix shipped as a side effect of #1029/#715, after `dashboard-ux-potholes-2026-10-29.md` was written and before #831 was ever worked, which is why the repeated "parked/needs-info" cycles never found anything to fix. The 2026-11-10 needs-info sweep was right that nothing here was waiting on the owner, but wrong about why it kept failing — it wasn't a stale verify timeout, it was that automated attempts (which must have found the ticket's "what to build" already done) likely had nothing to change and nothing to commit, which looks indistinguishable from a stuck build.

**Simplest sufficient approach:** don't re-implement a "fix" that already exists (that would be churn, and risks instead introducing an extra `send()` helper abstraction the codebase doesn't otherwise use, for two call sites that already aren't duplicated logic). Add one regression test, following the exact reused pattern, so this invariant is pinned the same way "triggers over polling" is pinned in `polling_guard.test.js` — not a new testing mechanism.

**Tokens:** spends a small, one-time amount writing a static test; saves future re-dispatch cycles that would otherwise burn tokens rediscovering "already fixed" every time #831 gets picked back up.

**More capable, not more passive:** closes a ticket that was silently looping without any human needing to intervene, and leaves a test that prevents the behavior from regressing — net reduction in owner attention needed, not an automation that removes judgment from a real decision.

**Decisions:** none — nothing here requires the owner to choose between options; this is a verify-and-close with one locking test.

## Tests to write first

Per "verify fails when code changes without a test changing" — there is no production code change, so strictly no test is *required*, but the ticket's acceptance criteria and break-it list are currently unverified by any test, which is exactly how this looped for weeks. I will add a new test file, `dashboard/test/main_window_lifecycle.test.js`, reusing the source-text-assertion pattern (no mocking Electron's runtime, since `index.js` can't be imported — confirmed via `entry_files_load.test.js`):

1. **Close during boot / any time → no destroyed-window send:** assert `createWindow()`'s body contains `created.on('closed', ...)` setting `mainWindow = null` only `if (mainWindow === created)`, guarding against a second window's close handler clobbering a newer window's reference (the actual misuse case `#715` and stale-closures tests elsewhere in this repo care about).
2. **Every `mainWindow` send is guarded:** scan the full source for `.webContents.send(` calls that reference `mainWindow` directly and assert none appear without the `?.` optional-chain (regex over the file, same technique as `polling_guard.test.js`'s `src.match(...)`). Catches a future call site added without the guard — the actual way this bug could reappear.
3. **Dock click after close reopens a working window:** assert `app.on('activate', ...)` and the `show:openInDocs` handler both guard window reuse with `!mainWindow || mainWindow.isDestroyed()` before calling `createWindow()`.
4. **Close mid-merge:** assert `pushMergeOp` (the function merge progress flows through, `index.js:46-48`) uses the guarded `mainWindow?.webContents.send`, not an unguarded one — the concrete "close mid-merge" scenario from the ticket's break-it list.
5. **Misuse not in the ticket's list — a stale `'closed'` listener outliving a recreated window:** covered by the `=== created` check in test 1; add a dedicated assertion for that comparison specifically (distinct from "did it null mainWindow at all"), since that's the subtle part a naive fix gets wrong (nulling unconditionally on any `'closed'` event would wrongly null a brand-new window if an old one's listener fires late).

No case needs a dependency-failure, concurrency, or malformed-input test — this is a window-handle lifecycle inside one process, not an I/O boundary.

## Task List

1. Add `dashboard/test/main_window_lifecycle.test.js` with the 5 source-text assertions above, following the `polling_guard.test.js` / `github_feed.test.js` pattern (`readFileSync` the real `electron/main/index.js`, regex/`indexOf` assertions — no Electron mocking, no new abstraction).
2. Run the full test suite (dashboard + Python) per the "full suites before a hand-merge" rule, confirm green.
3. Open a PR that states plainly in its description: the fix in #831 was already shipped by PR #1029 (#715 slice 1); this PR only adds the missing regression test and closes #831 ("Closes #831"), with the file/line evidence above so the owner can verify without re-deriving it.
4. No screenshots needed — no visible/UI change.