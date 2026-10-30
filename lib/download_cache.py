#!/usr/bin/env python3
"""One capped cache for what helpers download: datasets, models, archives (marvin#765 item 4).

On 2026-10-29 a helper's `curl` wrote 8.6 GB in 9 minutes (the Hebrew data and model fetches), into wherever its
script pointed, and nothing ever removed it. Downloads now go in one known folder (CACHE_DIR, also handed to every
helper-tab helper as $MARVIN_DOWNLOAD_CACHE) with a size cap (config/disk_triggers.json `download_cache_cap_gb`).
Kept out of ~/Downloads (the tidy agent files it) and ~/Documents (iCloud, and blocked to launchd jobs).

The cap is enforced by use, never by a timer: after each fetch, when a helper-tab helper ends, and in the disk
pre-flight's reclaim. Over the cap, the least recently used entries go first, except:
  - a pinned entry: `pin(name, pid)` holds it while that process lives (a finished job's pin protects nothing, so a
    crash can't pin a file forever);
  - an entry written in the last IN_PROGRESS_GRACE_S (a download still running);
  - links are unlinked, never followed.

    download_cache.py path                    # print the folder
    download_cache.py fetch URL [--name N]    # curl into the cache, pinned while it runs, then enforce the cap
    download_cache.py pin NAME [--pid PID]    # keep NAME while PID (default: the caller's parent) runs
    download_cache.py unpin NAME [--pid PID]
    download_cache.py touch NAME              # mark NAME used now
    download_cache.py trim                    # enforce the cap now
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

CACHE_DIR = Path.home() / ".cache" / "marvin-downloads"
DEFAULT_CAP_BYTES = 10 * 2**30
IN_PROGRESS_GRACE_S = 600
PINS = ".pins"
USED = ".used"
PARTIAL_PREFIX = ".partial-"


def cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def cap_bytes() -> int:
    import disk_triggers
    gb = disk_triggers.load_config().get("download_cache_cap_gb")
    return int(gb * 2**30) if isinstance(gb, (int, float)) and not isinstance(gb, bool) and gb > 0 else DEFAULT_CAP_BYTES


def _check(name: str) -> str:
    if not name or name.startswith(".") or "/" in name or name in ("..",) or "\0" in name:
        raise ValueError(f"not a cache entry name: {name!r}")
    return name


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pin(name: str, pid: int) -> None:
    d = cache_dir() / PINS
    d.mkdir(exist_ok=True)
    (d / f"{_check(name)}@{int(pid)}").touch()


def unpin(name: str, pid: int) -> None:
    (cache_dir() / PINS / f"{_check(name)}@{int(pid)}").unlink(missing_ok=True)


def is_pinned(name: str) -> bool:
    """A pin counts while its process lives; a dead process's pin is removed as it is found."""
    d = cache_dir() / PINS
    held = False
    for p in d.glob(f"{_check(name)}@*") if d.is_dir() else []:
        pid = p.name.rsplit("@", 1)[1]
        if pid.isdigit() and _alive(int(pid)):
            held = True
        else:
            p.unlink(missing_ok=True)
    return held


def touch(name: str) -> None:
    d = cache_dir() / USED
    d.mkdir(exist_ok=True)
    (d / _check(name)).touch()


def _last_used(p: Path) -> float:
    st = p.lstat()
    used = cache_dir() / USED / p.name
    marks = [st.st_mtime]
    if used.exists():
        marks.append(used.stat().st_mtime)
    return max(marks)


def _newest_write(p: Path) -> float:
    """The latest mtime anywhere inside (a download in progress keeps touching its file), links not followed."""
    newest = p.lstat().st_mtime
    if p.is_dir() and not p.is_symlink():
        for root, dirs, files in os.walk(p):
            for f in files + dirs:
                try:
                    newest = max(newest, os.lstat(os.path.join(root, f)).st_mtime)
                except OSError:
                    pass
    return newest


def _size(p: Path) -> int:
    if p.is_symlink() or not p.is_dir():
        return p.lstat().st_size
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _remove(p: Path) -> None:
    if p.is_symlink() or not p.is_dir():
        p.unlink(missing_ok=True)
    else:
        shutil.rmtree(p, ignore_errors=True)
    (cache_dir() / USED / p.name).unlink(missing_ok=True)


def enforce_cap(cap_bytes: int | None = None, now: float | None = None) -> dict:
    """Least recently used first, until the cache fits. Returns {"removed": [{name, size}], "freed_bytes",
    "kept_pinned", "kept_recent", "total_after"}. Time O(n log n) in entries plus one walk of each; memory O(n)."""
    cap = cap_bytes if cap_bytes is not None else globals()["cap_bytes"]()
    now = now or time.time()
    root = cache_dir()
    entries = [(p, _size(p), _last_used(p)) for p in root.iterdir() if not p.name.startswith(".")]
    total = sum(s for _, s, _ in entries)
    removed, kept_pinned, kept_recent, freed = [], [], [], 0
    for p, size, _used in sorted(entries, key=lambda e: e[2]):
        if total <= cap:
            break
        if is_pinned(p.name):
            kept_pinned.append(p.name)
            continue
        if now - _newest_write(p) < IN_PROGRESS_GRACE_S:
            kept_recent.append(p.name)
            continue
        _remove(p)
        total -= size
        freed += size
        removed.append({"name": p.name, "size": size})
    if removed:
        import disk_triggers
        disk_triggers.record("download-cache", freed,
                             f"removed {len(removed)} least recently used download(s) to fit the {cap / 2**30:.0f} GB cap",
                             removed=[r["name"] for r in removed])
    return {"removed": removed, "freed_bytes": freed, "kept_pinned": kept_pinned, "kept_recent": kept_recent,
            "total_after": total}


def fetch(url: str, name: str | None = None, run=subprocess.run) -> Path:
    """Download url into the cache as `name` (default: the URL's last path part), pinned by this process while it
    runs, written under a hidden partial name and renamed only when curl succeeds. Then the cap is enforced."""
    name = _check(name or Path(urlparse(url).path).name)
    root = cache_dir()
    final, partial = root / name, root / f"{PARTIAL_PREFIX}{name}"
    me = os.getpid()
    pin(name, me)
    try:
        r = run(["curl", "-f", "-L", "--retry", "2", "-o", str(partial), url])
        if r.returncode != 0:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"curl exited {r.returncode} for {url}")
        os.replace(partial, final)
        touch(name)
    finally:
        unpin(name, me)
    enforce_cap()
    return final


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="download_cache.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("path")
    f = sub.add_parser("fetch")
    f.add_argument("url")
    f.add_argument("--name")
    for verb in ("pin", "unpin"):
        p = sub.add_parser(verb)
        p.add_argument("name")
        p.add_argument("--pid", type=int, default=os.getppid())
    t = sub.add_parser("touch")
    t.add_argument("name")
    sub.add_parser("trim")
    a = ap.parse_args(argv)
    if a.cmd == "path":
        print(cache_dir())
    elif a.cmd == "fetch":
        print(fetch(a.url, a.name))
    elif a.cmd == "pin":
        pin(a.name, a.pid)
    elif a.cmd == "unpin":
        unpin(a.name, a.pid)
    elif a.cmd == "touch":
        touch(a.name)
    elif a.cmd == "trim":
        print(json.dumps(enforce_cap()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
