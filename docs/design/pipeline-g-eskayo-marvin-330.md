## North-star fit

**Reuses:** the whole data path already exists. `relations_service.js`'s `build()` already walks every registered repo once per TTL window and assembles a flat cross-project ticket array (`tickets.push({ ...i, repo })`) — it just doesn't keep that array around after building `cards`. `board.js` already has tested, exported-or-exportable blocked-by parsing (`dependencyRefs`/`openDependencies`) that this ticket's own "Blocked by graph" wording points at. `human_task.js`'s `parseHumanTask` already derives the ready-for-human "ask" and is already wired into `ProjectBoard`. `activity:overview` already proves the pattern of a pure function fed by `relations_service`'s cache, with zero extra GitHub calls. The only genuinely new logic is the transitive closure over the blocks graph and the needs-info "missing" derivation (no JS port of `ticket_policy.py`'s section-presence checks exists yet — unavoidable, mirrors the project's accepted Python/JS-pure-function-twin pattern already documented at the top of `board.js`).

**Simplest sufficient approach:** one new pure module (`needs_you.js`) with no IO, fed by data the dashboard already loaded for the boards and the "needs you" badges. No new GitHub calls, no new polling loop (reuses `relations_service`'s existing TTL cache), no new state machine (ranking only — it doesn't re-decide `ready-for-human`/`needs-info`, those labels are trusted as already-triaged).

**Tokens:** spends a small amount once (new pure function + ~10 focused tests), saves on every future "what's actually blocking me" question — this is explicitly the thing a human currently has to reconstruct by reading `life-of-a-ticket.md`'s hand-written tier list by eye.

**User capability:** this is squarely coaching, not replacing — it surfaces leverage so Gil decides faster what to unblock next; it doesn't act on tickets, doesn't change labels, doesn't post comments. Directly closes red-list item #7.

---

## What already exists vs. what's missing

| Needed | Status |
|---|---|
| Cross-project ticket list, already in memory | `relations_service.js` builds it every `build()` call, just discards it (`tickets` array, line ~13-38) |
| Direct "Blocked by" parsing | `board.js: dependencyRefs`, `openDependencies` — not exported, not transitive |
| Transitive closure over the blocks graph | **Does not exist.** `ticket_agents.py: plan_prioritize` only counts **direct** blockers (`blocks[b] += 1`), not transitive — this ticket explicitly asks for transitive, so I can't just reuse that dict |
| needs-info "missing" list, derivable from title+body alone (no comment fetch) | `ticket_policy.py: triage_verdict`/`has_break_it`/`human_task_gaps` — Python only, no JS mirror except the "Your task" subset (`human_task.js`) |
| ready-for-human "ask" | `human_task.js: parseHumanTask(body).fields['What I need from you']` — already exists, already used in `ProjectBoard`'s `HumanTaskPanel` |
| IPC path from dashboard home to board data | `activity:overview` → `relations.overview()` is the exact precedent to copy |
| UI slot named "dashboard home" | `DashboardHome.jsx`, rendered by `ActivityBoard.jsx` when `view === 'home'` |

---

## Design

### 1. `dashboard/electron/main/needs_you.js` (new, pure, no imports beyond `human_task.js` and `board.js`'s exports)

```js
import { dependencyRefs, openDependencies } from './board.js'
import { parseHumanTask } from '../../src/lib/human_task.js'
```

- `missingFor(ticket)` — mirrors `ticket_policy.py: triage_verdict`'s missing-section derivation (What to build / Acceptance criteria / How we'll try to break it), falling back to `parseHumanTask(body).missing` when the ticket reads as a human-task-shaped one (same `_HUMAN_TITLE` regex ported). Reuses `parseHumanTask` rather than re-deriving a second "Your task" gap-checker.
- `blocksGraph(tickets)` — per repo (blocked-by refs are same-repo only in every existing implementation; I'm not inventing cross-repo blocking that nothing else in the codebase supports), build `openNumbers` + reverse-adjacency (`blocks[n] = [dependents]`) via `openDependencies`, excluding `hold`/`not-planned`/`pinned` tickets from both ends (consistent with `board.js`'s existing `ignored` set and `ticket_policy.SKIP_LABELS`).
- `transitiveUnblocks(number, repo, graph)` — BFS/DFS from a node over the reverse edges, visited-set guarded (cycle-safe), returns `{ count, items: [{repo, number, title}] }` sorted by number, deduped.
- `rankNeedsYou(tickets, { now = Date.now() } = {})` — the pure entry point:
  1. filter to `state === 'OPEN'`, label includes `ready-for-human` or `needs-info`, excludes `hold`/`pinned`.
  2. for each candidate: `unblocks = transitiveUnblocks(...)`, `priority` (p0-p3 or null), `ageDays`, `ask` (= `missingFor` for needs-info, = `parseHumanTask(...).fields['What I need from you']` or its own missing list for ready-for-human).
  3. sort: `unblocks.count` desc → `priority` asc (missing priority sorts last) → `createdAt` asc (oldest first).
  4. return rows: `{ repo, number, title, url, kind, unblocks: { count, items: top 3 } }, ask, priority, ageDays }`.

### 2. `relations_service.js` — two small, surgical changes
- `build()`: also return `tickets` (the array it already assembles) alongside `cards`/`prs` — currently thrown away after `buildRelationIndex` is built.
- Add `needsYou: async () => rankNeedsYou((await ready()).tickets)` to the returned service object, same shape as the existing `overview` method.

