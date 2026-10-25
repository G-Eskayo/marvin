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


def test_the_copy_reports_its_tip_as_id_and_hash_through_the_real_cli(tmp_path):
    """--replica-max is what the Mini reads over ssh: an empty copy and a filled one both parse."""
    import subprocess
    env = {**os.environ, "HOME": str(tmp_path)}
    cli = [sys.executable, str(Path(hs.__file__)), "--replica-max"]
    assert subprocess.run(cli, env=env, capture_output=True, text=True).stdout.strip() == "0"
    # The new DB_PATH is ~/.agents/var/history.db; create it there
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


# ── migration from old path (marvin#449) ─────────────────────────────────────

def test_migration_copies_the_old_database_atomically(tmp_path):
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    # Populate the old database
    old_conn = hs.connect(old)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(i) for i in range(50)])
    old_count = hs.max_id(old_conn)
    old_hash = hs.digest(old_conn, old_count)
    old_conn.close()

    # Migrate
    assert hs.migrate_from_old(old, new) is True
    assert new.exists()

    # Verify the copy is identical
    new_conn = hs.connect(new)
    assert hs.max_id(new_conn) == old_count
    assert hs.digest(new_conn, old_count) == old_hash
    assert _count(new_conn) == 50
    new_conn.close()


def test_migration_is_idempotent_when_new_path_exists(tmp_path):
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    old_conn = hs.connect(old)
    hs.load(old_conn, "s", "d", [_line(1)])
    old_conn.close()

    new_conn = hs.connect(new)
    hs.load(new_conn, "s", "d", [_line(2)])
    new_count_before = _count(new_conn)
    new_conn.close()

    # Migrate when new path already has data: should not clobber it
    assert hs.migrate_from_old(old, new) is False

    new_conn = hs.connect(new)
    assert _count(new_conn) == new_count_before  # unchanged
    new_conn.close()


def test_migration_returns_false_when_old_path_does_not_exist(tmp_path):
    old = tmp_path / "nonexistent.db"
    new = tmp_path / "new_history.db"

    assert hs.migrate_from_old(old, new) is False


def test_migration_writes_marker_to_old_database(tmp_path):
    """After a verified migration, a migrated_to marker is written to src's meta table."""
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    # Populate the old database
    old_conn = hs.connect(old)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(i) for i in range(10)])
    old_conn.close()

    # Migrate
    assert hs.migrate_from_old(old, new) is True

    # Verify marker was written to old database
    old_conn = sqlite3.connect(old)
    marker = old_conn.execute("SELECT value FROM meta WHERE key = 'migrated_to'").fetchone()
    assert marker is not None
    assert str(new) in marker[0]
    old_conn.close()


def test_a_verify_failure_leaves_no_tmp_file_and_no_half_written_destination(tmp_path, monkeypatch):
    """If verify fails during migration, tmp and dst are cleaned up and marker is not written."""
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    # Populate the old database
    old_conn = hs.connect(old)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(i) for i in range(10)])
    old_conn.close()

    # Monkeypatch digest to force a mismatch on the second call (which is the dst verify)
    original_digest = hs.digest
    call_count = [0]
    def fake_digest(conn, upto):
        call_count[0] += 1
        if call_count[0] == 2:  # The second call is for dst verification
            return b"fake_hash_mismatch"
        return original_digest(conn, upto)
    monkeypatch.setattr(hs, "digest", fake_digest)

    # Attempt migration; should fail
    with pytest.raises(RuntimeError, match="migration verify failed"):
        hs.migrate_from_old(old, new)

    # Verify dst doesn't exist and no tmp files remain
    assert not new.exists()
    for f in tmp_path.glob(f".{new.name}*"):
        assert False, f"Leftover temp file: {f}"


