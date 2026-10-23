"""Tests for history_store.py (ADR 0066, marvin#449). Every test uses a temp database and temp files, never ~/.claude.
    ~/.agents/venv/bin/python -m pytest lib/tests/test_history_store.py -v
"""
from __future__ import annotations
import json
import os
import shutil
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
    env = {**os.environ, "HOME": str(tmp_path), "MARVIN_VAR_DIR": str(tmp_path / ".agents" / "var")}
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


# ── migration: old ~/.claude/history.db → new ~/.agents/var/history.db ────────

def test_migrate_once_is_a_noop_when_no_source_and_no_dest(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVIN_VAR_DIR", str(tmp_path / "var"))
    old = tmp_path / "old.db"
    new = tmp_path / "new.db"
    assert hs.migrate_once(old, new) is False
    assert not old.exists() and not new.exists()


def test_migrate_once_copies_and_retires_the_old_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVIN_VAR_DIR", str(tmp_path / "var"))
    old = tmp_path / "old.db"
    new = tmp_path / "new.db"

    old_conn = hs.connect(old)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(10)])
    old_conn.close()

    assert hs.migrate_once(old, new) is True
    assert new.exists() and _count(hs.connect(new)) == 10

    retired = [f for f in tmp_path.glob("old.migrated-*")]
    assert len(retired) == 1
    assert hs.connect(retired[0]).execute("SELECT COUNT(*) FROM events").fetchone()[0] == 10


def test_migrate_once_run_twice_is_a_clean_noop(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVIN_VAR_DIR", str(tmp_path / "var"))
    old = tmp_path / "old.db"
    new = tmp_path / "new.db"

    old_conn = hs.connect(old)
    hs.load(old_conn, "s", "d", [_line(1)])
    old_conn.close()

    assert hs.migrate_once(old, new) is True
    assert hs.migrate_once(old, new) is False
    assert _count(hs.connect(new)) == 1


def test_migrate_once_cleans_up_a_leftover_half_written_temp_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVIN_VAR_DIR", str(tmp_path / "var"))
    old = tmp_path / "old.db"
    new = tmp_path / "new.db"

    old_conn = hs.connect(old)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(5)])
    old_conn.close()

    (new.with_suffix(new.suffix + ".migrating")).write_text("garbage")
    assert hs.migrate_once(old, new) is True
    assert new.exists() and _count(hs.connect(new)) == 5
    assert not new.with_suffix(new.suffix + ".migrating").exists()


