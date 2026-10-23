"""Tests for history_store.py (ADR 0066, marvin#449). Every test uses a temp database and temp files, never ~/.claude.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_history_store.py -v
"""
from __future__ import annotations
import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import history_store as hs  # noqa: E402


@pytest.fixture
def db(tmp_path):
    conn = hs.connect(tmp_path / "history.db")
    yield conn
    conn.close()


def _count(conn, stream=None):
    q = "SELECT COUNT(*) FROM events" + (" WHERE stream = ?" if stream else "")
    return conn.execute(q, (stream,) if stream else ()).fetchone()[0]


def _line(i, **extra):
    return json.dumps({"t": 1791498937.0 + i, "caller": "c", "rc": 0, "ms": i, **extra})


def _append(path: Path, *lines: str):
    with open(path, "a") as f:
        f.write("".join(l + "\n" for l in lines))


# ── load(): lines into the database ──────────────────────────────────────────

def test_loading_the_same_lines_twice_adds_nothing_the_second_time(db):
    lines = [_line(i) for i in range(5)]
    assert hs.load(db, "gh-calls", "mac-mini-1", lines)["added"] == 5
    assert hs.load(db, "gh-calls", "mac-mini-1", lines) == {"added": 0, "duplicate": 5, "malformed": 0}
    assert _count(db) == 5


def test_the_same_line_from_two_macs_is_two_records(db):
    hs.load(db, "gh-calls", "mac-mini-1", [_line(1)])
    hs.load(db, "gh-calls", "macbook-pro-1", [_line(1)])
    assert _count(db) == 2


def test_a_malformed_line_is_kept_not_dropped(db):
    """Once the outbox is trimmed the database is the only copy: a line it can't parse is still history."""
    out = hs.load(db, "gh-calls", "d", ["{not json", "", "   ", _line(1)])
    assert out == {"added": 2, "duplicate": 0, "malformed": 1}
    assert db.execute("SELECT data, ts FROM events WHERE data = '{not json'").fetchone() == ("{not json", None)


def test_epoch_and_iso_timestamps_both_index(db):
    hs.load(db, "s", "d", [json.dumps({"t": 1791498937.5}), json.dumps({"t": "2026-10-08T16:23:25.731Z"}),
                           json.dumps({"at": "2026-10-08T22:10:52.280510+00:00"}), json.dumps({"no": "time"})])
    ts = sorted(r[0] for r in db.execute("SELECT ts FROM events WHERE ts IS NOT NULL"))
    from datetime import datetime, timezone
    expected = datetime(2026, 10, 8, 16, 23, 25, 731000, tzinfo=timezone.utc).timestamp()
    assert len(ts) == 3 and ts[0] == pytest.approx(expected, abs=0.001)


def test_a_huge_line_is_stored_whole(db):
    big = json.dumps({"t": 1.0, "blob": "x" * 2_000_000})
    hs.load(db, "s", "d", [big])
    assert db.execute("SELECT length(data) FROM events").fetchone()[0] == len(big)


def test_time_window_queries_use_the_index(db):
    plan = " ".join(r[3] for r in db.execute(
        "EXPLAIN QUERY PLAN SELECT data FROM events WHERE stream = ? AND ts BETWEEN ? AND ?", ("s", 0, 1)))
    assert "events_stream_ts" in plan


