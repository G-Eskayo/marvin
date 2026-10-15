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
