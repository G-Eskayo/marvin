## North-star fit

**Reuses before adding anything:**
- `dashboard/electron/main/docs_service.js:image()` — the existing convention that a relative path resolves against the *doc's own folder*, with a leading `/` meaning the repo root. The new link resolver copies this convention instead of inventing another.
- `dashboard/electron/main/docs_local.js:readLocalFile()` — already rejects any path containing a `..` segment after normalization (`"Not a readable doc path"`), and `DocViewer`'s existing `error` branch (`dashboard/src/components/DocsExplorer.jsx:381`) already renders that rejection as a plain message. Both "doesn't exist" and "escapes the repo root" fall out of this existing guard + existing error UI — no new security/validation code needed in the renderer.
- `DocsExplorer.jsx:openFile()` / `jumpToHeading()` / the `pendingHeading` effect (lines 776-787) — the existing "open a doc, then once content has loaded, scroll to a known heading index" pattern, already used for search-result jumps. Extended, not replaced.
- `DocsExplorer.jsx:openDeliverableFile()`'s `fileReq` ref — the existing stale-response guard pattern, reused inside `openFile()` for the new anchor path (this closes a pre-existing latent race in `openFile` too).
- `Markdown.jsx:parseDashLink()` / the `a` component's `dash://` interception branch — extended so a resolved relative link produces the same `{ type: 'doc', project, path, anchor }` shape and renders through the identical click-interception + styling already in place.
- `docs_text.js:extractOutline()` — the single source of heading order/text; new `slugifyHeading`/`headingIndexForAnchor` live beside it instead of re-parsing markdown elsewhere.

**Simplest sufficient approach:** one new pure file (`doc_links.js`, ~20 lines) plus small additions to three existing pure-logic files and two components. No new IPC channel, no new UI component, no new persisted state. The two trickiest requirements (missing file, escaping root) are free side effects of code that already exists for other reasons.

**Tokens/cost:** fixed, small, one-time cost (a handful of small diffs); no new recurring IPC traffic — anchor matching reuses the content already being fetched to open the doc.

**Phone-OS direction:** small positive — the Docs tab becomes a more complete, self-contained reader (cross-doc and in-doc navigation stay inside the app).

**More capable, not more passive:** yes — resolving a relative path or finding a heading has no learning/judgment value for the user; today they have to manually go find the target file. Nothing here reduces human judgment where it matters.

No north star argues against this.

## Decisions

None needed. Every requirement resolves via an existing pattern or a reasonable, low-stakes default (documented inline, not worth a button-choice): anchor matching on duplicate heading text takes the first match; an anchor that matches nothing is a silent no-op (lands where the doc already opens, same as today).

## Tests to write first

**`dashboard/test/doc_links.test.js`** (new) — `resolveDocLink(href, docPath)`:
1. Sibling link: `resolveDocLink('0033.md', 'docs/adr/0032.md')` → `{ path: 'docs/adr/0033.md', anchor: null }`.
2. `../` traversal within the repo: `resolveDocLink('../adr/0033.md', 'docs/plans/x.md')` → `{ path: 'docs/adr/0033.md', anchor: null }`.
3. Leading-`/` repo-root link: `resolveDocLink('/CONTEXT.md', 'docs/adr/0032.md')` → `{ path: 'CONTEXT.md', anchor: null }`.
4. Cross-doc link with anchor: `'../adr/0033.md#decision'` → `{ path: 'docs/adr/0033.md', anchor: 'decision' }`.
5. Pure same-doc anchor: `resolveDocLink('#section', 'docs/plans/x.md')` → `{ path: 'docs/plans/x.md', anchor: 'section' }`.
6. Scheme'd links (`http:`, `https:`, `mailto:`, `data:`, `javascript:`) → `null` (left untouched — non-regression for external links).
7. Protocol-relative (`//example.com/x`) → `null`.
8. **Attack — escapes the repo root**: `resolveDocLink('../../../../etc/passwd', 'docs/plans/x.md')` returns a path that still contains a leading `..` (e.g. `'../etc/passwd'`) — it must never resolve to some unrelated-but-valid file; it's left for the real `readLocalFile` guard to reject.
9. **Attack — malformed percent-encoding**: `resolveDocLink('%E0%A4%A.md', 'docs/x.md')` → `null`, no thrown exception.
10. **Attack — empty/whitespace href**: `''` and `'   '` → `null`.
11. **Attack — huge input**: href of 50,000 repeated `'../'` segments resolves without throwing or hanging.
12. Query string stripped before resolving: `'0033.md?x=1#y'` → `{ path: 'docs/adr/0033.md', anchor: 'y' }`.

