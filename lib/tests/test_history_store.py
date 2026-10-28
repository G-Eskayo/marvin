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
    conn = hs.connect(tmp_path / ".agents" / "var" / "marvin.db")  # the store the CLI opens (#621)
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


# ── marvin.db (#621): one store per Mac, and the one-time move of the old history.db ──────────────────────────────
# Every test here builds its own temp HOME layout; DB_PATH/OLD_DB_PATH are pointed away from the real machine by the
# suite-wide fixture in conftest.py, and these tests pass explicit temp paths on top of that.

def _old_store(path: Path, n: int = 50, device: str = "mac-mini-1") -> Path:
    """An old-format history.db (schema as it shipped before #621: no ticket column, user_version 0)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE events(id INTEGER PRIMARY KEY, stream TEXT NOT NULL, device TEXT NOT NULL, ts REAL,
                            hash BLOB NOT NULL UNIQUE, data TEXT NOT NULL);
        CREATE INDEX events_stream_ts ON events(stream, ts);
        CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE cursors(device TEXT NOT NULL, path TEXT NOT NULL, inode INTEGER NOT NULL, offset INTEGER NOT NULL,
                             fingerprint BLOB NOT NULL, PRIMARY KEY(device, path));
    """)
    conn.execute("BEGIN")
    hs.load(conn, "gh-calls", device, [_line(i, ticket=f"o/r#{i % 7}") for i in range(n)])
    hs.load(conn, "gh-calls", device, ["{not json"])
    conn.execute("INSERT INTO cursors VALUES ('mac-mini-1', '~/.claude/logs/gh-calls.jsonl', 1, 10, x'00')")
    conn.execute("INSERT INTO meta VALUES ('verified:laptop', '1.0')")
    conn.execute("COMMIT")
    conn.close()
    return path


@pytest.fixture
def layout(tmp_path):
    home = tmp_path / "home"
    return {"src": home / ".claude" / "history.db", "dst": home / ".agents" / "var" / "marvin.db"}