def test_launches_ticket_queries_use_the_partial_index(db):
    """The partial index on launches+ticket is used when querying by ticket and filtering valid JSON."""
    plan = " ".join(r[3] for r in db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM runs WHERE ticket = ?", ("#1",)))
    assert "events_launches_ticket" in plan


# ── load_source(): an outbox file, read from where the last run stopped ─────

def _spy_reader(path: Path):
    calls = []
    def read(from_byte):
        calls.append(from_byte)
        return hs.read_local(path, from_byte)
    return read, calls


def test_each_run_reads_only_the_new_bytes(db, tmp_path):
    f = tmp_path / "gh-calls.jsonl"
    _append(f, *[_line(i) for i in range(1000)])
    read, calls = _spy_reader(f)
    hs.load_source(db, "gh-calls", "d", str(f), read)
    size_after_first = f.stat().st_size
    _append(f, _line(1000))
    hs.load_source(db, "gh-calls", "d", str(f), read)
    assert _count(db) == 1001
    assert calls[-1] >= size_after_first - hs.FINGERPRINT_BYTES  # O(new), not O(file)


def test_a_half_written_last_line_waits_for_its_newline(db, tmp_path):
    f = tmp_path / "o.jsonl"
    _append(f, _line(1))
    with open(f, "a") as fh:
        fh.write(_line(2)[:10])  # a writer mid-append
    read, _ = _spy_reader(f)
    hs.load_source(db, "s", "d", str(f), read)
    assert _count(db) == 1
    with open(f, "a") as fh:
        fh.write(_line(2)[10:] + "\n")
    hs.load_source(db, "s", "d", str(f), read)
    assert _count(db) == 2 and _count(db) == len(set(r[0] for r in db.execute("SELECT data FROM events")))


def test_in_place_rotation_that_keeps_the_newer_half_loses_and_duplicates_nothing(db, tmp_path):
    """bin/gh rewrites gh-calls.jsonl in place with its newer half once it passes 5 MB."""
    f = tmp_path / "gh-calls.jsonl"
    _append(f, *[_line(i) for i in range(100)])
    read, _ = _spy_reader(f)
    hs.load_source(db, "gh-calls", "d", str(f), read)
    lines = f.read_text().splitlines()
    f.write_text("\n".join(lines[50:]) + "\n")  # exactly what bin/gh does
    _append(f, *[_line(i) for i in range(100, 160)])  # and it keeps growing past the old offset
    hs.load_source(db, "gh-calls", "d", str(f), read)
    assert _count(db) == 160


def test_a_file_replaced_by_a_new_one_is_read_from_the_start(db, tmp_path):
    f = tmp_path / "o.jsonl"
    _append(f, *[_line(i) for i in range(10)])
    read, _ = _spy_reader(f)
    hs.load_source(db, "s", "d", str(f), read)
    f.unlink()
    _append(f, *[_line(i) for i in range(10, 13)])
    hs.load_source(db, "s", "d", str(f), read)
    assert _count(db) == 13


def test_a_missing_outbox_is_not_an_error_and_moves_nothing(db, tmp_path):
    out = hs.load_source(db, "s", "d", str(tmp_path / "nope.jsonl"), lambda b: hs.read_local(tmp_path / "nope.jsonl", b))
    assert out["skipped"] == "missing" and _count(db) == 0


def test_a_failed_insert_leaves_the_cursor_where_it_was(db, tmp_path, monkeypatch):
    """Rows and the cursor commit together: a crash mid-load means the next run redoes it, never skips it."""
    f = tmp_path / "o.jsonl"
    _append(f, *[_line(i) for i in range(5)])
    read, _ = _spy_reader(f)
    real = hs.load
    monkeypatch.setattr(hs, "load", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
    with pytest.raises(sqlite3.OperationalError):
        hs.load_source(db, "s", "d", str(f), read)
    monkeypatch.setattr(hs, "load", real)
    hs.load_source(db, "s", "d", str(f), read)
    assert _count(db) == 5


def test_two_loaders_at_once_neither_fails_nor_duplicates(tmp_path):
    f = tmp_path / "o.jsonl"
    _append(f, *[_line(i) for i in range(2000)])
    errors = []
    def run():
        try:
            conn = hs.connect(tmp_path / "h.db")
            hs.load_source(conn, "s", "d", str(f), lambda b: hs.read_local(f, b))
            conn.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=run) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    conn = hs.connect(tmp_path / "h.db")
    assert _count(conn) == 2000


# ── reading the other Mac's outbox over ssh ─────────────────────────────────

def test_the_ssh_reply_is_split_into_inode_size_and_exact_bytes():
    payload = b'{"a": 1}\n{"b": "caf\xc3\xa9"}\n'
    assert hs.parse_remote_reply(b"12345 678\n" + payload) == (12345, 678, payload)


def test_a_remote_file_that_does_not_exist_reads_as_missing():
    assert hs.parse_remote_reply(b"MISSING\n") is None


def test_an_unreachable_mac_is_skipped_and_the_others_still_load(db, tmp_path):
    local = tmp_path / "gh-calls.jsonl"
    _append(local, _line(1))
    def unreachable(from_byte):
        raise hs.Unreachable("ssh: connect to host marvin-laptop port 22: Operation timed out")
    out = hs.load_sources(db, "gh-calls", [("mac-mini-1", str(local), lambda b: hs.read_local(local, b)),
                                           ("macbook-pro-1", "~/.claude/logs/gh-calls.jsonl", unreachable)])
    assert _count(db) == 1
    assert out["macbook-pro-1"]["skipped"].startswith("unreachable")


def test_a_hostile_file_name_is_read_as_a_name_never_run_as_a_command(tmp_path):
    """The command goes to `ssh host <cmd>`: run it in a real shell with a temp HOME and check nothing executes."""
    import subprocess
    name = "gh calls; touch PWNED $(touch PWNED2) `touch PWNED3`.jsonl"
    logs = tmp_path / ".claude" / "logs"
    logs.mkdir(parents=True)
    (logs / name).write_bytes(b'{"a": 1}\n{"b": 2}\n')
    cmd = hs.remote_read_command(f"~/.claude/logs/{name}", 9)
    reply = subprocess.run(["bash", "-c", cmd], cwd=tmp_path, env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                           capture_output=True).stdout
    assert hs.parse_remote_reply(reply)[2] == b'{"b": 2}\n'
    assert not any((tmp_path / p).exists() for p in ("PWNED", "PWNED2", "PWNED3"))


def test_a_missing_remote_file_says_missing_through_the_real_command(tmp_path):
    import subprocess
    cmd = hs.remote_read_command("~/.claude/logs/gh-calls.jsonl", 0)
    reply = subprocess.run(["bash", "-c", cmd], env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, capture_output=True).stdout
    assert hs.parse_remote_reply(reply) is None


# ── the laptop's copy (G3, marvin#456): ship only new rows ──────────────────

@pytest.fixture
def pair(tmp_path):
    src, dst = hs.connect(tmp_path / "mini.db"), hs.connect(tmp_path / "laptop.db")
    yield src, dst
    src.close(); dst.close()


def _ship(src, dst, limit=hs.SHIP_LIMIT, sent=None):
    def apply(rows):
        rows = list(rows)
        if sent is not None:
            sent.append(len(rows))
        return hs.apply_rows(dst, rows)
    return hs.ship(src, lambda: hs.tip(dst), apply, limit=limit)


def _rows(conn):
    return conn.execute("SELECT id, stream, device, ts, hash, data FROM events ORDER BY id").fetchall()


def test_the_copy_ends_up_identical_ids_included(pair):
    src, dst = pair
    hs.load(src, "gh-calls", "mac-mini-1", [_line(i) for i in range(50)])
    out = _ship(src, dst)
    assert out == {"sent": 50, "applied": 50, "already": 0, "conflict": 0}
    assert _rows(dst) == _rows(src)


def test_a_second_ship_sends_only_what_is_new(pair):
    src, dst = pair
    hs.load(src, "s", "d", [_line(i) for i in range(1000)])
    _ship(src, dst)
    hs.load(src, "s", "d", [_line(1000), _line(1001)])
    sent = []
    _ship(src, dst, sent=sent)
    assert sent == [2]  # O(new rows), not O(n)
    assert _rows(dst) == _rows(src)


def test_nothing_new_sends_nothing(pair):
    src, dst = pair
    hs.load(src, "s", "d", [_line(1)])
    _ship(src, dst)
    sent = []
    assert _ship(src, dst, sent=sent)["sent"] == 0 and sent in ([], [0])


def test_a_long_absence_catches_up_in_bounded_batches(pair):
    src, dst = pair
    hs.load(src, "s", "d", [_line(i) for i in range(25)])
    assert _ship(src, dst, limit=10)["sent"] == 10
    _ship(src, dst, limit=10); _ship(src, dst, limit=10)
    assert _rows(dst) == _rows(src)


def test_the_same_batch_applied_twice_changes_nothing(pair):
    src, dst = pair
    hs.load(src, "s", "d", [_line(i) for i in range(5)])
    rows = hs.rows_after(src, 0, 100)
    hs.apply_rows(dst, rows)
    assert hs.apply_rows(dst, rows) == {"applied": 0, "already": 5, "conflict": 0}


def test_a_divergent_row_is_reported_never_silently_kept(pair):
    """Same id, different record: the copy no longer matches the Mini. Say so."""
    src, dst = pair
    hs.load(src, "s", "d", [_line(1)])
    hs.load(dst, "s", "laptop", [_line(99)])  # something wrote into the copy directly
    out = _ship(src, dst)
    assert out["conflict"] == 1


def test_data_with_newlines_and_quotes_survives_the_wire(pair):
    src, dst = pair
    nasty = json.dumps({"t": 1.0, "msg": 'line one\nline "two"\r\n  \\ \x00 end'})
    hs.load(src, "s", "d", [nasty, "{broken json \"quote"])
    wire = hs.encode_rows(hs.rows_after(src, 0, 10))
    hs.apply_rows(dst, hs.decode_rows(wire))
    assert _rows(dst) == _rows(src)


def test_a_batch_cut_off_mid_transfer_applies_what_arrived_whole(pair):
    src, dst = pair
    hs.load(src, "s", "d", [_line(i) for i in range(3)])
    wire = hs.encode_rows(hs.rows_after(src, 0, 10))
    out = hs.apply_rows(dst, hs.decode_rows(wire[: len(wire) - 5]))  # last line truncated by a dropped connection
    assert out["applied"] == 2
    _ship(src, dst)
    assert _rows(dst) == _rows(src)


def test_an_unreachable_laptop_is_skipped(pair):
    src, _ = pair
    hs.load(src, "s", "d", [_line(1)])
    def gone():
        raise hs.Unreachable("ssh: connect to host marvin-laptop: Operation timed out")
    assert hs.ship(src, gone, lambda rows: None)["skipped"].startswith("unreachable")


def test_the_digest_matches_when_identical_and_catches_a_changed_row(pair):
    src, dst = pair
    hs.load(src, "s", "d", [_line(i) for i in range(20)])
    _ship(src, dst)
    top = hs.max_id(dst)
    assert hs.digest(src, top) == hs.digest(dst, top)
    dst.execute("UPDATE events SET data = 'tampered' , hash = x'00' WHERE id = 7")
    assert hs.digest(src, top) != hs.digest(dst, top)


def test_only_the_databases_home_mac_loads_outboxes(monkeypatch):
    """Loading into the laptop's copy would hand out ids that clash with the Mini's."""
    import types
    monkeypatch.setitem(sys.modules, "machine_profile", types.SimpleNamespace(registry_id=lambda: "macbook-pro-1"))
    with pytest.raises(SystemExit) as exc:
        hs.require_home()
    assert "mac-mini-1" in str(exc.value)


# ── migration from old to new location ────────────────────────────────────────

def test_migration_copies_data_from_old_to_new_location(tmp_path):
    """migrate_from_old() uses SQLite backup to copy the old database to the new location."""
    old_db = tmp_path / "old_history.db"
    new_db = tmp_path / "new_history.db"

    # Create and populate the old database
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(i) for i in range(10)])
    old_conn.close()

    # Run migration
    result = hs.migrate_from_old(old_db, new_db)
    assert result == {"migrated": 10}

    # Verify the new database has the same data
    new_conn = hs.connect(new_db)
    assert _count(new_conn) == 10
    new_conn.close()


