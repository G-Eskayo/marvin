# Fixes for marvin#449 (G4 cost-per-merged-PR, ADR 0066)

## North-star fit

**Reuses before adding anything new** (verified by reading the actual code in this worktree, not the design doc's claims about it):

- `lib/history_store.py`'s generic machinery (`SCHEMA`, `connect()`, `load()`, `load_source()`/`load_sources()`, `DEFAULT_STREAMS` already containing `"launches"`, the `events_stream_ts`/`launches_ticket` indexes, the `runs` view, `migrate_from_old()`) is already in this worktree and structurally close — this plan **fixes** its remaining defects, it doesn't rewrite it.
- `lib/ticket_stages.py:41-57` (`stage_key()`/`parse_stage_key()`) is the existing, canonical owner/repo/number codec. `lib/run_ticket.py:35,251` (`REPO = "G-Eskayo/marvin"`, `ticket_ref = f"{repo}#{issue_number}"`) and `lib/sandbox_orchestration.py:111-115` (`_launch(..., ticket_ref, ...)` → `marvin_launcher.launch(..., ticket=ticket_ref, ...)`) and `lib/marvin_launcher.py:159` (`"ticket": ticket`, never `pr_url`) confirm the real join field is the **string** `"G-Eskayo/marvin#123"` / `"G-Eskayo/clarity-captions#7"`, reconstructable as `f"{repo}#{number}"` from `parse_stage_key()`'s own return value. `lib/fit_check.py:71` (`rec.get("ticket") == ticket_ref`) already relies on this exact string equality — `pr_cost.py` must match that pattern, not invent a new one.
- `dashboard/webhook-server/merge_history.js:60-67`'s already-live "done/passed/`merged: <url>`" convention is reused as-is (same regex, same stage/status check) for `merged_tickets()`, just reading Python's `ticket_stages.STAGES_DIR` instead of Node's copy.
- `lib/model_registry.py`'s existing naming convention (Ollama tags like `"qwen2.5:14b"`, never a `claude*` prefix) is reused to split paid vs. local cost — no new registry lookup, no new naming scheme.
- ADR 0065 (delete by replacement cost: history is irreplaceable) and ADR 0066 (history store) are already-recorded decisions this plan applies, not reopens.

**What's actually still broken, found by reading the code (not the prior design doc's description of it):** `lib/pr_cost.py` in this worktree still keys `merged_tickets()` by the bare int `ticket_num` (line 37-50) and groups `cost_per_merged_pr()` by `(ticket, model)` (line 66-77) — exactly the defects code review flagged. The prior design doc claimed these were fixed; they weren't. Separately, by reading `lib/history_store.py`'s `SCHEMA` (lines 73-81) I found a defect review didn't catch: `launches_ticket` is a **partial index** and `runs` is a **view**, both calling `json_extract(data, ...)` directly on every `launches`-stream row with no `json_valid(data)` guard. ADR 0066 guarantees "a line that isn't valid JSON is still stored" — but SQLite's `json_extract` raises on malformed JSON, so a single malformed `launches` line would make `INSERT` itself fail (building the partial index) and make every `cost_per_merged_pr()` query raise. This directly contradicts the ticket's own misuse requirement (malformed input must not break the loader) and must be fixed alongside the review's findings.

**Simplest sufficient approach:** no new table, no new module, no new concurrency primitive. Every fix is a change to an existing function's body or a one-line SQL guard, not new machinery.

**Tokens:** zero runtime model cost (SQLite only). Saves tokens going forward: cost-per-PR becomes one query instead of an agent re-reading `launches.jsonl` by hand.

