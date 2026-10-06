# Node/Electron Stack

## Lessons

### Pinned Node version
Use a specific Node version (e.g., Node 20) rather than `latest` or `lts`. Electron requires compatibility testing with the pinned version, and unpinned dependencies can cause CI failures on new Node releases.

### Linux CI, macOS desktop
Electron apps typically run CI on ubuntu-latest (cheaper, sufficient for JavaScript/Electron testing). Desktop development and app signing happen on macOS locally, not in CI.

### Better-sqlite3 and native modules
If the project uses `better-sqlite3` or other native modules, CI must rebuild them via `npm install` with full build tools available. Some projects require explicit `@electron/rebuild` steps.

### Test command requirement
Check that `package.json` has a `test` script defined. Electron apps without a test script should report this clearly — never guess a default.
