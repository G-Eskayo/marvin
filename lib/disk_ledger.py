#!/usr/bin/env python3
"""Append-only disk-usage ledger for headroom forecasting (ADR 0056).

Tracks disk categories daily per machine: rebuildable caches, build output,
worktrees, models, iCloud cache, docker, user files, and other. Ledger lives
in ~/.claude/logs/disk-ledger.jsonl and is read by health_checks.py to
compute disk:headroom forecasts. Scheduled as part of the daily
cleanup-sweep job (lib/cleanup_sweep.py).

Every entry is one JSON line, keyed by machine ID and ISO date, so same-day
reruns overwrite (idempotent) but different days append.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402
from sandbox_orchestration import WORKTREES_ROOT  # noqa: E402

HOME = Path.home()
LEDGER_PATH = HOME / ".claude" / "logs" / "disk-ledger.jsonl"


def _default_du_kb(path: Path) -> int:
    """Get KB used by a path via du -sk, returns 0 if path doesn't exist."""
    try:
        result = subprocess.run(
            ["du", "-sk", str(path)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split()
            if parts and parts[0].isdigit():
                return int(parts[0])
    except Exception:
        pass
    return 0


def measure_categories(du: callable = None) -> dict[str, int]:
    r"""Measure disk usage by category (all in KB).

    - rebuildable_caches: npm, pnpm, pip, brew, Electron, SwiftPM caches
    - build_output: .build, .swiftpm, node_modules (not from worktrees)
    - worktrees: all pipeline worktrees under WORKTREES_ROOT
    - models: .ollama, .cache/huggingface, other ML model stores
    - icloud_cache: ~/Library/Mobile\ Documents (synced iCloud data)
    - docker: from `docker system df --format '{{json .}}'`
    - user_files: Documents, Desktop, Pictures, Downloads, Messages
    - other: everything else

    If du callable is provided, use it instead of subprocess (for testing).
    """
    du = du or _default_du_kb

    result = {
        "rebuildable_caches": 0,
        "build_output": 0,
        "worktrees": 0,
        "models": 0,
        "icloud_cache": 0,
        "docker": 0,
        "user_files": 0,
        "other": 0,
    }

    # Rebuildable caches
    result["rebuildable_caches"] += du(HOME / ".npm" / "_cacache")
    result["rebuildable_caches"] += du(HOME / ".pnpm-store")
    result["rebuildable_caches"] += du(HOME / ".cache" / "pip")
    result["rebuildable_caches"] += du(HOME / "Library" / "Caches" / "Homebrew")
    result["rebuildable_caches"] += du(HOME / "Library" / "Caches" / "Electron")
    result["rebuildable_caches"] += du(HOME / "Library" / "Caches" / "SwiftPM")

    # Worktrees
    if WORKTREES_ROOT.exists():
        result["worktrees"] = du(WORKTREES_ROOT)

    # Models
    result["models"] += du(HOME / ".ollama")
    result["models"] += du(HOME / ".cache" / "huggingface")

    # iCloud cache
    result["icloud_cache"] = du(HOME / "Library" / "Mobile Documents")

    # Docker
    try:
        proc = subprocess.run(
            ["docker", "system", "df", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            # Sum docker volumes, containers, images
            if isinstance(data, dict):
                for section in ["Volumes", "Containers", "Images"]:
                    if section in data:
                        for item in data[section]:
                            if "Size" in item:
                                size_str = item["Size"].split()[0]
                                try:
                                    result["docker"] += int(size_str)
                                except ValueError:
                                    pass
    except Exception:
        pass

    # User files
    for user_dir in ["Documents", "Desktop", "Pictures", "Downloads", "Messages"]:
        result["user_files"] += du(HOME / user_dir)

    return result


def append_entry(
    categories: dict[str, int],
    free_kb: int,
    total_kb: int,
    device: str | None = None,
    now: datetime | None = None,
    path: Path = LEDGER_PATH,
) -> None:
    """Append one entry to the ledger (JSONL format).

    Same-device-per-day entries overwrite (idempotent), but different days
    append, creating an append-only ledger. Keyed by registry_id() and ISO
    date so reruns on the same day replace.
    """
    device = device or machine_profile.registry_id()
    now = now or datetime.now(timezone.utc)
    iso_date = now.date().isoformat()

    entry = {
        "device": device,
        "date": iso_date,
        "timestamp": now.isoformat(),
        "free_kb": free_kb,
        "total_kb": total_kb,
        "categories": categories,
    }

    path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing entries, filter out today's entry for this device, append new one
    existing = []
    if path.exists():
        for line in path.read_text().strip().split("\n"):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not (row.get("device") == device and row.get("date") == iso_date):
                    existing.append(row)
            except json.JSONDecodeError:
                pass

    existing.append(entry)

    lines = [json.dumps(e) for e in existing]
    path.write_text("\n".join(lines) + "\n" if lines else "")


def run_daily_ledger() -> dict:
    """Cron entry point: measure all categories, append to ledger, return summary.

    Called from cleanup_sweep.run_daily_sweep() with both other sweeps, so
    the whole daily job logs together.
    """
    categories = measure_categories()

    # Get total and free disk space
    import os
    stat = os.statvfs(HOME)
    total_kb = (stat.f_blocks * stat.f_frsize) // 1024
    free_kb = (stat.f_bavail * stat.f_frsize) // 1024

    now = datetime.now(timezone.utc)
    append_entry(categories, free_kb, total_kb, device=None, now=now, path=LEDGER_PATH)

    return {
        "timestamp": now.isoformat(),
        "device": machine_profile.registry_id(),
        "free_kb": free_kb,
        "total_kb": total_kb,
        "categories": categories,
    }


if __name__ == "__main__":
    import json as json_
    summary = run_daily_ledger()
    print(json_.dumps(summary, indent=2))
