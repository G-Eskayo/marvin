---
date: 2026-10-10
author: MARVIN (via code audit)
---

# Docs vs Files: Analysis and Path Forward

The dashboard has two file-browsing tabs that exist to serve different functions but overlap visually and in naming. This document reviews what each is for, where they diverge, and proposes three options for resolving the ambiguity — then recommends one.

## §1: What Each Tab Is For

**Docs tab** (`dashboard/src/components/DocsExplorer.jsx`)
- **Purpose:** Cross-project design history — every repository's `CONTEXT.md`, `docs/adr/*.md`, `README.md`, and now `docs/plans/*.md` (merged with the rest of `docs/`).
- **Who writes into it:** Humans writing architecture decisions and design docs; agents writing automated planning documents (e.g., `docs/plans/resume-browser-vs-ai-2026-10-07.md` from an agent's review work).
- **Source:** Live from GitHub (primary) with a local clone fallback if the repo is checked out on this machine — reads identically regardless of which machine runs the dashboard.
- **Relations:** Fully wired into the dashboard's navigation system; Docs appear in the Related panel on tickets and PRs, and tickets/PRs can deep-link back into Docs via the `DocsExplorer` navigation props.
- **Scope:** Every repo across the whole GitHub account that has a `CONTEXT.md` file; auto-discovered, not hand-maintained.
- **Usage frequency:** Unknown (no telemetry; `App.jsx` `navigate()` has no analytics hook).

**Files tab** (`dashboard/src/components/FilesExplorer.jsx`)
- **Purpose:** A single-location viewer for deliverables MARVIN produces — the agent's work products intended for human review or downstream use (mockups, analysis documents, snapshots, screenshots, test data).
- **Who writes into it:** Only agents writing to `~/.claude/outbox/` (the one canonical location for "work products").
- **Source:** Local filesystem only (`dashboard/electron/main/outbox.js`); reads from `~/.claude/outbox` on the current machine.
- **Relations:** Not wired into the relations system — a PR or ticket referencing an outbox file can't deep-link to it today.
- **Scope:** Files in `~/.claude/outbox/` on this machine only.
- **Rendering:** Text, JSON, and plain Markdown only (as of 2026-10-10; images are not yet supported; `#402` adds image support and a shared file-viewer component).
- **Usage frequency:** Unknown (no telemetry).

**The intent is clear in the code and the design docs** (`CONTEXT.md:375–382` for Files; `:417–428` for Docs) — Docs is design/history, Files is deliverables. The ambiguity isn't in the intent, it's in the overlap: both are "file browsers" and both can contain planning documents (Files has generated outbox files; Docs has committed `docs/plans/` files). A new user sees two tabs labeled "Docs" and "Files" and can't immediately tell why there are two, or which one holds what.

## §2: Overlap and Gaps

| Dimension | Docs | Files | Note |
|-----------|------|-------|------|
| **Search** | Full-text search across all projects¹ | No search | Real gap: can't find an outbox file by content |
| **Rendering** | Markdown, notebooks (full fidelity), images | Text, JSON, Markdown (no image support yet) | `#402` adds images/CSV/PDF/notebooks to Files |
| **Relations** | Wired (tickets/PRs deep-link to Docs) | Not wired (outbox files can't be linked back) | Real gap: generated documents feel second-class |
| **Local vs. GitHub** | Both (GitHub primary, local fallback) | Local only (this machine's outbox) | Real structural difference, not a gap — intentional |
| **Outbox vs. `docs/plans`** | `docs/plans/*.md` surfaces in Docs | Generated outbox files surface in Files | **Already correctly split in code** (not unresolved): `doc_paths.js` `groupDocSections` matches `docs/**/*.md` including `docs/plans`; `outbox.js` reads `~/.claude/outbox` only. Feedback memory `[[use-outbox-not-scratchpad-for-deliverables]]` already enforces this split. |

**Real gaps (things the current design can't do):**
1. Find an outbox file by searching its content.
2. Reference an outbox file in a PR/ticket and have it show as Related.
3. Browse outbox files across machines (Docs solves this for repos via GitHub fallback; Files doesn't).

**Not gaps (things that work as designed):**
- Outbox files go to Files, committed plans go to Docs — this distinction is preserved in code and memory.
- Local-only Files browsing is intentional — outbox is ephemeral and machine-specific.

---

**¹ Docs search note:** The `dashboard/electron/main/files_search.js` file implements Docs-tab search (the "Where things are" Spotlight map from `findit`), not Files-tab search. It is wired into `index.js` and its own test file only, not into `FilesExplorer.jsx` or `outbox.js`. The Files tab remains unsearchable.

## §3: Three Options

### Option A: Rename Files

**On-screen change:** Retitle the "Files" tab to something less ambiguous: "Outbox," "Deliverables," "Generated," or "Produced."

**Migration:** Rename `FilesExplorer.jsx` to `OutboxExplorer.jsx` (or similar). Update `TABS` in `App.jsx`. No other code changes.

**Migration cost:** 2–3 hours (one rename refactor, test, confirm).

**What it fixes:** The name "Files" reads as a generic file browser and a synonym of "Docs." A clearer name signals that this is *one specific location* (the outbox), not a general filesystem view.

**What it doesn't fix:**
- Files are still not searchable.
- Files are still not wired into relations (no deep-linking from tickets).
- Files are still local-only (no cross-machine browsing).

**Risk:** Low. A renaming is self-contained and doesn't change the system's shape.

### Option B: Merge Into One Tab with Sidebar Sources

**On-screen change:** One "Content" (or "Documents") tab with a sidebar picker: Projects (Docs), Outbox (Files), MARVIN Master Doc (a special pseudo-project, like the catalog entry for shared settings).

**On-screen behavior:** Clicking "Projects" shows the current Docs view; clicking "Outbox" shows the current Files view; the main panel switches between them. The sidebar is permanent.

**Migration:** Refactor `DocsExplorer` and `FilesExplorer` into a unified `ContentExplorer` component with a sidebar. Add sidebar navigation logic. The underlying data fetching (`docs_service.js`, `outbox.js`) doesn't change.

**Migration cost:** 8–12 hours (component refactor, sidebar UX, state management, testing).

**What it fixes:**
- One tab means one name, one entry point — no ambiguity.
- Sidebar makes the dual sources (committed design + generated deliverables) explicit.
- Can expand the sidebar later to add cross-machine outbox browsing (e.g., "Outbox — this machine" vs. "Outbox — Mini").

**What it doesn't fix:**
- Still no search across Files (that's a `#402`-dependent feature).
- Still no relations wiring for outbox files.

**Risk:** Medium. Merging two views into one tab risks losing discoverability ("where did Docs go?") if the sidebar isn't clear. Requires UX validation.

**Blocks on:** `#402` in a minor way — if `#402` builds a unified file-viewer component, that component should live somewhere this merged tab can use it too (no new coupling, just shared ownership).

### Option C: Fold the Outbox Into Docs as a Pseudo-Project (Recommended)

**On-screen change:** The Docs tab gains a new "card" at the top or in a special section: "Outbox" (or "Generated — this machine"), rendered the same way as project cards but sourced from `~/.claude/outbox/` instead of GitHub.

**On-screen behavior:** Clicking the Outbox card opens that file browser within the Docs tab's own frame, reading from the same `docs_service.js`/`readFile` infrastructure. It appears in the project list like any other.

**On-screen benefit:** No new tab, no new mental model — Docs is still "design and deliverables," just making the deliverables visibly local to this machine (via a label like "Outbox — Mac Mini") and the committed ones visibly cross-machine (via project cards with "source: GitHub").

**Migration:** 
1. Add a pseudo-project entry to the catalog (or hardcode an "Outbox" entry, following the pattern of `MASTER_ID` in `docs_service.js:9, 29, 43, 65`).
2. Teach `DocsExplorer` to render an Outbox card like a project card.
3. Modify the file-fetch logic to handle `source: 'local-outbox'` the same way it handles `source: 'local'` (read from `~/.claude/outbox` instead of a cloned repo).
4. Hide or repurpose the Files tab (or leave it as a legacy fallback if other tools link to it).

**Migration cost:** 6–8 hours (catalog entry, card rendering, file-fetch branching, testing).

**What it fixes:**
- One tab (Docs) replaces two — simpler mental model.
- Outbox appears in the same list as projects, making it visible at a glance.
- Reuses the proven `MASTER_ID` pattern (used in `docs_service.js` for the master doc) instead of inventing a new "sidebar" or "dual-source" concept.
- The outbox card is labeled with the machine name, so cross-machine browsing (a future feature from `#402` or beyond) can show multiple outbox entries ("Outbox — Mac Mini," "Outbox — MacBook Pro").
- When `#402` delivers its shared file-viewer component, Docs can use it without any new wiring (just import and use in `DocsExplorer`).

**What it doesn't fix:**
- Still no search across outbox files (deferred to a later feature or `#402`'s work).
- Still no relations wiring for outbox files (that's a separate follow-up: add a `Related` card to link outbox files back to tickets).

**Risk:** Low-to-medium. The pattern is proven (`MASTER_ID`), and the refactor is contained within `DocsExplorer`. The main risk is UX clarity: is it obvious to a new user that "Outbox" is a special entry, not a GitHub project? Mitigate with a clear label ("Outbox — this machine") and an icon or visual distinction.

**Synergy with `#402`:** High. Option C places the shared file viewer (from `#402`) directly in the Docs tab's existing component tree, with no new wiring needed.

## §4: Recommendation

**Choose Option C** (fold outbox into Docs as a pseudo-project).

**Why:**
- **Reuses existing patterns:** The `MASTER_ID` pattern already exists in `docs_service.js` and is proven. No new abstractions needed.
- **Simplest sufficient shape:** One tab instead of two removes ambiguity; a pseudo-project entry is simpler than a sidebar or a merged component.
- **Closes both real gaps via `#402`:** When `#402` delivers image/CSV/PDF/notebook rendering, the Docs tab gets it for free (no new wiring). When relations-wiring for outbox files lands (a separate feature), it uses the same infra as project docs (both are now in `DocsExplorer`).
- **Preserves the real distinction:** Local/ephemeral (outbox, machine-specific) vs. committed/cross-machine (projects, GitHub-sourced) is still clear in the card labels and source indicators.
- **Scales to multiple machines:** As Gil's setup grows (Mac Mini + MacBook + others), the outbox entries can be labeled per machine, and a future feature can show all of them in one list.
- **Least risky UX change:** A new card in an existing list is simpler to understand than a new sidebar or a merged tab; existing Docs users see their familiar view plus one new entry.

**Next step:** Implement Option C in a follow-up ticket, filed only after Gil chooses it.

## Connections

- **`#402`** ('Files tab: show every file in its most readable form'): Builds the shared file-viewer component that Docs will use after Option C lands. Option C depends on `#402` being complete for full functionality (image/CSV/PDF/notebook support in the outbox card), but the refactor itself can land first — the outbox card will show text/JSON/markdown until `#402` ships.
- **Relations wiring for outbox files:** A separate future feature (not scoped here) to add `Related` deep-linking from tickets/PRs to outbox files. Unblocked by this choice; Option C makes it easier because outbox and project docs live in the same component.
