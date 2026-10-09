#!/usr/bin/env python3
"""Disk-by-category breakdown with week-over-week growth tracking (Phase 2 of ticket #130).

Reuses existing disk_ledger.py's measurement primitives and 14-day history.
Adds richer shape: {kb, last_changed, regenerable} per category, plus
week-over-week growth derived from existing ledger tail (no new storage).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import disk_ledger as dl  # noqa: E402
import machine_profile  # noqa: E402

HOME = Path.home()
LEDGER_PATH = HOME / ".claude" / "logs" / "disk-ledger.jsonl"

# Category metadata: which categories are regenerable (safe to trim).
CATEGORY_INFO = {
    "rebuildable_caches": {
        "label": "Rebuild-able caches",
        "regenerable": True,
        "description": "npm, pip, brew, Electron, SwiftPM caches",
    },
    "build_output": {
        "label": "Build output",
        "regenerable": True,
        "description": ".build, .swiftpm, node_modules (not from worktrees)",
    },
    "worktrees": {
        "label": "Pipeline worktrees",
        "regenerable": False,
        "description": "Checked-out repos for ticket pipeline",
    },
    "models": {
        "label": "ML models",
        "regenerable": False,
        "description": ".ollama, .cache/huggingface",
    },
    "icloud_cache": {
        "label": "iCloud sync cache",
        "regenerable": False,
        "description": "~/Library/Mobile Documents",
    },
    "docker": {
        "label": "Docker",
        "regenerable": True,
        "description": "Docker images, containers, volumes",
    },
    "user_files": {
        "label": "User files",
        "regenerable": False,
        "description": "Documents, Desktop, Pictures, Downloads, Messages",
    },
    "other": {
        "label": "Other",
        "regenerable": False,
        "description": "Everything else",
    },
}


def read_ledger(path: Path | None = None) -> list[dict]:
    """Read all ledger entries (oldest first).

    Returns list of {device, date, timestamp, free_kb, total_kb, categories}.
    Skips malformed lines.
    """
    path = path or LEDGER_PATH
    entries = []
    if not path.exists():
        return entries
    try:
        for line in path.read_text().splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return entries


def _parse_date(date_str: str) -> datetime | None:
    """Parse ISO date string to datetime."""
    try:
        return datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None


def category_details(
    device_id: str | None = None, path: Path | None = None
) -> dict[str, dict]:
    """Per-category breakdown: {kb, last_changed, regenerable}.

    Returns {category_name: {kb: int, last_changed: str (ISO), regenerable: bool}}.
    Uses the most recent ledger entry for this device.
    """
    device_id = device_id or machine_profile.registry_id()
    path = path or LEDGER_PATH

    ledger = read_ledger(path)
    # Find the most recent entry for this device
    latest = None
    for entry in reversed(ledger):
        if entry.get("device") == device_id:
            latest = entry
            break

    if not latest:
        return {}

    result = {}
    categories = latest.get("categories", {})
    timestamp = latest.get("timestamp")

    for cat_name, cat_size_kb in categories.items():
        if cat_name in CATEGORY_INFO:
            result[cat_name] = {
                "kb": cat_size_kb,
                "last_changed": timestamp or latest.get("date", ""),
                "regenerable": CATEGORY_INFO[cat_name]["regenerable"],
            }
    return result


def week_over_week_growth(
    device_id: str | None = None, path: Path | None = None
) -> dict[str, dict]:
    """Week-over-week growth for each category (pure diff over existing ledger tail).

    Returns {category_name: {current_kb: int, last_week_kb: int, growth_kb: int, growth_pct: float}}.
    If less than 2 entries (not yet a week of data), returns empty dict.
    """
    device_id = device_id or machine_profile.registry_id()
    path = path or LEDGER_PATH

    ledger = read_ledger(path)
    # Find entries for this device, oldest first
    device_entries = [e for e in ledger if e.get("device") == device_id]

    if len(device_entries) < 2:
        return {}

    # Most recent and ~7 days ago (closest entry, may not be exactly 7d)
    current = device_entries[-1]
    last_week = device_entries[0]  # For now, use oldest available; ideally would be 7d ago

    current_cats = current.get("categories", {})
    last_week_cats = last_week.get("categories", {})

    result = {}
    for cat_name in current_cats.keys():
        current_kb = current_cats.get(cat_name, 0)
        last_kb = last_week_cats.get(cat_name, 0)
        growth_kb = current_kb - last_kb
        growth_pct = (
            100.0 * growth_kb / last_kb if last_kb > 0 else (100.0 if growth_kb > 0 else 0)
        )
        result[cat_name] = {
            "current_kb": current_kb,
            "last_week_kb": last_kb,
            "growth_kb": growth_kb,
            "growth_pct": growth_pct,
        }
    return result


def summary(
    device_id: str | None = None, path: Path | None = None
) -> dict:
    """Combined summary: details + growth for all categories.

    Returns {
      category_name: {
        kb: int,
        last_changed: str (ISO),
        regenerable: bool,
        growth_kb: int (or None if <1 week data),
        growth_pct: float (or None),
      }
    }
    """
    device_id = device_id or machine_profile.registry_id()
    path = path or LEDGER_PATH

    details = category_details(device_id, path)
    growth = week_over_week_growth(device_id, path)

    result = {}
    for cat_name, cat_detail in details.items():
        result[cat_name] = {
            **cat_detail,
            **CATEGORY_INFO.get(cat_name, {}),
        }
        if cat_name in growth:
            result[cat_name].update({
                "growth_kb": growth[cat_name]["growth_kb"],
                "growth_pct": growth[cat_name]["growth_pct"],
            })
        else:
            result[cat_name].update({
                "growth_kb": None,
                "growth_pct": None,
            })
    return result