def test_a_writer_appending_during_the_backup_still_ends_up_consistent(tmp_path, monkeypatch):
    """A background thread inserts into src while migrate_from_old() runs; dst matches src up to dst's max id."""
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    # Populate the old database with initial data
    old_conn = hs.connect(old)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(i) for i in range(10)])
    old_conn.close()

    # Insert more data in a background thread during migration
    inserted = []
    original_migrate = hs.migrate_from_old
    def migrate_with_writer(src, dst):
        import time
        import threading
        def writer():
            time.sleep(0.1)  # Let migration start
            w_conn = hs.connect(src)
            hs.load(w_conn, "gh-calls", "mac-mini-1", [_line(i) for i in range(10, 15)])
            w_conn.close()
            inserted.append(True)
        t = threading.Thread(target=writer)
        t.start()
        try:
            return original_migrate(src, dst)
        finally:
            t.join()
    monkeypatch.setattr(hs, "migrate_from_old", migrate_with_writer)

    # Run migration with background writer
    result = hs.migrate_from_old(old, new)
    assert result is True
    assert inserted  # writer did insert

    # Verify dst matches src up to dst's own max id (race-free)
    new_conn = hs.connect(new)
    new_max = hs.max_id(new_conn)
    new_digest = hs.digest(new_conn, new_max)
    new_conn.close()

    old_conn = hs.connect(old)
    old_digest = hs.digest(old_conn, new_max)
    old_conn.close()

    assert new_digest == old_digest


def test_two_concurrent_migrations_serialize_to_one_successful_result(tmp_path):
    """Two threads calling migrate_from_old() at once; one returns True, one returns False."""
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    # Populate the old database
    old_conn = hs.connect(old)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(i) for i in range(10)])
    old_conn.close()

    results = []
    def migrate():
        try:
            results.append(("result", hs.migrate_from_old(old, new)))
        except Exception as exc:
            results.append(("error", exc))

    t1 = threading.Thread(target=migrate)
    t2 = threading.Thread(target=migrate)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(results) == 2
    assert new.exists()
    result_vals = [r[1] for r in results if r[0] == "result"]
    assert sorted(result_vals) == [False, True]


def test_a_garbage_old_file_fails_loudly_and_never_creates_the_new_database(tmp_path):
    """Non-SQLite bytes at src; should raise and never create dst."""
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    old.write_bytes(b"not a sqlite database\x00\x00")

    with pytest.raises(RuntimeError, match="migration failed"):
        hs.migrate_from_old(old, new)

    assert not new.exists()


def test_migration_raises_when_marker_exists_but_new_db_missing(tmp_path):
    """If src has migrated_to marker but dst doesn't exist, raises RuntimeError (ADR 0065)."""
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    # Populate and migrate once
    old_conn = hs.connect(old)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(i) for i in range(5)])
    old_conn.close()

    assert hs.migrate_from_old(old, new) is True
    assert new.exists()

    # Add a row to new to confirm it existed
    new_conn = hs.connect(new)
    hs.load(new_conn, "gh-calls", "mac-mini-1", [_line(100)])
    new_conn.close()

    # Delete new
    new.unlink()

    # Try to migrate again; should raise
    with pytest.raises(RuntimeError, match="migration marker found"):
        hs.migrate_from_old(old, new)

    # Verify dst was not recreated
    assert not new.exists()


def test_isolation_fixture_points_db_path_away_from_the_real_machine(db, tmp_path):
    """The isolation fixture ensures hs.DB_PATH and hs.OLD_DB_PATH are never the real defaults."""
    # This is a check on the fixture itself; just confirm they're not the real paths
    assert hs.DB_PATH != Path.home() / ".agents" / "var" / "history.db"
    assert hs.OLD_DB_PATH != Path.home() / ".claude" / "history.db"


def test_a_malformed_launches_line_does_not_break_loading_or_the_typed_view(db):
    """A malformed JSON launches line must not break INSERT or the runs view."""
    # Load both malformed and valid launches lines
    hs.load(db, "launches", "d", [
        "{not json",
        json.dumps({"t": 1791498937.0, "ticket": "G-Eskayo/marvin#123", "cost_usd": 0.01, "model": "claude-opus-5-5"}),
    ])

    # INSERT should succeed (no exception)
    assert _count(db, "launches") == 2

    # The runs view should not raise and should skip the malformed row
    rows = db.execute("SELECT * FROM runs").fetchall()
    assert len(rows) == 1  # Only the valid row
    assert rows[0][3] == "G-Eskayo/marvin#123"  # ticket field