def test_migration_is_idempotent(tmp_path):
    """Calling migrate_from_old when the target already exists does nothing."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create the old database
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(5)])
    old_conn.close()

    # First migration
    result1 = hs.migrate_from_old(old_db, new_db)
    assert result1 == {"migrated": 5}
    first_content = new_db.read_bytes()

    # Modify the old database (add more rows)
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(5, 15)])
    old_conn.close()

    # Second migration (should be skipped)
    result2 = hs.migrate_from_old(old_db, new_db)
    assert result2 == {"skipped": "already-migrated"}
    second_content = new_db.read_bytes()

    # File content should not have changed
    assert first_content == second_content

    # Verify it still has only 5 rows
    new_conn = hs.connect(new_db)
    assert _count(new_conn) == 5
    new_conn.close()


def test_migration_skips_if_old_does_not_exist(tmp_path):
    """migrate_from_old() returns {'skipped': 'no-old-database'} if the old path does not exist."""
    old_db = tmp_path / "nonexistent.db"
    new_db = tmp_path / "new.db"

    result = hs.migrate_from_old(old_db, new_db)
    assert result == {"skipped": "no-old-database"}

    # New database should not be created
    assert not new_db.exists()


def test_migration_creates_parent_directories(tmp_path):
    """migrate_from_old() creates the parent directory if it doesn't exist."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "nested" / "deep" / "new.db"

    # Create and populate the old database
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(1)])
    old_conn.close()

    # Run migration with nested path
    result = hs.migrate_from_old(old_db, new_db)
    assert result == {"migrated": 1}

    # Verify the new database exists with correct data
    assert new_db.exists()
    new_conn = hs.connect(new_db)
    assert _count(new_conn) == 1
    new_conn.close()


