## North-star fit

**Reuses before adding anything:**
- The parse/shape guard already in `load()` (`dashboard/electron/main/instance.js:26-32`: `JSON.parse` + `data && typeof data === 'object' && !Array.isArray(data)`) — factored out and reused for the fresh pre-write read, instead of writing new validation logic.
- The file's own `instancePath()` helper (`instance.js:22`) — currently `load()` and `setFeature` each hardcode `path.join(instanceDir(), 'instance.json')` instead of calling it; the fix uses it in both places.
- The error-banner pattern already used elsewhere in the dashboard for exactly this purpose (`<p role="alert" className="text-sm text-red-400">{error}</p>`, `dashboard/src/components/ProposalsSection.jsx:38`) — reused in `AddonNotSetUp.jsx` instead of inventing new error UI. `role="alert"` plus visible text satisfies the accessibility rule (color never alone).
- The project's pure-helper + static-render test pattern (`prFetchBanner`/`createGithubState` in `error_log.test.jsx`, and `addon_not_set_up.test.jsx`'s `html()`/`find()` helpers) — reused instead of pulling in jsdom/RTL. `vitest.config.js` states explicitly: "Tests render React components to static HTML (react-dom/server)" — this project has no DOM test environment, so `PortfolioHubGate`'s async `useEffect`/handler logic is moved into a small pure function (`enableAddon`) that is directly callable in a test, the same way the codebase already isolates logic from components elsewhere.
- `dashboard/test/instance.test.js`'s existing `at()` fixture (temp engine + temp instance dir, real `git init`) for all new `setFeature` tests — no new test scaffolding needed.

**Simplest sufficient approach:** one new tiny helper file (`enableAddon`) plus edits to the two files the issue names. No new IPC channel, no new persisted state, no jsdom dependency.

**Tokens:** small, localized diff; reusing existing patterns avoids designing and reviewing a new error-handling convention.

**Phone-OS direction:** tangential, but relevant — `instance.json` is the one piece of durable per-person state under ADR 0071; silently losing it is exactly the kind of "something breaks silently" that north star 2 calls out as reliability's precondition.

**More capable, not more passive:** fixes a destructive silent failure and makes a refused action visible instead of swallowed — strictly a safety/correctness fix.

**No Decisions section** — the ticket's evidence and fix description are concrete enough that no genuine open choice remains for the owner.

---

## Design

### `dashboard/electron/main/instance.js`

1. Factor the parse into a shared `readConfigFile()`:
   - Reads `instancePath('instance.json')`.
   - `ENOENT` → `{ config: {}, parseFailed: false }` (fresh install / missing file: writable).
   - Any other read error (EACCES, EISDIR, …), a `JSON.parse` throw, or a parsed value that isn't a plain object (array/string/number/null) → `{ config: {}, parseFailed: true }`.
   - Successful object parse → `{ config: data, parseFailed: false }`.
2. `load()` calls `readConfigFile()` and stores `parseFailed` on the cache (used later if anything needs to report instance health; not required elsewhere by this ticket).
3. `setFeature`:
   - Keeps the `KNOWN_ADDONS` allow-list check first (unchanged).
   - Re-reads with `readConfigFile()` **fresh, bypassing `cache`**, immediately before writing — this is the "re-read just before writing" fix for the race with another process.
   - If `parseFailed`, throws `Error("instance.json couldn't be read — fix or remove it before enabling add-ons")` and returns without touching the file.
   - Otherwise guards `config.features` to a plain object (replacing a wrong-shaped value, never trusting it), sets `features[name] = value`, writes via `writeFileSync(instancePath('instance.json'), ...)`, creates the instance dir if missing (unchanged), calls `reset()`.

### `dashboard/src/lib/addon_enable.js` (new)

```js
export async function enableAddon(name, api) {
  try {
    await api.setFeature(name, true)
  } catch (e) {
    return { features: null, error: e?.message || String(e) }
  }
  try {
    return { features: await api.features(), error: null }
  } catch (e) {
    return { features: null, error: e?.message || String(e) }
  }
}
```
Pure, dependency-injected (`api` = `window.api.instance`), directly unit-testable without a DOM.

### `dashboard/src/components/PortfolioHubGate.jsx`

- Add `error` state.
- `onEnable` calls `enableAddon(name, window.api.instance)`; on error, `setError(message)` (no `setFeatures`); on success, clear the error and `setFeatures(features)`.
- Pass `error` through to `<AddonNotSetUp>`.

### `dashboard/src/components/AddonNotSetUp.jsx`

- Accept an optional `error` prop; render `{error && <p role="alert" className="text-sm text-red-400">{error}</p>}` near the button, matching `ProposalsSection.jsx`'s existing pattern.

