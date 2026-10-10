# Docs Tab vs Files Tab: Consolidation Review

## What each tab is for

The dashboard currently has two document-browsing tabs with overlapping names but distinct purposes and architectures. Understanding where each fits is the foundation for deciding whether they should remain separate.

### Docs Tab (built 2026-10-01)

**Content source:** Project documentation — `CONTEXT.md`, `docs/adr/*.md`, and `README.md` from every catalogued GitHub repository and local project folder across the entire account. The tab auto-discovers projects via the project catalog, not hand-maintained list.

**Data origin:** Local-first (reads from a cloned repository on this machine if it exists), with GitHub as fallback when no local copy is present. This makes the view consistent regardless of which projects are currently cloned locally.

**Display capabilities:** Full-text search (30-minute cached, debounced), outline view, rendered markdown with full relation links (`#N` and `ADR 0033` become clickable `dash://` links), full-fidelity Jupyter notebook rendering, board-summary strip per project, and uncommitted/unpushed state badges. Related docs and tickets are discoverable via the Relations panel.

**Audience:** Writers — Gil edits CONTEXT.md and README.md directly in their repositories. The tab is a read-only view onto living documentation, not a content destination.

**Users:** People (Gil reviewing project state, understanding architecture, tracing decisions). Usage frequency is **unknown** — no tab-usage telemetry exists in the dashboard as of today.

---

### Files Tab (designed 2026-08-27, currently in design)

**Content source:** MARVIN's own deliverables — files that MARVIN produces and writes to `~/.claude/outbox/` during ticket work, research runs, and background jobs. Single source tree, no multi-project discovery.

**Data origin:** Local filesystem only — reads the outbox directly. No GitHub fallback, no cloning logic.