def test_migration_verifies_digest_matches(tmp_path):
    """migrate_from_old() verifies the backup by comparing digests."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create and populate the old database
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(50)])
    old_conn.close()

    # Run migration (should succeed)
    result = hs.migrate_from_old(old_db, new_db)
    assert result == {"migrated": 50}

    # Verify both have the same digest
    old_conn = hs.connect(old_db)
    new_conn = hs.connect(new_db)
    top = hs.max_id(old_conn)
    assert hs.digest(old_conn, top) == hs.digest(new_conn, top)
    old_conn.close()
    new_conn.close()


def test_migration_returns_actual_migrated_count(tmp_path):
    """Migration returns the actual count of rows in the backup."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create and populate the old database with initial data
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(15)])
    old_conn.close()

    # Run migration - it should report the actual row count of the backup
    result = hs.migrate_from_old(old_db, new_db)

    # Migration should return the migrated count (new_top)
    assert result == {"migrated": 15}

    # Verify the new database has the correct number of rows
    new_conn = hs.connect(new_db)
    assert _count(new_conn) == 15
    new_conn.close()


def test_migration_with_large_dataset(tmp_path):
    """Migration works with a larger dataset."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create and populate the old database with more data
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(100)])
    old_conn.close()

    # Run migration
    result = hs.migrate_from_old(old_db, new_db)
    assert result == {"migrated": 100}

    # Verify the new database has all rows
    new_conn = hs.connect(new_db)
    assert _count(new_conn) == 100
    # Verify digest matches
    old_conn = hs.connect(old_db)
    assert hs.digest(old_conn, 100) == hs.digest(new_conn, 100)
    old_conn.close()
    new_conn.close()


def test_migration_cleanup_on_atomic_replace_failure(tmp_path):
    """If atomic replace fails, temp file is cleaned up properly."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create old database
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(5)])
    old_conn.close()

    # Make parent dir read-only after backup but before replace
    # This will cause os.replace to fail
    new_db.parent.chmod(0o555)
    try:
        with pytest.raises(OSError):
            hs.migrate_from_old(old_db, new_db)
        # New database should not be created
        assert not new_db.exists()
    finally:
        new_db.parent.chmod(0o755)


