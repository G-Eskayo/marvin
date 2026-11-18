I have what I need. Here's the plan.

## North-star fit

Reuses, no new abstractions:
- `dashboard/electron/main/external_links.js` — `openLink()` (Chrome-first, rejects non-http/https/mailto) and `windowOpenHandler()` (deny + redirect), already wired at `index.js:402` for new-window attempts. Adds one sibling pure function, `navigateGuard()`, same shape as `windowOpenHandler()`.
- The per-feature `openLink` IPC channel convention (`docs:openLink`, `outbox:openLink`, `show:openLink` at `index.js:879/901/1325`) — adds `support:openLink` the same way, body identical to `show:openLink`.
- The in-app click-through-main-process pattern already in `Markdown.jsx:99-110` (`window.api?.docs?.openLink?.(...)` inside `onClick`) — applied to `SupportTab.jsx`'s `repo#N` link instead of inventing a new wiring style.
- The jsdom-free click-test pattern already used in `addon_not_set_up.test.jsx:39-44` (call the component as a plain function, walk the returned element tree, invoke `.props.onClick()` directly) plus the `globalThis.window = {...}` stub already used in `decisions_view.test.jsx:74`.

Simplest sufficient approach: two independent, already-precedented, few-line changes (a stateless navigation guard wired once at window creation; one more per-feature `openLink` channel) — no new test infrastructure (no jsdom introduced), no new component abstraction. Cost is a handful of lines plus two small pure-function/component tests; no runtime cost beyond the actual navigation attempt. Doesn't move the phone-OS needle either way — it's a Mac-dashboard correctness/security fix. It leaves the user strictly more capable: removes a dead end (dashboard replaced by github.com, no way back) and closes a real `javascript:`-navigation attack surface, without taking anything away.

The ticket's own "Fix" framing checked out against the code exactly as written — `SupportTab.jsx:208-211` is the only unguarded `<a>`, and `index.js:402` has `setWindowOpenHandler` but no `will-navigate` handler. No correction needed.

## Decisions

None — this is a fully-scoped bug fix with an existing pattern to follow; nothing here needs the owner's choice.

## Tests first

1. `dashboard/test/external_links.test.js` — new `describe('A link that would navigate the window itself away')`, mirroring the existing `windowOpenHandler` block:
   - `navigateGuard(open)` always calls `event.preventDefault()`, for any URL including a `javascript:` URL (the ticket's named attack) and a `file:` URL.
   - calls `open(url)` with the navigated-to URL.
   - still calls `preventDefault()` and swallows the error when `open()` throws (dependency failure — mirrors the existing "still denies the window when opening the link throws" test).
   - calling the returned handler twice in a row (double-click / redirect chain) behaves identically each time — no shared state leaks between calls.
   - malformed input: non-string / empty / `null` URL still gets `preventDefault()` and doesn't throw out of the handler (actual rejection of such URLs is already covered by `openLink`'s existing `it.each` block — the guard itself must just not crash).
2. `dashboard/test/support_view.test.jsx` — extend with:
   - `globalThis.window = { api: { support: { openLink: vi.fn() } } }`; render `Thread` directly as a function, find the `repo#N` anchor via a `find()` walker (reuse `addon_not_set_up.test.jsx`'s helper shape), call `.props.onClick({ preventDefault: vi.fn() })`, assert `preventDefault` was called and `window.api.support.openLink` was called once with `thread.request.url`.
   - the anchor keeps its real `href` (so right-click → Copy Link still works) — assert via the found element's `props.href`.
   - `window.api.support` missing/undefined (stale preload / race) — clicking must not throw (optional chaining).
3. No new test for `support:openLink`'s one-line `ipcMain.handle` wiring or the one-line `will-navigate` wiring in `createWindow()` — consistent with the existing untested wiring of `docs:openLink`/`outbox:openLink`/`show:openLink` and of `setWindowOpenHandler` at `index.js:402`; the pure logic underneath (`openLink`, `navigateGuard`) is what's tested.
4. Middle-click is already covered by the existing, passing `windowOpenHandler` tests — no new code or test needed there; just confirm the suite still passes after the change.

## Task List

1. `dashboard/electron/main/external_links.js` — add `export function navigateGuard(open)` returning `(event, url) => { event.preventDefault(); try { Promise.resolve(open(url)).catch(() => {}) } catch {} }`, with a one-line comment on why (the main window's own navigation must never leave the app).
2. `dashboard/test/external_links.test.js` — add the `navigateGuard` tests from above.
3. `dashboard/electron/main/index.js` `createWindow()` — right after the existing `setWindowOpenHandler(windowOpenHandler(...))` line (~402), add `mainWindow.webContents.on('will-navigate', navigateGuard((url) => openLink(url, { openExternal: shell.openExternal })))`, and import `navigateGuard` alongside `openLink, windowOpenHandler` (line 137).
4. `dashboard/electron/main/index.js` — add `ipcMain.handle('support:openLink', (_event, url) => openLink(String(url || ''), { openExternal: shell.openExternal }))` next to the other `support:*` handlers (~line 444-450).
5. `dashboard/electron/preload/index.js` — add `openLink: (url) => ipcRenderer.invoke('support:openLink', url)` to the `support` namespace (~line 91-102).
6. `dashboard/src/components/SupportTab.jsx` — change the `<a href={thread.request.url}>` at lines 208-211 to add `onClick={(e) => { e.preventDefault(); window.api?.support?.openLink?.(thread.request.url)?.catch?.(() => {}) }}`, keeping `href` and the existing classes/text unchanged (no visible change — no screenshots needed).
7. `dashboard/test/support_view.test.jsx` — add the `Thread` click tests from above.
8. Run `dashboard`'s test suite (not just the touched files) and confirm green before handing off.