def _file_rows(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT id, stream, device, ts, hash, data FROM events ORDER BY id").fetchall()
    finally:
        conn.close()


def test_the_default_store_is_marvin_db_under_agents_var_and_the_old_one_is_history_db(tmp_path):
    import subprocess
    lib = Path(hs.__file__).resolve().parent
    code = f"import sys; sys.path.insert(0, {str(lib)!r}); import history_store as hs; print(hs.DB_PATH); print(hs.OLD_DB_PATH)"
    out = subprocess.run([sys.executable, "-c", code], env={**os.environ, "HOME": str(tmp_path)},
                         capture_output=True, text=True, timeout=30).stdout.split()
    assert out == [str(tmp_path / ".agents" / "var" / "marvin.db"), str(tmp_path / ".claude" / "history.db")]


def test_the_suite_never_points_the_store_at_the_real_machine():
    real = Path(os.path.expanduser("~"))
    assert real not in hs.DB_PATH.parents and real not in hs.OLD_DB_PATH.parents


def test_migration_copies_every_row_cursor_and_meta_and_keeps_ids(layout):
    _old_store(layout["src"], 120)
    out = hs.migrate(layout["dst"], layout["src"])
    assert out["status"] == "migrated" and out["rows"] == 121
    assert _file_rows(layout["dst"]) == _file_rows(layout["src"])
    conn = hs.connect(layout["dst"])
    assert conn.execute("SELECT offset FROM cursors").fetchone() == (10,)
    assert conn.execute("SELECT value FROM meta WHERE key = 'verified:laptop'").fetchone() == ("1.0",)
    marker = json.loads(conn.execute("SELECT value FROM meta WHERE key = 'migrated_from'").fetchone()[0])
    assert marker["rows"] == 121 and len(marker["digest"]) == 64


def test_the_old_history_db_is_left_in_place_unchanged(layout):
    _old_store(layout["src"], 30)
    before = _file_rows(layout["src"])
    hs.migrate(layout["dst"], layout["src"])
    assert layout["src"].exists() and _file_rows(layout["src"]) == before


def test_rerunning_the_migration_does_nothing(layout):
    _old_store(layout["src"], 10)
    hs.migrate(layout["dst"], layout["src"])
    conn = hs.connect(layout["dst"])
    hs.load(conn, "gh-calls", "d", [_line(999)])  # new work in the new store must survive a rerun
    conn.close()
    assert hs.migrate(layout["dst"], layout["src"])["status"] == "done"
    assert len(_file_rows(layout["dst"])) == 12


def test_a_missing_history_db_gives_a_fresh_empty_store(layout):
    out = hs.migrate(layout["dst"], layout["src"])
    assert out["status"] == "fresh" and _file_rows(layout["dst"]) == []
    assert not layout["src"].exists()
    assert hs.migrate(layout["dst"], layout["src"])["status"] == "done"


@pytest.mark.parametrize("content", [b"", b"this is not a database at all" * 100, b"SQLite format 3\0" + b"\xff" * 4000])
def test_a_corrupt_history_db_fails_loudly_and_creates_nothing(layout, content):
    layout["src"].parent.mkdir(parents=True)
    layout["src"].write_bytes(content)
    if content == b"":  # an empty file is a valid empty database: nothing to copy, still a clean store
        assert hs.migrate(layout["dst"], layout["src"])["rows"] == 0
        return
    with pytest.raises(hs.MigrationError):
        hs.migrate(layout["dst"], layout["src"])
    assert not layout["dst"].exists()
    assert not list(layout["dst"].parent.glob("marvin.db.migrating*"))
    assert layout["src"].read_bytes() == content


def test_a_corrupt_history_db_makes_the_default_connect_fail_loudly(layout, monkeypatch):
    layout["src"].parent.mkdir(parents=True)
    layout["src"].write_bytes(b"garbage" * 1000)
    monkeypatch.setattr(hs, "DB_PATH", layout["dst"])
    monkeypatch.setattr(hs, "OLD_DB_PATH", layout["src"])
    with pytest.raises(hs.MigrationError, match="history.db"):
        hs.connect()


def test_the_default_connect_migrates_once_then_opens_the_new_store(layout, monkeypatch):
    _old_store(layout["src"], 5)
    monkeypatch.setattr(hs, "DB_PATH", layout["dst"])
    monkeypatch.setattr(hs, "OLD_DB_PATH", layout["src"])
    conn = hs.connect()
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 6
    hs.load(conn, "gh-calls", "d", [_line(500)])
    conn.close()
    conn = hs.connect()
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 7
    conn.close()


def test_a_half_written_destination_left_by_a_crash_is_discarded_and_redone(layout):
    _old_store(layout["src"], 40)
    layout["dst"].parent.mkdir(parents=True)
    tmp = layout["dst"].with_name("marvin.db.migrating")
    tmp.write_bytes(b"SQLite format 3\0" + b"\0" * 100)  # torn: header only
    tmp.with_name(tmp.name + "-journal").write_bytes(b"junk")
    assert hs.migrate(layout["dst"], layout["src"])["status"] == "migrated"
    assert _file_rows(layout["dst"]) == _file_rows(layout["src"])
    assert not tmp.exists() and not tmp.with_name(tmp.name + "-journal").exists()


def test_a_process_killed_mid_copy_leaves_no_store_and_the_next_run_completes(layout):
    import subprocess
    _old_store(layout["src"], 3000)
    lib = Path(hs.__file__).resolve().parent
    code = (f"import sys, os; sys.path.insert(0, {str(lib)!r}); import history_store as hs\n"
            f"hs.migrate(hs.Path({str(layout['dst'])!r}), hs.Path({str(layout['src'])!r}), pages=1,\n"
            f"           progress=lambda status, remaining, total: os._exit(9) if remaining < total // 2 else None)\n")
    assert subprocess.run([sys.executable, "-c", code], timeout=60).returncode == 9
    assert not layout["dst"].exists()
    assert hs.migrate(layout["dst"], layout["src"])["status"] == "migrated"
    assert _file_rows(layout["dst"]) == _file_rows(layout["src"])


def test_a_destination_that_exists_but_is_not_a_database_is_never_overwritten(layout):
    _old_store(layout["src"], 5)
    layout["dst"].parent.mkdir(parents=True)
    layout["dst"].write_bytes(b"not sqlite" * 50)
    with pytest.raises(hs.MigrationError):
        hs.migrate(layout["dst"], layout["src"])
    assert layout["dst"].read_bytes() == b"not sqlite" * 50


def test_a_store_made_without_the_migration_is_never_merged_or_overwritten(layout):
    """marvin.db opened by an explicit path (no marker) while history.db still exists: refuse rather than guess."""
    _old_store(layout["src"], 5)
    hs.connect(layout["dst"]).close()
    with pytest.raises(hs.MigrationError, match="marker"):
        hs.migrate(layout["dst"], layout["src"])
    assert len(_file_rows(layout["src"])) == 6


def test_disk_full_during_the_copy_leaves_no_store_and_the_old_file_intact(layout, monkeypatch):
    _old_store(layout["src"], 500)
    before = _file_rows(layout["src"])
    real_open = hs._open_target

    def full_disk(path):
        conn = real_open(path)
        conn.execute("PRAGMA max_page_count=3")  # SQLite's own SQLITE_FULL, through the real copy path
        return conn
    monkeypatch.setattr(hs, "_open_target", full_disk)
    with pytest.raises(hs.MigrationError, match="full"):
        hs.migrate(layout["dst"], layout["src"])
    assert not layout["dst"].exists()
    assert not list(layout["dst"].parent.glob("marvin.db.migrating*"))
    assert _file_rows(layout["src"]) == before
    monkeypatch.setattr(hs, "_open_target", real_open)
    assert hs.migrate(layout["dst"], layout["src"])["status"] == "migrated"


def test_a_copy_that_does_not_match_the_source_is_rejected(layout, monkeypatch):
    _old_store(layout["src"], 20)
    real = hs._fingerprint
    calls = []

    def tampered(conn):
        fp = real(conn)
        calls.append(fp)
        if len(calls) == 2:  # the copy's fingerprint: pretend a row went missing in transit
            fp = {**fp, "events": (fp["events"][0] - 1, fp["events"][1])}
        return fp
    monkeypatch.setattr(hs, "_fingerprint", tampered)
    with pytest.raises(hs.MigrationError, match="verify"):
        hs.migrate(layout["dst"], layout["src"])
    assert not layout["dst"].exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_an_unwritable_store_folder_fails_clearly_and_touches_nothing(layout):
    _old_store(layout["src"], 5)
    layout["dst"].parent.mkdir(parents=True)
    layout["dst"].parent.chmod(0o500)
    try:
        with pytest.raises((PermissionError, hs.MigrationError)):
            hs.migrate(layout["dst"], layout["src"])
        assert not layout["dst"].exists()
    finally:
        layout["dst"].parent.chmod(0o700)
    assert len(_file_rows(layout["src"])) == 6
    assert hs.migrate(layout["dst"], layout["src"])["status"] == "migrated"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_an_unreadable_history_db_fails_loudly_and_works_once_fixed(layout):
    _old_store(layout["src"], 5)
    layout["src"].chmod(0o000)
    try:
        with pytest.raises(hs.MigrationError):
            hs.migrate(layout["dst"], layout["src"])
        assert not layout["dst"].exists()
    finally:
        layout["src"].chmod(0o600)
    assert hs.migrate(layout["dst"], layout["src"])["rows"] == 6


def test_two_concurrent_migrations_one_copies_and_the_other_does_nothing(layout):
    """The old race (check-before-lock): every check now happens under the lock, so no caller can see a half state."""
    _old_store(layout["src"], 2000)
    n = 8
    barrier = threading.Barrier(n)
    results, errors = [], []

    def go():
        barrier.wait()
        try:
            results.append(hs.migrate(layout["dst"], layout["src"])["status"])
        except Exception as exc:  # noqa: BLE001 - the test is that there are none
            errors.append(exc)
    threads = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert sorted(results) == ["done"] * (n - 1) + ["migrated"]
    assert _file_rows(layout["dst"]) == _file_rows(layout["src"])


def test_concurrent_migrations_from_separate_processes_serialize(layout):
    import subprocess
    _old_store(layout["src"], 2000)
    lib = Path(hs.__file__).resolve().parent
    code = (f"import sys; sys.path.insert(0, {str(lib)!r}); import history_store as hs\n"
            f"print(hs.migrate(hs.Path({str(layout['dst'])!r}), hs.Path({str(layout['src'])!r}))['status'])\n")
    procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
             for _ in range(4)]
    outs = [p.communicate(timeout=60) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1] for o in outs]
    assert sorted(o[0].decode().strip() for o in outs) == ["done"] * 3 + ["migrated"]


