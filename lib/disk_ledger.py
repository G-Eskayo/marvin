#!/usr/bin/env python3
"""Append-only disk-usage ledger for headroom forecasting (ADR 0056).

Tracks disk categories daily per machine: rebuildable caches, build output,
worktrees, models, iCloud cache, docker, user files, and other. Ledger lives
in ~/.claude/logs/disk-ledger.jsonl and is read by health_checks.py to
compute disk:headroom forecasts. Scheduled as part of the daily
cleanup-sweep job (lib/cleanup_sweep.py).

Every entry is one JSON line, keyed by machine ID and ISO date, so same-day
reruns overwrite (idempotent) but different days append.

Bounded size walks (#586 "Cleanup sweep leaves du processes hung on protected folders (TCC); add timeouts and
single-flight"): under launchd, macOS privacy (TCC) can make a read of ~/Documents, ~/Library/Containers or an iCloud
folder block forever instead of failing. Each du is therefore:
- probed first: a quick top-level listing (PROBE_TIMEOUT_S) decides whether this process may read the folder at all;
  one it may not is reported "not measured (protected)" and never walked;
- time-limited inside du itself: the child arms alarm() before exec, so the kernel ends it after DU_TIMEOUT_S even
  when the Python that started it is killed first (how ~9 du orphans sat under launchd for up to 15 h);
- run at nice +10.
A run is single flight: a non-blocking flock beside the ledger (the main-health pattern from #457), so a slow run
never has the next one queue behind it; the lock dies with its process and can't go stale.
Cost: O(1) extra processes per folder (probe + du), at most len(folders) x (PROBE_TIMEOUT_S + DU_TIMEOUT_S) wall time
in the worst case; memory O(top-level entries of one folder) for the probe output.
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402
from sandbox_orchestration import WORKTREES_ROOT  # noqa: E402

HOME = Path.home()
LEDGER_PATH = HOME / ".claude" / "logs" / "disk-ledger.jsonl"


DU_CMD = ["du", "-sk"]
DU_TIMEOUT_S = 600  # the sweep runs at night: minutes for a 50 GB folder, but never hours
PROBE_CMD = ["/bin/ls", "-f"]
PROBE_TIMEOUT_S = 10
NOT_MEASURED_PROTECTED = "not measured (protected)"
NOT_MEASURED_TIMED_OUT = "not measured (timed out)"
NOT_MEASURED_FAILED = "not measured (du failed)"


def _bounded(argv: list[str], timeout: int) -> tuple[int, str, str] | None:
    """Run argv at low priority with a hard time limit that lives in the child, so it holds even if this process
    dies. Returns (returncode, stdout, stderr), or None when it timed out or could not start."""
    def limit():  # runs in the child between fork and exec; alarm() survives exec and SIGALRM's default kills
        os.nice(10)
        signal.alarm(timeout)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, errors="replace", preexec_fn=limit, start_new_session=True)
    except OSError:
        return None
    try:
        out, err = proc.communicate(timeout=timeout + 5)
    except subprocess.TimeoutExpired:  # belt and braces: the alarm should already have ended it
        proc.kill()
        proc.communicate()
        return None
    if proc.returncode == -signal.SIGALRM:
        return None
    return proc.returncode, out, err


def du_kb(path: Path, timeout: int | None = None) -> int | str:
    """KB used by path, 0 if it doesn't exist, or a "not measured (...)" reason. Never blocks past its limits."""
    path = Path(path)
    if not path.exists():
        return 0
    probe = _bounded([*PROBE_CMD, str(path)], PROBE_TIMEOUT_S)
    if probe is None or (probe[0] != 0 and "not permitted" in probe[2].lower()):
        return NOT_MEASURED_PROTECTED
    res = _bounded([*DU_CMD, str(path)], timeout or DU_TIMEOUT_S)
    if res is None:
        print(f"[disk_ledger] du gave up on {path} ({NOT_MEASURED_TIMED_OUT})", file=sys.stderr)
        return NOT_MEASURED_TIMED_OUT
    lines = res[1].strip().splitlines()
    parts = lines[-1].split() if lines else []
    return int(parts[0]) if parts and parts[0].isdigit() else 0


def _default_du_kb(path: Path) -> int | str:
    """du exits 1 when any subfolder is unreadable but still prints the total, so the total is kept whatever the exit
    code; and a 5 s timeout read big folders as 0. Both hid ~/Library/Developer (33 GB) as 0 (2026-10-14)."""
    return du_kb(path)


