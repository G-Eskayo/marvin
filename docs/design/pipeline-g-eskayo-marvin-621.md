## North-star fit

**Reuses, before adding anything:**
- The append-only, immutable-row invariant already enforced by `apply_rows()` (lib/history_store.py:421-437, `INSERT OR IGNORE` + "same id, different hash ⇒ conflict, never overwrite") and by `load()`/`load_source()` (never `UPDATE`/`DELETE`). This is the fact that makes the fix correct: rows already written to `old_path` can never change underneath the migration, only new ones can be appended. The fix reuses this existing guarantee instead of inventing new locking/snapshot machinery.
- `history_store.max_id()` and `history_store.digest()` (lib/history_store.py:390-391, 461-466) stay reused exactly as already wired into `migrate_from_old()` — no new function needed, just a different `upto_id` argument to `digest()`.
- `model_registry.py`'s `fcntl.flock` sidecar-lock pattern is already reused for `migrate_from_old()`'s check-then-act section (lines 124-126) — untouched, still correct.
- `conftest.py`'s `_isolate_history_store` fixture (lines 263-271) is already wired and correct — no change.

**Current state, verified by reading the file (not assumed):** every fix from the *previous* review round — `json_valid()` guards on the index/view, the read-only `mode=ro` open, the real `input_tokens`/`output_tokens`/`cache_read_tokens`/`cache_write_tokens` columns (matching `marvin_launcher.launch()` at lib/marvin_launcher.py:159-164 exactly), `cost_per_ticket()`'s `registry=` param/`ticket IS NOT NULL`/empty-list-returns-`{}`, and ADR 0066's `marvin#621` reference — are **already implemented correctly** in the working tree (confirmed via `git diff main` and a clean 44/44 local run of `test_history_store.py`). None of that is re-touched by this plan. Only the one must-fix defect from this review round remains.

**The must-fix, and why the simpler of the review's two offered fixes is right:** the review names two options — (a) hold `old_conn`'s read transaction open across `backup()` so SQLite's WAL snapshot isolation freezes the copy, or (b) relax the comparison to `new_top >= old_top and digest(new_conn, old_top) == old_dig`. Option (a) depends on an unverified assumption: that `sqlite3.Connection.backup()` actually honors an already-open deferred read transaction's pinned snapshot rather than starting its own — behavior that isn't something this codebase can lean on without a very fragile test. Option (b) needs no such assumption: because rows are immutable once written (see invariant above), *any* backup taken after the snapshot was read is guaranteed to contain at least those same `old_top` rows unchanged, plus possibly more. Checking the prefix instead of exact equality is strictly correct and simpler — same line count changed, no transaction-lifecycle restructuring. This is the fix this plan implements.

**Where this saves tokens:** the change is a ~6-line edit to one function plus one new test — far cheaper than the review's fuller alternative, and it closes the exact gap the review measured (a race that currently makes every `connect()` call flaky under write pressure).

**Phone-OS / self-reliance direction:** unchanged — already correctly moved to `~/.agents/var/history.db`.

**User capability:** this is reliability-of-the-record infrastructure Gil never looks at directly. Its value is indirect: a migration that intermittently raises `RuntimeError` on the Mini would silently block every `history_store` read/write that goes through `connect()` until the race broke the other way — exactly the kind of invisible failure north star #2 (reliability, nothing breaks silently) rules against. Fixing it leaves the system more trustworthy, not the user more passive.

**No Decisions section:** the fix is dictated by the review and the codebase's own existing invariant — nothing here needs Gil to choose between options.

## What's already correct and untouched

`lib/history_store.py`: the flock-serialized check-then-act, the read-only `mode=ro` open of `old_path`, the `json_valid()`-guarded index/view, the real token-field names in `runs`, `cost_per_ticket()`'s registry/ticket-filter/empty-list handling, `DEFAULT_STREAMS` including `"launches"`, and `connect()`'s migrate-before-open ordering. `docs/adr/0066-history-store-files-are-the-outbox.md`'s "Updates" note already correctly cites `marvin#621`. `lib/tests/conftest.py`'s `_isolate_history_store` fixture. All verified by reading the current file and `git diff main`, not assumed. None of this is touched.

## The fix

In `migrate_from_old()` (lib/history_store.py:173-190), replace:

```python
new_has_events = new_conn.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
if new_has_events:
    new_top = new_conn.execute("SELECT MAX(id) FROM events").fetchone()[0] or 0
    new_dig = digest(new_conn, new_top) if new_top > 0 else ""
else:
    new_top, new_dig = 0, ""

if old_top != new_top or old_dig != new_dig:
    raise RuntimeError(...)
...
return {"migrated": old_top}
```

with a check against the **prefix** of the copy, not the whole thing:

```python
new_has_events = new_conn.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
new_top = (new_conn.execute("SELECT MAX(id) FROM events").fetchone()[0] or 0) if new_has_events else 0
new_dig = digest(new_conn, old_top) if old_top > 0 else ""

# A concurrent writer may append rows to old_path between the snapshot above and this backup()
# call; those rows are real and backup() legitimately copies them too (new_top may exceed
# old_top). Existing rows never change once written (apply_rows()/load() only INSERT OR IGNORE),
# so what must match exactly is the snapshot's own prefix, not the copy's current total.
if new_top < old_top or old_dig != new_dig:
    raise RuntimeError(f"backup verification failed: old {old_top}/{old_dig[:8]}, new {new_top}/{new_dig[:8]}")
...
return {"migrated": new_top}
```