def test_migration_resolves_paths_from_module_globals_at_call_time(tmp_path, monkeypatch):
    """migrate_from_old() should resolve src/dst from module globals, not bound defaults."""
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    # Populate the old database
    old_conn = hs.connect(old)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(1)])
    old_conn.close()

    # Monkeypatch module globals and call with no args
    monkeypatch.setattr(hs, "OLD_DB_PATH", old)
    monkeypatch.setattr(hs, "DB_PATH", new)

    # Should work with no arguments
    assert hs.migrate_from_old() is True
    assert new.exists()


def test_launches_stream_is_in_defaults():
    assert "launches" in hs.DEFAULT_STREAMS


def test_launches_schema_includes_runs_view_with_all_fields(db):
    # Create a launches event with all the new fields
    hs.load(db, "launches", "d", [
        json.dumps({
            "t": 1791498937.0, "ticket": "G-Eskayo/marvin#123", "cost_usd": 0.045,
            "model": "claude-opus-5-5", "input_tokens": 100, "output_tokens": 50,
            "cache_read_tokens": 10, "cache_write_tokens": 5, "kind": "agent", "exit_code": 0
        }),
    ])

    # Query the runs view
    rows = db.execute(
        "SELECT id, ts, data, ticket, cost_usd, model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, kind, exit_code FROM runs"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][3] == "G-Eskayo/marvin#123"  # ticket
    assert rows[0][4] == pytest.approx(0.045)  # cost_usd
    assert rows[0][5] == "claude-opus-5-5"  # model
    assert rows[0][6] == 100  # input_tokens
    assert rows[0][7] == 50  # output_tokens
    assert rows[0][8] == 10  # cache_read_tokens
    assert rows[0][9] == 5  # cache_write_tokens
    assert rows[0][10] == "agent"  # kind
    assert rows[0][11] == 0  # exit_code


def test_the_runs_view_upgrades_in_place_when_an_older_schema_already_exists(tmp_path):
    """When an older DB with a narrower runs view is opened, the view is upgraded in place."""
    db_path = tmp_path / "history.db"

    # Create a DB with an older narrow runs view
    old_conn = sqlite3.connect(db_path, isolation_level=None)
    old_conn.execute("CREATE TABLE events(id INTEGER PRIMARY KEY, stream TEXT, device TEXT, ts REAL, hash BLOB UNIQUE, data TEXT)")
    old_conn.execute("CREATE VIEW runs AS SELECT id, ts, data FROM events WHERE stream = 'launches'")
    old_conn.close()

    # Load a launches row with the new fields
    conn = hs.connect(db_path)
    hs.load(conn, "launches", "d", [json.dumps({
        "t": 1791498937.0, "ticket": "G-Eskayo/marvin#100", "cost_usd": 0.05,
        "model": "claude-opus-5-5", "input_tokens": 200, "output_tokens": 100
    })])

    # Query the view and check it has the new columns
    rows = conn.execute(
        "SELECT ticket, cost_usd, model, input_tokens, output_tokens FROM runs"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "G-Eskayo/marvin#100"
    assert rows[0][1] == pytest.approx(0.05)
    assert rows[0][2] == "claude-opus-5-5"
    conn.close()


def test_launches_ticket_index_actually_exists(db):
    """Verify the launches_ticket index exists via sqlite_master."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='launches_ticket'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "launches_ticket"


def test_connect_calls_migrate_from_old_automatically(tmp_path, monkeypatch):
    """connect() with no explicit path should call migrate_from_old() first."""
    old = tmp_path / "old_history.db"
    new = tmp_path / "new_history.db"

    # Populate the old database
    old_conn = hs.connect(old)
    hs.load(old_conn, "gh-calls", "mac-mini-1", [_line(1)])
    old_conn.close()

    # Monkeypatch module globals
    monkeypatch.setattr(hs, "OLD_DB_PATH", old)
    monkeypatch.setattr(hs, "DB_PATH", new)

    # connect() with no args should auto-migrate
    conn = hs.connect()
    assert new.exists()
    assert _count(conn) == 1
    conn.close()