def test_a_writer_committing_after_the_snapshot_still_leaves_a_verified_copy(layout):
    """Real overlap, synchronised with events, not a sleep: the old loader commits new rows and moves its cursor
    after the copy's snapshot is taken and while the copy runs. The copy is the snapshot (verified by count and hash),
    and the rows written after it are not lost: the cursor in the copy is the snapshot's, so the next load reads them."""
    _old_store(layout["src"], 0)
    outbox = layout["src"].parent / "logs" / "gh-calls.jsonl"
    outbox.parent.mkdir(parents=True)
    _append(outbox, *[_line(i) for i in range(400)])
    old = sqlite3.connect(layout["src"], isolation_level=None, timeout=30)
    old.execute("DELETE FROM cursors")
    hs.load_source(old, "gh-calls", "mac-mini-1", str(outbox), lambda b: hs.read_local(outbox, b))
    snap_rows = old.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    snapshot_taken, writer_done = threading.Event(), threading.Event()
    steps_seen_after_write = []

    def writer():
        snapshot_taken.wait(10)
        _append(outbox, *[_line(i) for i in range(400, 450)])
        w = sqlite3.connect(layout["src"], isolation_level=None, timeout=30)
        hs.load_source(w, "gh-calls", "mac-mini-1", str(outbox), lambda b: hs.read_local(outbox, b))
        w.close()
        writer_done.set()

    def progress(status, remaining, total):
        if writer_done.is_set():
            steps_seen_after_write.append(remaining)

    t = threading.Thread(target=writer)
    t.start()

    def on_snapshot():
        snapshot_taken.set()
        assert writer_done.wait(10), "the writer must commit while the copy holds its snapshot"
    out = hs.migrate(layout["dst"], layout["src"], pages=1, progress=progress, on_snapshot=on_snapshot)
    t.join()
    old.close()
    assert steps_seen_after_write, "the copy must still be running after the writer committed"
    assert out["rows"] == snap_rows
    assert len(_file_rows(layout["src"])) == snap_rows + 50  # the old file did take the write

    new = hs.connect(layout["dst"])
    hs.load_source(new, "gh-calls", "mac-mini-1", str(outbox), lambda b: hs.read_local(outbox, b))
    got = {r[0] for r in new.execute("SELECT data FROM events WHERE data != '{not json'")}
    assert got == {_line(i) for i in range(450)}
    new.close()


