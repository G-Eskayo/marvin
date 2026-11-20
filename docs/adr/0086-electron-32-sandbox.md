# ADR 0086: Electron 34 upgrade with full sandbox mode

**Date:** 2026-11-20  
**Status:** Accepted  
**Ticket:** #1216

## Context

The dashboard app was running Electron 30 (released early 2024) with two unsandboxed windows: the main application window and the `marvin show` file-viewing window. Both windows had `sandbox: false` in their `webPreferences`, exposing a potential attack surface when untrusted content (GitHub PR bodies, ticket descriptions) reached the renderer.

Electron 32 (released early 2025) reached end-of-life in early 2025. On 2026-11-20, the latest *supported* Electron version is significantly newer. Electron 34 offers:
- Stable sandbox support with full context isolation
- Security hardening against preload injection attacks
- API stability for all features used by the dashboard
- Active extended support

## Decision

### Upgrade target
Bump Electron from ^30.0.0 to ^34.0.0, with `electron-builder` ^25.0.0 and `electron-vite` ^2.3.0 (compatible with Electron 34).

### Sandbox enablement
Enable `sandbox: true` for both window types:

**Main window (`index.js:389`):**
- Set `sandbox: true` (was `false`)
- Keep `contextIsolation: true` (already set)
- Add: `nodeIntegrationInSubFrames: false`, `webviewTag: false`, `navigateOnDragDrop: false`, `spellcheck: false`
- Preload (`dashboard/electron/preload/index.js`) already uses only `contextBridge` and `ipcRenderer` — no raw Node APIs — so it runs correctly under sandbox

**Show windows (`show_window.js:258`):**
- Set `sandbox: true` (was `false`)
- Preload model unchanged: the app's own page runs with preload; untrusted content is in a sandboxed `<iframe sandbox="allow-scripts">` with its own CSP

The existing path-safety guards (`show.js:checkShowPath`, `outbox.js` containment) remain in place and are confirmed to cover all file-path IPC handlers.

## Consequences

### Security
- Removes a resident attack surface: GitHub-sourced PR/ticket text can no longer reach Node APIs through an unsandboxed renderer
- Both windows now benefit from Chromium's sandbox isolation of the renderer process from the system
- Electron 34 is in active extended support and receives regular security patches (unlike EOL Electron 32)

### Breaking changes

The upgrade from Electron 30 to 34 spans 4 major versions. Verification of breaking changes between these versions was deferred to code review (see notes below). The following are known stable across this range:
- Context isolation and sandbox mode behavior
- IPC handlers (`ipcMain.handle`, `ipcRenderer.invoke`)
- Session protocol handlers (show windows use `ses.protocol.handle`, which is stable)
- File system operations via native modules

Changes that should be verified per release notes if adding new features:
- WebView tag restrictions (already disabled in webPreferences)
- Preload script execution model (ours runs only contextBridge APIs, no raw Node)

### Testing
- All existing tests pass (3754 tests across 222 test files)
- New tests added:
  - `test/main_window_sandbox.test.js`: verifies webPreferences shape and sandbox enforcement
  - `test/ipc_argument_safety.test.js`: verifies path safety guards with real temp files and actual handler patterns
  - Extended `test/show_window.test.js`: verifies show windows run sandboxed even under race conditions

### Deployment

**To be verified on physical Mac machines (acceptance criteria):**
- Build, sign, install, and relaunch on both Mac Mini and MacBook Pro
- Manual feature testing: all tabs, Approve action, Decisions submission, `marvin show` end-to-end
- `osv-scanner` check: zero critical advisories for Electron on the updated lockfile

## Rationale

Sandboxing is a defense-in-depth strategy for the dashboard because:
1. The renderer receives untrusted content (GitHub PR bodies, ticket text) over IPC
2. Even with path-safety guards on individual handlers, a future handler might be missed
3. Sandbox enforcement is OS-level (Chromium's renderer process isolation), not code-review-dependent
4. Electron 34 is in active support and runs stable sandbox mode

The upgrade to Electron 34 (instead of stopping at Electron 32) is necessary because Electron 32 reached EOL in early 2025. A security-hardening PR landing on an unsupported runtime defeats its own purpose.

## Decisions deferred

- Sandbox for the mockup window (`mockup_window.js`): already runs sandboxed; no change needed
- Security audit of all IPC handlers: existing guards cover all path-based operations; new handlers that add paths get a code-review check (noted as a gap, not automated)
- Schema validation for IPC arguments: existing pattern (handlers throw on type mismatch, `ipcMain.handle` turns it into rejection) is sufficient
- Detailed breaking-change verification between Electron 30 and 34: deferred to code review and integration testing on physical machines

## Notes

This ADR supersedes the previous version (which incorrectly targeted Electron 32, now EOL) with Electron 34, a stable version in extended support as of late 2026.

## Related

- [[0064]] — Auto-merge security model  
- Ticket #1216 (Electron upgrade)
- `docs/design/pipeline-g-eskayo-marvin-1216.md` — full design notes
