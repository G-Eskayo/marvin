# Docs vs Files Tab Consolidation Review

**Ticket:** #403 (this review)  
**Related:** #402 (image rendering in Files tab)  
**Status:** Design review, waiting for decision

## Current State: What Each Tab Does

### Docs Tab

**Purpose:** Project architecture, decisions, and reference documentation browser.

**Data sources & reading order:**
1. **Local clone first** (if this project exists on this machine)
   - Reads working tree directly: `CONTEXT.md`, `README.md`, `docs/adr/`, `*.ipynb` (root), `docs/**/*.md`
   - Shows git state badges: `uncommitted` (changed locally, not staged) and `unpushed` (committed but not on GitHub)
   - Implementation: `dashboard/electron/main/docs_local.js`
2. **GitHub default branch** (fallback if no local clone)
   - Reads via GitHub API (identical results on both machines, no local clone needed)
   - Implementation: `dashboard/electron/main/docs.js`

**Search:** Full-text across all projects (currently Docs only).

**Rendering capabilities:**
- Markdown (native via `Markdown.jsx`, with image resolution to GitHub raw URLs)
- Jupyter notebooks (.ipynb) converted to markdown (images embedded as `data:` URIs, always render)

**Relations:** Shows connected tickets, PRs, and docs via the `Related` component (when viewing a project doc), wired into `dashboard/src/components/DocsExplorer.jsx`.

**Current limitations:**
- **Images:** Relative markdown image paths `![alt](imgs/x.png)` resolve to `raw.githubusercontent.com` only for committed+pushed files; uncommitted local images in markdown don't show
- **Notebooks:** Notebook **markdown cells** with relative image paths have the same limitation; **output images** (PNG/JPEG from cell execution) are embedded as `data:` URIs and always render

**Writer:** Authors via git commits. Read-only in the dashboard.

**Usage frequency:** Unknown. No analytics instrumentation in `dashboard/src` or `dashboard/electron/main`.

---

### Files Tab

**Purpose:** Browse generated deliverables (proposals, plans, exports, reports) stored in `~/.claude/outbox`.

**Data source:** Local filesystem only, scoped to `~/.claude/outbox`. Implementation: `dashboard/electron/main/outbox.js`.

**Rendering capabilities:**
- Markdown (via `Markdown.jsx`, same as Docs tab)
- JSON (pretty-printed)
- Plain text

**File detection:** `detectKind()` in `outbox.js` recognizes `.md` → markdown, `.json` → json (if valid), everything else → text. No image rendering, no notebook support.

**Current limitations:**
- **No search**
- **No relations** (no ticket/PR/doc linking)
- **No images:** Relative paths in markdown (`![alt](shots/x.png)`) don't render because `Markdown.jsx` has no outbox context. Issue #402.
- **No notebooks:** `.ipynb` files render as text (JSON) even though `docs/plans/` notebooks convert to markdown in Docs tab
- **Local-only:** Cannot read from GitHub

**Writer:** Agents and manual export tools. All writes to `~/.claude/outbox`.

**Usage frequency:** Unknown (same: no instrumentation).

---

## Overlaps, Gaps, and Anomalies