### 3. `dashboard/electron/main/index.js` / `preload/index.js`
- `ipcMain.handle('activity:needsYou', () => relations.needsYou())` next to the existing `activity:overview` line.
- `preload`: `activity.needsYou: () => ipcRenderer.invoke('activity:needsYou')`.

### 4. `dashboard/src/components/DashboardHome.jsx`
- Add `needsYou` to the existing `Promise.all` load.
- New collapsible section (styled like `NextUpQueue`, for visual consistency with its sibling "what's queued for the agent" list) above "Project Boards": each row shows `#number title`, an `unblocks N` badge (hidden/dim when 0, matching acceptance criterion's "sorts above items that unblock nothing"), the first few unblocked titles, and the one-line `ask` — for `needs-info` rows rendered as "missing: …".
- Clicking a row calls the same `onOpenProject`-style navigation other tabs use (`onOpenTicket` passed down through `ActivityBoard` → `DashboardHome`, a one-line prop addition, same pattern as `NextUpQueue`/`ProjectBoard`).

---

## Tests first (`dashboard/test/needs_you.test.js`, Vitest, no mocks — plain fixture objects like `board.test.js`)

**From "How we'll try to break it" / misuse, applied to a pure ranking function:**

1. **#153-shaped case (the acceptance criterion, literally):** a `ready-for-human` ticket with 5 open tickets whose body says `Blocked by #<that number>` → `unblocks.count === 5`, sorted above a `needs-info` ticket that blocks nothing.
2. **Transitive, not just direct:** A blocked-by nothing; B "Blocked by #A"; C "Blocked by #B" → A's `unblocks.count === 2` (not 1) — this is the one case that would silently regress to the existing *direct-only* `plan_prioritize` behavior if someone "simplified" it; a test that fails the moment transitivity is dropped.
3. **Cycle:** A blocked-by B, B blocked-by A → no infinite loop, each counts the other exactly once.
4. **Self-reference:** a ticket's body says "Blocked by #<itself>" (a person's mistake / bad input) → ignored, doesn't inflate its own count or loop forever.
5. **Bad/malformed input:** missing `body`, `null` body, `labels: []`, no `createdAt` → no throw, ticket excluded or ranked last, never crashes the whole list.
6. **Huge input:** a few hundred synthetic tickets with a deep chain (A←B←C←...←Z) → completes without stack overflow (iterative BFS, not naive recursion) and returns correct count.
7. **Held/not-planned blockers excluded:** a ready-for-human ticket blocked only by a `hold`-labelled or `NOT_PLANNED`-closed ticket → doesn't count as actively blocking (mirrors `board.js`'s existing `ignored` semantics) — and a candidate that itself carries `hold` is excluded from the list entirely (already acknowledged by a person, don't re-nag).
8. **`pinned` excluded:** a `ready-for-human`-labelled ticket also carrying `pinned` → excluded (a person already took the wheel).
9. **Closed tickets never counted or listed:** a ticket blocked-by a since-closed ticket number doesn't appear as an active blocker, and a closed ticket never appears as a candidate row even if it still carries a stale `needs-info` label.
10. **needs-info "missing" list, each gap case from `ticket_policy.py`'s own test matrix:** no "What to build"-ish heading → flagged; heading present but no `- [ ]` acceptance checklist → flagged; both present but no "How we'll try to break it" section (and not a `research`-labelled ticket, not a human-task-shaped title) → flagged; a `research`-labelled ticket missing the break-it section → **not** flagged (exempt, same as the Python version).
11. **needs-info that is actually a parked human-task:** title matches the human-task regex (e.g. "design session: …"), body has a `## Your task` section missing 2 of the 4 fields → `ask` reuses `parseHumanTask`'s exact missing list, not a duplicate/diverging implementation.
12. **ready-for-human "ask":** body has a complete `## Your task` section → `ask` is the `What I need from you` text, not a missing-list message.
13. **Tie-break order:** two candidates with equal `unblocks.count` → the one with the more urgent `priority:pN` label sorts first; equal priority (or both unlabelled) → older `createdAt` sorts first.
14. **Empty input:** `rankNeedsYou([])` → `[]`, no throw.
15. **No qualifying tickets:** every ticket is `ready-for-agent`/`done`/has no state label → `[]`.
16. **Repeated calls / stale cache (via `relations_service`):** `needsYou()` called twice before the TTL expires → underlying `getBoardData` (the stand-in for a GitHub call) is invoked exactly once, matching the existing `relations_service.test.js` cache-assertion pattern (`toHaveBeenCalledTimes(1)`) — proves "no extra GitHub calls" rather than just asserting it in prose.
17. **One repo's board data throwing:** mirrors the existing `relations_service` test ("one repo failing to load does not take the rest down") — a repo that throws in `getBoardData` must not blank the whole needs-you list, only drop that repo's candidates.
18. **Cross-repo numbering collision:** repo A has ticket #12 and repo B has an unrelated ticket #12 → each repo's blocks graph is scoped to its own repo, so A's #12 unblocking doesn't accidentally pick up B's #12 as a dependent.

Any later change to `needs_you.js`'s ranking order, the blocks-graph traversal, or `missingFor`'s section checks must change the expected output of at least one of these tests — that's the verify gate for this ticket.