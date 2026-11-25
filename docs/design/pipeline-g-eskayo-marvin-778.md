## North-star fit

**Reuses before adding anything new:**
- `dashboard/src/lib/saved_state.js`'s `readSaved`/`writeSaved` (already used by `MrReview.jsx:679,818` for collapsed-group state) — the exact "per-viewer convenience, storage may be missing/throwing/full, never crash" localStorage pattern needed for drafts and the active tab. No new persistence primitive.
- `dashboard/electron/main/mr_seen.js`'s read/mark-seen shape — the precedent for "have I already shown this to the user" state, reused for the one-time build-SHA toast.
- `path.join(os.homedir(), '.claude', 'logs', …)` (`error_log.js:8`, `dashboard_rebuild.py`'s `FAILED_FILE`) — the established cross-language (Python/Node/bash) shared-state directory, reused for the new ready-file, lock dir and demo-hold flag instead of inventing a new location.
- `electron/main/triggers.js`'s `createTriggerHub`/`watchFiles`, already wired in `index.js:1383-1421` (and already forwarded to the renderer via the generic `'trigger'` IPC channel that `SupportTab.jsx`'s `triggers.on` already consumes) — reused for the new `build` topic; no new IPC-forwarding plumbing needed.
- `electron/main/index.js`'s `registerXHandlers()` / preload namespace convention (`support:*`, `instance:*`) — reused for a new `registerBuildHandlers()` + `window.api.build`.
- `lib/test_slot.py`'s `fcntl.flock`-based lock is the project's real lock precedent, but it's merge-specific; bash has no `flock` binary on macOS, so the rebuild lock is a small new `lib/rebuild_lock.py` (mkdir-atomic, PID-liveness-checked) called from bash exactly the way `rebuild_and_install.sh` already shells out to `merge_server_wait.py` for non-trivial logic — kept thin and testable rather than inventing bash-native logic with no test harness.
- `electron/main/show_bounds.js`'s `createBoundsStore` (temp-file-then-rename) is the atomic-JSON-write precedent, mirrored (not literally reused, since it's bounds-shaped) for the ready-file and shown-sha file.

