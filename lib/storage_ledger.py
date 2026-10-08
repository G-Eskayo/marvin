#!/usr/bin/env python3
"""Daily disk usage ledger and expansion forecast for #243. Records free/total disk space
and categorized usage to ~/.claude/logs/storage-ledger-<machine_id>.jsonl (one entry per day),
enabling trend analysis and time-to-floor forecasts in the health-check system.

Run standalone for immediate measurement and logging:
    ~/.agents/venv/bin/python storage_ledger.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import machine_profile  # noqa: E402
import health_checks as hc  # noqa: E402
import job_events  # noqa: E402

HOME = Path.home()
LEDGER_DIR = HOME / ".claude" / "logs"

CATEGORIES = [
    "rebuildable_caches",
    "build_output",
    "worktrees",
    "models",
    "icloud_cache",
    "docker",
    "user_files",
    "other",
]

CATEGORY_PATHS = {
    "rebuildable_caches": [
        "~/.npm/_cacache",
        "~/.pnpm-store",
        "~/Library/Caches/pip",
        "~/Library/Caches/Homebrew",
        "~/Library/Caches/SwiftPM",
        "~/Library/Caches/*/Electron",
    ],
    "build_output": [
        "~/.agents-pipeline-worktrees/*/build",
        "~/.agents-pipeline-worktrees/*/.build",
        "~/.agents-pipeline-worktrees/*/node_modules",
    ],
    "worktrees": [
        "~/.agents-pipeline-worktrees",
    ],
    "models": [
        "~/.ollama",
    ],
    "icloud_cache": [
        "~/Library/Mobile Documents",
    ],
    "docker": [
        "~/.docker",
    ],
    "user_files": [
        "~/Documents",
        "~/Desktop",
        "~/Downloads",
    ],
}


def categorize(du_output: str) -> dict[str, int]:
    """Parse `du -sk` output and categorize by size in KB.

    Input format: lines like '12345\t/path/to/dir'
    Returns: {category_name: total_kb_in_category, ...}
    """
    categories_sum = {cat: 0 for cat in CATEGORIES}

    for line in du_output.strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            kb = int(parts[0])
            path = parts[1]
        except (ValueError, IndexError):
            continue

        # Categorize by path
        matched = False
        for cat, patterns in CATEGORY_PATHS.items():
            for pattern in patterns:
                if _matches_path(path, pattern):
                    categories_sum[cat] += kb
                    matched = True
                    break
            if matched:
                break
        if not matched:
            categories_sum["other"] += kb

    return categories_sum


def _matches_path(path: str, pattern: str) -> bool:
    """Simple pattern matching for category assignment. Handles ~ expansion."""
    expanded = pattern.replace("~", str(HOME))
    if "*" in expanded:
        import fnmatch
        return fnmatch.fnmatch(path, expanded)
    return path.startswith(expanded) or path.startswith(expanded.rstrip("/"))


def measure(run=subprocess.run) -> dict[str, int]:
    """Measure current disk usage and categorize."""
    paths = []
    for patterns in CATEGORY_PATHS.values():
        for pattern in patterns:
            expanded = pattern.replace("~", str(HOME))
            paths.append(expanded)

    if not paths:
        return {cat: 0 for cat in CATEGORIES}

    try:
        proc = run(
            ["du", "-sk"] + paths,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return {cat: 0 for cat in CATEGORIES}
        return categorize(proc.stdout)
    except Exception:
        return {cat: 0 for cat in CATEGORIES}


def _get_disk_usage() -> tuple[int, int] | None:
    """Return (free_kb, total_kb) from df output, or None on error."""
    try:
        proc = subprocess.run(
            ["df", "-k", str(HOME)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return None
        lines = proc.stdout.strip().splitlines()
        if len(lines) < 2:
            return None
        parts = lines[1].split()
        if len(parts) >= 4:
            total_kb = int(parts[1])
            free_kb = int(parts[3])
            return free_kb, total_kb
    except Exception:
        pass
    return None


def append_entry(
    categories: dict[str, int],
    free_kb: int,
    total_kb: int,
    machine_id: str | None = None,
    now: datetime | None = None,
    path: Path | None = None,
) -> None:
    """Append a daily entry to the ledger file."""
    machine_id = machine_id or machine_profile.registry_id()
    now = now or datetime.now(timezone.utc)
    path = path or (LEDGER_DIR / f"storage-ledger-{machine_id}.jsonl")

    entry = {
        "date": now.date().isoformat(),
        "free_kb": free_kb,
        "total_kb": total_kb,
        "categories": categories,
    }

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def read_ledger(
    machine_id: str,
    days: int = 14,
    path: Path | None = None,
) -> list[dict]:
    """Read the last N days of entries from the ledger."""
    path = path or (LEDGER_DIR / f"storage-ledger-{machine_id}.jsonl")
    if not path.exists():
        return []

    entries = []
    try:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                entries.append(entry)
            except json.JSONDecodeError:
                continue
    except Exception:
        return []

    return entries[-days:] if days else entries


@job_events.reported("storage-ledger", "Disk storage ledger")
def main() -> None:
    """Main entry point: measure, log, and trigger auto-trim if needed."""
    categories = measure()
    disk = _get_disk_usage()
    if disk is None:
        return

    free_kb, total_kb = disk
    free_pct = 100 * free_kb / total_kb if total_kb else 0

    append_entry(categories, free_kb, total_kb)
    job_events.step("Ledger updated", f"{free_kb / 1048576:.1f} GiB free ({free_pct:.0f}%)")

    if free_pct < hc.DISK_YELLOW_BELOW_PCT:
        import storage_trim
        trimmed = storage_trim.run_auto_trim()
        if trimmed:
            reclaimed_kb = sum(item["size_kb"] for item in trimmed)
            job_events.step(
                "Auto-trim completed",
                f"reclaimed {reclaimed_kb / 1048576:.1f} GiB from {len(trimmed)} item(s)",
            )


if __name__ == "__main__":
    main()
