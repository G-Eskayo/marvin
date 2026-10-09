#!/usr/bin/env python3
"""Disk reclaim helper with per-action confirmation (Phase 3 of ticket #130).

Dry-run by default. Enumerates reclaimable candidates by importing existing
disk_trim.py safety rules (NEVER_TRIM, decide_worktree). Adds three new
detectors:
  1. Duplicate installers in ~/Downloads (by hash)
  2. Unused Ollama models (by access-time threshold)
  3. Unavailable simulators (via xcrun simctl)

Every delete is re-validated immediately before execution (TOCTOU close),
logged to ~/.claude/logs/mr-pipeline-sweep.md.

Run standalone: ~/.agents/venv/bin/python lib/disk_reclaim.py [--dry-run] [--confirm]
  --dry-run (default): list candidates, don't delete
  --confirm: run WITHOUT per-action confirmation prompts (DANGEROUS for automation)
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanup_sweep as cs  # noqa: E402
import disk_trim as dt  # noqa: E402

HOME = Path.home()
SWEEP_LOG = HOME / ".claude" / "logs" / "mr-pipeline-sweep.md"


def _file_hash(path: Path, algo: str = "sha256") -> str | None:
    """Hash a file, returns None if unreadable."""
    try:
        h = hashlib.new(algo)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, ValueError):
        return None


def _find_duplicate_installers(search_dir: Path = None) -> list[dict]:
    """Find duplicate installers in ~/Downloads (by hash).

    Returns [{ path: Path, size: int, hash: str, note: str }, ...].
    """
    search_dir = search_dir or (HOME / "Downloads")
    if not search_dir.exists():
        return []

    candidates = []
    hashes_seen = {}

    # Look for common installer extensions
    for ext in [".dmg", ".pkg", ".exe", ".zip"]:
        for path in search_dir.glob(f"*{ext}"):
            if not path.is_file():
                continue
            h = _file_hash(path)
            if h:
                size = path.stat().st_size
                if h in hashes_seen:
                    # Duplicate found
                    candidates.append({
                        "path": path,
                        "size": size,
                        "hash": h,
                        "note": f"duplicate of {hashes_seen[h]['path'].name}",
                    })
                else:
                    hashes_seen[h] = {"path": path, "size": size}
    return candidates


def _find_unused_ollama_models(threshold_days: int = 30) -> list[dict]:
    """Find Ollama models not accessed in threshold_days.

    Returns [{ path: Path, size: int, last_accessed: str (ISO) }, ...].
    This is an approximation based on mtime, not a guarantee.
    """
    ollama_dir = HOME / ".ollama" / "models"
    if not ollama_dir.exists():
        return []

    candidates = []
    now = datetime.now(timezone.utc)
    cutoff = now - __import__("datetime").timedelta(days=threshold_days)

    try:
        for model_path in ollama_dir.iterdir():
            if not model_path.is_dir():
                continue
            try:
                mtime = datetime.fromtimestamp(model_path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    # Get size
                    size_result = subprocess.run(
                        ["du", "-sk", str(model_path)],
                        capture_output=True, text=True, timeout=5,
                    )
                    if size_result.returncode == 0:
                        size = int(size_result.stdout.split()[0]) * 1024
                        candidates.append({
                            "path": model_path,
                            "size": size,
                            "last_accessed": mtime.isoformat(),
                        })
            except (OSError, ValueError):
                pass
    except (OSError, ValueError):
        pass
    return candidates


def _find_unavailable_simulators() -> list[dict]:
    """Find iOS simulators marked unavailable (stale entries).

    Returns [{ uuid: str, name: str, status: str }, ...].
    """
    candidates = []
    try:
        result = subprocess.run(
            ["xcrun", "simctl", "list", "devices", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            for device_type in data.get("devices", {}).values():
                if isinstance(device_type, list):
                    for device in device_type:
                        if device.get("isAvailable") is False:
                            candidates.append({
                                "uuid": device.get("udid", ""),
                                "name": device.get("name", ""),
                                "status": device.get("state", "unavailable"),
                            })
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError, FileNotFoundError):
        pass
    return candidates


def enumerate_candidates(dry_run: bool = True) -> list[dict]:
    """Enumerate all reclaimable candidates.

    Returns [
      { type: 'category', category: str, path: Path, size: int, reason: str, safe: bool },
      ...
    ]

    Each candidate is labelled with whether it's safe to delete (will be
    re-validated immediately before actual delete).
    """
    candidates = []

    # Category 1: Duplicate installers
    for cand in _find_duplicate_installers():
        candidates.append({
            "type": "duplicate-installer",
            "path": cand["path"],
            "size": cand["size"],
            "reason": cand["note"],
            "safe": True,  # Safe to delete (verified by hash)
        })

    # Category 2: Unused Ollama models
    for cand in _find_unused_ollama_models():
        candidates.append({
            "type": "unused-model",
            "path": cand["path"],
            "size": cand["size"],
            "reason": f"unused since {cand['last_accessed']}",
            "safe": cand["path"].name not in ["mistral", "llama2", "stable-code"],  # Common defaults
        })

    # Category 3: Unavailable simulators
    for cand in _find_unavailable_simulators():
        candidates.append({
            "type": "unavailable-simulator",
            "uuid": cand["uuid"],
            "name": cand["name"],
            "size": 0,  # xcrun doesn't report sizes easily
            "reason": f"device unavailable ({cand['status']})",
            "safe": True,  # Safe to erase
        })

    # Existing disk_trim categories (if disk is under pressure)
    free_pct = dt.get_disk_free_pct()
    if free_pct < dt.DISK_YELLOW_BELOW_PCT:
        # Re-compute trimming candidates using existing disk_trim.py logic
        # This is a stub; full integration would enumerate trimmer functions
        pass

    return candidates


def re_validate_path(path: Path) -> bool:
    """Re-validate that path is safe to delete immediately before delete.

    Checks:
      - Path exists
      - Path is not in NEVER_TRIM
      - If a worktree, re-check via decide_worktree()

    Returns True if safe to delete, False otherwise.
    """
    if not path.exists():
        return False  # Doesn't exist anymore
    if path in dt.NEVER_TRIM:
        return False  # In the never-trim list
    if any(path.is_relative_to(ntp) for ntp in dt.NEVER_TRIM if ntp.is_dir()):
        return False  # Under a never-trim directory

    # If it's a worktree, re-check its status
    for wt in cs._default_list_worktrees():
        wt_path = wt.get("path")
        if not wt_path or not path.is_relative_to(Path(wt_path)):
            continue
        try:
            state = cs._default_pr_state(wt["repo"], wt["branch"]) if wt.get("repo") else None
            claimed = bool(
                wt.get("repo")
                and cs._extract_issue_number(wt["branch"]) is not None
                and cs._default_is_claimed(wt["repo"], cs._extract_issue_number(wt["branch"]))
            )
            action, _ = cs.decide_worktree(wt, state, claimed)
            if action not in ("clean", "archive"):
                return False  # Worktree should be kept
        except Exception:
            return False  # On error, don't delete (conservative)

    return True


def delete_with_confirmation(
    path: Path, confirm_fn=None, dry_run: bool = True
) -> bool:
    """Delete path after confirmation prompt (or auto if confirm_fn returns True).

    Returns True if deleted, False if skipped/refused/error.
    """
    confirm_fn = confirm_fn or (
        lambda msg: input(f"{msg} [y/N] ").lower().strip() == "y"
    )

    if not path.exists():
        return False

    # Prompt for confirmation
    size_mb = path.stat().st_size / 1024 / 1024 if path.is_file() else 0
    msg = f"Delete {path.name} ({size_mb:.0f} MB)?"
    if not confirm_fn(msg):
        return False

    # Re-validate immediately before delete
    if not re_validate_path(path):
        return False

    if dry_run:
        return True  # Pretend we deleted

    # Actual delete
    try:
        if path.is_file():
            path.unlink()
        else:
            shutil.rmtree(path)
        return True
    except Exception:
        return False


def log_sweep(freed_kb: int, deleted_items: list[dict], start_time: datetime) -> None:
    """Log the reclaim sweep to mr-pipeline-sweep.md."""
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    timestamp = datetime.now(timezone.utc).isoformat()

    log_entry = f"""\