def test_concurrent_migrations_race_safely(tmp_path):
    """Multiple migrate_from_old calls racing each other both succeed or one skips."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create old database
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(5)])
    old_conn.close()

    errors = []
    results = []

    def run_migration():
        try:
            result = hs.migrate_from_old(old_db, new_db)
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    # Run two migrations concurrently
    threads = [threading.Thread(target=run_migration) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # At most one should succeed with {"migrated": 5}, the other skipped or failed
    assert errors == []
    assert len(results) == 2
    # One should be migrated, one should be skipped
    success_count = sum(1 for r in results if "migrated" in r)
    skip_count = sum(1 for r in results if "skipped" in r)
    assert success_count + skip_count == 2

    # Verify the new database exists and has the correct data
    new_conn = hs.connect(new_db)
    assert _count(new_conn) == 5
    new_conn.close()


def test_migration_of_empty_source_database(tmp_path):
    """Migration of an empty (or no-events) database works correctly."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create empty old database (no events table or events are empty)
    old_conn = hs.connect(old_db)
    old_conn.close()

    # Run migration
    result = hs.migrate_from_old(old_db, new_db)
    assert result == {"migrated": 0}

    # Verify the new database exists but has no events
    new_conn = hs.connect(new_db)
    assert _count(new_conn) == 0
    new_conn.close()