**Phone-OS / capability:** gives MARVIN a real, queryable cost-per-merged-PR signal (feeds #81's cost-visibility gap) and finishes moving state off `~/.claude` onto `~/.agents/var` (MARVIN self-reliance). This is instrumentation MARVIN builds and reads itself — raises MARVIN's own self-knowledge, doesn't change what Gil does day to day.

## Decisions

None needed from Gil. `docs/plans/memory-search-progress-2026-10-22.md`'s Decisions section (read directly: `db-home`, `work-sharing`, `box-first`, `search-scope`) is already fully resolved for this slice (A1), and the two implementation-level choices below are one-line, trivially-reversible calls, not design forks:

- **Paid vs. local split:** `model is None or model.startswith("claude")` → paid; anything else (an Ollama tag) → local. Matches `model_registry.py`'s existing naming convention; every launch today is paid, so this is dormant but correct code, not a guess.
- **Malformed `launches` lines:** excluded from the `runs` view and the `launches_ticket` index via `AND json_valid(data)`, but still stored in `events` (ADR 0066's guarantee holds at the storage layer; only the typed view/index skip them until they're valid).

## Tests (written first)

**Ticket's own break-list** ("a half-written destination, a rerun, a source that changes mid-copy, a missing source") **plus misuse it didn't name:**

1. `test_migration_returns_false_when_old_path_does_not_exist` — missing source (exists, keep).
2. `test_migration_is_idempotent_when_new_path_exists` — a rerun (exists, keep).
3. `test_a_verify_failure_leaves_no_tmp_file_and_no_half_written_destination` — **new**: monkeypatch `digest` to force a mismatch; assert `RuntimeError`, `dst` doesn't exist, no `.{name}.*.tmp`/`-wal`/`-shm` survive, `src` is untouched.
4. `test_a_writer_appending_during_the_backup_still_ends_up_consistent` — **new**: a background thread inserts into `src` while `migrate_from_old()` runs (the ticket's "source that changes mid-copy"); assert it returns `True` and `dst`'s digest matches `src`'s up to `dst`'s own max id (race-free invariant, not a comparison against `src`'s ever-growing total).
5. `test_two_concurrent_migrations_serialize_to_one_successful_result` — **new**: two threads call `migrate_from_old()` at once under the lock; assert exactly one `True`, one `False`, `dst` matches `src`.
6. `test_a_garbage_old_file_fails_loudly_and_never_creates_the_new_database` — **new**: non-SQLite bytes at `src`; assert raise, `dst` never created.
7. `test_migration_raises_when_marker_exists_but_new_db_missing` — **new, the must-fix #3/ADR-0065 regression test**: migrate once, add a fresh row to `dst`, delete `dst`, call `migrate_from_old()` again; assert `RuntimeError` (citing the marker) and `dst` is **not** silently recreated from the stale `src` snapshot.
8. `test_migration_writes_marker_to_old_database` (exists, keep).
9. `test_migration_resolves_paths_from_module_globals_at_call_time` (exists, keep).
10. `test_isolation_fixture_points_db_path_away_from_the_real_machine` — **new**: `hs.DB_PATH`/`hs.OLD_DB_PATH` under the autouse fixture never equal the real default paths (locks in what every other test depends on; the fixture itself is already correct, confirmed by reading `conftest.py:265-271`, so no production change here).

**`runs` view / `launches_ticket` index — malformed-JSON safety (found independently, not in the review's list):**

11. `test_a_malformed_launches_line_does_not_break_loading_or_the_typed_view` — **new, the real defect**: `hs.load(conn, "launches", "d", ["{not json", valid_line])` must not raise (today it would, building the partial index); `SELECT * FROM runs` must not raise either; the malformed row is present in `events` (ADR 0066: nothing is dropped) but absent from `runs`.
12. `test_launches_ticket_index_actually_exists` — **rewrite of the must-fix #6 test** (`lib/tests/test_history_store.py:504`, currently computes `plan` and asserts nothing): assert via `SELECT name FROM sqlite_master WHERE type='index' AND name='launches_ticket'`, not an un-asserted `EXPLAIN QUERY PLAN`.
13. `test_launches_schema_includes_runs_view_with_all_fields` (exists, keep; update its fixture's `"ticket"` value to a string ref for consistency with real data).
14. `test_the_runs_view_upgrades_in_place_when_an_older_schema_already_exists` — **new**: pre-create a DB with a narrower hand-written `runs` view (simulating an older deployment), then call `connect()`; assert the new columns (`model`, `input_tokens`, …) are present — guards the `DROP VIEW IF EXISTS` + recreate fix.

**`pr_cost.py` (rewritten against the real join field):**

15. `test_merged_tickets_keys_by_the_real_ticket_ref_string` — **the must-fix #1/#2 regression test**: a stage file named via `ticket_stages.stage_key(None, 123)` with a `done`/`passed`/`merged: <url>` event; assert the result is keyed `"G-Eskayo/marvin#123"` (string), derived via `ticket_stages.parse_stage_key` (reused), not a hand-rolled parse or a bare int.
16. `test_merged_tickets_keys_another_projects_ticket_by_its_own_repo_not_marvins_numbering` — **the must-fix #2 collision regression test**: a `clarity-captions` stage file numbered `#7` and a `marvin` stage file also numbered `#7`; assert both appear as two distinct entries (`"G-Eskayo/clarity-captions#7"` and `"G-Eskayo/marvin#7"`), not one collapsed into the other.
17. `test_merged_tickets_ignores_non_merged_stages` (exists, keep).
18. `test_merged_tickets_handles_missing_directory` (exists, keep).
19. `test_merged_tickets_dedupes_duplicate_merge_events` (exists, keep, re-keyed to string).
20. `test_cost_per_merged_pr_joins_launches_by_the_real_ticket_field` — **the must-fix #3 regression test** (replaces `test_cost_per_merged_pr_aggregates_launches_by_ticket`): launches carrying `"ticket": "G-Eskayo/marvin#100"` (what `marvin_launcher.launch()` actually writes, no `pr_url` anywhere) are found and summed.
21. `test_cost_per_merged_pr_returns_one_row_per_ticket_with_paid_and_local_split_and_tokens_by_model` — **the must-fix #3 regression test**: mixed `model=None`/`"claude-haiku-4-5"` vs. `model="qwen2.5:14b"` launches on one ticket; assert exactly **one** row for that ticket (not one per model), `paid_cost + local_cost == cost_usd`, and `tokens_by_model` has both models' input/output totals.
22. `test_a_merged_ticket_with_no_launches_reports_zero_not_omitted` — **the must-fix #3 regression test**: a merged ticket with zero matching launch rows still appears, with `cost_usd == 0` and `rows == 0`.
23. `test_cost_per_merged_pr_ignores_unmapped_tickets` (exists, keep, re-keyed).
24. `test_cost_per_merged_pr_sorts_by_per_pr_cost_descending` — **the must-fix #3 regression test**: two merged tickets, one with cost split across two models that together exceed the other's single-model cost; assert the sort is by the ticket's **total**, not by any single model's row.
25. `test_cost_per_merged_pr_tolerates_a_malformed_launches_line` — a non-JSON line loaded into `launches` alongside valid merged-ticket rows (now safe per test 11); query still returns the valid rows.
26. `test_cost_per_merged_pr_handles_null_token_counts` (exists, keep).

**`github_usage.py` test correctness (must-fix #7):**

27. Rewrite `test_github_usage_cache_can_read_from_history_store_launches` (`lib/tests/test_github_usage.py:329`) → `test_update_cache_db_ignores_the_launches_stream`: read `update_cache_db`'s actual body (`lib/github_usage.py:213-234`) — it hardcodes `stream IN ('gh-calls', 'gh-budget')` and never touches `launches`. Drop the false docstring claim ("includes costs in the hourly summary") and the nonexistent `pr_url` fixture field; instead load a `launches` row using the **real** `ticket` field alongside `gh-calls`/`gh-budget` rows, and assert `update_cache_db`'s result is unaffected by the `launches` row's presence (gh-calls/gh-budget aggregation is unchanged whether or not a third stream exists in the same database) — this is the thing actually worth testing now that three streams share one DB.

No changes needed (confirmed by reading, not assumed): `lib/github_usage.py`'s `report()` (its `hs.DB_PATH.exists()` guard already prevents it from creating an empty DB before migration), `config/launchd/com.marvin.history-load.plist` (already correctly repointed to `~/.agents/var/history.db`), `lib/tests/conftest.py`'s `_isolate_history_store` fixture (already correct).

## Task list

1. `lib/history_store.py`, `migrate_from_old()`: add `_already_migrated(src)` (reads `src`'s `meta` table for the `migrated_to` key, tolerating a missing `meta` table); call it when `dst` is missing but `src` exists, and raise `RuntimeError` instead of proceeding — fixes must-fix #3/ADR 0065.
2. `lib/history_store.py`, same function: fix resource cleanup — `src_conn`/`dst_conn` closed in a `finally`, not left dangling on exception; remove `tmp`, `tmp-wal`, `tmp-shm` in `finally`; move the `migrated_to` marker write to **after** a successful `os.replace()` (not before), so a failed replace never leaves a marker pointing at a destination that doesn't exist.
3. `lib/history_store.py`, `SCHEMA`: guard `runs` (view) and `launches_ticket` (partial index) against malformed JSON with `AND json_valid(data)`; change `CREATE VIEW IF NOT EXISTS runs` to `DROP VIEW IF EXISTS runs` + `CREATE VIEW runs` so an older narrower view upgrades in place.
4. `lib/tests/test_history_store.py`: add tests 3-7, 10, 11, 12, 14.
5. `lib/pr_cost.py`, `merged_tickets()`: key by `f"{repo}#{number}"` from `ticket_stages.parse_stage_key(f.stem)`, not the bare `ticket_num`.
6. `lib/pr_cost.py`, `cost_per_merged_pr()`: pre-populate one entry per merged ticket (ts = merge timestamp) before querying launches, so a ticket with no launches still appears at zero; query `runs` grouped by `(ticket, model)`, fold each `(ticket, model)` row into its ticket's entry (`rows` and `cost_usd` accumulate; `paid_cost`/`local_cost` by the paid/local classifier; `tokens_by_model[model] = {"input":, "output":}`); sort the final per-ticket list by `cost_usd` descending. Drop the unused `history_store as hs` import.
7. `lib/tests/test_pr_cost.py`: rewrite every fixture's `"ticket"` field to the real string format; add tests 15-26.
8. `lib/tests/test_github_usage.py`: replace `test_github_usage_cache_can_read_from_history_store_launches` with `test_update_cache_db_ignores_the_launches_stream`.
9. Run the test suite and confirm green.
