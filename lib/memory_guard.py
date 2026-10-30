#!/usr/bin/env python3
"""No new heavy work while memory pressure is high, and never stop anything to make room (marvin#845).

On 2026-10-30 the Mac mini hung with five helpers and their builds running at once: the cause was memory. This guard
sits where heavy work starts (helper-tab, so every lane line too; the ticket pipeline before it claims; task_dispatch
for work it runs on this Mac; the merge gate before a rebase + retest) and reads macOS's own verdict, the kernel's
memory pressure level (kern.memorystatus_vm_pressure_level: normal, warn or critical), plus swap in use for the
message. At warn or critical the work is refused in plain words ("The Mac mini's memory is under pressure, so #N
waits"), the owner is told once, and the work is queued. Nothing running is ever stopped (owner's rule).

Queued work starts again on events, never on a timer:
  the notification  `watch` holds a libdispatch DISPATCH_SOURCE_TYPE_MEMORYPRESSURE source and blocks on it; when
                    macOS reports the level back at normal, one queued item starts. It ends when the queue is empty
                    (a second source on the queue directory wakes it when another trigger empties it). Live on the
                    Mini macOS sent this small process no note at all (see PressureSource), so in practice:
  a finished job    a helper's exit, a dispatched task's exit and the end of a merge call `kick`, which starts one
                    more queued item if pressure is normal (pressure that stays normal sends no further notification).
  a new start       a check at normal with work still queued starts the watcher, whose first look starts one item.
One item per trigger, so each start sees the pressure the previous one caused. A level that can't be read never blocks
(same as the disk pre-flight).

Merges first (marvin#940): a merge is work keyed `merge:<PR url>`. While one waits here or runs (the webhook marks a
running merge on lib/test_slot.py's merges.lock), any other new work is refused and queued the same way, even at normal
pressure: the memory is kept for the merge. The drain starts a queued merge before older queued work, and starts no
other work while a merge runs; the merge ending is the trigger (the webhook's `kick`). MARVIN_MEMORY_PRESSURE_LEVEL overrides the reading (the test suite pins it to normal).

    memory_guard.py check --what "#845" [--key K] [--cwd DIR] [-- command args...]   # 0 = go, 3 = refused (+ queued)
    memory_guard.py watch      # the notification wait (started by check; one at a time)
    memory_guard.py drain      # start the oldest queued item if pressure is normal
    memory_guard.py kick       # drain in the background, only when something is queued
    memory_guard.py status     # one JSON line: level, swap, what waits (Health's memory:pressure card)
    memory_guard.py forget --key K   # drop a queued item that started some other way (prints {"forgotten": bool})
"""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import json
import os
import queue
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator

HERE = Path(__file__).resolve()
PY = Path.home() / ".agents" / "venv" / "bin" / "python"
STATE_DIR = Path.home() / ".claude" / "memory-guard"
QUEUE_DIR = STATE_DIR / "queue"
LOCK_PATH = STATE_DIR / "watch.lock"
DRAIN_LOCK_PATH = STATE_DIR / "queue.lock"
LOG_PATH = Path.home() / ".claude" / "logs" / "memory-guard.jsonl"
STARTED_LOG = Path.home() / ".claude" / "logs" / "memory-guard-started.log"
LOG_MAX_BYTES = 2**20
LEVEL_ENV = "MARVIN_MEMORY_PRESSURE_LEVEL"
REFUSED_RC = 3
SYSCTL = "/usr/sbin/sysctl"   # absolute: launchd's PATH omits /usr/sbin
LEVELS = {1: "normal", 2: "warn", 4: "critical"}
HIGH = ("warn", "critical")
_READ = object()
QUEUE_CHANGED = "queue-changed"   # the watcher's other event: the queue directory changed (an item added or started)
O_EVTONLY = 0x8000                # <sys/fcntl.h>: open a directory only to watch it
DISPATCH_VNODE_WRITE = 0x2

GB = lambda n: f"{n / 2**30:.1f} GB"  # noqa: E731


# ── reading pressure ────────────────────────────────────────────────────────────────────────────────────────────

