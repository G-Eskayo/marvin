# Docs and Files merge: design (marvin#403)

Ticket: G-Eskayo/marvin #403 "Docs vs Files: review the two tabs and whether to merge them".
Decision (Gil, 2026-10-21): fold the Files tab (the `~/.claude/outbox` browser) into Docs. Each project shows its
deliverables next to its CONTEXT, decisions (ADRs) and README. Deliverables are matched to projects from text, not a
hand-kept list. Anything that matches no project goes to **Unsorted**. One search covers both. The Files tab goes away,
and every file renders through the shared `FileView` / `ImageViewer` from #402 "Files tab: show every file in its most
readable form (images, markdown with images, PDFs, tables)" (PR #561).

This is the design step. No dashboard code changes here. The layout needs Gil's pick from the mock-ups (PR Decisions)
before a build ticket is cut.

## 1. What Gil sees

The same in every option:

- The tab bar loses **Files**: Metrics, MR Review, Health, Docs, Activity, Portfolio.
- The Docs search box says *Search all docs and deliverables…*.
- A new **Unsorted deliverables** entry sits under *Where things are* at the top of the project list, with a count.
- Every deliverable opens in the main pane through #402's `FileView`: images in `ImageViewer` (click to zoom),
  markdown rendered with its images, PDFs, CSV tables, HTML in the sandboxed frame, and code or text as text.
  Each file shows **why it was matched**, e.g. "matched to clarity-captions by the phrase 'seal speak' in its docs".
- A ticket number in a folder name links to the ticket (`seal-speak-share-139-…` shows `#139`), using the same link
  style as `#123` in docs. Clicking it goes to Activity, like any other ticket link.
- The tab draws the last saved match map instantly and refreshes in the background
  (memory rule: dashboard loads from saved state).

The three layouts (mock-ups: `docs/screenshots/ticket-403-*.png`, and the phone-friendly page
`~/.claude/outbox/marvin-403-docs-files-merge-2026-10-21/docs-files-merge-mockups.html`):

| | Project page | Unsorted | Search |
|---|---|---|---|
| **A. Section on the card** | The doc tree is unchanged. The project card ends with a **Deliverables** section: one card per folder, newest first, with image thumbnails and kind badges, and "Show all N". | A page listing the 7 whole items and the 10 leftovers from mixed folders, with the naming rule that files them. | One list. A `Doc` / `Deliverable` tag on each result. Image and folder hits show thumbnails. |
| **B. Groups in the tree** | The second column has two collapsible groups, **Docs** and **Deliverables**. Deliverable folders expand to files with #402 kind badges. A file opens in the main pane exactly as a doc does. | The same tree, for the unsorted items. | Results grouped: Docs (n), then Deliverables (n). |
| **C. Tabs on the page** | A tab strip: **Docs / Decisions / Deliverables**. The tree lists the active tab's items. Deliverables is a grid of folder cards with cover images. | Only a Deliverables tab, as a grid. | Filter chips: All, Docs, Decisions, Deliverables. |
| **Hybrid of B and C** (added 2026-10-21 after Gil: "I like B and C") | B's tree with C's three groupings as top-level collapsible groups: **Docs**, **Decisions** (the ADRs), **Deliverables**. Selecting a file opens it in the main pane, as in B. Selecting a deliverable *folder* shows its contents as C's card grid. | The tree has only a Deliverables group. Its root shows the card grid of the whole items, plus the mixed-folder leftovers. | C's filter chips on top of results grouped Docs / Decisions / Deliverables. |

### New visual elements (everything else is the current app's markup and classes)

- All options: the *Unsorted deliverables* list entry and its count badge. The changed search placeholder. The
  "matched by …" line. The `#n` ticket chip on a folder name (reuses the Markdown ticket-link classes). The
  `Deliverable` result tag (reuses the emerald project-chip classes from "Files on this Mac"). Kind badges reuse
  #402's `file_kinds.js` labels and classes.
- A: the Deliverables section on the project card (folder cards with a thumbnail strip). Its card style reuses the
  search-result card classes.