def test_migrate_once_folds_in_an_unflushed_wal(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVIN_VAR_DIR", str(tmp_path / "var"))
    old = tmp_path / "old.db"
    new = tmp_path / "new.db"

    old_conn = hs.connect(old)
    hs.load(old_conn, "s", "d", [_line(i) for i in range(5)])
    old_conn.close()

    old_conn = sqlite3.connect(old, isolation_level=None)
    old_conn.execute("BEGIN IMMEDIATE")
    hs.load(old_conn, "s", "d", [_line(99)])
    old_conn.execute("COMMIT")

    assert hs.migrate_once(old, new) is True
    assert _count(hs.connect(new)) == 6


def test_connect_doesnt_error_when_database_already_exists_after_migration(tmp_path, monkeypatch):
    """Verify migration is idempotent: multiple connect() calls to same path work fine."""
    var_dir = tmp_path / "var"
    old = tmp_path / ".claude" / "history.db"
    old.parent.mkdir(parents=True, exist_ok=True)
    new = var_dir / "history.db"

    old_conn = hs.connect(old)
    hs.load(old_conn, "s", "d", [_line(1)])
    old_conn.close()

    monkeypatch.setattr(hs, "DB_PATH", new)
    monkeypatch.setattr(hs, "OLD_DB_PATH", old)

    c1 = hs.connect(new)
    assert _count(c1) == 1
    c1.close()

    c2 = hs.connect(new)
    assert _count(c2) == 1
    c2.close()


def test_connect_with_arbitrary_path_never_triggers_migrate(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVIN_VAR_DIR", str(tmp_path / "var"))

    call_count = [0]
    original_migrate = hs.migrate_once
    def spy_migrate(o=None, n=None):
        call_count[0] += 1
        return original_migrate(o, n)
    monkeypatch.setattr(hs, "migrate_once", spy_migrate)

    conn = hs.connect(tmp_path / "arbitrary.db")
    conn.close()

    assert call_count[0] == 0


def test_connect_creates_var_dir_if_missing(tmp_path, monkeypatch):
    var_dir = tmp_path / "var"
    monkeypatch.setenv("MARVIN_VAR_DIR", str(var_dir))
    assert not var_dir.exists()

    conn = hs.connect(var_dir / "history.db")
    conn.close()

    assert var_dir.exists()


# ── runs view and ticket index ────────────────────────────────────────────────

def test_a_wellformed_launch_line_surfaces_through_runs(db):
    launch = json.dumps({"t": 1791498937.0, "kind": "agent", "model": "claude-opus", "ticket": "#621",
                        "cost_usd": 0.05, "tokens_in": 100, "tokens_out": 50, "tokens_cached": 0,
                        "tokens_created_cache": 0, "exit_code": 0, "duration_s": 1.5})
    hs.load(db, "launches", "d", [launch])
    row = db.execute("SELECT kind, model, ticket, cost_usd FROM runs WHERE ticket = ?", ("#621",)).fetchone()
    assert row == ("agent", "claude-opus", "#621", 0.05)


def test_a_malformed_launch_line_does_not_break_runs_queries(db):
    hs.load(db, "launches", "d", ["{not json"])
    assert hs.load(db, "launches", "d", [json.dumps({"t": 1.0, "ticket": "#99"})]) == {"added": 1, "duplicate": 0, "malformed": 0}
    assert db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1


def test_a_malformed_launch_line_still_inserts_into_events(db):
    hs.load(db, "launches", "d", ["{not json"])
    assert _count(db) == 1
    assert db.execute("SELECT ts FROM events WHERE stream = 'launches'").fetchone()[0] is None


def test_runs_index_uses_events_launches_ticket(db):
    plan = " ".join(r[3] for r in db.execute(
        "EXPLAIN QUERY PLAN SELECT * FROM runs WHERE ticket = ?", ("#1",)))
    assert "events_launches_ticket" in plan


def test_a_launch_with_no_ticket_is_excluded_from_ticket_keyed_aggregation(db):
    hs.load(db, "launches", "d", [json.dumps({"t": 1.0, "kind": "utility-call", "cost_usd": 0.05, "tokens_in": 10, "tokens_out": 5, "tokens_cached": 0, "tokens_created_cache": 0})])
    costs = hs.cost_by_ticket(db)
    assert costs == {}
    assert db.execute("SELECT COUNT(*) FROM events WHERE stream = 'launches'").fetchone()[0] == 1


# ── cost_by_ticket and cost_per_merged_pr ──────────────────────────────────────

def test_two_runs_under_the_same_ticket_aggregate_correctly(db):
    l1 = json.dumps({"t": 1.0, "ticket": "#621", "cost_usd": 0.05, "tokens_in": 100, "tokens_out": 50, "tokens_cached": 10, "tokens_created_cache": 5})
    l2 = json.dumps({"t": 2.0, "ticket": "#621", "cost_usd": 0.03, "tokens_in": 80, "tokens_out": 40, "tokens_cached": 5, "tokens_created_cache": 2})
    hs.load(db, "launches", "d", [l1, l2])
    costs = hs.cost_by_ticket(db)
    assert costs["#621"] == {"cost_usd": 0.08, "tokens_in": 180, "tokens_out": 90, "tokens_cached": 15,
                             "tokens_created_cache": 7, "paid_cost_usd": 0.08, "local_cost_usd": 0}


def test_zero_cost_and_paid_cost_split_correctly(db):
    l1 = json.dumps({"t": 1.0, "ticket": "#621", "cost_usd": 0.0, "tokens_in": 10, "tokens_out": 5, "tokens_cached": 0, "tokens_created_cache": 0})
    l2 = json.dumps({"t": 2.0, "ticket": "#621", "cost_usd": 0.1, "tokens_in": 20, "tokens_out": 10, "tokens_cached": 0, "tokens_created_cache": 0})
    hs.load(db, "launches", "d", [l1, l2])
    costs = hs.cost_by_ticket(db)
    assert costs["#621"]["paid_cost_usd"] == 0.1
    assert costs["#621"]["local_cost_usd"] == 0.0
    assert costs["#621"]["cost_usd"] == 0.1


def test_merged_prs_raises_on_gh_failure(tmp_path, monkeypatch):
    def mock_run(cmd, **kwargs):
        result = type('Result', (), {'returncode': 1, 'stderr': 'gh error'})()
        return result
    with pytest.raises(RuntimeError, match="gh pr list failed"):
        hs.merged_prs("repo", runner=mock_run)


def test_merged_prs_skips_a_pr_with_empty_closing_issues(tmp_path, monkeypatch):
    def mock_run(cmd, **kwargs):
        result = type('Result', (), {
            'returncode': 0,
            'stdout': json.dumps([{"number": 1, "closingIssuesReferences": []}])
        })()
        return result
    prs = hs.merged_prs("repo", runner=mock_run)
    assert len(prs) == 1 and prs[0]["closingIssuesReferences"] == []


def test_a_pr_that_closed_multiple_tickets_is_represented_once_per_ticket(db):
    l1 = json.dumps({"t": 1.0, "ticket": "#621", "cost_usd": 0.05, "tokens_in": 100, "tokens_out": 50, "tokens_cached": 0, "tokens_created_cache": 0})
    l2 = json.dumps({"t": 2.0, "ticket": "#622", "cost_usd": 0.03, "tokens_in": 80, "tokens_out": 40, "tokens_cached": 0, "tokens_created_cache": 0})
    hs.load(db, "launches", "d", [l1, l2])

    def mock_run(cmd, **kwargs):
        result = type('Result', (), {
            'returncode': 0,
            'stdout': json.dumps([{"number": 100, "closingIssuesReferences": [{"number": 621}, {"number": 622}]}])
        })()
        return result

    costs = hs.cost_per_merged_pr(db, "repo", runner=mock_run)
    assert costs[100]["closed_issues"] == [621, 622]
    assert costs[100]["cost_usd"] == pytest.approx(0.08, abs=0.001)


def test_a_ticket_with_recorded_runs_and_no_merged_pr_is_absent_from_cost_per_merged_pr(db):
    l1 = json.dumps({"t": 1.0, "ticket": "#999", "cost_usd": 0.05, "tokens_in": 100, "tokens_out": 50, "tokens_cached": 0, "tokens_created_cache": 0})
    hs.load(db, "launches", "d", [l1])

    def mock_run(cmd, **kwargs):
        result = type('Result', (), {
            'returncode': 0,
            'stdout': json.dumps([{"number": 100, "closingIssuesReferences": [{"number": 621}]}])
        })()
        return result

    costs = hs.cost_per_merged_pr(db, "repo", runner=mock_run)
    assert 100 not in costs


def test_ticket_field_format_variability_correlates_to_the_same_issue(db):
    l1 = json.dumps({"t": 1.0, "ticket": "G-Eskayo/marvin#621", "cost_usd": 0.05, "tokens_in": 100, "tokens_out": 50, "tokens_cached": 0, "tokens_created_cache": 0})
    l2 = json.dumps({"t": 2.0, "ticket": "#621", "cost_usd": 0.03, "tokens_in": 80, "tokens_out": 40, "tokens_cached": 0, "tokens_created_cache": 0})
    hs.load(db, "launches", "d", [l1, l2])

    def mock_run(cmd, **kwargs):
        result = type('Result', (), {
            'returncode': 0,
            'stdout': json.dumps([{"number": 100, "closingIssuesReferences": [{"number": 621}]}])
        })()
        return result

    costs = hs.cost_per_merged_pr(db, "repo", runner=mock_run)
    assert costs[100]["closed_issues"] == [621, 621]
    assert costs[100]["cost_usd"] == pytest.approx(0.08, abs=0.001)


# ── isolation fixture verification ──────────────────────────────────────────

def test_the_isolation_fixture_points_db_path_away_from_the_real_machine():
    """Verify _isolate_history_store redirects to temp paths, never the real machine's defaults."""
    real_db = Path.home() / ".agents" / "var" / "history.db"
    real_old_db = Path.home() / ".claude" / "history.db"
    assert hs.DB_PATH != real_db, f"DB_PATH should be redirected away from {real_db}"
    assert hs.OLD_DB_PATH != real_old_db, f"OLD_DB_PATH should be redirected away from {real_old_db}"
