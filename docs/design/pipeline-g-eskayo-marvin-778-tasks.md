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