---

## Tests (written first)

**`dashboard/test/instance.test.js`** — new `describe('setFeature', ...)` using the existing `at()` fixture:
1. Corrupt JSON (`'{not json'`) + `setFeature` → throws, file byte-for-byte unchanged.
2. Wrong-shaped top-level JSON (`'[]'`, `'"a string"'`) → same refusal, file unchanged (`it.each`).
3. Empty file (`''`) → refusal, file unchanged.
4. Missing `instance.json` (fresh install, dir exists) → succeeds, creates the file as `{"features":{"<name>":true}}`.
5. Missing instance *directory* entirely → succeeds, creates dir + file (ticket's named break-it case: file missing entirely).
6. Valid config with unrelated fields (`owner`, `tickets_repo`, other `features.*`) → after enabling, those fields are byte-identical except the one new `features.<name>` key (acceptance criterion: "only `features` changes").
7. **Race** (ticket's named break-it case): call `features()` to populate the cache, then externally rewrite the file with a different unrelated field, then `setFeature` → the write reflects the externally-written content, not the stale cached snapshot.
8. **Race + corruption**: same as 7, but the external rewrite is corrupt JSON → `setFeature` now refuses (detected fresh, not from the earlier successful cached load); file is left exactly as the external process wrote it.
9. Repeat calls: `setFeature('portfolio', true)` twice → idempotent, well-formed.
10. Toggle off after on → final `features.portfolio === false`, other fields untouched.
11. Unreadable-file stand-in: `instance.json` is a directory (EISDIR) → refuses, portable across root/non-root (no `chmod` reliance).
12. Unknown add-on, including `__proto__`/`constructor` → still throws `Unknown add-on`, file never touched (regression + prototype-pollution misuse).

**`dashboard/test/addon_enable.test.js`** (new, pure-function style):
1. Success path: fake `api` resolves both calls → returns `{features, error:null}`, calls `setFeature` before `features()`.
2. `setFeature` rejects → returns `{features:null, error:<message>}`, never calls `features()`.
3. Rejection with a non-`Error` value (string/object, as IPC can serialize) → still returns a string `error`, never throws.
4. `setFeature` resolves but `features()` then rejects (dependency failure after success) → surfaces that error rather than throwing unhandled.

**`dashboard/test/addon_not_set_up.test.jsx`** (extend existing file):
1. `error` prop renders `role="alert"` + the message text.
2. No `error` prop → no `role="alert"` node (existing cases stay green).
3. Error text is escaped, not raw HTML (mirrors the existing addon-name XSS-escaping test).
4. Error is conveyed by visible text, not color alone (assert both `role="alert"` and the message text together).

Coverage note: `PortfolioHubGate` itself keeps only trivial state-wiring (`setError`/`setFeatures`) around the now-pure `enableAddon`; per this project's own test convention (`vitest.config.js`: components render via `react-dom/server`, no DOM/jsdom), the logic that needs correctness guarantees is fully exercised by the `instance.test.js` and `addon_enable.test.js` suites above, so no jsdom/RTL dependency is added for this ticket.

---

## Task List

1. [ ] `dashboard/electron/main/instance.js`: factor `readConfigFile()` out of `load()`, tracking `parseFailed`; use `instancePath()` consistently.
2. [ ] `dashboard/electron/main/instance.js`: `setFeature` re-reads fresh (bypassing cache) right before writing, refuses and throws when `parseFailed`, guards `config.features` to a plain object before assignment.
3. [ ] `dashboard/test/instance.test.js`: add the 12 `setFeature` cases above (write first, confirm they fail against the current code, then land step 1–2 to turn them green).
4. [ ] `dashboard/src/lib/addon_enable.js`: new pure `enableAddon(name, api)` helper.
5. [ ] `dashboard/test/addon_enable.test.js`: add the 4 cases above.
6. [ ] `dashboard/src/components/AddonNotSetUp.jsx`: accept and render an `error` prop (`role="alert"` pattern reused from `ProposalsSection.jsx`).
7. [ ] `dashboard/test/addon_not_set_up.test.jsx`: add the 4 cases above.
8. [ ] `dashboard/src/components/PortfolioHubGate.jsx`: add `error` state, wire `onEnable` through `enableAddon`, pass `error` to `AddonNotSetUp`.
9. [ ] Run the full dashboard test suite; run the app, trigger a corrupt `instance.json` and a valid-enable path by hand at 900px and 1440px, and pin screenshots on the PR per the acceptance criterion.
10. [ ] PR body: `Closes #786`, name the reused patterns (file + function) per the delegation preamble.