def measure_categories(du: callable = None, not_measured: list | None = None) -> dict[str, int]:
    r"""Measure disk usage by category (all in KB).

    - rebuildable_caches: npm, pnpm, pip caches and all of ~/Library/Caches
    - build_output: .build, .swiftpm, node_modules (not from worktrees)
    - worktrees: all pipeline worktrees under WORKTREES_ROOT
    - models: .ollama, .cache/huggingface, other ML model stores
    - icloud_cache: ~/Library/Mobile\ Documents (synced iCloud data)
    - docker: from `docker system df --format '{{json .}}'`
    - user_files: Documents, Desktop, Pictures, Downloads, ~/Library/Messages, ~/Library/Photos
    - xcode: ~/Library/Developer (simulators, DerivedData, device support; builder simulators leak here)
    - app_support: ~/Library/Application Support, Containers, Group Containers (app data, VM bundles, wallpapers)
    - other: everything else, filled in by with_other() once the disk's used space is known

    If du callable is provided, use it instead of subprocess (for testing). A folder du could not measure (a
    "not measured (...)" string) adds nothing and is appended to not_measured as {"path", "reason"}.
    """
    walk = du or _default_du_kb
    skipped = not_measured if not_measured is not None else []

    def du(path):
        kb = walk(path)
        if isinstance(kb, int):
            return kb
        skipped.append({"path": str(path), "reason": str(kb or NOT_MEASURED_FAILED)})
        return 0

    result = {
        "rebuildable_caches": 0,
        "build_output": 0,
        "worktrees": 0,
        "models": 0,
        "icloud_cache": 0,
        "docker": 0,
        "user_files": 0,
        "xcode": 0,
        "app_support": 0,
        "other": 0,
    }

    # Rebuildable caches
    result["rebuildable_caches"] += du(HOME / ".npm" / "_cacache")
    result["rebuildable_caches"] += du(HOME / ".pnpm-store")
    result["rebuildable_caches"] += du(HOME / ".cache" / "pip")
    result["rebuildable_caches"] += du(HOME / "Library" / "Caches")  # Homebrew, Electron, SwiftPM and every app's cache

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
    # Messages and Photos live under ~/Library: a "~/Messages" entry here missed 53 GB on the laptop (2026-10-14)
    for user_dir in ["Documents", "Desktop", "Pictures", "Downloads", "Library/Messages", "Library/Photos"]:
        result["user_files"] += du(HOME / user_dir)

    # Found 2026-10-14: 18 GB of simulators, wallpapers and app data grew on the mini with no category to show it
    result["xcode"] = du(HOME / "Library" / "Developer")
    for app_dir in ["Application Support", "Containers", "Group Containers"]:
        result["app_support"] += du(HOME / "Library" / app_dir)

    return result


def with_other(categories: dict[str, int], used_kb: int) -> dict[str, int]:
    """"other" = used space no named category explains (macOS, apps, unlisted folders). It was declared but never
    computed, so it always read 0 and anything outside the named folders was invisible."""
    named = sum(v for k, v in categories.items() if k != "other")
    return {**categories, "other": max(0, used_kb - named)}


def append_entry(
    categories: dict[str, int],
    free_kb: int,
    total_kb: int,
    device: str | None = None,
    now: datetime | None = None,
    path: Path = LEDGER_PATH,
    not_measured: list | None = None,
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
    if not_measured:
        entry["not_measured"] = not_measured

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
    the whole daily job logs together. Single flight: if another run holds the lock, returns {"busy": True} at once.
    """
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH.with_suffix(".lock"), "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("[disk_ledger] another run is still measuring; skipped", file=sys.stderr)
            return {"busy": True}
        not_measured: list = []
        categories = measure_categories(not_measured=not_measured)

        stat = os.statvfs(HOME)
        total_kb = (stat.f_blocks * stat.f_frsize) // 1024
        free_kb = (stat.f_bavail * stat.f_frsize) // 1024
        categories = with_other(categories, total_kb - free_kb)

        now = datetime.now(timezone.utc)
        append_entry(categories, free_kb, total_kb, device=None, now=now, path=LEDGER_PATH, not_measured=not_measured)

        return {
            "timestamp": now.isoformat(),
            "device": machine_profile.registry_id(),
            "free_kb": free_kb,
            "total_kb": total_kb,
            "categories": categories,
            "not_measured": not_measured,
        }


if __name__ == "__main__":
    import json as json_
    summary = run_daily_ledger()
    print(json_.dumps(summary, indent=2))