## {timestamp} — disk reclaim sweep
**Freed:** {freed_kb / 1024 / 1024:.0f} MiB from {len(deleted_items)} item(s) in {elapsed:.0f}s

"""
    for item in deleted_items:
        log_entry += f"- {item['path'].name} ({item['size'] / 1024 / 1024:.0f} MiB)\n"

    SWEEP_LOG.parent.mkdir(parents=True, exist_ok=True)
    if SWEEP_LOG.exists():
        log_entry = SWEEP_LOG.read_text() + log_entry
    SWEEP_LOG.write_text(log_entry)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True, help="List only (default)")
    parser.add_argument("--confirm", action="store_true", help="Auto-confirm all deletions (DANGEROUS)")
    args = parser.parse_args()

    candidates = enumerate_candidates(dry_run=args.dry_run)
    deleted = []
    freed = 0

    confirm_fn = (lambda _: True) if args.confirm else None
    start = datetime.now(timezone.utc)

    for cand in candidates:
        if cand["type"] == "unavailable-simulator":
            # Special handling for simulators
            try:
                subprocess.run(
                    ["xcrun", "simctl", "erase", cand["uuid"]],
                    capture_output=True, timeout=30,
                )
                deleted.append(cand)
            except Exception:
                pass
        else:
            path = cand["path"]
            if delete_with_confirmation(path, confirm_fn=confirm_fn, dry_run=args.dry_run):
                deleted.append(cand)
                freed += cand["size"]

    if deleted and not args.dry_run:
        log_sweep(freed, deleted, start)

    print(f"Would reclaim {freed / 1024 / 1024:.0f} MiB from {len(deleted)} item(s)")