**Why simplest sufficient:** no SHA needs to be baked into the Electron bundle (no Vite/electron-builder config changes) — the ready-file written next to the install already carries `{sha, installedAt}` at a fixed OS path; the running app just remembers "the sha I last showed" and compares. No new "Settings" page, no new storage layer, no new IPC framework. The one genuinely new piece of logic (don't let a merge mid-build get lost, but still show only one banner) is solved by a bounded re-check loop inside the existing script, not a queue/message-bus.

**Where it spends vs. saves:** spends a little build-script complexity (lock + bounded re-check loop) to buy back the thing north star 3 cares about most here: a demo that doesn't eat someone's typed answer or kick them off-stage. Saves resources everywhere else — no new files system (reuses `~/.claude/logs`), no new renderer state library, no polling (event-driven via the existing file-watch trigger hub).

**More capable or more passive:** more capable — the owner (or Noah, on a shared install) keeps working through an update instead of losing a draft and being dropped on Metrics; the demo-hold switch hands explicit control back rather than quietly hoping no merge lands on stage.

**Correcting the ticket's own citations:** `dashboard/webhook-server/merge.js:1102-1112` (`triggerRebuildIfDashboardChanged`) is a second, independent call site that spawns `rebuild_and_install.sh` directly, bypassing `dashboard_rebuild.py`'s `decide()` entirely (confirmed by reading both files). The ticket's "a lock stops two rebuilds overlapping (#392)" line is correct that this needs fixing, but the fix must live inside `rebuild_and_install.sh` itself (the one place both callers funnel through), not inside `decide()`, which only guards the *periodic* caller.

**Decisions:** none needed from the owner — the one decision this ticket raised (`update`) is already answered on the issue ("Both of the above, plus a demo-hold switch"). No new Decisions block.

**Stale doc found:** `CONTEXT.md:860-866` still documents the old, superseded trade-off ("the relaunch drops unsaved in-tab edits") and the pre-#443 15-min/1h policy. This PR must correct it, not just add new text beside it.

---

## Tests to write first

**Python — `lib/tests/test_dashboard_rebuild.py`** (extends existing `decide()`/`_facts()` tests):
1. `demo_hold=True` → `("skip", ...)` regardless of every other input (bad/empty/huge staleness all still skip) — misuse: a stuck-on hold must never be silently overridden by staleness urgency.
2. `demo_hold=False` behaves exactly as today (no regression on the 13 existing cases).
3. `_facts()` reads `demo_hold` from the flag file's mere existence — present → `True`, absent → `False`, and a *directory* accidentally created at that path (malformed state) doesn't raise.

**New — `lib/tests/test_rebuild_lock.py`** (new module `lib/rebuild_lock.py`):
4. Acquire succeeds when the lock dir doesn't exist.
5. Acquire fails ("busy") when held by a PID that `pid_alive()` reports alive — the base "two rebuilds overlap" case (#392).
6. Acquire **succeeds and takes over** when the lock dir exists but its recorded PID is dead (kill -9 mid-rebuild — the ticket's explicit break test "no half-deleted bundle").
7. A lock dir that exists with a missing, empty, or non-integer `pid` file (malformed/corrupt state) is treated as stale and taken over, not fatal.
8. `release(dir, pid)` only removes the lock when the calling PID matches the recorded holder — a wrong-process or late/duplicate release from a process that lost a race never deletes someone else's live lock (misuse: a person's mistake / wrong order).
9. Two sequential `try_acquire` calls for the same dir with different PIDs: second fails while the first is "alive" (simulated), confirming no race in the common path.

**JS/vitest — `dashboard/test/build_status.test.js`** (new module `electron/main/build_status.js`):
10. `shouldNotify(runningSha, readySha)`: `null` runningSha + any readySha → notify once; same sha twice → no repeat notify; a readySha that reverts to `runningSha` (e.g. a rollback) → no notify.
11. `shouldShowOnceToast(lastShownSha, currentSha)`: differ → show + "would persist `currentSha`"; equal → don't show; both `null` (fresh install, no ready-file ever) → don't show.
12. `shouldAutoRestart({pendingSha, blurredSinceMs, now, demoHold, idleMs})`: true only when pending + blurred ≥ idleMs + demoHold false; false for any single condition failing (not pending; focused; demoHold true; blurred exactly at the boundary minus 1ms).
13. Reading a malformed/truncated ready-file (bad JSON, missing `sha` key, a boolean instead of an object) never throws — returns "nothing pending," matching `readPrefs`/`readSaved`'s existing never-throw contract.
14. Reading/writing the "last shown sha" file round-trips, and a missing/unwritable `userData` dir (permissions) degrades to "never shown" rather than crashing (reuses `saved_state.js`'s try/catch ethos, ported to fs).

**JS/vitest — `dashboard/test/App.test.jsx` (or extend an existing App-level test if one exists) and component-level tests:**
15. `SupportTab`: typing a reply, then remounting the component with a fresh `useState` (simulating a relaunch) restores the draft text for that `repo#number`; a draft for a *different* request is not shown; sending a reply clears both the in-memory and the persisted draft (no resurrection next time you open that thread).
16. `ProjectBoard`'s `TicketReply`: same restore/clear round trip for the ticket-comment box.
17. `Decisions`: typing answers while `editing`, then remounting, restores the unsaved choices; but if the *questions changed* in the meantime (signature mismatch — GitHub edited the Decisions block while you were offline), the stale saved draft is discarded, not silently shown as if it still applied (misuse: stale state after external change); submitting successfully clears the persisted draft for that PR/ticket.
18. `App`: the active tab persists across a simulated remount and is restored; a `localStorage` that throws on `setItem` (quota/private window) doesn't prevent the tab from switching in the current session.
19. `App`/`BuildUpdateBanner`: receiving a `{topic:'build'}` trigger with a new sha shows the banner exactly once even if the same trigger fires twice in a row (repeat — debounced by sha-equality, not by trigger count); clicking "Restart now" calls `window.api.build.restartNow()`; a `build:status` call that rejects (IPC error, dependency failing) leaves the app usable with no banner, not a crash.
20. Demo-hold toggle: turning it on calls `window.api.build.setDemoHold(true)` and flips the control's own displayed state optimistically but corrects itself if the main process reports failure (wrong permissions to write the flag file).

**Manual/no-harness (flagged, not faked as automated):** the bash lock-dir + bounded re-check loop in `rebuild_and_install.sh` itself has no shell-test harness in this repo (confirmed: no `.sh` is exercised by any existing test). All of its *decision* logic is pushed into the tested `rebuild_lock.py` and tested `dashboard_rebuild.decide()`; what's left in bash is thin orchestration, verified manually (kill -9 mid-build; two merges fired back-to-back) before merge, and called out as such in the PR rather than claimed as covered.

---

## Task List

1. **`lib/rebuild_lock.py`** (new): `pid_alive`, `try_acquire(lock_dir, pid)`, `release(lock_dir, pid)`, plus a tiny `acquire`/`release` CLI entry point. Tests: #4–9.
2. **`lib/dashboard_rebuild.py`**: add `demo_hold` to `decide()` (short-circuit first) and `DEMO_HOLD_FILE` existence check to `_facts()`. Tests: #1–3.
3. **`dashboard/scripts/rebuild_and_install.sh`**:
   - Demo-hold check at the very top (flag file present → log + `exit 0`, skip the failure/backoff path entirely).
   - Acquire the lock via `rebuild_lock.py` before pulling; busy → log + `exit 0`; release via `trap … EXIT`.
   - Remove the preemptive `osascript quit app "MARVIN"`/`"MARVIN Metrics"` + `sleep 1`.
   - Replace `rm -rf "$DEST"; cp -R "$SRC" "$DEST"` with an atomic swap: `mv` the old bundle aside, `mv` the freshly built one into place, then `rm -rf` the old one — never a half-deleted `$DEST` (closes the other half of #392).
   - Wrap pull→install in a bounded (max 3) re-check loop: after installing, re-fetch/compare `origin/main`'s dashboard-relevant commit; if it moved, loop and rebuild again before notifying — "second build wins, one prompt."
   - Check whether the app was already running (pgrep) right before/after the atomic swap; if not running, `open -a "$DEST"` as before (unchanged path for a fresh/offline install); if running, do **not** quit/open — just write the ready-file.
   - Always write `~/.claude/logs/dashboard-build-ready.json` (`{sha, installedAt}`, temp+rename) once the final loop iteration installs successfully.
4. **`dashboard/electron/main/build_status.js`** (new): `readReady(file)`, `readShown(file)`/`writeShown(file, sha)` (mirroring `mr_seen.js`), and the pure decision functions `shouldNotify`, `shouldShowOnceToast`, `shouldAutoRestart`. Tests: #10–14.
5. **`dashboard/electron/main/index.js`**:
   - `registerBuildHandlers()`: `build:status`, `build:restartNow` (`app.relaunch(); app.exit()`), `build:demoHold` get/set (flag-file existence toggle, reusing the same path `dashboard_rebuild.py`/`rebuild_and_install.sh` check).
   - `triggerHub.watchFiles('build', [{ dir: …, match: n => n === 'dashboard-build-ready.json' }])` alongside the existing `watchFiles` calls (~line 1383-1420); the existing generic `triggerHub.onTrigger((t) => mainWindow?.webContents.send('trigger', t))` already forwards it, no change needed there.
   - Wire `mainWindow.on('blur'/'focus', …)` to drive the idle-auto-restart check via `shouldAutoRestart`.
6. **`dashboard/electron/preload/index.js`**: new `build: { status, restartNow, demoHold: { get, set } }` namespace, same shape as `support`.
7. **`dashboard/src/components/BuildUpdateBanner.jsx`** (new): subscribes to `window.api.triggers.on` for `topic === 'build'`, shows "Update ready: Restart now / Later", and a persistent "Demo hold" toggle in the header regardless of pending state. Tests: #19–20.
8. **`dashboard/src/App.jsx`**: mount `BuildUpdateBanner` between `<header>` and `<main>`; persist `activeTab` via `saved_state.js` (`readSaved`/`writeSaved`) and restore it as the initial state — this also closes ticket #593's tab-persistence half as a side effect (window-bounds persistence, the other half of #593, stays out of scope). Tests: #18.
9. **`dashboard/src/components/SupportTab.jsx`**: persist `draft`/`check` per `repo#number` via `saved_state.js`; restore on `open()`; clear on successful send. Tests: #15.
10. **`dashboard/src/components/ProjectBoard.jsx`** (`TicketReply`): same persist/restore/clear for the comment box. Tests: #16.
11. **`dashboard/src/components/Decisions.jsx`**: persist the in-progress `draft` only while `editing`, keyed by `repo#number`; on mount, restore only if the saved draft's question-id signature still matches the live `questions` (discard stale saves otherwise); clear on successful submit. Tests: #17.
12. **`CONTEXT.md:860-866`**: rewrite the "app itself is rebuilt and relaunched" paragraph — replace "the relaunch drops unsaved in-tab edits (Portfolio)" and the stale 15-min/1h figures with the new behavior (ready-file + banner, draft/tab persistence, demo-hold, one-prompt-per-burst, bounded re-check loop), and add the SHA-stamp + demo-hold facts #443/#392 didn't have.
13. **Screenshots**: 900px and 1440px of the update-ready banner and the demo-hold toggle, pinned on the PR (AC5) — only if anything visibly changed once built, per the private-repo PR-image rule.