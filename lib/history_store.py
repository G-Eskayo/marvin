#!/usr/bin/env python3
"""History store (ADR 0066, marvin#449): one SQLite record of what MARVIN did on both Macs.

Jobs keep appending to their JSONL logs, which are now *outboxes*. This module moves new outbox lines into
`~/.claude/history.db` on the Mini, the laptop's over ssh whenever it's reachable. The database is the record.

Complexity (north star #1):
- load: O(new lines x log n). A cursor per outbox (device, path) remembers the byte offset and inode, so a run reads
  only what was appended since the last one. The cursor commits in the same transaction as the rows, so a crash
  redoes a load and never skips one.
- rotation: bin/gh rewrites gh-calls.jsonl in place with its newer half once it passes 5 MB, so an offset can end up
  pointing into the middle of different lines. A fingerprint of the bytes just before the offset catches that, and the
  file is read once from the start (at most 5 MB). Loading is idempotent, so the re-read adds only what's new.
- queries: O(log n + k) on the (stream, ts) index.

A line's identity is a hash of (device, stream, line): the same line twice from one Mac is one record, from two Macs
two. A line that isn't valid JSON is still stored (ts NULL): once outboxes are trimmed the database is the only copy.

Usage: history_store.py [stream ...]   (default: gh-calls; run every 5 min on the Mini by launchd)
"""
from __future__ import annotations
import hashlib
import json
import os
import shlex
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOME = Path.home()
DB_PATH = HOME / ".claude" / "history.db"
LOGS_REL = "~/.claude/logs"
FINGERPRINT_BYTES = 64
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY,           -- rowid order: what the backup ships incrementally (G3)
    stream TEXT NOT NULL,
    device TEXT NOT NULL,
    ts REAL,                          -- epoch seconds; NULL when the line has no readable time
    hash BLOB NOT NULL UNIQUE,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_stream_ts ON events(stream, ts);
CREATE TABLE IF NOT EXISTS cursors(
    device TEXT NOT NULL,
    path TEXT NOT NULL,
    inode INTEGER NOT NULL,
    offset INTEGER NOT NULL,
    fingerprint BLOB NOT NULL,
    PRIMARY KEY(device, path)
);
"""


class Unreachable(Exception):
    """The other Mac couldn't be read (asleep, away, ssh refused). Its outbox waits; nothing is lost."""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)  # transactions are explicit (BEGIN IMMEDIATE)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript(SCHEMA)
    return conn


def _ts(record: dict) -> float | None:
    for key in ("t", "at", "timestamp", "ts"):
        value = record.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def _hash(device: str, stream: str, line: str) -> bytes:
    return hashlib.sha256(f"{device}\0{stream}\0{line}".encode()).digest()[:16]


def load(conn: sqlite3.Connection, stream: str, device: str, lines: Iterable[str]) -> dict:
    """Insert lines; blank lines are skipped. Runs inside the caller's transaction when there is one."""
    out = {"added": 0, "duplicate": 0, "malformed": 0}
    for line in lines:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            ts = _ts(record) if isinstance(record, dict) else None
        except ValueError:
            ts = None
            out["malformed"] += 1
        cur = conn.execute("INSERT OR IGNORE INTO events(stream, device, ts, hash, data) VALUES (?, ?, ?, ?, ?)",
                           (stream, device, ts, _hash(device, stream, line), line))
        out["added" if cur.rowcount else "duplicate"] += 1
    return out


# ── reading an outbox from a byte offset ────────────────────────────────────

def read_local(path: Path | str, from_byte: int) -> tuple[int, int, bytes] | None:
    """(inode, size, bytes from from_byte) or None when the file doesn't exist."""
    path = Path(path).expanduser()
    try:
        with open(path, "rb") as f:
            st = os.fstat(f.fileno())
            f.seek(from_byte)
            return st.st_ino, st.st_size, f.read()
    except FileNotFoundError:
        return None


def remote_read_command(path: str, from_byte: int) -> str:
    """A shell command for `ssh host <cmd>` that prints "<inode> <size>" then the bytes from from_byte.
    `~/` becomes "$HOME"/ so the rest of the path is quoted and can never run as a command."""
    path_expr = f'"$HOME"/{shlex.quote(path[2:])}' if path.startswith("~/") else shlex.quote(path)
    return (f"f={path_expr}; if [ ! -f \"$f\" ]; then echo MISSING; exit 0; fi; "
            f"stat -f '%i %z' \"$f\" && tail -c +{int(from_byte) + 1} \"$f\"")


