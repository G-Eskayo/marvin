#!/usr/bin/env python3
"""One test run at a time on a machine, merges first (marvin#940).

On 2026-10-30 the Mac mini's memory filled with MARVIN's own test runs: the merge gate's pytest workers, an after-merge
full suite started once per merge (they piled up after a burst), helpers' runs, all at once on top of the owner's apps.
The merge machinery starved its own merges. This is the single queue they all go through:

  the merge gate     its pytest and vitest run through `test_slot.py run --merge` (merge.js)
  main-health        the after-merge full suite takes the slot before it starts (main_health.py)
  helpers            a whole-suite or parallel pytest takes it in the repo conftest, a whole vitest run in
                     vitest.config.js; one test file is small and never waits

Merges first: a merge marks itself on merges.lock (a shared flock) for as long as it waits or runs, from the Approve
to the end (`hold-merge`, held by the webhook). Any other run waits until no merge is marked, then takes the slot, and
if a merge marked itself meanwhile, it gives the slot back and waits again. A merge goes straight for the slot.
Everything waits by blocking on a flock: no polling, nothing to go stale (a lock dies with its process), the same on
macOS and Linux. Nothing running is ever stopped: a merge that arrives during a helper's run waits for it to end.

A run inside a held slot (the gate's pytest, whose conftest asks again) passes straight through: the holder sets
MARVIN_TEST_SLOT in the environment its children inherit.

Workers are sized to free memory, not cores: `workers` prints how many pytest-xdist / vitest workers fit in what is
free now, leaving a reserve, at least 1 and at most the core count.

    test_slot.py run [--merge] [--what W] -- command args...   # run it in the slot; exit code is the command's
    test_slot.py hold [--merge] [--what W]   # hold the slot until stdin closes (prints "held" once taken)
    test_slot.py hold-merge     # mark a merge until stdin closes (prints "held" once marked)
    test_slot.py workers        # how many test workers fit in free memory now
    test_slot.py status         # one JSON line: who holds the slot, whether a merge is marked
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pwd
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DIR_ENV = "MARVIN_TEST_SLOT_DIR"
HELD_ENV = "MARVIN_TEST_SLOT"
WORKER_MB_ENV = "MARVIN_TEST_WORKER_MB"
# Outside ~/.claude (tests never write there) and from the account's real home: the conftest moves HOME to a temp
# copy before the suite starts, and every run on the machine must find the same lock.
DEFAULT_DIR = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache" / "marvin" / "test-slot"
GB = 2**30
# One pytest-xdist worker on lib/tests peaks near 400 MB, a vitest worker about the same (estimate; override with
# MARVIN_TEST_WORKER_MB). The reserve is what a run leaves free for everything else on the machine.
PER_WORKER = 512 * 2**20
RESERVE = GB
UNKNOWN_WORKERS = 2


def slot_dir() -> Path:
    return Path(os.environ.get(DIR_ENV) or DEFAULT_DIR)


def _open(d: Path, name: str):
    d.mkdir(parents=True, exist_ok=True)
    return open(d / name, "a")


def merge_pending(d: Path | None = None) -> bool:
    """Is a merge waiting or running on this machine (anyone holding merges.lock)?"""
    with _open(d or slot_dir(), "merges.lock") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False


def _wait_no_merge(d: Path) -> None:
    """Block until no merge is marked. Taking and dropping the exclusive lock is the wait; a pending exclusive request
    does not stop a new merge marking itself (checked on macOS: shared locks are still granted)."""
    with _open(d, "merges.lock") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fcntl.flock(fh, fcntl.LOCK_UN)


def holder(d: Path | None = None) -> dict | None:
    try:
        return json.loads(((d or slot_dir()) / "holder.json").read_text())
    except (OSError, ValueError):
        return None


@contextmanager
def slot(what: str, merge: bool = False, d: Path | None = None, say=None) -> Iterator[bool]:
    """Hold this machine's test slot for the block. Yields True when taken here, False inside an already held slot.
    say(text) is told once when the run has to wait."""
    if os.environ.get(HELD_ENV):
        yield False
        return
    d = d or slot_dir()
    marked = _open(d, "merges.lock") if merge else None
    fh = _open(d, "slot.lock")
    try:
        if marked:
            fcntl.flock(marked, fcntl.LOCK_SH)
        told = False
        while True:
            try:
                if not merge and merge_pending(d):
                    raise BlockingIOError
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                if say and not told:
                    h = holder(d)
                    say(f"waiting for {'a merge' if not merge and merge_pending(d) else (h or {}).get('what', 'another test run')}"
                        " to finish (one test run at a time on this machine)")
                    told = True
                if merge:
                    fcntl.flock(fh, fcntl.LOCK_EX)
                else:
                    _wait_no_merge(d)
                    fcntl.flock(fh, fcntl.LOCK_EX)
            if merge or not merge_pending(d):
                break
            fcntl.flock(fh, fcntl.LOCK_UN)   # a merge marked itself while we waited: it goes first
        try:
            (d / "holder.json").write_text(json.dumps({"what": what, "pid": os.getpid(), "merge": merge,
                                                        "since": time.time()}))
        except OSError:
            pass
        os.environ[HELD_ENV] = what
        try:
            yield True
        finally:
            os.environ.pop(HELD_ENV, None)
            try:
                (d / "holder.json").unlink()
            except OSError:
                pass
    finally:
        fh.close()   # closing drops the flock
        if marked:
            marked.close()


# ── workers sized to free memory ─────────────────────────────────────────────────────────────────────────────────

def parse_vm_stat(out: str) -> int | None:
    """Bytes macOS can hand out now: free + inactive + speculative + purgeable pages."""
    m = re.search(r"page size of (\d+) bytes", out)
    if not m:
        return None
    page = int(m.group(1))
    pages = 0
    for name in ("free", "inactive", "speculative", "purgeable"):
        p = re.search(rf"^Pages {name}:\s+(\d+)\.", out, re.M)
        pages += int(p.group(1)) if p else 0
    return pages * page


def parse_meminfo(out: str) -> int | None:
    m = re.search(r"^MemAvailable:\s+(\d+) kB", out, re.M)
    return int(m.group(1)) * 1024 if m else None


def free_memory() -> int | None:
    try:
        if sys.platform == "darwin":
            return parse_vm_stat(subprocess.run(["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=10).stdout)
        return parse_meminfo(Path("/proc/meminfo").read_text())
    except (OSError, subprocess.SubprocessError):
        return None


def workers(free_bytes: int | None = -1, cores: int | None = None, per_worker: int | None = None,
            reserve: int = RESERVE) -> int:
    """How many test workers fit: (free - reserve) / per worker, at least 1, at most the cores. Unknown free memory
    gives a small safe number."""
    cores = cores or os.cpu_count() or 1
    if per_worker is None:
        try:
            per_worker = int(os.environ.get(WORKER_MB_ENV, "")) * 2**20
        except ValueError:
            per_worker = PER_WORKER
    free_bytes = free_memory() if free_bytes == -1 else free_bytes
    if free_bytes is None:
        return min(UNKNOWN_WORKERS, cores)
    return max(1, min(cores, int((free_bytes - reserve) // per_worker)))


# ── which runs take the slot ─────────────────────────────────────────────────────────────────────────────────────

def is_heavy(args: list[str], parallel: bool, cwd: Path | None = None) -> bool:
    """A parallel run, or a run of a whole directory (no args = the rootdir). One file or one test is small."""
    if parallel:
        return True
    paths = [a for a in args if not a.startswith("-")]
    if not paths:
        return True
    base = Path(cwd or os.getcwd())
    return any((base / p.split("::", 1)[0]).is_dir() for p in paths)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(prog="test_slot", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--merge", action="store_true")
    r.add_argument("--what", default=None)
    r.add_argument("command", nargs=argparse.REMAINDER)
    h = sub.add_parser("hold")
    h.add_argument("--merge", action="store_true")
    h.add_argument("--what", default="a test run")
    for name in ("hold-merge", "workers", "status"):
        sub.add_parser(name)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        command = a.command[1:] if a.command[:1] == ["--"] else a.command
        if not command:
            ap.error("run needs a command after --")
        what = a.what or " ".join(command)[:80]
        with slot(what, merge=a.merge, say=lambda t: print(f"test-slot: {what}: {t}", file=sys.stderr, flush=True)):
            return subprocess.run(command).returncode
    if a.cmd == "hold":
        # For a caller with no flock of its own (the webhook, vitest.config.js): held until it closes the pipe or dies.
        with slot(a.what, merge=a.merge, say=lambda t: print(f"test-slot: {a.what}: {t}", file=sys.stderr, flush=True)):
            print("held", flush=True)
            sys.stdin.read()
        return 0
    if a.cmd == "hold-merge":
        with _open(slot_dir(), "merges.lock") as fh:
            fcntl.flock(fh, fcntl.LOCK_SH)
            print("held", flush=True)
            sys.stdin.read()   # until the webhook closes the pipe or dies
        return 0
    if a.cmd == "workers":
        print(workers())
        return 0
    print(json.dumps({"holder": holder(), "merge_pending": merge_pending()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
