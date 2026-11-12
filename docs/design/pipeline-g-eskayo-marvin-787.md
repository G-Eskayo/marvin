Confirmed. I have everything needed to write the plan.

## North-star fit

**Reuses, before adding anything new:**
- `profiles:selftest`'s dry-run-and-report shape (`dashboard/electron/main/index.js:496-504`) and `merge.js:445`'s `String(e?.stderr || e?.message || e).trim().split('\n').pop()` idiom — the established way this codebase turns a failed subprocess into one plain line instead of a thrown stack.
- `docsClickHandlers`'s extraction pattern (`dashboard/electron/main/docs_handlers.js:9-23`): testable pure functions live in `docs_handlers.js`, `index.js` just wires them to `ipcMain.handle`. `docs:build` follows the same split as the existing `docs:refresh`/`docs:freshen` handlers — registered directly in `index.js`, outside the click table, since it's an explicit action, not a passive click (the click table's "zero network calls" guarantee, `docs_clicks_network.test.js`, must stay true).
- `cleanIpcError` (`dashboard/src/lib/ipcError.js`), already used in `MrReview.jsx` — reused as-is, no changes to it.
- The `image()` function's existing precedent for an expected-absent state is *not* reused as a return-shape change to `content()` — instead the simpler fix is a `missing` flag on the master entry already returned by `repos()` (`docs_service.js:65-77`), which the UI already fetches on mount and already looks up via `cache.repos.find(...)` (`DocsExplorer.jsx:722`). No new IPC round trip, no error-message parsing needed to detect the common case.
- `tidy_agent.py --dry-run` (already shipped, `~/.claude/organize/tidy_agent.py`): it scans and **writes `_WHERE-THINGS-ARE.md` unconditionally**, it just skips filing anything (`do_moves` returns early, `moved=0`). This is the generator the ticket means; reusing its existing flag means zero changes to that script.

**Why simplest sufficient:** No new polling, no new error-classification language, no new IPC-content-return shape. One flag, one handler, one extracted pure function, five renderer call-sites switched to an existing helper.

**Tokens:** Spends a little now (one subprocess call per explicit click); saves going forward by cutting the number of times a user reports "the Docs tab is broken" as a bug when it's really just day-one-before-the-overnight-job.

**Phone-OS direction:** Neutral — a dashboard-only polish fix.

**More capable or more passive:** More capable — turns a dead end (a raw IPC stack the user can't act on) into a one-click fix they control, without silently reorganizing their Desktop on their behalf (see decision below).

**Decision made, not punted:** "Build it now" runs `tidy_agent.py --dry-run`, not the full daily pass. The full pass also *moves aged Desktop/Downloads files into `~/Documents` buckets* as a side effect (`tidy_agent.py:112-147`). A "view this doc" action in the Docs tab silently filing the user's Desktop is exactly the kind of surprising, unapproved side effect past feedback has flagged (`feedback-confirm-ui-interaction-first`, `feedback-no-unapproved-ui-changes`) — not a toss-up, so no Decisions-section is created for it.

## Tests (written first)

In `dashboard/test/docs_service.test.js` (extends the existing `svc()` fixture):
1. `repos()` marks the master entry `missing: true` when `readMaster()` returns `null`.
2. `repos()` marks it `missing: false` once a doc exists (extends the existing "lists the master doc first…" test).
3. `content(MASTER_ID, …)` still throws `'The master doc has not been generated yet'` when `readMaster` returns `null` (not currently asserted anywhere — regression guard for the error path the empty-state fallback still relies on).

New `dashboard/test/docs_build.test.js`, for a `runMasterBuild({ exec, python, script, timeout })` extracted into `docs_handlers.js`:
4. Happy path: `exec` resolves → `{ ok: true }`, and `exec` was called with `[script, '--dry-run']`.
5. **Generator fails (ticket's own case):** `exec` rejects with a multi-line Python-traceback-shaped `stderr` → result is `{ ok: false, output }` where `output` is exactly the last non-blank line, contains no `\n` and no `Traceback`.
6. **Dependency failing / wrong permissions:** `exec` rejects with an `ENOENT`/`EACCES`-shaped error that has no `stderr`, only `.message` → still one plain line, taken from `.message`.
7. **Malformed/huge output:** `exec` rejects with a huge multi-thousand-line `stderr` → `output` is still a single bounded line (no truncation logic needed beyond `.pop()`, but prove it doesn't throw or hang on size).
8. **Timeout:** `exec` rejects with a `killed/SIGTERM`-shaped error → resolves (doesn't throw) with a plain one-line message.
9. Confirms the given `timeout`/`maxBuffer` options are passed through to `exec` unchanged (so the wiring in `index.js` is provably exercised by the one thing the test *can* check without Electron).
10. **Repeats/concurrency (UI-level, documented, not unit-tested):** covered by `disabled={building}` on the button — called out explicitly in the task list rather than faked with a testing-library harness this repo doesn't have (`@testing-library/react` isn't a dependency here; no existing DocsExplorer render test exists to extend).

`ipcError.js`/`cleanIpcError` itself is unchanged — its existing tests (`ipc_error.test.js`) already cover it; DocsExplorer.jsx's switch to it is wiring, verified by the dev-server check below, matching the rigor level of its sibling usage in `MrReview.jsx` (no dedicated render test there either).

**Desktop folder missing:** `tidy_agent.py` already recreates `~/Desktop` via `ACTIVE.mkdir(parents=True, exist_ok=True)` before it scans or writes — that's existing, out-of-repo behavior, not something this ticket's code touches. Tests 4-9 above cover the dashboard's side of this: whatever that script does or doesn't survive, `runMasterBuild`'s contract (one plain line on any failure, `{ok:true}` on any success) holds either way.

**Verify-fails-when-code-changes-without-a-test-changing** check: the `missing` flag, the thrown message, and `runMasterBuild`'s four failure shapes are each pinned by a distinct assertion above.

## Task List

1. `dashboard/electron/main/docs_service.js`: in `repos()`, add `missing: readMaster() == null` to the `master` object literal.
2. `dashboard/electron/main/docs_handlers.js`: add and export `runMasterBuild({ exec, python, script, timeout = 300_000 })`, returning `{ ok: true }` on success or `{ ok: false, output: <one trimmed line> }` on failure (reusing the `String(err?.stderr || err?.message || err).trim().split('\n').pop()` idiom from `merge.js`).
3. `dashboard/electron/main/index.js`:
   - Import `runMasterBuild` alongside `docsTextFor`, `maxNumbers`, `docsClickHandlers` (line 141).
   - Add `const TIDY_AGENT_SCRIPT = join(homedir(), '.claude', 'organize', 'tidy_agent.py')` next to `CATALOG_SCRIPT`/`AGENTS_PYTHON`/`FIND_FILE_SCRIPT`.
   - Register `ipcMain.handle('docs:build', () => runMasterBuild({ exec: execFileAsync, python: AGENTS_PYTHON, script: TIDY_AGENT_SCRIPT }))` next to `docs:refresh`/`docs:freshen`.
4. `dashboard/electron/preload/index.js`: add `build: () => ipcRenderer.invoke('docs:build')` to the `docs: {...}` bridge block.
5. `dashboard/src/components/DocsExplorer.jsx`:
   - Import `cleanIpcError` from `../lib/ipcError.js`; replace the `String(err)` call sites used for user-facing error text (search error, files-search error, `handleRefresh`, `loadTree`, `openFile`, `openDeliverableFile`) with `cleanIpcError(err)`.
   - Add `building` state and a `handleBuildMaster` function: calls `window.api.docs.build()`, on `{ok:false}` sets `error` to `r.output` directly, on success refreshes `cache` via `docs.repos()` and calls the existing `openFile(MASTER_ID, 'WHERE-THINGS-ARE.md')`.
   - In `handleSelectRepo`, skip the auto `openFile(...)` call for the master project when its cached entry has `missing: true`, and reset `error` to `null`.
   - Add a small local `MasterEmptyState` component (same file, same pattern as `FileGroup`/`SummaryCards`): "MARVIN builds this map overnight." + a "Build it now" button (`disabled={building}`, label swaps to "Building…"), showing `error` inline as plain text if the last build attempt failed.
   - In `renderMain()`, branch to `<MasterEmptyState .../>` when `selectedRepo === MASTER_ID && selectedProject?.missing`, before the generic `if (error) …` fallback.
6. Run the full dashboard test suite (`dashboard`'s vitest) plus a dev-server check: point `HOME` at a temp dir with no `_WHERE-THINGS-ARE.md`, confirm the empty state (not an error) renders, click "Build it now", confirm the real doc opens; capture 900px and 1440px screenshots and pin them to the PR via `marvin-show` per the acceptance criterion.