def parse_remote_reply(reply: bytes) -> tuple[int, int, bytes] | None:
    head, _, payload = reply.partition(b"\n")
    if head.strip() == b"MISSING":
        return None
    inode, size = head.split()
    return int(inode), int(size), payload


def ssh_reader(host: str, path: str) -> Callable[[int], tuple[int, int, bytes] | None]:
    def read(from_byte: int):
        try:
            result = subprocess.run(["ssh", *SSH_OPTS, host, remote_read_command(path, from_byte)],
                                    capture_output=True, timeout=120)
        except subprocess.TimeoutExpired as exc:
            raise Unreachable(f"ssh to {host} timed out") from exc
        if result.returncode != 0:
            raise Unreachable(result.stderr.decode(errors="replace").strip()[:200] or f"ssh exit {result.returncode}")
        return parse_remote_reply(result.stdout)
    return read


def load_source(conn: sqlite3.Connection, stream: str, device: str, path: str,
                read: Callable[[int], tuple[int, int, bytes] | None]) -> dict:
    """Load what one outbox gained since the last run. Rows and cursor commit together."""
    row = conn.execute("SELECT inode, offset, fingerprint FROM cursors WHERE device = ? AND path = ?",
                       (device, path)).fetchone()
    got, buf_start, start = None, 0, 0
    if row:
        inode, offset, fingerprint = row
        back = min(offset, FINGERPRINT_BYTES)
        got = read(offset - back)  # re-read the bytes just before the offset to check they're the same ones
        if got and got[0] == inode and got[1] >= offset and hashlib.sha256(got[2][:back]).digest() == fingerprint:
            buf_start, start = offset - back, offset
        else:  # replaced, truncated or rewritten in place: read it all once; loading is idempotent
            got = None
    if got is None:
        got = read(0)
        if got is None:
            return {"skipped": "missing"}
    inode, buf = got[0], got[2]

    end = buf.rfind(b"\n") + 1  # a half-written last line waits for its newline
    new_offset = buf_start + end if end > start - buf_start else start
    lines = buf[start - buf_start:new_offset - buf_start].decode("utf-8", errors="replace").splitlines()
    fingerprint = hashlib.sha256(buf[max(0, new_offset - FINGERPRINT_BYTES - buf_start):new_offset - buf_start]).digest()

    conn.execute("BEGIN IMMEDIATE")
    try:
        out = load(conn, stream, device, lines)
        conn.execute("INSERT OR REPLACE INTO cursors(device, path, inode, offset, fingerprint) VALUES (?, ?, ?, ?, ?)",
                     (device, path, inode, new_offset, fingerprint))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return out


def load_sources(conn: sqlite3.Connection, stream: str,
                 sources: list[tuple[str, str, Callable[[int], tuple[int, int, bytes] | None]]]) -> dict:
    """{device: result}; one unreachable Mac never stops the others."""
    results = {}
    for device, path, read in sources:
        try:
            results[device] = load_source(conn, stream, device, path, read)
        except Unreachable as exc:
            results[device] = {"skipped": f"unreachable: {exc}"}
    return results


def default_sources(stream: str) -> list[tuple[str, str, Callable]]:
    """This Mac's outbox plus every other registered Mac's, read over Tailscale ssh."""
    import machine_profile
    path = f"{LOGS_REL}/{stream}.jsonl"
    local = Path(path).expanduser()
    sources = [(machine_profile.registry_id(), path, lambda b: read_local(local, b))]
    for device, info in machine_profile.remote_devices().items():
        host = info.get("tailscale_hostname")
        if host:
            sources.append((device, path, ssh_reader(host, path)))
    return sources


def run(streams: list[str] | None = None, db_path: Path | None = None) -> dict:
    conn = connect(db_path)
    try:
        return {stream: load_sources(conn, stream, default_sources(stream)) for stream in (streams or ["gh-calls"])}
    finally:
        conn.close()


def main(streams: list[str] | None = None) -> dict:
    import job_events

    @job_events.reported("history-load", "History store load")
    def _run():
        results = run(streams)
        for stream, devices in results.items():
            job_events.step(stream, "; ".join(f"{d}: {r.get('skipped') or str(r.get('added', 0)) + ' new'}"
                                              for d, r in devices.items()))
        return results
    return _run()


if __name__ == "__main__":
    result = main(sys.argv[1:] or None)
    if sys.stdout.isatty():  # launchd runs every 5 min: a log line each time would grow forever
        print(json.dumps(result, indent=2))