| Capability | Docs | Files | Gap | Notes |
|---|---|---|---|---|
| **Search** | ✅ Full-text | ❌ None | Files has no way to find files by content | Docs search is Docs-only; outbox not included. |
| **Rendering: Markdown** | ✅ | ✅ | None | Both use `Markdown.jsx`. |
| **Rendering: Notebooks** | ✅ (.ipynb → markdown) | ❌ (renders as text) | Files can't open .ipynb intelligently | Docs converts via `dashboard/src/lib/ipynb.js`; Files lacks this. |
| **Rendering: Images** | ⚠️ Committed only | ❌ Not shown | Both fail on local uncommitted images; #402 fixes Files | Relative markdown images need GitHub URL (Docs) or IPC read (Files). |
| **Rendering: JSON** | ❌ Not supported | ✅ Pretty-printed | Docs can't view JSON exports | Outbox often contains .json snapshots; Docs has no viewer. |
| **Rendering: CSV/TSV, PDF, HTML** | ❌ None | ❌ None | Neither tab handles these | Future work (scope beyond #402). |
| **Relations** (tickets, PRs, docs) | ✅ Via `Related.jsx` | ❌ None | Files provides no cross-linking | Docs only in project doc view (not search results). |
| **Local git state badges** | ✅ uncommitted/unpushed | N/A | Not applicable (Files = generated outbox) | Files doesn't track git state; outbox is ephemeral. |
| **Local + GitHub** | ✅ Local-first + GitHub fallback | ❌ Local-only | Files cannot see GitHub-only paths | Can't link outbox deliverables to repo docs. |
| **Navigation** | ✅ Project selector + doc tree | ✅ File tree (flat, no metadata) | Files structure lacks project/category context | Unlike Docs, no way to know "which project is this for?" |
| **Scope** | Catalog of all projects (multi-repo) | Single folder (.claude/outbox) | Symmetric by design; scopes are intentionally different | Each tab has a different purpose and data model. |

**Note on #402:** Image rendering in Files tab is a known issue (files render as `kind: 'text'` in a `<pre>` block). #402 fixes Files-tab rendering only, via a new outbox-scoped viewer component (images via IPC + `data:` URLs, markdown via outbox-context-aware path resolution, notebooks, CSV, PDF, HTML). It does not change `Markdown.jsx` or fix Docs' own image-resolution gap.

---

## The Outbox vs docs/plans/ Split

The system intentionally separates two categories of deliverables:

1. **`~/.claude/outbox`** → Files tab
   - Generated, ephemeral outputs (proposals, reports, test snapshots)
   - Not in git; not pushed
   - Example: agent-generated proposal.md in Files tab

2. **`docs/plans/`** → Part of Docs tab (when pushed to repo)
   - Hand-curated or stable plans approved for the permanent record
   - Committed to git, pushed to GitHub
   - Example: `~/.agents/docs/plans/storage-and-distribution-2026-10-06.md` shown in Docs tab

**Current state:** Outbox files appear only in Files tab (local-only). Docs-plan files appear only in Docs tab (after push). There is no flow to "promote outbox → docs/plans" in the UI.

---

## Three Options for the Future

### A: Keep both tabs, rename them so they no longer read as synonyms

**On-screen change:**
- Both tabs stay in the tab bar (`App.jsx` TABS array: Metrics, MR Review, Health, Docs, Files, Activity, Portfolio)
- Rename "Files" tab to something more specific (e.g., "Deliverables", "Outbox", "Drafts") to clarify it's not a general file browser
- Add help text to each tab explaining scope: "Project docs and decisions" vs. "Generated proposals and reports"

**Migration work:**
- Change Files tab label in `App.jsx:18`
- Add tooltip/header in each tab's component
- Minimal component changes

**Risks:**
- Two tabs, two code paths, two UI patterns to maintain
- Users may still be confused if naming doesn't land right
- No consolidation of overlapping rendering logic

**What breaks:**
- Muscle memory if users are used to the current label
- Otherwise, additive (no breaking workflow changes)

**Estimated effort:** 1–2 hours (rename + help text).

---

### B: Merge into one tab with sources (Projects, Outbox, Plans) in its sidebar

**On-screen change:**
- Replace Docs and Files tabs with a single unified tab (e.g., "References")
- Left sidebar now shows three sections: Projects (repo docs), Outbox (deliverables), Plans (hand-curated docs/plans/)
- Search spans all three sections
- MASTER_ID pattern in `DocsExplorer.jsx:17` already shows one project as "master"; extend this for Outbox as a pseudo-source

**Migration work:**
- Merge `FilesExplorer.jsx` rendering into `DocsExplorer.jsx`'s FileViewer logic (or create unified viewer)
- Extend data layer: keep `window.api.docs.*` for repos, keep `window.api.outbox.*` for outbox, create unified cache
- Update search (`docs_search.js`) to span all three sources
- Modify `App.jsx:13-21` TABS array (remove Files, keep Docs with new label)
- Add Outbox and Plans as sidebar pseudo-projects or sections

**Risks:**
- Larger merge of two component hierarchies; subtle bugs in unified navigation
- If search doesn't distinguish "which source?" users may conflate repo docs with outbox drafts
- Sidebar becomes crowded (already has Projects, master doc; adding Outbox + Plans = 4 levels of navigation)

**What breaks:**
- Files tab URL/shortcuts (if any exist)
- Mental model: users expecting separate "Docs" and "Files" tabs

**Estimated effort:** 4–6 hours (component merge, sidebar restructure, search unification).

---

### C: Fold the outbox into Docs as a pseudo-project, like the master doc

**On-screen change:**
- Files tab removal is deferred to a follow-up ticket (this ticket does not remove it)
- Docs tab gains "Outbox" as a new left-sidebar entry (same level as other projects, or as a special marker like MASTER_ID)
- Outbox files are browsable in the same doc tree UI as repo docs
- Search includes outbox files (single search bar, all sources)
- Tab bar can go from 7 to 6 once Files tab is removed in follow-up

**Migration work:**
- Add Outbox as a special project-like entry in the Docs tab's RepoList (use `MASTER_ID` pattern or a new `OUTBOX_ID`)
- Extend data layer: `docs_cache.js` loads outbox tree alongside project repos
- Unify rendering: ensure `FilesExplorer.jsx`'s markdown/JSON/text renderers work in DocsExplorer (or shared component)
- Update search to include outbox as a source
- Files tab removal deferred to follow-up ticket (separate decision)

**Risks:**
- Outbox and repo docs have very different meanings (generated vs. committed); treating them as "both just projects" in one UI may obscure the distinction
- Sidebar may feel crowded if Outbox is treated as a project
- If outbox grows large, search performance may degrade
- Users may accidentally treat an outbox draft as a "real" doc

**What breaks:**
- User expectations may shift (Docs tab is no longer about docs alone)
- Files tab is kept for now; removal is a separate follow-up decision after this change ships

**Estimated effort:** 3–5 hours (data-layer unification, pseudo-project wiring, search integration).

---

## Recommendation: **Option A**

**Reasoning:**

1. **Scopes are genuinely different.** The outbox/docs/plans distinction (ephemeral vs. committed) is real and valuable. Merging them into one Docs tab (B, C) obscures this distinction and makes the UI's purpose less clear to new users.

2. **Usage frequency is unknown** (no analytics instrumentation), so we can't justify the cost of B or C (3–6 hours) based on "users will be confused." Option A's low-cost renaming lets us gather direct user feedback before a larger restructure.

3. **Rendering overlap is minimal.** Markdown works in both; JSON/text work only in Files; notebooks need conversion (not yet in Files). A shared viewer would help, but is orthogonal to the tab decision. Fix #402 first, then decide whether rendering consolidation is worth it.

4. **Option A is reversible.** If renaming "Files" to "Deliverables" doesn't help and users still conflate the tabs, we can always merge them later. If we merge now (B, C) and later need to split them, that's harder.

5. **Maintenance burden is real.** Two clear, purpose-driven tabs are easier to reason about than one tab with three sidebar sections. As feature load grows, the trade-off may shift; we're not there yet.

**Path forward:**
- Rename Files tab to "Deliverables" (or similar)
- Add help text / scope clarity to both tabs
- Fix #402 (image rendering) in parallel — this improves Files tab experience regardless of architecture
- Revisit on direct user feedback (support tickets, bug reports) rather than guessing from analytics (which don't exist)
- If users consistently struggle with the distinction after this change, escalate to B or C in a follow-up ticket

**Connections:** #402 (image rendering in Files tab) is one focused fix that benefits all three options equally. Start that ticket in parallel so both features ship together.

---

## Decisions
<!-- marvin:decisions -->
### tabs_architecture: Docs and Files — keep separate, merge, or fold?
- [ ] Option A: Keep both tabs, rename them so they no longer read as synonyms
- [ ] Option B: Merge into one tab, with sources (Projects, Outbox, Plans) in its sidebar
- [ ] Option C: Fold the outbox into Docs as a pseudo-project, like the master doc
