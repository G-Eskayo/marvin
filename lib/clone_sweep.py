#!/usr/bin/env python3
"""Orphaned Xcode code_sign_clone cleanup (G-Eskayo/marvin#415).

Finds and removes orphaned Xcode code_sign_clone build artifacts under
DARWIN_USER_TEMP_DIR and DARWIN_USER_CACHE_DIR that are both old (MIN_AGE_HOURS)
and orphaned (no processes open their files).

code_sign_clone artifacts are created during Xcode builds as temporary signing
caches. Parent directories have the format *.code_sign_clone, with entries
code_sign_clone.* inside them. These accumulate and consume disk space when
builds are interrupted or fail.

Found 2026-10-06: worktrees were removed but clones accumulated (39 GiB on
mac-mini, 94% full); distinct from this is the code_sign_clone pattern (same
root cause: artifacts left from interrupted builds).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from disk_trim import _get_size_kb  # noqa: E402

HOME = Path.home()
MIN_AGE_HOURS = 1
CLONE_PARENT_GLOB = "*.code_sign_clone"
CLONE_ENTRY_GLOB = "code_sign_clone.*"


def _darwin_user_roots() -> set[Path]:
    """Get Darwin user-local temp and cache roots via getconf, so is_open()
    can check for actual file opens without false positives from Spotlight/iCloud
    traversal of system-wide directories."""
    roots = set()
    for key in ("DARWIN_USER_TEMP_DIR", "DARWIN_USER_CACHE_DIR"):
        try:
            result = subprocess.run(
                ["getconf", key],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                roots.add(Path(result.stdout.strip()))
        except Exception:
            pass
    return roots


def _looks_like_clone(path: Path) -> bool:
    """Check if path is a code_sign_clone artifact. Explicit symlink rejection first
    (symlinked dirs are still-open references), then parent/entry pattern check."""
    if path.is_symlink():
        return False
    parent_name = path.parent.name
    entry_name = path.name
    # Parent directory must end with .code_sign_clone, entry must start with code_sign_clone.
    return parent_name.endswith(".code_sign_clone") and entry_name.startswith("code_sign_clone.")


def _default_list_clones() -> list[dict]:
    """List all code_sign_clone entries under DARWIN_USER_TEMP_DIR and DARWIN_USER_CACHE_DIR.
    Two-level glob (*.code_sign_clone/code_sign_clone.*) in each root, stat() guarded
    against FileNotFoundError, per-root and per-entry exception isolation.
    Returns list of dicts with path and age_hours."""
    clones = []
    now = time.time()

    for root in _darwin_user_roots():
        try:
            # Glob parent directories matching *.code_sign_clone
            for parent in sorted(root.glob(CLONE_PARENT_GLOB)):
                try:
                    if not parent.is_dir():
                        continue
                    # Glob entries matching code_sign_clone.* within each parent
                    for entry in sorted(parent.glob(CLONE_ENTRY_GLOB)):
                        try:
                            if not entry.is_dir():
                                continue
                            age_hours = (now - entry.stat().st_mtime) / 3600
                            clones.append({
                                "path": entry,
                                "age_hours": age_hours,
                            })
                        except FileNotFoundError:
                            pass  # entry was removed concurrently
                except FileNotFoundError:
                    pass  # parent was removed concurrently
        except FileNotFoundError:
            pass  # root was removed concurrently

    return clones


def _default_is_open(path: Path) -> bool | None:
    """Check if any process has files open under this path via /usr/sbin/lsof.
    One-shot call with prefix matching on path string.
    Returns True if open, False if closed, None if lsof failed (be conservative)."""
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-n", "-P", "+c", "0", "-F", "n", str(path)],
            capture_output=True, text=True, timeout=5,
        )
        # lsof returns 0 if any processes hold the path open, non-zero if none do.
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        # lsof failed; be conservative and assume it's open
        return None


def find_orphan_clones(
    min_age_hours: float = MIN_AGE_HOURS,
    list_clones: Callable[[], list[dict]] | None = None,
    is_open: Callable[[Path], bool | None] | None = None,
) -> list[dict]:
    """Find clones that are old enough and not open by any process.
    Age filter, shape guard, fail-closed is_open + immediate re-check,
    per-entry exception isolation so one bad entry never aborts the batch.
    Returns list of dicts with path and reason."""
    list_clones = list_clones or _default_list_clones
    is_open = is_open or _default_is_open

    orphans = []
    for clone in list_clones():
        if clone["age_hours"] < min_age_hours:
            continue
        if not _looks_like_clone(clone["path"]):
            continue

        try:
            open_state = is_open(clone["path"])
            if open_state is None:
                continue  # lsof failed; be fail-closed

            if open_state:
                continue  # still open

            # Re-check immediately to guard against a race where a process opened it
            # between the first check and now.
            open_state_recheck = is_open(clone["path"])
            if open_state_recheck is None or open_state_recheck:
                continue

            orphans.append({
                "path": clone["path"],
                "age_hours": clone["age_hours"],
            })
        except Exception:
            # Per-entry exception isolation: one bad clone never aborts the batch.
            pass

    return orphans


def sweep_clones(
    list_clones: Callable[[], list[dict]] | None = None,
    is_open: Callable[[Path], bool | None] | None = None,
    min_age_hours: float = MIN_AGE_HOURS,
) -> list[dict]:
    """Remove orphan clones. Per-entry exception isolation.
    Returns list of dicts with path, size_kb, and age_hours for successful removals,
    or path, error, and age_hours for failures."""
    orphans = find_orphan_clones(min_age_hours, list_clones, is_open)
    removed = []

    for orphan in orphans:
        path = orphan["path"]
        try:
            size_kb = _get_size_kb(path)
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append({
                "path": path,
                "size_kb": size_kb,
                "age_hours": orphan["age_hours"],
            })
        except (PermissionError, FileNotFoundError) as e:
            # FileNotFoundError: concurrent removal (nothing to report).
            # PermissionError: log it for review, but keep processing.
            if not isinstance(e, FileNotFoundError):
                removed.append({
                    "path": path,
                    "error": str(e),
                    "age_hours": orphan["age_hours"],
                })
        except Exception as e:
            # Any other exception (OSError, etc.) is logged for review.
            removed.append({
                "path": path,
                "error": str(e),
                "age_hours": orphan["age_hours"],
            })

    return removed


if __name__ == "__main__":
    result = sweep_clones()
    print(json.dumps(
        [{"path": str(r["path"]), **{k: v for k, v in r.items() if k != "path"}} for r in result],
        indent=2
    ))
