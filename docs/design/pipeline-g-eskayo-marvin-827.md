I have everything needed to write the plan.

## North-star fit

**Reuses:** `windowOpenHandler` + `openLink` in `dashboard/electron/main/external_links.js` (already wired at `index.js:402` for new-window requests, and already safety-tested in `test/external_links.test.js`), and the `target="_blank" rel="noreferrer"` anchor pattern used everywhere else a repo/PR link is rendered (`Markdown.jsx:119`, `MrReview.jsx:320`, `WorkshopItem.jsx:210`, `MrDetail.jsx:241`, `ProposalsSection.jsx:220`, `Decisions.jsx:225`). `SupportTab.jsx:208-210` is the one outlier missing `target="_blank"`, which is why a plain click there performs in-place navigation (`will-navigate`) instead of a new-window request — the only kind of navigation `index.js` doesn't yet guard. The `will-navigate`-guard shape itself (prevent default, optionally hand the URL to a callback) already exists three times for other, specialized windows (`show_window.js:272`, `mockup_window.js:111`, `show_web.js:148`), so the new code is a fourth, minimal instance of the same shape, scoped to the one window (the main dashboard) that lacks it — not a new mechanism.

**Simplest sufficient approach:** two small changes — (1) one attribute added to one anchor in `SupportTab.jsx` so it goes through the existing, already-tested `windowOpenHandler`→`openLink` path like every other link in the app; (2) one new pure function in `external_links.js` (`willNavigateHandler`), wired once in `index.js`'s `createWindow()`, as a second line of defense so *any* future in-place-navigating link (markdown without `target`, a redirect, a script-set `location`) still can't replace the dashboard. I'm scoping "app-wide" to mean "the whole dashboard UI inside the one main window," not literally every Electron window the app creates — the three other windows (`show_window`, `mockup_window`, `show_web`) already have their own, different navigation policies (some intentionally silent-block, not open-externally) that I should not touch; redefining them via a global `web-contents-created` hook would change their behavior outside this ticket's scope and risk. I'll record this as my own scoping call below, not a Decision, since it follows directly from reading the existing specialized-window code.

**Tokens:** spends a few lines of new code; saves having to re-derive the fix next time a markdown/link component anywhere forgets `target="_blank"` — the `will-navigate` guard catches that class of bug once, at the one choke point (the main window), rather than requiring an audit of every `<a>` in the dashboard.

**More capable, not more passive:** this is pure safety plumbing — it removes a trap (losing the whole dashboard to a GitHub page with no way back) without changing what the user does himself.

**Machine:** no preference — it's dashboard/Electron source, built and tested wherever the worktree runs.

## Scoping note (not a Decision — stated for the record)
Electron does not fire `will-navigate` for same-document navigation (hash changes, `history.pushState`), only for real document loads — confirmed against Electron's documented contract and consistent with how `createWindow`'s own hash-based `marvin show` routing (`loadAppPage`, `index.js:365-370`) already works today. So guarding `will-navigate` on the main window cannot break that routing; I verified this by reasoning, not by modifying and re-running (there's no existing index.js-level test harness to run it against — matches the repo's existing practice of leaving `createWindow()`'s wiring untested directly and testing the underlying pure functions instead, as `external_links.test.js` already does for `windowOpenHandler`).

## Tests to write first

In `dashboard/test/external_links.test.js` (new `describe('A link that would navigate the dashboard's own window away')`, mirroring the existing `windowOpenHandler` tests):
1. Always calls `event.preventDefault()`, for both a safe URL and an unsafe one — the window itself must never navigate, ever.
2. Hands the URL to `open()` when it's a legitimate link, supporting both the two-arg `(event, url)` emit shape and the single-arg `event.url` shape (mirrors the defensive dual-shape handling already in `show_web.js`'s `guard`) — Electron's API has carried both shapes across versions in this codebase's own tests.
3. Never opens `javascript:alert(1)`, `file:///etc/passwd`, `''`, `null`, and a 10,000-character garbage string — asserted end-to-end through the real `openLink`/`safeExternalUrl` (no mock), reusing the existing parameterized bad-URL list from `external_links.test.js:51`.
4. Still denies/doesn't throw when `open()` throws synchronously or returns a rejected promise (mirrors the existing "still denies the window when opening the link throws" test).
5. Stateless under repeats: calling the handler many times in a tight loop, interleaved with different URLs, never throws and never carries state between calls (no accumulating listeners/handles).

In `dashboard/test/support_view.test.jsx` (extend the existing `Thread`-rendering tests):
6. The repo#number link in `Thread` now renders `target="_blank" rel="noreferrer"` (the actual fix, regression-locked).
7. A thread whose request body contains a `[click](javascript:alert(1))` markdown link still renders that link with `target="_blank"` — exercised through the real `Markdown`/`ReactMarkdown` component, not a mock, since this is exactly the "javascript: URL in markdown" break-test from the ticket, and Chromium's own target=_blank restriction (not our code) is what neutralizes it — this test documents and locks that existing dependency instead of re-implementing it.
8. `Thread` renders without throwing when `thread.request.url` is missing, empty, or an implausibly long/malformed string (bad/stale upstream API data) — the link still carries `target="_blank"` whatever the href.

Not independently tested, with reasons given directly rather than invented:
- **Middle-click**: Chromium treats a modified click (middle/cmd/ctrl) as a new-window request regardless of the `target` attribute — this is Electron/Chromium-internal behavior, not reachable from jsdom/Vitest, and already covered by the pre-existing `windowOpenHandler` tests (nothing in this fix changes that path). Stated here as a confirmed non-regression, not a new test.
- **Wrong permissions / stale mid-navigation window state**: not applicable — the handler is a pure function attached directly to a live `webContents`; Electron guarantees it only fires while that `webContents` is alive.

## Decisions
None — the fix direction, the file to touch, and the existing pattern to reuse are all unambiguous from the ticket and the code.

## Task List
1. Add `willNavigateHandler(open)` to `dashboard/electron/main/external_links.js`, paired with the existing `windowOpenHandler`: always `preventDefault()`, then pass the resolved URL (supporting both event shapes) to `open()`, swallowing throws/rejections.
2. Write the tests in `dashboard/test/external_links.test.js` (items 1–5 above) against that new function.
3. Wire it in `dashboard/electron/main/index.js`'s `createWindow()`: `mainWindow.webContents.on('will-navigate', willNavigateHandler((url) => openLink(url, { openExternal: shell.openExternal })))`, next to the existing `setWindowOpenHandler` line.
4. Add `target="_blank" rel="noreferrer"` to the repo#number anchor in `Thread` (`dashboard/src/components/SupportTab.jsx:208-210`).
5. Write the tests in `dashboard/test/support_view.test.jsx` (items 6–8 above) against the updated `Thread`.
6. Run the dashboard test suite in full (not just the touched files) per the "full suites before a hand-merge" rule, and confirm no visible rendering changed (the `target`/`rel` attributes are invisible), so the screenshot acceptance criterion needs no screenshots — note that explicitly in the PR rather than omitting it silently.