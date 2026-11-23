## North-star fit

**Reuses:** `electron/main/mockup_window.js` (and `show_web.js`) already run the exact target `webPreferences` shape — `sandbox: true, contextIsolation: true, nodeIntegration: false, nodeIntegrationInSubFrames: false, webSecurity: true, webviewTag: false, navigateOnDragDrop: false, spellcheck: false` — for the two panes that already show untrusted content. The main window (`electron/main/index.js:384-390`) and the `marvin show` window (`electron/main/show_window.js:246-267`) just need the same flag flipped, no new mechanism. `electron/preload/index.js` already only uses `contextBridge`/`ipcRenderer` from `'electron'` (no other Node import), which is exactly what a sandboxed preload is allowed to use — so no preload rewrite is needed. IPC argument-rejection already exists generically via `timed()`/`instrumentIpc` in `electron/main/timing.js` (ipcMain.handle's own catch-and-reject, tested in `test/timing.test.js`). PR/ticket-body HTML inertness already exists and is already adversarially tested in `test/issue_body.test.jsx` (`<script>`, `onerror=`, `javascript:`, huge bodies) — none of that is touched by an Electron bump.

**Simplest sufficient approach:** flip two booleans to match an existing pattern, bump one devDependency major (plus whatever electron-builder/electron-vite compatibility that forces), and re-run the existing suite — not a preload rewrite or an index.js refactor. The three prior attempts failed code review/timed out; the likely failure mode is scope creep (trying to make `index.js` unit-testable, or guessing a specific Electron version number) rather than the actual fix being hard. This plan deliberately stays small.

**Tokens:** spends tokens up front (this research pass) to avoid repeating the same three failed iterations; saves by not inventing new test infrastructure for `index.js` (it has never been unit-tested — by design, since `'electron'` outside the real binary isn't a usable module — and this ticket doesn't need to change that).

**Phone-OS direction:** neutral — this is dependency hygiene and attack-surface reduction on an already-built tool, not new capability.

**More capable, not more passive:** yes — closes a real injection path (PR bodies/comments are attacker-reachable text rendered in a Node-adjacent process) without removing any feature Gil uses.

**Machine:** this planning pass ran in the ticket's worktree (headless-safe). The actual `npm run build:mac` / `rebuild_and_install.sh` / sandboxed-tab verification must run on a real Mac with a GUI session — noted as a Decision below, since the acceptance criteria literally require both Macs and this worktree can't satisfy that by itself.

## Decisions

Two things in this ticket can't be settled by code-reading alone; both appear to be exactly what made the prior 3 attempts fail or stall (one timed out at 20 min, two failed review with unspecified "must-fix issues" — plausibly disputes over how to treat these same two ambiguities).

```markdown
## Decisions
<!-- marvin:decisions -->
### osvscope: #1216's own acceptance criterion says "osv-scanner shows zero critical advisories for Electron" — but osv-scanner isn't wired into this repo yet (that's #1218, still open). How should this PR treat that criterion?
- [ ] A: Drop it from this PR's acceptance criteria; verify "no known critical CVE in the resolved Electron version" by reading Electron's own release/security notes instead, and let #1218 do the automated check once it ships
- [ ] B: Block merging this PR until #1218 ships and reports zero criticals for the new Electron
- [ ] C: Build a minimal one-off `osv-scanner` run in CI just for this PR (ahead of #1218) to produce the number

### verifyboth: "Builds, signs, installs and relaunches through rebuild-and-install on both Macs" and "every tab loads, Approve/Decisions submit, marvin show works (screenshots)" both need a real GUI session on each Mac — this worktree is headless and can't run them. How should that be verified?
- [ ] A: PR ships once `vitest run` is green and `npm run build:mac` packages cleanly here; Gil (or a session with a GUI) runs `rebuild_and_install.sh` on both Macs and the manual tab/screenshot pass before merging
- [ ] B: A follow-up ticket does the on-Mac verification after this PR merges, with auto-merge/trust-ramp rules applying as normal
```

## Tests written first

All in `dashboard/`, run via `npx vitest run` (the "full dashboard suite", `.github/required-checks.json`'s `dashboard` check — Node-only, no real Electron binary needed, confirmed by `vitest.config.js` having no `'electron'` alias/mock today).

**From "How we'll try to break it":**
1. **A PR body with HTML or script content: rendered inert.** Already covered by `test/issue_body.test.jsx` ("a `<script>` or event-handler tag never survives as markup", `javascript:`/`data:text`/`vbscript:` link rejection, HTML-comment stripping, 300 KB body truncation). No new test — rerunning this file after the bump *is* the regression check (it exercises `prepareIssueBody`/`IssueBody.jsx`, which nothing in this ticket touches).
2. **A preload API called with unexpected arguments from the renderer: rejected.** New test in `test/timing.test.js` (or a new `test/ipc_bad_args.test.js` if that file's shape doesn't fit): register a handler shaped like a real one (destructuring its payload, e.g. `({ number, url, head = null }) => ...`) through `instrumentIpc`, invoke it with `undefined`, a bare string, and `null`, and assert the returned promise rejects (doesn't throw synchronously into the main process) and that `recordError` is still called. This generalizes the existing generic `timed()` coverage to the actual "malformed renderer payload" shape the ticket calls out.
3. **The mobile backend and webhook server, which share code, still run.** New guard test (e.g. `test/no_electron_in_shared_code.test.js`): walk `webhook-server/**/*.js` and `mobile-backend/**/*.js` and assert none of them `import ... from 'electron'` or `require('electron')` — true today (confirmed), and this pins it so a future PR can't silently couple them to the Electron major. Combined with: the existing webhook-server tests already inside `dashboard/test` (e.g. `merge.test.js`, `gate_flaky_rerun.test.js`) staying green after the bump, with no code changes needed in either directory.

**New tests for the sandbox flip itself (not explicitly listed, but the acceptance criteria require them):**
4. `test/show_window.test.js`: extend the existing `make()`/`fakeElectron()` harness (it already exposes `windows[].opts.webPreferences`) with an assertion that the created window's `webPreferences.sandbox === true` (and `contextIsolation === true`, `nodeIntegration === false`) — the same style the file already uses, zero new infra.
5. A small source-level regression test (new, since `index.js` can't be imported under vitest — confirmed no test anywhere imports it, by design) asserting `electron/main/index.js`'s main-window `webPreferences` block contains `sandbox: true` and not `sandbox: false`, by reading the file text and matching the specific `createWindow()` block (not a blanket string search, to avoid false negatives from the comment at `show_window.js:258`). This is the minimum honest substitute for unit-testing a module that structurally can't be instantiated outside the real Electron binary.

**Misuse the ticket's list didn't name, added per the north stars' "tests try to break it":**
6. **Repeats/concurrency**: rerun the existing `show_window.test.js` race test ("two shows racing for one project") unchanged — confirms sandboxing doesn't change the dedup/reuse behavior.
7. **A person's mistake**: confirm (existing test, rerun only) that `<img src="https://evil.example/x.png">` inside a PR body still can't phone out, since `img-src` in `index.html`'s CSP is unaffected by this change (`test/csp.test.js`) — not a new test, a noted non-regression.
8. **Each dependency failing**: the build step's existing fallback path in `scripts/rebuild_and_install.sh` (signed build fails → ad-hoc re-sign) is shell, not vitest-covered; call this out explicitly as something the on-Mac verification (Decision `verifyboth`) must exercise at least once post-bump, since a new Electron major can change what `codesign --verify --deep --strict` accepts.

## Task List

1. Research the exact target Electron major at execution time (do **not** guess a version number from training knowledge): check npm's `electron` dist-tags/changelog and Electron's own release/breaking-changes notes for every major between 30 and the target. Record the chosen version and a one-line reason (e.g. "latest stable, no breaking change hits this app's API surface") in the PR body.
2. Check `electron-builder` (`^24.13.3`) and `electron-vite` (`^2.3.0`) compatibility with the target Electron major; bump either if their own docs say so for that major. No other devDependency should need to move.
3. Bump `dashboard/package.json`'s `electron` devDependency (and the `allowScripts` pin) to the chosen version; update `dashboard/package-lock.json` accordingly (`npm install` inside `dashboard/`).
4. Flip `sandbox: false` → `sandbox: true` in `electron/main/index.js`'s `createWindow()` (`webPreferences`, currently line 388).
5. Flip `sandbox: false` → `sandbox: true` in `electron/main/show_window.js`'s `makeWindow()` (`webPreferences`, currently line 258); update its stale comment (currently says "the app's own preload, as the main window" justifying `sandbox: false` — rewrite to reflect the new value).
6. Re-read every breaking-change note for the skipped majors against this codebase's actual Electron API usage (`setWindowOpenHandler`, `webContents.send`, `session.fromPartition`, `protocol.handle`, `net`, `nativeImage`, `powerMonitor`, `WebContentsView`, `screen` — all imported in `index.js`) and patch any renamed/removed API found. Expect this to be a no-op given the narrow API surface actually used, but verify rather than assume.
7. Add the test in task 2/item 4 above (`webPreferences.sandbox` assertion in `test/show_window.test.js`).
8. Add the source-level regression test for `index.js`'s `createWindow()` webPreferences (item 5 above).
9. Add the malformed-IPC-argument rejection test (item 2 above).
10. Add the "no `'electron'` import in `webhook-server`/`mobile-backend`" guard test (item 3 above).
11. Run `npx vitest run` in `dashboard/` (the full suite) and fix anything the version bump broke; confirm the pre-existing `test/issue_body.test.jsx`, `test/csp.test.js`, `test/show_window.test.js`, `test/mockup_window.test.js`, `test/show_web.test.js` and the webhook-server tests all still pass unchanged.
12. Run `npm run build:mac` inside `dashboard/` in this worktree to confirm the app still packages under the new major (electron-builder step only — not sign/install/relaunch, which needs a real Mac GUI session per the `verifyboth` Decision).
13. Resolve the `osvscope` Decision's chosen option and act on it (either write the release-notes-based "no known critical CVE" note into the PR body, or leave the criterion explicitly deferred to #1218, per whichever option is picked).
14. Open the PR with the two Decisions above, naming #1216 ("Closes #1216") and cross-referencing #1218 for the osv-scanner criterion; leave the on-Mac build/sign/install/relaunch and sandboxed-tab/screenshot pass for whoever actions the `verifyboth` Decision.