**`dashboard/test/docs_text.test.js`** (new) — `slugifyHeading`, `headingIndexForAnchor`:
13. `slugifyHeading('Decisions for the owner')` → `'decisions-for-the-owner'`.
14. `headingIndexForAnchor(markdown, 'decisions-for-the-owner')` finds the right index among several headings.
15. **Person's mistake — wrong case**: `headingIndexForAnchor(markdown, 'Decisions-For-The-Owner')` finds the same index.
16. **Attack — duplicate heading text**: two `## Summary` headings → returns the first index, no crash.
17. **Attack — no headings at all**: returns `null`.
18. **Attack — anchor matches nothing**: returns `null`.

**`dashboard/test/docs_view.test.js`** (extend) — new pure `resolveJumpIndex(content, pending)`:
19. `pending = { index: 3 }` → returns `3` regardless of content (search-result path, unchanged behavior).
20. `pending = { anchor: 'x' }` with matching content → returns the resolved index.
21. `pending = null`, or `content == null` → returns `null` (nothing to jump to yet).
22. Anchor that doesn't match → returns `null`.

**`dashboard/test/render_smoke.test.jsx`** (extend) — `Markdown.jsx` render branches via `renderToStaticMarkup` (matching the existing `parseDashLink`/doc-image test style — no click simulation, this codebase has none):
23. `[x](../adr/0033.md)` with `ctx={{ project: 'marvin', docPath: 'docs/plans/x.md' }}` renders through the in-app link branch (`href="#"`, the pill class), not a raw `href`.
24. `[x](#section)` with the same `ctx` also renders through the in-app branch.
25. **Non-regression — no `ctx.docPath`**: the same `[x](../adr/0033.md)` with `ctx={{ repo: 'owner/repo' }}` (a ticket/PR body's shape) renders as a plain `<a href="../adr/0033.md" target="_blank">`, exactly as today — proves ticket/PR bodies are untouched.
26. **Non-regression**: an existing `dash://doc/...` link still renders identically with the new resolver in place (precedence preserved).
27. **Non-regression**: `[x](https://example.com)` with `ctx.docPath` set still renders as a plain external link.

## Task List

1. Add `dashboard/src/lib/doc_links.js` with `resolveDocLink(href, docPath)`; write `dashboard/test/doc_links.test.js` first (tests 1–12), then implement until green.
2. Add `slugifyHeading`/`headingIndexForAnchor` to `dashboard/src/lib/docs_text.js`; write `dashboard/test/docs_text.test.js` first (tests 13–18), then implement.
3. Add `resolveJumpIndex(content, pending)` to `dashboard/src/lib/docs_view.js`; extend `dashboard/test/docs_view.test.js` first (tests 19–22), then implement.
4. In `dashboard/src/components/Markdown.jsx`, add a `resolveLink(href, ctx)` helper (`parseDashLink(href) || resolveDocLink(...)` wrapped into `{ type: 'doc', project, path, anchor }`) and use it in the `a` component in place of the bare `parseDashLink` call; extend `dashboard/test/render_smoke.test.jsx` first (tests 23–27), then implement.
5. In `dashboard/src/components/DocsExplorer.jsx`:
   - pass `ctx={{ ...docCtx, docPath: selectedPath }}` to `DocViewer` instead of raw `docCtx`;
   - thread `anchor` through `onLink` → `openDoc(project, path, anchor)` → `openFile(repoName, filePath, headingIndex, anchor)`;
   - replace the `pendingHeading` state/effect with a single `pendingJump` state resolved via the new pure `resolveJumpIndex`, feeding the existing `jumpToHeading`;
   - add the existing `fileReq`-style stale-response guard (already used by `openDeliverableFile`/`openFolder`) to `openFile`, so a slow earlier open can't clobber a faster later one.
6. Run the full dashboard test suite (`vitest`) and confirm green.
7. Manually run the app against a project with real relative links (`~/.agents`, the one cited in the ticket with 39 links) to confirm links open and `#anchor` scrolls; capture screenshots at 900px and 1440px and pin them on the PR via `marvin-show` (acceptance criterion — the relative-link style visibly changes from plain-blue to the in-app pill).