def test_a_writer_inserting_between_copy_steps_never_breaks_verification(layout):
    _old_store(layout["src"], 3000)
    w = sqlite3.connect(layout["src"], isolation_level=None, timeout=30)
    inserted = []

    def progress(status, remaining, total):
        if len(inserted) < 20:
            w.execute("INSERT INTO events(stream, device, ts, hash, data) VALUES ('s', 'd', 1, ?, 'x')",
                      (os.urandom(16),))
            inserted.append(remaining)
    out = hs.migrate(layout["dst"], layout["src"], pages=2, progress=progress)
    w.close()
    assert len(inserted) == 20
    assert out["rows"] == 3001 and len(_file_rows(layout["dst"])) == 3001


# ── the schema: created once, by version, never rewritten on connect (the old per-connect DDL) ─────────────────────

def test_reopening_the_store_never_rewrites_the_schema(tmp_path):
    p = tmp_path / "marvin.db"
    hs.connect(p).close()
    a = sqlite3.connect(p)
    cookie = a.execute("PRAGMA schema_version").fetchone()[0]
    for _ in range(5):
        hs.connect(p).close()
    assert a.execute("PRAGMA schema_version").fetchone()[0] == cookie
    assert a.execute("PRAGMA user_version").fetchone()[0] == hs.SCHEMA_VERSION
    a.close()


