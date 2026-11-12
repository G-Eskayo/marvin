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