def test_migration_with_single_row(tmp_path):
    """Migration works correctly with a single row."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create old database with just one row
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(1)])
    old_conn.close()

    # Run migration
    result = hs.migrate_from_old(old_db, new_db)
    assert result == {"migrated": 1}

    # Verify the new database has the one row
    new_conn = hs.connect(new_db)
    assert _count(new_conn) == 1
    new_conn.close()


def test_connect_calls_migration_automatically(tmp_path, monkeypatch):
    """connect() calls migrate_from_old() as the first step when using the default DB_PATH."""
    old_db = tmp_path / "old.db"
    new_db = tmp_path / "new.db"

    # Create and populate the old database
    old_conn = hs.connect(old_db)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(7)])
    old_conn.close()

    # Patch the paths
    monkeypatch.setattr(hs, "OLD_DB_PATH", old_db)
    monkeypatch.setattr(hs, "DB_PATH", new_db)

    # Call connect with no arguments (uses the default DB_PATH) — should migrate
    conn = hs.connect()

    # Verify the data was migrated
    assert _count(conn) == 7
    conn.close()

    # Second connect should find new_db already exists and not try to migrate again
    conn = hs.connect()
    assert _count(conn) == 7
    conn.close()


# ── cost_per_ticket() ────────────────────────────────────────────────────────

def test_cost_per_ticket_groups_runs_by_ticket(db):
    """cost_per_ticket() groups the runs view by ticket and aggregates costs."""
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1.0, "ticket": "#1", "model": "claude-opus-5-5", "cost_usd": 0.1, "input_tokens": 500, "output_tokens": 500}),
        json.dumps({"t": 2.0, "ticket": "#1", "model": "claude-opus-5-5", "cost_usd": 0.05, "input_tokens": 200, "output_tokens": 300}),
        json.dumps({"t": 3.0, "ticket": "#2", "model": "claude-opus-5-5", "cost_usd": 0.2, "input_tokens": 1000, "output_tokens": 1000}),
    ])
    result = hs.cost_per_ticket(db)
    assert result["#1"]["paid_cost_usd"] == pytest.approx(0.15)
    assert result["#1"]["paid_tokens"] == 1500
    assert result["#1"]["runs"] == 2
    assert result["#2"]["paid_cost_usd"] == pytest.approx(0.2)
    assert result["#2"]["paid_tokens"] == 2000
    assert result["#2"]["runs"] == 1


def test_cost_per_ticket_filters_by_ticket_list(db):
    """cost_per_ticket(tickets=[...]) returns only the specified tickets."""
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1.0, "ticket": "#1", "model": "claude-opus-5-5", "cost_usd": 0.1, "input_tokens": 500, "output_tokens": 500}),
        json.dumps({"t": 2.0, "ticket": "#2", "model": "claude-opus-5-5", "cost_usd": 0.2, "input_tokens": 1000, "output_tokens": 1000}),
        json.dumps({"t": 3.0, "ticket": "#3", "model": "claude-opus-5-5", "cost_usd": 0.3, "input_tokens": 1500, "output_tokens": 1500}),
    ])
    result = hs.cost_per_ticket(db, tickets=["#1", "#3"])
    assert set(result.keys()) == {"#1", "#3"}
    assert result["#1"]["paid_cost_usd"] == pytest.approx(0.1)
    assert result["#3"]["paid_cost_usd"] == pytest.approx(0.3)


def test_cost_per_ticket_classifies_local_models(db, monkeypatch):
    """cost_per_ticket() classifies ollama models as local and claude as paid."""
    import types
    mock_registry = types.SimpleNamespace()
    mock_registry.get = lambda model: (
        {"runtime": "ollama"} if model == "ollama:qwen2.5" else
        None if model == "claude-opus-5-5" else
        None
    )
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1.0, "ticket": "#1", "model": "ollama:qwen2.5", "cost_usd": 0.0, "input_tokens": 200, "output_tokens": 300}),
        json.dumps({"t": 2.0, "ticket": "#1", "model": "claude-opus-5-5", "cost_usd": 0.1, "input_tokens": 500, "output_tokens": 500}),
    ])
    result = hs.cost_per_ticket(db, registry=mock_registry)
    assert result["#1"]["local_tokens"] == 500
    assert result["#1"]["paid_tokens"] == 1000
    assert result["#1"]["local_cost_usd"] == pytest.approx(0.0)
    assert result["#1"]["paid_cost_usd"] == pytest.approx(0.1)


def test_cost_per_ticket_handles_null_cost_and_tokens(db):
    """cost_per_ticket() treats NULL cost and tokens as 0."""
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1.0, "ticket": "#1", "model": "claude-opus-5-5"}),  # no cost or tokens
        json.dumps({"t": 2.0, "ticket": "#1", "model": "claude-opus-5-5", "cost_usd": 0.1, "input_tokens": 500, "output_tokens": 500}),
    ])
    result = hs.cost_per_ticket(db)
    assert result["#1"]["paid_cost_usd"] == pytest.approx(0.1)
    assert result["#1"]["paid_tokens"] == 1000
    assert result["#1"]["runs"] == 2


def test_cost_per_ticket_returns_empty_dict_for_empty_tickets_list(db):
    """cost_per_ticket(tickets=[]) returns {} immediately."""
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1.0, "ticket": "#1", "model": "claude-opus-5-5", "cost_usd": 0.1, "input_tokens": 500, "output_tokens": 500}),
    ])
    result = hs.cost_per_ticket(db, tickets=[])
    assert result == {}


def test_the_copy_reports_its_tip_as_id_and_hash_through_the_real_cli(tmp_path):
    """--replica-max is what the Mini reads over ssh: an empty copy and a filled one both parse."""
    import subprocess
    env = {**os.environ, "HOME": str(tmp_path)}
    cli = [sys.executable, str(Path(hs.__file__)), "--replica-max"]
    assert subprocess.run(cli, env=env, capture_output=True, text=True).stdout.strip() == "0"
    conn = hs.connect(tmp_path / ".agents" / "var" / "history.db")
    hs.load(conn, "s", "d", [_line(1)])
    conn.close()
    top, h = subprocess.run(cli, env=env, capture_output=True, text=True).stdout.split()
    assert top == "1" and len(bytes.fromhex(h)) == 16


def test_opening_a_new_database_waits_for_a_writer_instead_of_failing(tmp_path):
    """Switching a fresh file to WAL needs an exclusive lock, and SQLite refuses that at once ("database is locked")
    without honouring the busy timeout: 13 of 60 four-thread opens failed (2026-10-15, found by the merge gate)."""
    import time
    path = tmp_path / "h.db"
    reader = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    reader.execute("CREATE TABLE x(a)")
    reader.execute("BEGIN IMMEDIATE")  # a writer mid-transaction, as when another loader is creating the tables
    reader.execute("INSERT INTO x VALUES (1)")
    threading.Timer(0.3, lambda: reader.execute("COMMIT")).start()
    started = time.time()
    conn = hs.connect(path)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert time.time() - started >= 0.25  # it waited for the reader rather than failing
    conn.close()
    reader.close()


def test_the_remote_read_command_works_with_gnu_stat_as_well_as_bsd():
    # The Macs read mac-mini-2012's logs over ssh; Linux's stat -f means "filesystem", not BSD's format flag.
    cmd = hs.remote_read_command("~/.claude/logs/x.jsonl", 0)
    assert "stat -c '%i %s'" in cmd and "stat -f '%i %z'" in cmd
