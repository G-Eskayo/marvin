# ADR 0066 — History store: the files are the outbox, the database is the record

**Date:** 2026-10-14  
**Status:** Accepted 2026-10-15 (grilled with Gil 2026-10-14)  
**Related:** ADR 0065 (replacement cost), ADR 0021/0022 (code and data sync), north star #1, storage plan §9 F6, CONTEXT.md "Databases"

## Context

MARVIN keeps its history as about 20 JSON/JSONL files per Mac in `~/.claude/logs` (GitHub calls 21k lines, dashboard timing 26k, launches, pipeline failures, errors, ticket-agent actions, the disk ledger), plus bench metrics and telemetry. Every feature that needs history parses whole files, and reaching the other Mac's history means ssh. Gil wants several databases, each with one job. The first is the **history store**: one queryable record of what MARVIN did on both Macs, to make the dashboard faster and give MARVIN's tools real history to query.

It isn't a way to save space: the record files total about 10 MB per Mac, and a database with indexes can be bigger than the JSONL it holds. Under north star #1 (least resources per objective), the goal is fast access for the least machinery.

Two Macs rule out writing straight to one database: SQLite can't be written safely over the network, and the laptop is often away or offline. Every writer needs a local buffer anyway, and the JSONL file already is one.

## Decision

1. **Writers don't change.** Every job keeps appending to its JSONL file. The file is now the **outbox**.
2. **One database on the Mini is the record**: SQLite (`~/.claude/history.db`, WAL mode). It's built into Python, so there's no new dependency, and it answers queries over this volume in milliseconds. The Mini is already the merge authority for data sync. DuckDB was considered and not needed at MBs of data.
3. **One generic table, not a schema per stream:** `events(stream, device, ts, hash UNIQUE, data JSON)`, indexed on `(stream, ts)`. Per-stream shapes are SQLite JSON views. `hash` is the line's content hash, so loading is idempotent: running twice adds nothing.
4. **A loader** runs every few minutes on the Mini. It remembers a byte offset (and inode, for rotation) per outbox, so each run reads only the new lines: O(new lines × log n), never O(file). It reads the Mini's outboxes, and the laptop's over ssh whenever the laptop is reachable. The laptop catches up when it comes back.
5. **Backup = the laptop's read copy, shipped incrementally.** After each load, the rows added since the laptop's last confirmed row are sent and applied with the same idempotent insert: O(new rows) per cycle. A full copy (O(n)) every 5 minutes was the first draft and was rejected: it grows forever (2026-10-14 complexity review). The laptop's dashboard reads its local copy, which is fast, works offline, and is minutes stale at worst. A full verified copy runs only weekly, as the check.
6. **Trimming comes last, per stream.** A line is trimmed from its outbox only when (a) it's in the database, (b) the backup holding it is verified on the other Mac, and (c) every reader of that stream reads the database. Until a stream's readers have moved, its file is never trimmed. History is irreplaceable (ADR 0065): it's kept forever in the database. **Retention (Gil, 2026-10-15):** the two high-volume streams (`gh-calls`, `dashboard-timing`) keep every line for 30 days, then roll into hourly summaries kept forever; every other stream keeps every line forever.
7. **Order:** one stream end to end first (tracer bullet), then the rest. First stream: `gh-calls.jsonl`, the biggest, read by the GitHub usage chart (24h/7d/30d) and a health check.

## Consequences

- No writer is touched, and a broken loader loses nothing: the outbox just grows until it's fixed. The loader's last success is a Health check.
- After trimming, the database is the only long-term copy, so the backup in step 5 is required, not optional, and must be verified before any trim.
- The pattern store (CONTEXT.md) is a separate database with a separate job, designed later.

## Time and space complexity

n = rows stored, k = rows a query returns, h = hours covered.

| Operation | Today (files) | History store |
|---|---|---|
| Load new records | n/a (append to file) | O(new × log n): offset per outbox, B-tree insert, UNIQUE hash check |
| Range query (a stream over a time window) | O(N): parse the whole file on each request | O(log n + k): `(stream, ts)` index |
| Hourly chart over 30 days | O(N) (github_usage caches the new bytes) | O(log n + h) from the hourly summaries |
| Backup to the other Mac | n/a | O(new rows) per cycle; O(n) weekly verify |
| Space | O(1): files capped at 5 MB, history thrown away | O(n) if every line is kept; O(h × keys) with hourly summaries, bounded by time, not by activity |

## Storage cost (measured 2026-10-14, both Macs)

- Raw log growth: laptop ~1.2 MB/day, Mini ~2.8 MB/day. About 95% of it is two streams (every GitHub call, every dashboard timing sample). Today these files are capped and rotated at 5 MB, so older history is thrown away; total today is ~17 MB.
- SQLite with this schema is 1.71× the raw JSON (7.3 MB of logs → 12.5 MB database, index + hash included).
- **Keep every line forever:** ~6.8 MB/day → ~2.5 GB/year on the Mini, the same again as the laptop backup (~5 GB/year across both).
- **Keep raw for 30 days, then hourly summaries for the two big streams (chosen 2026-10-15):** ~200 MB steady raw window, plus hourly rows (measured 116 B/row; ~80k rows/yr per Mac) and the small streams in full → ~0.25 GB in year one and ~60 MB more each year after; about double that counting the backup.
- Caveats: rates come from 2.5–14 days of data and pipeline activity is bursty; the 1.71× is measured on the laptop's mix. The disk headroom forecast (ADR 0056) tracks the real numbers.

## Updates

**2026-10-23 (marvin#621):** Moved database from `~/.claude/history.db` to `~/.agents/var/history.db` (aligning with system ownership and storage plan). Added `migrate_from_old()` for idempotent migration via SQLite backup; `connect()` runs it transparently. Added `launches` stream and a `runs` view to query by ticket, with `cost_per_ticket()` for cost tracking per ticket, split by local/paid models.
