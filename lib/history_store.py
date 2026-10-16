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

Usage: history_store.py [stream ...]   (default: gh-calls gh-budget; run every 5 min on the Mini by launchd)
       history_store.py --replica-max | --apply < rows | --digest ID   (run over ssh against another Mac's copy)

The laptop's copy (G3): after each load the Mini ships the rows the copy doesn't have yet (id > the copy's max, at
most SHIP_LIMIT per run), so it costs O(new rows). Ids are kept, so the copy is identical. Once a week a digest of
every row's hash is compared on both sides (O(n), weekly). A row already in the copy with different content is a
divergence: the run fails loudly instead of skipping it.
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
HOME_DEVICE = "mac-mini-1"  # the database's home: the only Mac that loads outboxes (ADR 0066)
SHIP_LIMIT = 50_000  # rows per run to the laptop's copy, so a long absence catches up in bounded steps
VERIFY_EVERY_S = 7 * 86400
DEFAULT_STREAMS = ["gh-calls", "gh-budget"]  # gh-budget: the allowance readings the GitHub usage chart draws (G4)
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
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
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


def _enable_wal(conn: sqlite3.Connection, wait_s: float = 30.0) -> None:
    """Switching a file to WAL needs an exclusive lock, and while another connection holds a write reservation SQLite
    refuses at once ("database is locked") without honouring the busy timeout: 13 of 60 four-thread opens of a new
    database failed that way (2026-10-15). Retry with backoff. Once set, WAL is stored in the file, so after the first
    open this returns at once."""
    import time
    delay, deadline = 0.01, time.monotonic() + wait_s
    while True:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc) or time.monotonic() >= deadline:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.5)


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, isolation_level=None)  # transactions are explicit (BEGIN IMMEDIATE)
    conn.execute("PRAGMA busy_timeout=30000")
    _enable_wal(conn)
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


def tail_since(path: Path | str, since_ts: float, chunk: int = 65536) -> list[dict]:
    """The records in a JSONL log newer than since_ts, oldest first, reading backwards from the end only as far as
    it needs: O(k + chunk), not O(file). A half-written last line is skipped; lines with no readable time are kept
    only if they sit among newer lines."""
    try:
        f = open(path, "rb")
    except (FileNotFoundError, IsADirectoryError):
        return []
    with f:
        f.seek(0, 2)
        pos = f.tell()
        data = b""
        while pos > 0:
            n = min(chunk, pos)
            pos -= n
            f.seek(pos)
            data = f.read(n) + data
            nl = data.find(b"\n")
            if pos > 0 and nl == -1:
                continue
            first = (data[nl + 1:] if pos > 0 else data).split(b"\n", 1)[0]
            try:
                ts = _ts(json.loads(first))
            except (ValueError, AttributeError):
                ts = None
            if ts is not None and ts <= since_ts:
                break
    if pos > 0:
        data = data[data.find(b"\n") + 1:]
    data = data[:data.rfind(b"\n") + 1]
    out = []
    for line in data.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict) and (_ts(record) or 0) > since_ts:
            out.append(record)
    return out


# ── the laptop's copy (G3, marvin#456): same ids, shipped incrementally ─────

