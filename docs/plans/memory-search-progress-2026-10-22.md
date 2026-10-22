# One record, one search, real progress (design, 2026-10-22)

Status: **draft for Gil**. Nothing is built yet. It extends the storage plan (`storage-and-distribution-2026-10-06.md`, §G, ADR 0066).

## Problem

Three things went wrong on 2026-10-22:

- **A loop no one could see.** Ticket #81 was planned 13 times and cost $28 with nothing to show. Nothing flagged it.
- **A storm no one could see.** The GitHub call storm (about 150 calls a minute from the dashboard) was invisible until someone read the raw logs.
- **Search that couldn't find things.** Docs search didn't find a doc by its own name (#609).

All three come from the same cause. Every view re-reads its own log files and keeps its own little index. Nothing holds one record that every view can ask.

## Goals

1. **One record:** every event, from every machine, in one queryable store that the dashboard, Vitals, the brief and agents all read.
2. **One search:** one ranked search across docs, ADRs, tickets, PRs, comments, memories, handoffs, outbox files and PDF text.
3. **Progress you can see:** Activity answers four questions: are we moving, what is stuck, what does it cost, and how close is each project to its next milestone.
4. **ROI:** every part should make work cheaper or better (north star #1).

**Non-goals:** this doesn't replace GitHub as the record for tickets and PRs, and it doesn't build a new UI without mock-ups that Gil approves.

## What exists (reuse it)

| Piece | State |
|---|---|
| `lib/history_store.py` (SQLite, WAL, idempotent by content hash) | Live on the Mini, with a backup on the laptop. Only `gh-calls` and `gh-budget` are loaded (193k rows, 57 MB). |
| `com.marvin.history-load` (launchd), incremental loads | Live (G2, G3) |
| Docs search (`dashboard/electron/main/docs_search.js`) | Ranking fixed in PR #610. A follow-up adds one ranked list, fast-forwarding of clean clones, and PDF text. |
| Vitals v4 `build_data.py` | Re-reads every log on each build. It should read the store instead. |

## Design

### A. The record (finishes G6)
- Load every stream into the history store: `launches`, ticket stages, job events, `dashboard-timing`, health status, disk ledger, token usage and merges.
- Each stream is one loader. The schema is the same `events` table plus a few **typed views**: `runs`, `merges`, `gh_calls`, `health`.
- Indexes on (stream, ts) and (ticket), so a range query is O(log n + k).
- **Move it out of `~/.claude`.** The database becomes `~/.agents/var/history.db` (MARVIN self-reliance). The move is one migration, and it is verified by row count and hash.
- Raw `.jsonl` files can be trimmed only after a week of clean loads for that stream (G5 rule).

### B. One search (SQLite FTS5)
- A `search` FTS5 table with these columns: kind (doc, adr, ticket, pr, comment, memory, handoff, outbox, pdf), title, path or URL, body, and updated time.
- It ranks with BM25 and weights titles and paths above body text. That is the same rule as #610, done by the engine.
- **Feeding it:**
  - Local files get an incremental re-index when the file watcher says they changed.
  - GitHub items come from the dashboard's cached lists. That means no new GitHub calls.
  - PDFs are indexed once per content hash.
- **Who uses it:** Docs search, a global search box, and agents through a CLI (`marvin search "..."`), which is cheaper than an agent grepping.
- **Cost:** about 5–10% of the text size. Queries take milliseconds.

### C. A timeline of what happened
- The `events` view, in order: merges, runs (with cost and exit), decisions, failures, holds, syncs.
- Activity's progress views, the morning brief, handoffs and Vitals all read it, so there is one truth.

### D. An Activity progress strip (mock-up first, Gil approves)
- **One row per project:**
  - Moving: merged this week.
  - Stuck: looping, held or blocked.
  - Cost: tokens per merged PR, with paid and local split out.
  - Progress toward the next milestone (`due` field, ADR 0047).
- **Loop alarm:** a ticket planned 3 or more times in 24 hours shows as stuck, with its cost.
- **Chat helpers** appear as runs (the work in progress on the helper-in-Activity ticket).

### E. A cap on tests per machine (stops the throttling)
- A machine-wide limit (default 1 full suite at a time on the MacBook, 2 on the Mini) through a lock file. Every test run takes it first: the gate, agents and the pipeline.
- Heavy suites run on the Mini by default.
- **Evidence:** on 2026-10-22 the MacBook reached load 34–37 on 8 cores, with 3 helpers and the gate all running `-n auto`.

## Complexity
- **Loads:** O(new rows) per run.
- **Search index:** O(changed files) per update.
- **Queries:** O(log n + k).
- **Space:** the store is about 2× the raw logs before trimming and about 1× after. The search index is about 10% of the text.

## Rollout (vertical slices)
1. **E: the test cap.** It's small, and it stops the throttling now.
2. **A1: move the database and load `launches`.** That unlocks cost per PR.
3. **B1: FTS5 for docs and ADRs,** wired into Docs search behind the existing box.
4. **C and D: the timeline and the progress strip.** Mock-up first.
5. **A2 and B2:** the remaining streams and search kinds, one at a time.

## Decisions
<!-- marvin:decisions -->
### db-home: Where does the database live?
- [ ] `~/.agents/var/history.db` on each Mac, with the Mini as the record and the laptop holding a backup copy (as today, just moved)
- [ ] The Mini only. The laptop reads it over Tailscale.

### first: What goes first?
- [ ] The test cap (stops the throttling), then the database move and launches
- [ ] Search first
- [ ] The Activity progress strip first

### search-scope: What should one search cover? (pick any)
- [ ] Docs, ADRs, plans
- [ ] Tickets, PRs, comments
- [ ] Memories and handoffs
- [ ] Outbox deliverables and PDF text
- [ ] Chat transcripts

### notes: Anything to add? (text) (optional)