def test_many_connections_opening_an_old_store_at_once_upgrade_it_exactly_once(tmp_path):
    p = _old_store(tmp_path / "history.db", 100)
    n = 12
    barrier = threading.Barrier(n)
    errors = []

    def go():
        barrier.wait()
        try:
            c = hs.connect(p)
            c.execute("SELECT COUNT(*) FROM gh_calls").fetchone()
            c.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=go) for _ in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    c = sqlite3.connect(p)
    assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'view' AND name = 'gh_calls'").fetchone()[0] == 1
    assert c.execute("PRAGMA user_version").fetchone()[0] == hs.SCHEMA_VERSION


def test_a_prepared_statement_on_another_connection_survives_new_opens(tmp_path):
    p = tmp_path / "marvin.db"
    a = hs.connect(p)
    hs.load(a, "gh-calls", "d", [_line(i) for i in range(5)])
    cur = a.execute("SELECT data FROM events ORDER BY id")
    first = cur.fetchone()
    hs.connect(p).close()  # used to drop and recreate the view, invalidating this cursor's statement
    assert first and len(cur.fetchall()) == 4
    a.close()


def test_ticket_lookups_use_an_index_and_tolerate_malformed_lines(tmp_path):
    conn = hs.connect(tmp_path / "marvin.db")
    hs.load(conn, "launches", "d", [json.dumps({"t": 1, "ticket": "o/r#621"}), json.dumps({"t": 2, "ticket": None}),
                                    "{not json", json.dumps([1, 2]), json.dumps({"t": 3})])
    assert conn.execute("SELECT COUNT(*) FROM events WHERE ticket = ?", ("o/r#621",)).fetchone()[0] == 1
    plan = " ".join(r[3] for r in conn.execute("EXPLAIN QUERY PLAN SELECT id FROM events WHERE ticket = ?", ("x",)))
    assert "events_ticket" in plan
    conn.close()


def test_the_gh_calls_view_reads_the_fields_and_skips_malformed_lines(tmp_path):
    conn = hs.connect(tmp_path / "marvin.db")
    hs.load(conn, "gh-calls", "mac", [json.dumps({"t": 5, "caller": "c", "cmd": "pr list", "rc": 0, "ms": 9}), "{bad"])
    hs.load(conn, "gh-budget", "mac", [json.dumps({"t": 6})])
    assert conn.execute("SELECT device, ts, caller, cmd, rc, ms FROM gh_calls").fetchall() == [
        ("mac", 5.0, "c", "pr list", 0, 9)]
    conn.close()


def test_many_writers_on_a_fresh_store_at_once_lose_nothing(layout, monkeypatch):
    monkeypatch.setattr(hs, "DB_PATH", layout["dst"])
    monkeypatch.setattr(hs, "OLD_DB_PATH", layout["src"])
    _old_store(layout["src"], 10)
    n = 8
    barrier = threading.Barrier(n)
    errors = []

    def go(k):
        barrier.wait()
        try:
            c = hs.connect()
            c.execute("BEGIN IMMEDIATE")
            hs.load(c, "gh-calls", f"w{k}", [_line(i) for i in range(50)])
            c.execute("COMMIT")
            c.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=go, args=(k,)) for k in range(n)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []
    assert len(_file_rows(layout["dst"])) == 11 + n * 50