def max_id(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM events").fetchone()[0]


def tip(conn: sqlite3.Connection) -> tuple[int, bytes | None]:
    """(highest id, its hash): what a copy reports so the Mini can check the copy still matches, in O(log n)."""
    row = conn.execute("SELECT id, hash FROM events ORDER BY id DESC LIMIT 1").fetchone()
    return (row[0], row[1]) if row else (0, None)


def rows_after(conn: sqlite3.Connection, after_id: int, limit: int) -> list[tuple]:
    return conn.execute("SELECT id, stream, device, ts, hash, data FROM events WHERE id > ? ORDER BY id LIMIT ?",
                        (after_id, limit)).fetchall()


def encode_rows(rows: Iterable[tuple]) -> bytes:
    """One JSON array per line: json escapes newlines, so a record can never split a line."""
    return b"".join(json.dumps([r[0], r[1], r[2], r[3], r[4].hex(), r[5]]).encode() + b"\n" for r in rows)


def decode_rows(wire: bytes) -> list[tuple]:
    rows = []
    for line in wire.splitlines():
        try:
            i, stream, device, ts, h, data = json.loads(line)
            rows.append((i, stream, device, ts, bytes.fromhex(h), data))
        except (ValueError, TypeError):
            continue  # a line cut off by a dropped connection: the next run sends it again
    return rows


def apply_rows(conn: sqlite3.Connection, rows: Iterable[tuple]) -> dict:
    """Idempotent. A row whose id (or hash) is already there with different content is a divergence: counted."""
    out = {"applied": 0, "already": 0, "conflict": 0}
    conn.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            cur = conn.execute("INSERT OR IGNORE INTO events(id, stream, device, ts, hash, data) VALUES (?, ?, ?, ?, ?, ?)", row)
            if cur.rowcount:
                out["applied"] += 1
                continue
            same = conn.execute("SELECT 1 FROM events WHERE id = ? AND hash = ?", (row[0], row[4])).fetchone()
            out["already" if same else "conflict"] += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return out


def ship(conn: sqlite3.Connection, remote_tip: Callable[[], tuple[int, bytes | None]],
         apply: Callable[[list[tuple]], dict], limit: int = SHIP_LIMIT) -> dict:
    """Send the rows the copy doesn't have yet: O(new rows). First check the copy's last row is ours (O(log n)):
    if something wrote into the copy, its ids run ahead and a plain "id > max" would skip the divergence."""
    try:
        top, top_hash = remote_tip()
    except Unreachable as exc:
        return {"skipped": f"unreachable: {exc}"}
    if top:
        ours = conn.execute("SELECT hash FROM events WHERE id = ?", (top,)).fetchone()
        if not ours or ours[0] != top_hash:
            return {"sent": 0, "applied": 0, "already": 0, "conflict": 1}
    rows = rows_after(conn, top, limit)
    if not rows:
        return {"sent": 0, "applied": 0, "already": 0, "conflict": 0}
    try:
        return {"sent": len(rows), **apply(rows)}
    except Unreachable as exc:
        return {"skipped": f"unreachable: {exc}"}


def digest(conn: sqlite3.Connection, upto_id: int) -> str:
    """Fingerprint of every row up to upto_id. O(n): run weekly, not every 5 minutes."""
    h = hashlib.sha256()
    for (row_hash,) in conn.execute("SELECT hash FROM events WHERE id <= ? ORDER BY id", (upto_id,)):
        h.update(row_hash)
    return h.hexdigest()


def _remote(host: str, args: str, stdin: bytes | None = None) -> bytes:
    cmd = f"cd ~/.agents && venv/bin/python lib/history_store.py {args}"
    try:
        result = subprocess.run(["ssh", *SSH_OPTS, host, cmd], input=stdin, capture_output=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise Unreachable(f"ssh to {host} timed out") from exc
    if result.returncode != 0:
        raise Unreachable(result.stderr.decode(errors="replace").strip()[-200:] or f"ssh exit {result.returncode}")
    return result.stdout


def ship_to(conn: sqlite3.Connection, host: str, now: float | None = None) -> dict:
    """Ship to one Mac's copy over ssh, and once a week compare digests."""
    import time
    def remote_tip():
        top, _, h = _remote(host, "--replica-max").decode().strip().partition(" ")
        return int(top or 0), (bytes.fromhex(h) if h else None)
    out = ship(conn, remote_tip, lambda rows: json.loads(_remote(host, "--apply", encode_rows(rows))))
    if out.get("skipped"):
        return out
    now = now or time.time()
    key = f"verified:{host}"
    last = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if not last or now - float(last[0]) >= VERIFY_EVERY_S:
        try:
            top = remote_tip()[0]
            same = _remote(host, f"--digest {top}").strip().decode() == digest(conn, top)
        except Unreachable as exc:
            return {**out, "verify": f"skipped: {exc}"}
        out["verify"] = "match" if same else f"MISMATCH up to row {top}"
        if same:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, str(now)))
    return out


def require_home() -> None:
    import machine_profile
    me = machine_profile.registry_id()
    if me != HOME_DEVICE:
        raise SystemExit(f"history_store loads outboxes only on {HOME_DEVICE} (this is {me}): the other Macs hold copies")


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
        return {stream: load_sources(conn, stream, default_sources(stream)) for stream in (streams or DEFAULT_STREAMS)}
    finally:
        conn.close()


def main(streams: list[str] | None = None) -> dict:
    import job_events
    import machine_profile

    @job_events.reported("history-load", "History store load")
    def _run():
        require_home()
        results = run(streams)
        for stream, devices in results.items():
            job_events.step(stream, "; ".join(f"{d}: {r.get('skipped') or str(r.get('added', 0)) + ' new'}"
                                              for d, r in devices.items()))
        conn = connect()
        try:
            # Copies go to the Macs only: mac-mini-2012 holds untrusted code and must never hold MARVIN's history.
            for device, info in machine_profile.remote_macs().items():
                host = info.get("tailscale_hostname")
                if not host:
                    continue
                shipped = ship_to(conn, host)
                results.setdefault("copies", {})[device] = shipped
                job_events.step(f"copy to {device}", shipped.get("skipped") or
                                f"{shipped['applied']} sent" + (f", verify {shipped['verify']}" if "verify" in shipped else ""))
                if shipped.get("conflict") or "MISMATCH" in str(shipped.get("verify", "")):
                    raise RuntimeError(f"{device}'s copy has diverged from the record: {shipped}")
        finally:
            conn.close()
        return results
    return _run()


def _replica_cli(args: list[str]) -> None:
    """What the Mini runs on another Mac over ssh, against that Mac's copy."""
    conn = connect()
    try:
        if args[0] == "--replica-max":
            top, h = tip(conn)
            print(f"{top} {h.hex() if h else ''}".strip())
        elif args[0] == "--apply":
            print(json.dumps(apply_rows(conn, decode_rows(sys.stdin.buffer.read()))))
        elif args[0] == "--digest":
            print(digest(conn, int(args[1])))
    finally:
        conn.close()


if __name__ == "__main__":
    if sys.argv[1:2] and sys.argv[1].startswith("--"):
        _replica_cli(sys.argv[1:])
    else:
        result = main(sys.argv[1:] or None)
        if sys.stdout.isatty():  # launchd runs every 5 min: a log line each time would grow forever
            print(json.dumps(result, indent=2))