- B: group headers (`▾ DOCS 56`, `▾ DELIVERABLES 8`). Doc sections become collapsible. The tree column is wider
  (`w-72` instead of `w-56`) so dated folder names fit. A file header with *Reveal in Finder* reuses #402's
  file-card button.
- C: the page tab strip with counts, and the grid of folder cards with a cover image. "Decisions" is a new
  grouping of `docs/adr/`. Search filter chips.
- Hybrid (mock-ups `ticket-403-h-*.png`):
  - Three top-level group headers in the tree (`▾ DOCS 33`, `▸ DECISIONS 24`, `▾ DELIVERABLES 8`). Decisions
    holds `docs/adr/`, which moves out of the Docs group. B's collapsible doc sections and the `w-72` tree column
    carry over.
  - Deliverable folders in the tree expand to subfolders and files. A selected folder is highlighted like a
    selected doc.
  - A folder header in the main pane (name, date, file count, matched by, *Reveal in Finder*) and a 4-column grid of
    item cards. Images show a cover; markdown shows its first heading and opening text; subfolders show their
    first image and file count. The card classes are C's.
  - The Unsorted root is a selectable group header that shows C's folder-card grid.
  - Search: C's chips (All, Docs, Decisions, Deliverables) above group labels in B's style, now three groups.
  - Alternative mocked but not recommended (`ticket-403-h-1b-file-open-tree-chips.png`): Docs / Decisions /
    Deliverables as rounded chips at the top of the tree column, which then lists one grouping at a time.

## 2. Matching outbox items to projects

The rule is derived, never stored. A project's **vocabulary** comes from the catalog that the Docs tab already reads
(`lib/project_catalog.py` → `~/.claude/catalog/projects.<device>.json`, read by `electron/main/catalog.js` and
`docs_service.js`):

- the id (the `portfolio:` prefix is dropped), the name, the GitHub repo name, the basenames of its local folders;
- the `aliases` field the catalog already supports in `overrides.json`. It already exists for memory-note matching.
  It is optional: the measurement below is identical without it.

All names are slugged the same way (lowercase, runs of other characters become `-`), and dates (`2026-10-21`,
`202610161406`) are stripped from item names. Each **top-level** outbox item (folder or loose file) is tried in order.
The first tier that gives exactly one project wins:

1. **Name.** A project slug appears as whole words in the item name. The longest slug wins
   (`clarity-captions-xcode-string-churn` → clarity-captions). A number right after the slug is that project's ticket
   (`marvin-402-files-viewer` → marvin, #402).
2. **Inside a name.** The item's words are a run inside exactly one project's slug (`resume-selector` →
   ML-Powered-Resume-Selector-using-Naive-Bayes). One word counts only when it starts the slug (`mitre` →
   mitre-technique-prediction). A tie between an active and a dormant/archived project goes to the active one.
3. **Number.** `pr-359`, `ticket-402` or `t555`. This resolves only when exactly one repo has that number. The PR
   and issue lists come from the relations index, which is already in memory.
4. **Content.** The first 2 KB of up to 20 text files inside name `G-Eskayo/<repo>` (the same qualified-ref rule as
   `relations.js` `extractRefs`) or a project folder (`~/Developer/<dir>/`). `~/.agents` doesn't count, because every
   MARVIN run command mentions `~/.agents/venv`. One project must clearly lead (at least twice the votes of the next).
5. **Docs phrase** (top-level items only). A 2 to 4 word window of the name occurs at least twice in one project's
   docs, and at least twice as often as in any other project's docs (`seal speak`: clarity-captions 5, marvin 2).
   It runs over the docs search index, which covers local and GitHub docs, so it gives the same answer on both Macs.
   The dominance rule matters because MARVIN's own docs mention every project.

Then:

- **Children follow their folder.** A child that names a different project on its own (tiers 1 to 4) moves to that
  project. This is how `ci-workflows/` and `migrations/` split across projects.
- **Unmatched folders** are split child by child. Children that still match nothing stay in Unsorted under their
  folder name.
- `README.md` at the outbox root is the outbox's own readme and is skipped.

### Measured against the real `~/.claude/outbox` (2026-10-21, MacBook Pro catalog, 36 projects)

Script and full output: `~/.claude/outbox/marvin-403-docs-files-merge-2026-10-21/outbox-match-measurement.py` and
`outbox-match-result.txt`. It runs in about 0.4 s in Python, including reading every local clone's docs.

- **28 top-level items:**
  - **16 matched whole:** 7 by name, 1 by number, 2 by content, 6 by docs phrase.
  - **5 were split by their children:** `backups/` (1 of 5 matched), `ci-workflows/` (3 of 4), `migrations/`
    (13 of 18), `pr-screenshots/` (5 of 5, all marvin by PR number), `repo-diffs-2026-10-06/` (2 of 2).
  - **7 went to Unsorted whole.**
- **Unsorted, 17 entries (65 files):**
  - Whole items: `2026-08-22-instagram-ai-saves/`, `portfolio-mockups-2026-10-09/`,
    `portfolio-research-2026-10-10/`, `storage-2026-10-06/`, `sync-stash-rescue-2026-10-08/`,
    `readme-diffs-2026-10-05.diff`, `usage_probe.py`.
  - Left over in mixed folders: `backups/claude-sync-stash-2026-10-14.patch`,
    `backups/claude-sync-stash-2026-10-15.patch`, `backups/quarantine.md.conflicted-2026-10-14`,
    `backups/settings.json.pre-home-202610161406`, `ci-workflows/README.md`, `migrations/algorithms`,
    `migrations/anomaly-detection`, `migrations/marketplace-ml-agent`, `migrations/pipeline`,
    `migrations/regression-and-classification`.
- **Per project:** marvin 16 items; clarity-captions 8 (the five `seal-speak-*` folders,
  `clarity-captions-xcode-string-churn-2026-10-20`, `ci-workflows/clarity-captions`, `migrations/clarity-captions`);
  paper-dive, resume-tailor, Distributed LLM Inference and SkineeDipping 2 each; 8 more projects 1 each.
- **Misses that are honest, not bugs:**
  - `migrations/anomaly-detection` fits two projects (ML_unsupervised_learning-anomaly-detection-project and
    anomaly-detection-v2), so it stays Unsorted rather than guessing.
  - `portfolio-mockups-2026-10-09` holds both portfolio-site shots and #377 marvin shots.
  - The `seal-speak-*` folders match only through the docs-phrase tier. The catalog doesn't know clarity-captions
    ships as *Seal Speak*; that name lives in its ADR 0011 and README. Adding `"aliases": ["seal-speak"]` in
    `overrides.json` would make it a name match, but nothing needs it.
- **Rejected while measuring** (too many false positives): a bare docs-phrase rule without dominance put
  `regression-and-classification` in marvin and `settings-no-saved.png` in killer-sudoku. Single words inside a
  slug put `repos.sh` in ingested-repos. Counting `~/.agents/` paths put the Instagram report in marvin. None of
  these is in the final rule.

How Gil files something by hand without a hand-kept list: name it `<project>-<topic>-<date>` or `<project>-<n>-…`.
This is already the outbox README's convention and what MARVIN writes today. The Unsorted page says so.

## 3. One search across docs and deliverables

Extend `electron/main/docs_search.js`. Don't add a second index.

- `docs_service.js` gets `deliverables()`. It returns entries in the shape `searchDocs` already takes:
  `{ repo: <projectId | '__unsorted__'>, path: 'outbox/<rel>', label, content, kind: 'deliverable' }`.
  - **Text deliverables** (md, txt, json, csv, html with tags stripped) index their text, capped at 200 KB a file,
    and split into sections by `splitSections` as docs are.
  - **Every deliverable** also gets one section made of its path words (`seal speak app store 2026 10 20 ipad 13in 1
    captions paper png`), so images, PDFs and video are found by name.
- `createIndexer` merges these like local docs. They are local files, read once, kept in memory, and refreshed in
  the background when the new `outbox` trigger fires. `searchDocs` itself doesn't change. The renderer reads
  `r.kind` to tag, group or filter results (the A, B or C search layout).
- The "Files on this Mac" Spotlight section stays as it is.

## 4. What happens to the Files tab

- Remove `files` from `TABS` in `App.jsx`. Delete `FilesExplorer.jsx` once its `FileView` use moves into `DocsExplorer`.
- Keep `outbox.js` (`resolveOutboxPath`, `listOutboxTree`, `readOutboxFile` and #402's kind-aware reads) and the
  `outbox:content` IPC. Docs uses them for the file pane, and their traversal and symlink guards stay the only way in.
- Any `navigate('files', …)` deep link becomes `navigate('docs', { projectId, outboxPath })`.
- Update CONTEXT.md: the "Dashboard app — Files tab" section says Files was folded into Docs on 2026-10-21 (#403).
  The Docs tab section gains **Deliverable** (a file or folder in `~/.claude/outbox`, shown under the project it's
  matched to) and **Unsorted** (deliverables no project claims).

## 5. Migration and risks

**Migration.** Nothing moves on disk. The outbox stays where it is and keeps syncing (ADR 0022). The match map is a
derived cache (`~/.claude/logs/outbox-matches.json`), so deleting it costs one rebuild. Build order:

1. Matcher plus tests.
2. Deliverables in `docs_service` and search.
3. The chosen layout.
4. Remove the Files tab.

All of it lands after PR #561 merges.

| Risk | Mitigation |
|---|---|
| A wrong match hides a file under the wrong project | Each file shows why it was matched. Every tier needs exactly one winner, so ties go to Unsorted. Adversarial tests use the real outbox names above, plus hostile ones (`marvin-marvin-mobile`, `pr-0`, `../x`, 300-character names, emoji). |
| A bare number gets ambiguous as repos grow (clarity-captions reaching #359 makes `pr-359` fit two repos) | It then fails safe into Unsorted. Prefer `<project>-<n>` names, which MARVIN already writes. |
| Huge folders: `marvin-icon-proto/` has 5,659 of the 5,824 files (454 MB) | Match by the folder name only. The tree lists the first 200 children with "N more". Search indexes paths only past 200 files and text only under 200 KB a file. |
| Different answers on the two Macs | The catalog is per device, but its names come from the same repos. The docs-phrase tier uses the shared docs index (local and GitHub). The outbox itself is synced. |
| Hostile HTML or SVG in the outbox | Rendered only through #402's sandboxed frame and kind-aware reads, with no new path into the filesystem. |
| PR #561 changes `FileView` / `ImageViewer` | This design only calls them. The build ticket is blocked by #561. |
| The docs-phrase tier is the weakest tier | It runs only for top-level items and needs 2x dominance. Today it decides 6 items (the five `seal-speak-*` folders and the research-colony digest, all checked correct) and nothing else. |

## 6. Space and time complexity

Definitions:

- P = projects (36 today)
- V = vocabulary slugs (43)
- I = top-level outbox items (28)
- C = children looked at (≈60)
- F = outbox files (5,824, or 165 outside `marvin-icon-proto`)
- T = total docs text in the docs index

**Matching:**

- **Name and inside-name tiers:** O((I + C) · V · L) substring checks, where L is the name length (≤100). About
  4,000 checks.
- **Number tier:** O(I + C) lookups in per-repo number sets that the relations index already holds.
- **Content tier:** bounded I/O. Each unmatched item reads at most 20 files × 2 KB = 40 KB.
- **Docs-phrase tier:** for each still-unmatched top-level item, at most ~10 windows (2 to 4 words of a name of 8
  words or fewer), each scanned against the docs text: O(W · T). Today it runs for the 18 top-level items the cheaper tiers miss.
- **Steady state:** results are cached by `(item name, mtime)`. An outbox change re-matches only the changed
  top-level item, which is O(1) items. A catalog or docs change marks the cache stale and rebuilds it in the
  background (about 0.4 s measured, whole outbox).
- **Space:** the match map is O(I + C) small records, about 10 KB on disk.

**Indexing:**

- **Time:** O(F_text · s) to read and split text deliverables, where s ≤ 200 KB, plus O(F) path sections. That's
  done once, then incremental on the `outbox` trigger. A search stays the same `searchDocs` linear scan over
  sections: O(sections · |query|). It grows by about 165 entries plus the capped proto folder, against 295+ docs.
- **Space:** O(Σ min(size, 200 KB)) of text for text deliverables, plus one short path string per file. There is
  no image data in the index; thumbnails are read on demand through `outbox:content`.

## 7. Patterns reused

- **Project catalog and `docs_service`** (`find`, `tree`, `content`): deliverables become another part of the tree
  that `tree(id)` returns.
- **`relations.js` `extractRefs`**: qualified `owner/repo#n` and `#n` refs (content tier, ticket chips), and the
  relations index's PR and issue lists (number tier).
- **`docs_search.js` `searchDocs` / `createIndexer`**: the local-docs path (read once, refresh on a trigger), with no
  second index.
- **`files_search.js` `projectFor`**: path-prefix attribution to a project. It's the same idea as the content tier's
  `~/Developer/<dir>` rule.
- **`triggers.js` `watchFiles`**: a new `outbox` topic on `~/.claude/outbox`, debounced like `docs`.
- **`docs_cache.js`**: renders saved state at boot, then refreshes.
- **#402**: `FileView`, `ImageViewer`, `file_kinds.js` labels and badges, the `outbox.js` guards.
- **Existing UI**: `TreeItem`, `StateBadge`, the search-result card, the `Related` section, the Markdown ticket-link
  style.

## 8. North-star fit

- **Reuse first.** There's no new tab, no new index and no new viewer. One matcher (about 150 lines with tests) plus
  layout work.
- **Elegant sufficiency.** Five cheap textual tiers clear 16 of 28 items whole and most children. The rest go to
  Unsorted honestly instead of guessing.
- **Phone-OS direction.** One place per project for "what it is" and "what it produced". Option B's drill-down tree
  maps onto a phone's list → detail navigation best.
- **Leaves Gil more capable.** He finds a deliverable by thinking about the project, not by remembering a folder,
  and the "matched by" line teaches the naming rule instead of hiding it.

## 9. Recommendation

**Update 2026-10-21:** Gil liked B and C, so the hybrid is now the recommended option. It keeps B's single tree, where
files open like docs, and adds C's three groupings, folder grid and search chips.

**Three top-level groups, not tab chips.** With groups, docs, decisions and deliverables are in view together (or
collapsed to one line each), and that's what Gil asked for on 2026-10-21. Chips show one grouping at a time, which
brings back C's separation. At the tree's width the three chips also wrap onto two lines (see `h-1b`). Collapsing
covers the length problem: Decisions starts collapsed (24 ADRs for clarity-captions, 69 for marvin). Whether a
group stays open per project is left to the build ticket, and it goes to Gil before anyone builds it.

The original recommendation, before Gil's feedback:

**B, groups in the tree.** A deliverable is then just another item in the project's tree and opens in the same pane,
the same way a doc does. That's one mental model and the smallest new surface: two group headers, collapsible
sections and a wider column. It scales to marvin's 16 items because folders collapse. It also reuses `DocTree`,
`TreeItem` and #402's `FileView` with the least new code.

A's thumbnail strip is the best part of A. It could be added to B's project card as "latest deliverables" if Gil wants
the visual overview; the PR's Decisions ask about that as an optional mix.

C splits docs from decisions from deliverables, which works against "docs and deliverables together", and it adds the
most new UI (tabs, grid, chips).

## 10. Open questions (for the build ticket, not blocking the layout pick)

- Should a deliverable folder whose name carries a ticket also appear in that ticket's Related list on Activity? It's
  the same relation seen from the other side.
- Unsorted leftovers like `backups/` and `sync-stash-rescue-*` are MARVIN machinery more than deliverables. Should
  they be hidden from Docs entirely (a derived rule: no date-free folders of `.patch` / `.bak` files), or stay
  visible in Unsorted?
