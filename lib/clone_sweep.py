#!/usr/bin/env python3
"""Orphan clone sweep: detects and removes stale Xcode sign-on clones (ADR TBD).

Xcode's signing workflow creates temporary shallow clones under Darwin user temp
dirs (via getconf DARWIN_USER_TEMP_DIR) with names like *.code_sign_clone.
These clones accumulate when the sign-on doesn't delete them (networking issues,
crashes, race conditions). This module lists, ages, and removes them.

Run directly for diagnostics (prints JSON summary); integrated into cleanup_sweep.py
(daily scheduled on both machines by config/launchd/com.marvin.cleanup-sweep.plist).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

MIN_AGE_HOURS = 1
CLONE_PARENT_GLOB = "*.code_sign_clone"
CLONE_ENTRY_GLOB = "code_sign_clone.*"


def _darwin_user_roots() -> set[Path]:
    """Temporary directories where Xcode creates sign-on clones.

    Uses `getconf DARWIN_USER_TEMP_DIR` and `DARWIN_USER_CACHE_DIR` per call
    with per-call exception isolation (one failure doesn't stop discovery).
    Returns a set so duplicate sources (if both point to the same place) are
    automatically deduplicated.
    """
    roots = set()
    for var in ["DARWIN_USER_TEMP_DIR", "DARWIN_USER_CACHE_DIR"]:
        try:
            result = subprocess.run(
                ["getconf", var],
                capture_output=True, text=True, timeout=5, check=True,
            )
            path_str = result.stdout.strip()
            if path_str:
                roots.add(Path(path_str))
        except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
            pass
    return roots


def _looks_like_clone(path: Path) -> bool:
    """Heuristic: reject symlinks first, then check parent-suffix + entry-prefix."""
    if path.is_symlink():
        return False
    parent_name = path.parent.name
    entry_name = path.name
    return parent_name.endswith(".code_sign_clone") and entry_name.startswith("code_sign_clone.")


def _default_list_clones(
    min_age_hours: float = MIN_AGE_HOURS,
    list_clones: Callable[[], list[dict]] | None = None,
) -> list[dict]:
    """Find all orphan clones under Darwin user roots.

    Returns a list of dicts with 'path' and 'age_hours'. Iterates roots and globs
    two levels deep (root -> parent -> entry), with per-root and per-entry exception
    isolation so one bad path never stops discovery.
    """
    import time

    now = time.time()
    clones = []

    for root in _darwin_user_roots():
        try:
            for parent in root.glob(CLONE_PARENT_GLOB):
                try:
                    for entry in parent.glob(CLONE_ENTRY_GLOB):
                        if _looks_like_clone(entry):
                            age_hours = (now - entry.stat().st_mtime) / 3600
                            if age_hours >= min_age_hours:
                                clones.append({"path": entry, "age_hours": age_hours})
                except (OSError, ValueError):
                    pass
        except (OSError, ValueError):
            pass

    return clones


def _default_is_open(path: Path, timeout_sec: float = 5) -> bool | None:
    """Check if a path is open by any process.

    Uses system-wide `lsof -n -P +c 0 -F cn` (no path argument), parses output,
    and checks for a prefix match against str(path) + "/". Returns True/False/None
    (None on OSError/TimeoutExpired to distinguish transient failures from a closed path).
    Same pattern as relocate_project.open_by() but returning bool/None instead of list.
    """
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-n", "-P", "+c", "0", "-F", "cn"],
            capture_output=True, text=True, timeout=timeout_sec,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    resolved = path.resolve()
    prefix = str(resolved) + "/"
    for line in result.stdout.splitlines():
        if line.startswith("n") and (line[1:] == str(resolved) or line[1:].startswith(prefix)):
            return True
    return False


def find_orphan_clones(
    min_age_hours: float = MIN_AGE_HOURS,
    is_open: Callable[[Path], bool | None] | None = None,
) -> list[dict]:
    """Find clones that are old and not currently open.

    Applies age filter and fail-closed is_open check (assume open on None).
    Performs an immediate re-check before returning to catch races.
    Per-entry exception isolation.
    """
    is_open = is_open or _default_is_open

    candidates = _default_list_clones(min_age_hours)
    orphans = []

    for entry in candidates:
        try:
            open_state = is_open(entry["path"])
            # Fail-closed: only False means definitely closed; True or None skips removal
            if open_state is not False:
                continue
            # Re-check immediately before declaring it safe to remove
            recheck = is_open(entry["path"])
            if recheck is not False:
                continue
            orphans.append(entry)
        except Exception:
            pass

    return orphans


def sweep_clones(
    min_age_hours: float = MIN_AGE_HOURS,
    is_open: Callable[[Path], bool | None] | None = None,
    find_clones: Callable[..., list[dict]] | None = None,
) -> list[dict]:
    """Remove orphan clones and return what was removed.

    Uses shutil.rmtree/unlink for removal. Reuses disk_trim._get_size_kb() for
    size accounting (no duplicate size logic). PermissionError logged as error
    and marked as failed; FileNotFoundError silent success. Per-entry exception
    isolation. Returns list of removed entries with size_kb.
    """
    find_clones = find_clones or (lambda: find_orphan_clones(min_age_hours, is_open))
    removed = []

    try:
        from disk_trim import _get_size_kb
    except ImportError:
        def _get_size_kb(path: Path) -> int:
            return 0

    for entry in find_clones():
        path = entry["path"]
        try:
            size_kb = _get_size_kb(path)
            if path.is_symlink():
                path.unlink()
            else:
                shutil.rmtree(path)
            removed.append({**entry, "size_kb": size_kb})
        except PermissionError as exc:
            print(f"[clone-sweep] failed to remove {path}: {exc}", file=sys.stderr)
        except FileNotFoundError:
            pass
        except Exception as exc:
            print(f"[clone-sweep] unexpected error removing {path}: {exc}", file=sys.stderr)

    return removed


if __name__ == "__main__":
    result = {
        "clones_found": _default_list_clones(),
        "clones_removed": sweep_clones(),
    }
    print(json.dumps(result, default=lambda x: str(x)))