def read_level(run: Callable = subprocess.run) -> str | None:
    """"normal", "warn" or "critical" from the kernel, or None when it can't be read."""
    override = os.environ.get(LEVEL_ENV, "").strip().lower()
    if override:
        return override if override in LEVELS.values() else None
    try:
        r = run([SYSCTL, "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True, text=True, timeout=5)
        return LEVELS.get(int(r.stdout.strip())) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def read_swap_used(run: Callable = subprocess.run) -> int | None:
    try:
        r = run([SYSCTL, "-n", "vm.swapusage"], capture_output=True, text=True, timeout=5)
        m = re.search(r"used = ([\d.]+)([KMG])", r.stdout or "")
        return int(float(m.group(1)) * {"K": 2**10, "M": 2**20, "G": 2**30}[m.group(2)]) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def level_from_mask(mask: int) -> str | None:
    """The level a DISPATCH_SOURCE_TYPE_MEMORYPRESSURE event reports (the worst bit set)."""
    for bit in (4, 2, 1):
        if mask & bit:
            return LEVELS[bit]
    return None


def machine_name() -> str:
    try:
        from machine_profile import registry_id
        from health_checks import machine_words
        return machine_words(registry_id())
    except Exception:  # noqa: BLE001 -- a name for a message, never a reason to fail
        return "Mac"


# ── the log (Health reads it) ───────────────────────────────────────────────────────────────────────────────────

def record(event: str, **fields) -> None:
    """One JSON line per event. Never raises: a log that can't be written must not change what the guard decides."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > LOG_MAX_BYTES:   # keep the newest half, bounded forever
            lines = LOG_PATH.read_text(errors="replace").splitlines()
            LOG_PATH.write_text("\n".join(lines[len(lines) // 2:]) + "\n")
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ── the check ───────────────────────────────────────────────────────────────────────────────────────────────────

def check(what: str, level=_READ, swap=_READ) -> dict:
    """{"ok", "level", "swap_used", "message"}. Refuses only at warn or critical."""
    level = read_level() if level is _READ else level
    if level not in HIGH:
        return {"ok": True, "level": level, "swap_used": None, "message": ""}
    swap = read_swap_used() if swap is _READ else swap
    detail = f"Pressure: {level}" + (f", {GB(swap)} of swap in use." if swap else ".")
    message = (f"The {machine_name()}'s memory is under pressure, so {what} waits. "
               f"Nothing was stopped to make room. {detail}")
    return {"ok": False, "level": level, "swap_used": swap, "message": message}


# ── the queue: one JSON file per item, oldest first ─────────────────────────────────────────────────────────────

@contextmanager
def _queue_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(DRAIN_LOCK_PATH, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _entries() -> list[tuple[Path, dict]]:
    if not QUEUE_DIR.is_dir():
        return []
    out = []
    for p in sorted(QUEUE_DIR.glob("*.json")):   # names start with a nanosecond stamp: sorted = first in, first out
        try:
            out.append((p, json.loads(p.read_text())))
        except (OSError, ValueError):
            continue
    return out


def queued() -> list[dict]:
    return [e for _, e in _entries()]


def _enqueue(what: str, argv: list[str], cwd: str | None, key: str | None) -> bool:
    """True when added, False when an item with the same key is already waiting."""
    with _queue_lock():
        if key and any(e.get("key") == key for e in queued()):
            return False
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        entry = {"what": what, "argv": list(argv), "cwd": cwd, "key": key,
                 "queued_at": datetime.now(timezone.utc).isoformat()}
        (QUEUE_DIR / f"{time.time_ns():020d}-{uuid.uuid4().hex[:6]}.json").write_text(json.dumps(entry))
        return True


def _spawn_detached(argv: list[str]) -> None:
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     cwd=str(Path.home()), start_new_session=True)


def _self_cmd(*args: str) -> list[str]:
    return [str(PY if PY.exists() else sys.executable), str(HERE), *args]


def start_watcher() -> None:
    _spawn_detached(_self_cmd("watch"))


def _tell(title: str, message: str) -> None:
    if os.environ.get("HELPER_TAB_QUIET"):
        return
    try:
        import notify
        notify.notify(title, message)
    except Exception:  # noqa: BLE001
        pass


def is_merge(key: str | None) -> bool:
    return bool(key) and key.startswith("merge:")


def merge_pending() -> bool:
    """A merge waiting here for memory, or running (marked by the webhook). Unknown counts as no: never blocks."""
    if any(is_merge(e.get("key")) for e in queued()):
        return True
    try:
        import test_slot
        return test_slot.merge_pending()
    except Exception:  # noqa: BLE001 -- a lock that can't be read never holds work back
        return False


def _merge_message(what: str) -> str:
    return (f"A merge is running on the {machine_name()}, so {what} waits. Nothing was stopped. "
            "It starts by itself when the merge is done.")


def guard(what: str, argv: list[str] | None, cwd: str | None, key: str | None = None,
          level_reader: Callable[[], str | None] = read_level, swap_reader: Callable[[], int | None] = read_swap_used,
          start_watcher: Callable[[], None] | None = None, tell: Callable[[str, str], None] | None = None) -> dict:
    """Check before heavy work. Normal: go. Warn or critical: refuse, queue `argv` (when given) to run in `cwd` once
    pressure drops, arm the notification wait, tell the owner once per queued item. Returns check()'s dict plus
    "queued" and "reason" (memory or merge). Work that is not a merge also waits while a merge waits or runs."""
    start_watcher = start_watcher or globals()["start_watcher"]
    tell = tell or _tell
    level = level_reader()
    if level not in HIGH and argv and not is_merge(key) and merge_pending():
        added = _enqueue(what, argv, cwd, key)
        start_watcher()
        message = _merge_message(what)
        record("refused", what=what, level=level, reason="merge", queued=True, new=added)
        if added:
            tell(f"{what} waits: a merge is running", message)
        return {"ok": False, "level": level, "swap_used": None, "message": message, "queued": True, "reason": "merge"}
    if level not in HIGH:
        if queued():
            start_watcher()   # after a restart nothing is waiting on the notification: re-arm it (it exits if one is)
        return {**check(what, level=level), "queued": False, "reason": None}
    r = check(what, level=level, swap=swap_reader())
    added = _enqueue(what, argv, cwd, key) if argv else False
    if argv:
        r["message"] += " It starts by itself when pressure drops."
        start_watcher()
    else:
        r["message"] += " Start it again when pressure drops."
    record("refused", what=what, level=level, swap_used=r["swap_used"], queued=bool(argv), new=added)
    if added or not argv:
        tell(f"{what} waits: memory under pressure", r["message"])
    return {**r, "queued": bool(argv), "reason": "memory"}


# ── starting queued work ────────────────────────────────────────────────────────────────────────────────────────

def _start(entry: dict) -> None:
    cwd = entry.get("cwd")
    cwd = cwd if cwd and Path(cwd).is_dir() else str(Path.home())
    STARTED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(STARTED_LOG, "a") as log:
        subprocess.Popen(entry["argv"], cwd=cwd, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                         start_new_session=True)


def drain(level_reader: Callable[[], str | None] = read_level, start: Callable[[dict], None] | None = None) -> dict | None:
    """Start one queued item if pressure is normal (or unreadable): the oldest merge, else the oldest item while no
    merge runs. One item per call. Returns it, or None."""
    start = start or _start
    with _queue_lock():
        items = _entries()
        if not items:
            return None
        level = level_reader()
        if level in HIGH:
            return None
        merges = [(p, e) for p, e in items if is_merge(e.get("key"))]
        if merges:
            path, entry = merges[0]
        elif merge_pending():
            return None
        else:
            path, entry = items[0]
        path.unlink(missing_ok=True)
    try:
        start(entry)
        record("started", what=entry.get("what"), level=level, waited_since=entry.get("queued_at"))
    except Exception as exc:  # noqa: BLE001 -- a command that can't start is reported, not retried forever
        record("start-failed", what=entry.get("what"), error=f"{type(exc).__name__}: {str(exc)[:200]}")
        _tell(f"{entry.get('what')} could not start", str(exc)[:200])
    return entry


def forget(key: str) -> bool:
    """Drop the queued item with this key, if it is still waiting (marvin#940): a merge queued for memory that was
    approved again and started, or that another Mac is about to merge. False when it was not there (never queued, or
    already started): under the queue lock, so a drain and a forget never both have it."""
    with _queue_lock():
        for path, entry in _entries():
            if entry.get("key") == key:
                path.unlink(missing_ok=True)
                record("forgotten", what=entry.get("what"))
                return True
    return False


def kick() -> None:
    """After a guarded job ends: drain in the background, only when something is waiting (a directory listing)."""
    if QUEUE_DIR.is_dir() and any(QUEUE_DIR.glob("*.json")):
        _spawn_detached(_self_cmd("drain"))


# ── the macOS notification ──────────────────────────────────────────────────────────────────────────────────────

class PressureSource:
    """A libdispatch DISPATCH_SOURCE_TYPE_MEMORYPRESSURE source for normal, warn and critical, plus (given watch_dir) a
    DISPATCH_SOURCE_TYPE_VNODE source on the queue directory. macOS calls a handler on each change; events() blocks on
    those calls, with no timer of its own.

    Measured live on the Mac mini, 2026-10-30 (macOS 26): the kernel sent a small listener no pressure note at all,
    neither warn nor the return to normal, while `memory_pressure -l warn` held warn for 40 s (same from Swift and
    under launchd). XNU notifies the processes with the largest footprint first, so a bystander waits in vain. The
    queue therefore also starts on finished jobs (`kick`), and the directory source lets this watcher end once one of
    those has emptied the queue, rather than wait forever."""

    def __init__(self, watch_dir: Path | None = None) -> None:
        d = ctypes.CDLL("/usr/lib/system/libdispatch.dylib")
        d.dispatch_source_create.restype = ctypes.c_void_p
        d.dispatch_source_create.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
        d.dispatch_get_global_queue.restype = ctypes.c_void_p
        d.dispatch_get_global_queue.argtypes = [ctypes.c_long, ctypes.c_ulong]
        d.dispatch_source_get_data.restype = ctypes.c_ulong
        d.dispatch_source_get_data.argtypes = [ctypes.c_void_p]
        d.dispatch_source_set_event_handler_f.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        d.dispatch_resume.argtypes = [ctypes.c_void_p]
        d.dispatch_source_cancel.argtypes = [ctypes.c_void_p]
        self._d = d
        self._q: queue.Queue = queue.Queue()
        # DISPATCH_SOURCE_TYPE_MEMORYPRESSURE is the address of this exported symbol (<dispatch/source.h>).
        kind = ctypes.addressof(ctypes.c_char.in_dll(d, "_dispatch_source_type_memorypressure"))
        self._src = d.dispatch_source_create(kind, 0, 0x1 | 0x2 | 0x4, d.dispatch_get_global_queue(0, 0))
        self._cb = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(self._on_event)   # kept: the handler must outlive the source
        if self._src:
            d.dispatch_source_set_event_handler_f(self._src, ctypes.cast(self._cb, ctypes.c_void_p))
            d.dispatch_resume(self._src)
        self._dir_fd, self._dir_src = -1, None
        self._dir_cb = ctypes.CFUNCTYPE(None, ctypes.c_void_p)(lambda _ctx: self._q.put(QUEUE_CHANGED))
        if watch_dir is not None:
            try:
                Path(watch_dir).mkdir(parents=True, exist_ok=True)
                self._dir_fd = os.open(str(watch_dir), O_EVTONLY)
            except OSError:
                self._dir_fd = -1
            if self._dir_fd >= 0:
                vnode = ctypes.addressof(ctypes.c_char.in_dll(d, "_dispatch_source_type_vnode"))
                self._dir_src = d.dispatch_source_create(vnode, self._dir_fd, DISPATCH_VNODE_WRITE,
                                                         d.dispatch_get_global_queue(0, 0))
                if self._dir_src:
                    d.dispatch_source_set_event_handler_f(self._dir_src, ctypes.cast(self._dir_cb, ctypes.c_void_p))
                    d.dispatch_resume(self._dir_src)

    @property
    def armed(self) -> bool:
        return bool(self._src)

    def _on_event(self, _ctx) -> None:
        self._q.put(level_from_mask(self._d.dispatch_source_get_data(self._src)))

    def events(self) -> Iterator[str]:
        while True:
            level = self._q.get()   # blocks until macOS reports a change
            if level is not None:
                yield level

    def close(self) -> None:
        if self._src:
            self._d.dispatch_source_cancel(self._src)
        if self._dir_src:
            self._d.dispatch_source_cancel(self._dir_src)
        if self._dir_fd >= 0:
            os.close(self._dir_fd)
            self._dir_fd = -1


def _try_lock():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_PATH, "a")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except OSError:
        fh.close()
        return None


def watch(events: Iterable[str] | None = None, level_reader: Callable[[], str | None] = read_level) -> dict:
    """Wait on the notification while anything is queued; on each return to normal start one item. One watch at a
    time (a lock); a second exits at once. The source is armed before the level is first read, so a drop between the
    refusal and this start is not missed."""
    started: list[str] = []
    source = None
    first = True
    while True:
        lock = _try_lock()
        if lock is None:
            return {"already": first, "started": started}
        first = False
        ended = False
        try:
            if events is None:
                source = PressureSource(watch_dir=QUEUE_DIR)
                events = source.events()
            it = iter(events)
            record("watching", waiting=len(queued()))

            def step():
                e = drain(level_reader=level_reader)
                if e:
                    started.append(e.get("what"))
            step()
            while queued():
                level = next(it, None)
                if level is None:
                    ended = True
                    break
                if level == QUEUE_CHANGED:
                    continue   # another trigger started or added an item: look at the queue again
                record("pressure", level=level)
                if level == "normal":
                    step()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        # Something queued between the last look and the unlock would have found the lock held and left it to us.
        if ended or not queued():
            if source:
                source.close()
            return {"already": False, "started": started}


# ── status for Health / Vitals / the phone ──────────────────────────────────────────────────────────────────────

def status(level_reader: Callable[[], str | None] = read_level, swap_reader: Callable[[], int | None] = read_swap_used,
           now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    refused, started = [], 0
    try:
        lines = LOG_PATH.read_text(errors="replace").splitlines()[-500:]
    except OSError:
        lines = []
    for line in lines:
        try:
            e = json.loads(line)
            if datetime.fromisoformat(e["ts"]) < now - timedelta(hours=24):
                continue
        except (ValueError, KeyError, TypeError):
            continue
        if e.get("event") == "refused":
            refused.append(str(e.get("what", "?")))
        elif e.get("event") == "started":
            started += 1
    return {"level": level_reader(), "swap_used": swap_reader(), "waiting": [e.get("what") for e in queued()],
            "refused_24h": refused, "resumed_24h": started}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="memory_guard", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--what", required=True)
    c.add_argument("--key")
    c.add_argument("--cwd")
    c.add_argument("command", nargs=argparse.REMAINDER)
    for name in ("watch", "drain", "kick", "status"):
        sub.add_parser(name)
    f = sub.add_parser("forget")
    f.add_argument("--key", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        command = a.command[1:] if a.command[:1] == ["--"] else a.command
        r = guard(a.what, command or None, a.cwd or os.getcwd(), key=a.key)
        print(json.dumps({k: r[k] for k in ("ok", "level", "queued", "message")}))
        if not r["ok"]:
            print(r["message"], file=sys.stderr)
        return 0 if r["ok"] else REFUSED_RC
    if a.cmd == "watch":
        print(json.dumps(watch()))
    elif a.cmd == "drain":
        e = drain()
        print(json.dumps({"started": e.get("what") if e else None}))
    elif a.cmd == "kick":
        kick()
    elif a.cmd == "forget":
        print(json.dumps({"forgotten": forget(a.key)}))
    else:
        print(json.dumps(status()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
