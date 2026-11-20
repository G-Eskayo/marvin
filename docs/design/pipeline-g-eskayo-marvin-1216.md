## North-star fit

**Reuses before adding anything new:**
- `dashboard/electron/main/mockup_window.js`'s `webPreferences: { sandbox: true, contextIsolation: true, nodeIntegration: false }` (already correct pattern, in production today) is the template for both windows this ticket must flip — `dashboard/electron/main/index.js:384-389` (`createWindow`'s `mainWindow`) and `dashboard/electron/main/show_window.js:255-266` (`makeWindow`).
- `dashboard/test/github_feed.test.js:192-202` already reads `electron/main/index.js`'s source text and asserts on it with `indexOf`/regex, because `index.js` runs real Electron-app side effects and isn't dependency-injected like the other main-process modules. That's the existing pattern for testing `createWindow`'s `webPreferences`, not a new DI refactor.
- `dashboard/test/show_window.test.js:172` already asserts on `makeWindow`'s injected `BrowserWindow` options object (`show_window.js` *is* DI-testable) — extend that one `toMatchObject`, don't add a parallel test file.
- `dashboard/test/issue_body.test.jsx:44-47` ("a `<script>` or event-handler tag never survives as markup") already covers the ticket's "PR body with HTML or script content: rendered inert" break-it case, at the renderer-side sanitizer (`issueBody.js`), independent of the main-process sandbox flag. No new test needed there — just confirmed-still-green after the bump.
- Type/path-guard pattern already used for untrusted renderer input (`outbox.js`, `files_search.js`, `docs_service.js`, `show.js`'s `checkShowPath`, `ticket_input.js`, …) is reused for the "unexpected arguments" break-it case rather than inventing a new validation style.
- `dashboard/scripts/rebuild_and_install.sh` is the existing build/sign/install/relaunch pipeline (acceptance criterion 2) — reused unchanged; no new script.

**Why this is the simplest sufficient approach:** The thing that makes this ticket tractable rather than a rewrite is a fact already verified by reading the code, not assumed: `dashboard/electron/preload/index.js` imports nothing but `{ contextBridge, ipcRenderer }` from `'electron'` — no `fs`, `path`, `child_process`, nothing Node-specific. A sandboxed preload can still do everything this one does. So "move anything the preload needs Node for behind IPC" (the ticket's stated risk) is **already true today** — there is nothing to move. That collapses the sandbox part of this ticket from a refactor into a two-line flip (`sandbox: false` → `true`) on each of the two remaining windows, verified by tests, not a speculative rewrite.

**Where it spends tokens, deliberately:** reviewing Electron's breaking-change notes for every major skipped (30 → latest supported) is real, non-skippable reading — a skipped breaking change (e.g. a removed API `index.js` calls, a changed default) is exactly the kind of thing that "builds clean but breaks `marvin show` on a real Mac" and north star 1 says to spend the tokens once here rather than debug it live later.

**Phone-OS direction:** more reliable (an unsupported Electron with 45 advisories, and a renderer with `sandbox: false` rendering other people's PR text, is a standing liability to "nothing may break silently") — a prerequisite for, not itself, OS-shaped work.

**Which machine:** the `npm`/build/test work runs wherever this worktree already is; `rebuild_and_install.sh` and the real-app verification (criteria 2–3) must run on **both Macs**, per the ticket, because codesign/ad-hoc-sign behavior and `launchctl`-managed services (`com.marvin.dashboard-webhook`) are per-machine.

**More capable, not more passive:** yes — it removes a standing security exposure (45 advisories, an unsandboxed window rendering external text) without changing what the user does; pure risk reduction, no behavior change for Gil.

**Decisions:** none. Everything the ticket leaves open (exact target Electron major, whether electron-builder/Node-in-CI need a bump) is an objective fact resolvable by running `npm view`/reading release notes at implementation time, not a judgment call for the owner — so no Decisions section.

## Tests to write first

One per "How we'll try to break it" bullet, plus the misuse cases the section didn't list:

1. **PR body with HTML/script content rendered inert** — `dashboard/test/issue_body.test.jsx:44-47` already exists and must stay green through the bump; no new test, but it's the regression gate for this bullet.
2. **Preload API called with unexpected arguments from the renderer: rejected** — new test(s) calling real registered-handler logic (not just the pure helper) with type-confused and malformed input: e.g. `boards:ticket`/`boards:load` with an unregistered repo string (extends the existing `assertRegistered` pattern in `index.js`), `docs:reveal`/`outbox:*` with a non-string, an object, `__proto__`, or a `../../../etc/passwd`-style path, reusing `isRevealable`/`checkPath`'s existing guard pattern. Pick 2–3 representative handlers rather than all of them.
3. **The mobile backend and webhook server still run** — not new tests: confirm the full existing `mobile-backend/*` and `webhook-server/*` vitest suites (already dozens of files, e.g. `mobile_backend_*.test.js`, `dashboard_gh_api.test.js`) pass unmodified after the `electron` devDependency bump, since neither imports `'electron'` directly (verified: no match in `webhook-server/`).
4. **Sandbox is actually on** (new, not in the ticket's bullet list but required by acceptance criterion 3 and the north star): extend `test/show_window.test.js:172`'s `toMatchObject` to include `sandbox: true`; add a source-text assertion in a test file (same style as `github_feed.test.js:192-202`) that `index.js`'s `createWindow`'s `webPreferences` literal contains `sandbox: true`.
5. **Every main-process entry file still parses** — `test/entry_files_load.test.js` already runs `node --check` over every file in `electron/main`, `electron/preload`, `webhook-server`; no change needed, it's the catch-all for a bad merge/syntax regression from the bump.
6. **Empty/huge/malformed renderer payloads** — add a case feeding `relations:ticket`/`relations:pr`-style handlers a huge string or `null`/`undefined` where a repo/number is expected, confirming `Number()`/`String()` coercion + the existing guards don't throw an unhandled exception that would crash the main process (crash = a silent break, which north star 2 forbids).
7. **Repeats/concurrency** — none of this ticket's own new code is concurrency-sensitive (it's two static config flags + a version bump), so no new concurrency test; rely on the existing suite.
8. **Wrong permissions / stale state / person's mistakes** — not applicable to this ticket's actual diff (no new permission or persisted-state surface is introduced); noting it was considered and ruled out rather than skipping silently.

## Task List

1. Resolve the exact target Electron major at implementation time (`npm view electron versions`/release notes — this planning session has no network access to pin a number itself) and read its breaking-change notes plus every major skipped since 30.
2. Bump `electron` in `dashboard/package.json` to that version; update the `allowScripts` key (`"electron@30.5.1": true` → the new pinned version string) so a clean `npm ci` still runs Electron's install script under npm's script allowlist.
3. Check whether `electron-builder` (currently `^24.13.3`) needs a bump for compatibility with the new Electron major; bump if its own compatibility notes say so.
4. Check the new major's minimum Node version against `.github/workflows/ci.yml`'s `node-version: 20` for the `dashboard-tests` job; bump CI (and any local `.nvmrc`/docs that mention it) if required.
5. Flip `dashboard/electron/main/index.js`'s `createWindow` `webPreferences.sandbox` from `false` to `true`.
6. Flip `dashboard/electron/main/show_window.js`'s `makeWindow` `webPreferences.sandbox` from `false` to `true`; update its comment (currently explains why it's `false`).
7. Write the new tests from the list above (sandbox-on assertions in `show_window.test.js` and a new `index.js` source-text test; the unexpected-arguments tests against 2–3 representative IPC handlers).
8. Run the full dashboard suite (`npm test` in `dashboard/`) and fix anything the major bump broke (deprecated/removed APIs this app actually calls — `WebContentsView`, `session`, `protocol.handle`, `nativeImage`, `powerMonitor`, `screen`, per the imports in `index.js`).
9. Run `npm install` + `npm run build:mac` locally to confirm the app still packages.
10. Run `osv-scanner` (or equivalent) against the updated `dashboard/package-lock.json` and confirm zero critical advisories for Electron; since no `osv-scanner` config exists in this repo yet, confirm there is nothing to add that would filter out devDependencies for the future osv-scanner ticket to inherit (i.e., leave no `.osv-scanner.toml`/ignore-devDependencies setting behind).
11. On each Mac: run `dashboard/scripts/rebuild_and_install.sh`, confirm it builds, signs (or falls back to ad-hoc signing), installs over `/Applications/MARVIN.app`, and relaunches.
12. With the sandboxed build installed: click through every tab, run Approve and Decisions submit on a real PR, and run `marvin show` (screenshot evidence) on both Macs, per acceptance criterion 3.
13. Update the explanatory comments at `index.js`'s `createWindow` and `show_window.js`'s `makeWindow` that currently justify `sandbox: false`, since they'll no longer be accurate.