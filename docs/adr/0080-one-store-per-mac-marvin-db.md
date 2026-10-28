# 0080 — One store per Mac: `~/.agents/var/marvin.db`, and history.db moves into it once

## Status

Proposed (2026-10-28, marvin#621). Amends ADR 0066 decision 2 (where the database lives). The decision itself was the
owner's, 2026-10-26: one store per Mac, not a separate history database beside a health database.

## Context

ADR 0066 put the history store at `~/.claude/history.db`. Since then two things changed:

- **Self-reliance (2026-10-21):** MARVIN's per-machine state lives under `~/.agents/var/` (gitignored, never synced
  through git), so MARVIN works with no `~/.claude` at all. Nothing new goes under `~/.claude`.
- **The Vitals plan** needs a per-Mac SQLite store for health, metrics and run costs, with the same `events` table.
  Two databases with the same table, the same loader shape and the same backup would be two of everything.

Three automated builds of the move (2026-10-23) failed review on concurrency: the "already migrated?" checks ran before
the lock, the views were dropped and recreated on every connect, and the test of a write during the copy didn't
really overlap.

## Decision

1. **One file per Mac:** `~/.agents/var/marvin.db`. It holds the history streams now, and health, run costs, GitHub
   calls and search as those land. ADR 0066's table, loader, cursors and backup are unchanged. The Mini stays the
   record and the laptop keeps its copy.
2. **The schema is versioned** with `PRAGMA user_version`. A connect whose version is current does one PRAGMA read and
   nothing else. An older file is upgraded once, inside one `BEGIN IMMEDIATE`, re-checked under the write lock. Views
   are `CREATE VIEW IF NOT EXISTS` in that upgrade, never dropped and recreated.
3. **`ticket` is a virtual generated column** (from the JSON line, NULL when the line isn't valid JSON) with a partial
   index, so (ticket) lookups are O(log n + k) with no bytes added per row, nothing to backfill and nothing extra to
   ship to the copy.
4. **The move runs once, on the first no-argument `connect()`, entirely under one flock** (`marvin.db.lock`):
   - every check (does the store exist, does it carry the `migrated_from` marker) is inside the lock;
   - the old file is copied from **one read snapshot** with SQLite's backup API, and the copy's row count and content
     hash (events, cursors, meta) must equal the snapshot's, and `quick_check` must pass;
   - the store is built as `marvin.db.migrating` and appears only by an atomic rename, with the marker already inside,
     so it's never half there; a crashed attempt's leftovers are removed by the next one;
   - a store without the marker beside a still-present old file is refused, never merged or overwritten.
5. **The old `history.db` is never deleted by this change.** It stays in place as a backup. Retiring it is a later,
   separate step.

## Consequences

- A writer still on the old file during the copy isn't blocked (WAL) and can't make the copy inconsistent. Rows it
  commits after the snapshot aren't in the copy, but the copy's cursors are the snapshot's, so the next load reads
  those lines from the outbox again (loading is idempotent). Nothing is lost.
- A corrupt or unreadable old file makes the store fail to open, loudly, until it's moved aside or fixed: the
  history-load job reports red rather than starting an empty store over the top of real history.
- Code that wants this Mac's store calls `history_store.connect()` with no path. An explicit path opens that file
  only (tests, other tools).

## Complexity

The move is O(rows) once (copy and hash). After that, opening the store is O(1): a flock, one key lookup and one
PRAGMA read. Range queries stay O(log n + k) on (stream, ts) and (ticket).