No change to the transaction/rollback structure, the lock, or the read-only open — this is the entire diff. `digest(new_conn, new_top)` becomes `digest(new_conn, old_top)`, the comparison becomes `new_top < old_top` instead of `!=`, and the returned count reflects what was actually copied.

## Tests first

Mapped to the ticket's "Done when" break-it list (half-written destination, a rerun, a source that changes mid-copy, a missing source) plus misuse it didn't name:

1. **`test_a_source_that_changes_mid_copy_is_still_captured_consistently`** (new — the must-fix test). Load 5 rows into `old_path`, record `snapshot_dig = digest(old_conn, 5)`. Monkeypatch `sqlite3.Connection.backup` so that, just before calling the real `backup()`, a second connection appends 5 more rows (ids 6–10) to `old_path` and commits. Assert `migrate_from_old()` returns `{"migrated": 10}` (not a `RuntimeError`), and that the new database's `digest(new_conn, 5) == snapshot_dig`. Against the current code this raises `RuntimeError("backup verification failed...")` exactly as the review describes — this is the test that catches the bug.
2. **`test_a_stale_half_written_tmp_file_does_not_block_a_fresh_migration`** (new — ticket's named "half-written destination" case, currently untested). Drop a leftover `.history.db.<junk>.migrating` file in `new_path.parent` (simulating a crashed earlier attempt). A fresh `migrate_from_old()` call still succeeds and produces the correct row count — `tempfile.mkstemp`'s unique naming means the stale file is never read.
3. **`test_a_corrupt_old_database_fails_loudly_not_silently`** (new — malformed-input misuse). Write garbage bytes (no SQLite header) to `old_path`. `migrate_from_old()` raises `RuntimeError`; `new_path` is never created; no `.migrating` tmp file is left behind.
4. **`test_backup_failure_leaves_old_untouched_and_cleans_up_the_tmp_file`** (new — dependency-failure misuse). Monkeypatch `sqlite3.Connection.backup` to raise `sqlite3.OperationalError("disk I/O error")`. Assert the exception propagates, no `*.migrating` file remains in `new_path.parent`, and `old_path` is still fully readable with its original row count untouched.
5. **`test_two_concurrent_migrations_neither_corrupt_nor_duplicate`** (new — concurrency misuse; regression guard for the existing flock, same thread shape as `test_two_loaders_at_once_neither_fails_nor_duplicates` at line 168). 4 threads call `migrate_from_old(old_db, new_db)` at once; no exceptions, exactly one real migration happens, final row count matches the source.
6. **`test_an_empty_old_database_migrates_cleanly`** (new — empty-input boundary, currently untested). Zero-row `old_path` migrates to `{"migrated": 0}`; digest of zero rows matches trivially on both sides.
7. **`test_a_source_with_no_read_permission_fails_loudly`** (new — wrong-permissions misuse). `chmod(old_path, 0o000)`; `migrate_from_old()` raises `RuntimeError` via the existing `except sqlite3.OperationalError` wrapper (lib/history_store.py:137-138), rather than hanging or silently skipping. Restore permissions in a `finally` so cleanup isn't blocked.
8. **Keep unchanged** (already present, already passing, still valid under the new comparison since the happy path has `old_top == new_top`): `test_migration_copies_data_from_old_to_new_location`, `test_migration_is_idempotent` (rerun), `test_migration_skips_if_old_does_not_exist` (missing source), `test_migration_creates_parent_directories`, `test_migration_verifies_digest_matches`, `test_connect_calls_migration_automatically`.

**Full suite:** `~/.agents/venv/bin/python -m pytest lib/tests/test_history_store.py -v` first (confirm test 1 fails against the current code for the stated reason, then passes after the fix), then `lib/ -q` in full — 0 failed, no new outliers vs. the current 44-passed baseline.

## Task List

1. Edit `migrate_from_old()` in `lib/history_store.py` (lines ~173-190): change `new_dig = digest(new_conn, new_top)` to `digest(new_conn, old_top)`, change the verification condition from `old_top != new_top or old_dig != new_dig` to `new_top < old_top or old_dig != new_dig`, and change `return {"migrated": old_top}` to `return {"migrated": new_top}`.
2. Add test 1 (`test_a_source_that_changes_mid_copy_is_still_captured_consistently`) to `lib/tests/test_history_store.py`; run it against the unmodified code first to confirm it fails with `RuntimeError("backup verification failed...")`, then confirm it passes after step 1.
3. Add tests 2–7 (stale tmp file, corrupt source, backup failure, concurrent migrations, empty source, no-read-permission) to `lib/tests/test_history_store.py`.
4. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_history_store.py -v` — confirm all pass, including the 6 pre-existing migration tests unchanged by step 1.
5. Run the full `lib/ -q` suite — confirm 0 failed, count only up by the new tests added here, no timing regression.