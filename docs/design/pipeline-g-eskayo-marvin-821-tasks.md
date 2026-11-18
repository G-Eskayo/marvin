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