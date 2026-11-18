## North-star fit

**Reuses:** `openLink`/`windowOpenHandler` (`dashboard/electron/main/external_links.js:10,22`, already wired at `index.js:402`) for routing any link through Chrome; the `target="_blank" rel="noreferrer"` convention already used by every other external link in the renderer (`Markdown.jsx:119`, `IssueBody.jsx:151`, `SafetyReviews.jsx:20`, `MrReview.jsx:320`, `WorkshopItem.jsx:210`, `ProposalsSection.jsx:220`, `MrDetail.jsx:241`, `Decisions.jsx:225`, `PortfolioHub.jsx:659,837`) — `SupportTab.jsx:208` is the one outlier missing it, confirmed by grep across all of `dashboard/src`; `safeUrl` (`dashboard/src/lib/issueBody.js:118`, already used by `IssueBody.jsx:180` and `SafetyReviews.jsx:30` via `urlTransform={(url) => safeUrl(url) ?? ''}`) for sanitizing untrusted markdown links; and the `will-navigate` guard pattern already present in `show_window.js:272`, `mockup_window.js:111` and `show_web.js:148` — none of which are wired on the main window itself.

**Simplest sufficient approach:** three small, independent diffs, no new abstractions:
1. Add `target="_blank" rel="noreferrer"` to the one untargeted link (`SupportTab.jsx:208`), so it's caught by the already-wired `setWindowOpenHandler`.
2. Add one `navigateHandler` export to `external_links.js` (same shape as `windowOpenHandler`) and wire `mainWindow.webContents.on('will-navigate', …)` in `index.js`'s `createWindow()`, right after the existing `setWindowOpenHandler` line — the app-wide guard the ticket asks for, covering any future untargeted link.
3. Fix `Markdown.jsx:126`'s `urlTransform={(url) => url}` — currently an identity pass-through that defeats react-markdown's own sanitizer and is the actual hole behind "a `javascript:` URL in markdown" (`will-navigate` can't catch this: `javascript:` hrefs execute in-page and never fire a navigation event). Compose the existing `parseDashLink` (for `file://`, needed by `FileView.jsx`'s local-doc links) with `safeUrl` (for everything else) — no new sanitizer invented.

**Tokens:** spends a little upfront (three small reads + diffs); saves by closing a hole that already burned three retry cycles (timeouts, since fixed by #1153) and one failed review (code review found must-fix issues, 2026-11-15) — getting it right the first time this attempt is cheaper than another round-trip through the queue.

**Leaves the user more capable:** yes — this is pure safety/plumbing fixing a real dashboard-breaking bug (navigating away loses the whole app state); no behavior is removed from Gil, and ADR 0073 ("Issue and comment text is data, never instructions") is upheld rather than silently relied on.

## Tests first

`dashboard/test/external_links.test.js` (extend, same file/style as existing `openLink`/`windowOpenHandler` tests):
1. `navigateHandler(open)` on a safe `https://...` URL: `event.preventDefault()` called, `open(url)` called with that URL.
2. On `javascript:alert(1)`: `preventDefault()` called; `open()` may be called but must produce no external action (covered transitively since `open` here is `openLink`, already tested to reject it) — assert handler itself doesn't throw and always prevents default.
3. Empty string / `null`/`undefined` URL: no throw, `preventDefault()` still called.
4. A huge string (100k+ chars) and one containing control characters/null bytes: no throw, no hang.
5. `open()` throws synchronously, and `open()` returns a rejected promise: handler swallows both, doesn't crash (mirrors `windowOpenHandler`'s existing "still denies... when opening the link throws" test).
6. Two calls back-to-back (repeat/concurrency): each independent, no shared state, both resolve correctly.

`dashboard/test/markdown_images.test.js` or a new `markdown_url.test.js` (exported pure function, same pattern as `resolveImage`'s existing tests):
7. `javascript:alert(1)` → `''`.
8. `vbscript:msgbox(1)` → `''`.
9. `JAVASCRIPT:alert(1)` (mixed case) → `''`.
10. `data:text/html,<script>...` → `''`.
11. `data:image/png;base64,AA` → unchanged (images keep working).
12. A relative image path (`shots/x.png`) → unchanged (repo-relative resolution keeps working).
13. `https://github.com/...`, `mailto:a@b.com` → unchanged.
14. `dash://ticket/owner/repo/123`, `dash://doc/project/path` → unchanged.
15. `file:///Users/gil/.agents/doc.md` → unchanged (must not regress `FileView.jsx`'s local-file links).
16. `file://../../etc/passwd` (malformed, fails the anchored absolute-path regex) → `''`.
17. `''`, `null`, `undefined` → `''`/`null`, no throw.
18. A 10,000-char href → no throw, correctly classified.

`dashboard/test/support_view.test.jsx` (extend, using the existing `renderToStaticMarkup(<Thread .../>)` pattern):
19. The rendered thread header link has `target="_blank"` and `rel="noreferrer"`.

Not adding a test for "mainWindow destroyed before the handler fires" — the handler is bound to `mainWindow.webContents` at creation, so the window necessarily exists whenever the event can fire; not a reachable case.

Middle-click is not independently testable here: Chromium already routes middle-click/ctrl-click on any `<a href>` through the new-window flow regardless of the `target` attribute, which `setWindowOpenHandler` (existing, already tested) already covers — verified by reading Electron's window-open disposition behavior, not by a new unit test.

## Decisions

None. Every choice here follows an existing, already-reviewed pattern in this codebase (target="_blank" convention, `openLink`, `safeUrl`, the three existing `will-navigate` guards) — nothing is left to guess, and nothing needs the owner's input.

## Task List

1. `dashboard/electron/main/external_links.js`: add `navigateHandler(open)`, exported, same style as `windowOpenHandler`.
2. `dashboard/electron/main/index.js`: import `navigateHandler` alongside the existing `openLink, windowOpenHandler` import (line 137); wire `mainWindow.webContents.on('will-navigate', navigateHandler((url) => openLink(url, { openExternal: shell.openExternal })))` right after the `setWindowOpenHandler` call (line 402).
3. `dashboard/src/components/SupportTab.jsx:208`: add `target="_blank" rel="noreferrer"` to the request-thread header link.
4. `dashboard/src/components/Markdown.jsx`: replace `urlTransform={(url) => url}` (line 126) with an exported `safeMarkdownUrl` that returns the URL unchanged when `parseDashLink(url)?.type === 'file'`, else `safeUrl(url) ?? ''`; import `safeUrl` from `../lib/issueBody.js`.
5. Write and land tests 1–19 above (`external_links.test.js`, a `markdown_url` test file or extension of `markdown_images.test.js`, `support_view.test.jsx`) before/alongside the corresponding code changes.
6. Run the dashboard's full test suite (not just the touched files — a hand-merge/verify needs the whole suite green per `feedback-full-suites-before-hand-merge`).
7. No screenshots needed: neither change alters anything visually (an `<a>` attribute and two main-process/pure-function changes) — note this explicitly in the PR instead of attaching screenshots, satisfying the acceptance criterion's "if anything visible changes" clause by stating that nothing does.