**Display capabilities:** Single tree view of the outbox folder, read-only, no search box. File type detection (`detectKind` in `dashboard/electron/main/outbox.js:134-150`) recognizes only `.md`, `.json`, and `.text`; everything else renders as plaintext, and binaries (PNG, PDF, CSV) are read as UTF-8 and break (known bug #402). No relations, no outline, no board strip.

**Audience:** Consumers of MARVIN's output — screenshots, reports, analysis, decisions that MARVIN has finished. The tab is a destination for MARVIN's own deliverables, not a general documentation store.

**Users:** Primarily Gil (reviewing what MARVIN produced), and the pipeline/agents (via the Files tab API, though this is not yet surfaced). Usage frequency is **unknown** — no tab-usage telemetry exists.

---

## Overlap and gaps

The two tabs solve different problems, but there is real overlap and some gaps that create friction today.

### Overlaps

**Naming:** Both called "Docs" and "Files" in the tab bar, but the mapping is inexact. "Files" is too generic (both are files), and "Docs" could plausibly mean either (Docs is project documentation, but Files contain deliverable documents like reports). This ambiguity is the immediate symptom driving the ticket.

**Content addressability:** Projects can end up appearing in both places (e.g., a project with CONTEXT.md gets a Docs card *and* outbox files are visible in Files). A person looking for "where did MARVIN put that analysis?" might check either tab, and the answer could be in both.

### Gaps and asymmetries

**Search:** Docs tab has full-text search over all catalogued documents. Files tab has no search at all — you browse the outbox tree. For a growing outbox with many deliverables, this is a usability cliff.

**Rendering fidelity:** Docs renders notebooks in full detail (plots, images, outputs). Files only understands plaintext — images and PDFs are broken (bug #402). If MARVIN produces a Jupyter notebook analysis, it belongs in outbox (it's a deliverable), but Files can't display it properly today.

**Relations and context:** Docs links tickets to documents, documents to tickets, and PRs to both — a full graph. Files has no relations, no way to see "which ticket produced this file" or "what changed between runs."

**Local vs. GitHub sourcing:** Docs has both — it reads the local clone first, falls back to GitHub if needed, and shows badges for uncommitted/unpushed work. Files has only local — appropriate for deliverables, but asymmetric with how Docs works.

### Settled rule: the outbox vs. plans split

Memory already encodes the split (`feedback-use-outbox-not-scratchpad-for-deliverables`): non-doc deliverables (screenshots, reports, mockups, analysis scripts) go to `~/.claude/outbox/`; reviewed design/planning documents (design docs, task lists, analysis notes that are meant to be revisited) go to `~/.agents/docs/plans/`, which syncs and surfaces in the Docs tab. This is **not an open question** — it's a working rule that has proven in practice. The Docs tab already renders these plans correctly.

---

## Options

Three realistic paths forward, each with different tradeoffs. For each, the description focuses on what Gil will see and do, the migration scope (what code/components change), risks, and the implications for the #402 shared-viewer dependency.

### Option A: Keep both tabs, rename so they no longer read as synonyms

**What you see on screen:**
- Tab 1: **"Projects"** (was "Docs") — displays the project catalog, docs (CONTEXT.md / README.md / ADRs), and the master "Where things are" summary. Local-first, full search, relations. Unchanged feature set.
- Tab 2: **"Deliverables"** (was "Files") — displays MARVIN's output files in `~/.claude/outbox/`. Local only, tree browser, no search. Unchanged feature set.
- No other UI changes. Related documents remain discoverable via the Relations panel.

**Migration work:**
- Update `dashboard/src/App.jsx:18` from `label: 'Files'` to `label: 'Deliverables'`.
- Update `dashboard/src/App.jsx:17` from `label: 'Docs'` to `label: 'Projects'`.
- Update `DocsExplorer.jsx`'s header text and any help/tooltip text referencing the old name.
- No component architecture changes. No merging, no deletion, no new discovery logic.

**Risks:**
- "Deliverables" may still feel like a project/Docs thing to new users — the semantic distinction (catalog vs. output) is learned, not immediately obvious.
- The relationship between the two remains implicit. A user looking at a deliverable has no way to navigate back to the project that produced it without leaving the tab.

**Implications for #402 (shared viewer component):**
- The Deliverables tab will still need the shared viewer component to handle images, PDFs, notebooks correctly (bug #402).
- The shared viewer will be *dedicated* to the Deliverables tab (only Files/outbox files use it), so #402's implementation is simpler (no catalog/project context to carry, no relations to link).
- Recommended in #402: build the shared viewer as a single `UniversalViewer` component that Deliverables plugs in place of the current `FileViewer`.

---

### Option B: Merge into one tab with sources in a sidebar

**What you see on screen:**
- Single tab: **"Docs"** (or "Knowledge")
- Left sidebar with three sections: **Projects** (catalog), **Deliverables** (outbox), **Plans** (reviewed design/task docs)
- Main area: unified renderer that works for all three sources — markdown with relations (projects, deliverables), notebooks (with images), plain text (outbox). The renderer is **shared** across all three sources.
- Each source badge shows whether local/GitHub/outbox, and clicking a document goes to the main area.

**Migration work:**
- Merge `DocsExplorer.jsx` and `FilesExplorer.jsx` into a single unified explorer component (refactor both to share a common document container and tab-like "source picker" sidebar).
- Consolidate search: one search box that searches all three sources (Projects docs, Deliverables content, Plans). This requires extending `docs_search.js` to also search `~/.claude/outbox/`.
- Unify the file viewer: create a shared `UniversalViewer` component that replaces both `FileViewer` (from DocsExplorer/docs.js) and the naive plaintext viewer (from FilesExplorer/outbox.js). This viewer must handle markdown, notebooks, images, PDFs, CSVs.
- Update `App.jsx` to remove the `files` tab from `TABS` array.
- Retire `FilesExplorer.jsx` and `outbox.js` to keep them available for reference but mark as superseded.

**Risks:**
- **Integration complexity:** merging two separate discovery paths (catalog + filesystem + GitHub) into one unified source picker requires careful state management. A bug in the merged code could break both tabs simultaneously.
- **Shared viewer dependency:** the success of this merge hinges on the shared viewer component (#402) being fully functional. Building the merge now and the viewer later creates a broken state (images still broken until #402 ships, but we can't just use the old FilesExplorer as a fallback without duplicating code).
- **Sidebar sprawl:** if the sidebar grows (adding more sources like a Knowledge-base search, or pinned items), discoverability could become harder.
- **Relation complexity:** relating deliverables to projects/tickets (showing "this file was created by ticket #N") requires cross-linking outbox files back to the ticket system, which doesn't exist yet. Relations will be incomplete until that's built.

**Implications for #402 (shared viewer component):**
- **#402 becomes blocking** — the merge can't ship with working image rendering until #402 lands.
- The shared viewer must be **truly universal**: markdown, notebooks, images, PDFs, CSVs, plaintext. This is a larger scope than just "Deliverables images"; it's a core part of the merged experience.
- Recommended in #402: build the `UniversalViewer` as a standalone, composable component with pluggable format handlers. Both the merged Docs tab and any future preview surfaces (e.g., a file manager, a deliverable inspector) can use it.

---

### Option C: Fold the outbox into Docs as a pseudo-project

**What you see on screen:**
- Single tab: **"Docs"** (unchanged name)
- Project list in the sidebar still shows all catalogued projects, **plus a pseudo-project card** at the bottom: **"MARVIN Deliverables"** (or "Output", "Generated")
- Click it to view all outbox files rendered with the same markdown viewer, outline, and relations logic as project docs.
- Outbox deliverables appear alongside projects in search results, marked with a special badge ("Generated").

**Migration work:**
- Update `docs_service.js` to treat `~/.claude/outbox/` as a synthetic catalog entry (a project record with `kind: "outbox"`).
- Extend `docs.js`/`docs_local.js` to handle the outbox as a "local" document source, reusing the same markdown + relations rendering pipeline.
- Remove `FilesExplorer.jsx` and `outbox.js` entirely — they're no longer needed.
- Update `App.jsx` to remove the `files` tab from the `TABS` array.
- Extend `docs_search.js` to index outbox files alongside project docs.

**Risks:**
- **Semantic mismatch:** treating deliverables as a "project" blurs the distinction between (1) design/documentation that lives in repos, and (2) generated output that lives in a temporary folder. Over time this could make the system feel like "MARVIN's output is just another repo," which contradicts the intentional split.
- **Outbox scaling:** if MARVIN produces hundreds of deliverables, the outbox project card could get crowded. The pseudo-project has no repo, no README, so it's less natural to navigate than a real project.
- **Relations incomplete:** relating outbox files back to the tickets that created them requires cross-linking that doesn't exist yet. The pseudo-project would show no relations by default.

**Implications for #402 (shared viewer component):**
- The shared viewer is **optional but recommended** — the outbox files would render via the existing markdown viewer (which already handles notebooks), but images and PDFs would still be broken (same #402 bug as today).
- If #402 is implemented, the shared viewer could be integrated into `docs.js` to improve rendering for all sources (projects, deliverables, plans), not just the outbox.
- Recommended in #402: if this option is chosen, prioritize image/PDF rendering to fix the current broken state. Notebooks already work via the existing renderer; CSV and other formats can wait.

---

## Recommendation

**Choose Option A: Rename to "Projects" and "Deliverables".**

**Rationale:**

1. **Clarity with minimal risk.** The immediate problem is that "Docs" and "Files" sound like synonyms and don't clarify what each tab does. Renaming to "Projects" and "Deliverables" removes the ambiguity at nearly zero migration cost (two string changes, no architectural work).

2. **Unblocks #402 independently.** Option B makes #402 a prerequisite for the merge, turning a bug fix into a blocking dependency. Option C defers #402's benefits (better rendering) but creates semantic confusion. Option A lets #402 be built and shipped on its own schedule. The Deliverables tab gets better rendering as soon as #402 lands, but the tab remains functional (albeit with plaintext-only view) until then.

3. **Preserves the intended split.** The memory rule that separates outbox deliverables from reviewed docs (`~/.agents/docs/plans/`) is working — plans already show in the Projects tab correctly. Renaming honors that split instead of collapsing it.

4. **Simpler to verify.** Option B's merged code path requires testing all three sources (projects, deliverables, plans) through a single renderer. Option A keeps them independent, so verification is straightforward — each tab works as before, with updated labels.

5. **Leaves the door open.** If a merged tab becomes desirable later (e.g., after #402 ships and cross-linking between deliverables and tickets is built), the architecture is still amenable to it. Renaming first doesn't lock us out of consolidation later; merging now would be much harder to unwind if it causes problems.

The recommendation is not "do this now and never merge," but "clarify the names so the current design is intelligible, and revisit consolidation once the dependencies (#402, relations, cross-linking) are in place and proven."

---

## Decisions
<!-- marvin:decisions -->
### merge: Keep Docs and Files as two tabs, or merge them?
- [ ] A: Keep both, rename so they no longer read as synonyms
- [ ] B: Merge into one tab with sources (Projects, Outbox, Plans) in its sidebar
- [ ] C: Fold the outbox into Docs as a pseudo-project, like the master doc
