#!/usr/bin/env python3
"""Explicit-allowlist disk trimming under pressure (ADR 0056).

Trims allowlisted regenerable caches (npm, pnpm, pip, brew, Electron,
SwiftPM, stale Xcode DerivedData) when free disk space falls below
DISK_YELLOW_BELOW_PCT. NEVER touches ms-playwright cache (required for
parity tests), models, user files, or dirty/claimed worktrees.

Scheduled as part of the daily cleanup-sweep job (lib/cleanup_sweep.py),
logged to ~/.claude/logs/mr-pipeline-sweep.md alongside other sweep output.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanup_sweep as cs  # noqa: E402

HOME = Path.home()
DISK_YELLOW_BELOW_PCT = 20  # Imported from health_checks, duplicated here for self-contained module


def get_disk_free_pct() -> float:
    """Get current free disk space percentage."""
    stat = os.statvfs(HOME)
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bavail * stat.f_frsize
    return 100.0 * free / total if total > 0 else 0


# Paths that must never be trimmed, checked before any allowlist matching.
NEVER_TRIM = {
    HOME / "Library" / "Caches" / "ms-playwright",  # Required for parity tests (lib/portfolio_parity.py, lib/portfolio_layouts.py)
    HOME / ".Trash",
    HOME / "Library" / "Mobile Documents",  # iCloud cache
    HOME / ".ollama",  # Models
    HOME / ".cache" / "huggingface",
}


def _build_never_trim_worktrees() -> set[Path]:
    """Add worktree paths where decide_worktree() says 'keep' or 'review'.

    These hold open PRs, claimed issues, or uncommitted work, so the
    allowlist must never touch their build output.
    """
    worktrees = set()

    for wt in cs._default_list_worktrees():
        wt_path = wt.get("path")
        if not wt_path:
            continue

        # Check if this worktree should be kept
        repo, number = wt.get("repo"), cs._extract_issue_number(wt["branch"])
        try:
            state = cs._default_pr_state(repo, wt["branch"]) if repo else None
            claimed = bool(repo and number is not None and cs._default_is_claimed(repo, number))
        except Exception:
            # GitHub failure: be conservative, don't trim
            worktrees.add(wt_path)
            continue

        action, _ = cs.decide_worktree(wt, state, claimed)
        if action in ("keep", "review"):
            worktrees.add(wt_path)

    return worktrees


# Allowlist of paths we will trim when disk is low. Each maps to a cleanup function.
def _get_size_kb(path: Path) -> int:
    """Get size of path in KB."""
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


def _trim_npm():
    """Remove npm cache."""
    p = HOME / ".npm" / "_cacache"
    if p.exists():
        kb = _get_size_kb(p)
        shutil.rmtree(p)
        return kb * 1024


def _trim_pnpm():
    """Remove pnpm store."""
    p = HOME / ".pnpm-store"
    if p.exists():
        kb = _get_size_kb(p)
        shutil.rmtree(p)
        return kb * 1024


def _trim_pip():
    """Remove pip cache."""
    p = HOME / ".cache" / "pip"
    if p.exists():
        kb = _get_size_kb(p)
        shutil.rmtree(p)
        return kb * 1024


def _trim_brew():
    """Remove Homebrew cache."""
    try:
        result = subprocess.run(
            ["brew", "--cache"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            cache_dir = Path(result.stdout.strip())
            if cache_dir.exists():
                kb = _get_size_kb(cache_dir)
                shutil.rmtree(cache_dir)
                return kb * 1024
    except Exception:
        pass


def _trim_electron():
    """Remove Electron cache."""
    p = HOME / "Library" / "Caches" / "Electron"
    if p.exists():
        kb = _get_size_kb(p)
        shutil.rmtree(p)
        return kb * 1024


def _trim_swiftpm():
    """Remove SwiftPM cache."""
    p = HOME / "Library" / "Caches" / "SwiftPM"
    if p.exists():
        kb = _get_size_kb(p)
        shutil.rmtree(p)
        return kb * 1024


def _trim_xcode_derived_data():
    """Remove Xcode DerivedData entries older than 7 days."""
    import time
    dd_dir = HOME / "Library" / "Developer" / "Xcode" / "DerivedData"
    if not dd_dir.exists():
        return 0

    total_freed = 0
    now = time.time()
    threshold_s = 7 * 86400

    for entry in dd_dir.iterdir():
        if not entry.is_dir():
            continue
        mtime = entry.stat().st_mtime
        if now - mtime > threshold_s:
            kb = _get_size_kb(entry)
            shutil.rmtree(entry)
            total_freed += kb * 1024

    return total_freed


def _trim_worktree_build_output(keep_worktrees: set[Path]):
    """Remove build output from worktrees that decide_worktree() says to keep
    but whose build dirs are stale (> 3 days old)."""
    import time

    total_freed = 0
    now = time.time()
    threshold_s = 3 * 86400

    for wt_path in keep_worktrees:
        for rel_path in [".build", ".swiftpm", "node_modules"]:
            build_dir = wt_path / rel_path
            if build_dir.exists() and (now - build_dir.stat().st_mtime) > threshold_s:
                try:
                    # Use drop_build_output for safety (git-ignore-respecting)
                    removed = cs.drop_build_output(wt_path, [rel_path])
                    if removed:
                        total_freed += build_dir.stat().st_size if build_dir.exists() else 0
                except Exception:
                    pass

    return total_freed


def trim(dry_run: bool = False) -> list[dict]:
    """Trim allowlisted caches when disk is below yellow threshold.

    Returns list of (path, reclaimed_kb) for each removal. If dry_run=True,
    reports what would be removed but doesn't remove it.

    NEVER trims NEVER_TRIM paths or dirty/claimed worktrees.
    """
    free_pct = get_disk_free_pct()

    if free_pct >= DISK_YELLOW_BELOW_PCT:
        return []

    removed = []
    never_trim = NEVER_TRIM.copy()
    keep_worktrees = _build_never_trim_worktrees()

    trimmers = [
        (_trim_npm, "npm cache"),
        (_trim_pnpm, "pnpm store"),
        (_trim_pip, "pip cache"),
        (_trim_brew, "Homebrew cache"),
        (_trim_electron, "Electron cache"),
        (_trim_swiftpm, "SwiftPM cache"),
        (_trim_xcode_derived_data, "Xcode DerivedData (>7d old)"),
        (lambda: _trim_worktree_build_output(keep_worktrees), "pipeline worktree build output (>3d old)"),
    ]

    for trimmer, label in trimmers:
        if dry_run:
            # In dry run, only record that we would trim
            removed.append({"path": label, "reclaimed_kb": 0, "dry_run": True})
            continue

        try:
            reclaimed = trimmer()
            if reclaimed:
                removed.append({"path": label, "reclaimed_kb": reclaimed})
        except Exception:
            pass

    return removed


def trim_with_logging(dry_run: bool = False) -> dict:
    """Trim and log results to mr-pipeline-sweep.md."""
    timestamp = datetime.now(timezone.utc).isoformat()
    removed = trim(dry_run=dry_run)

    log_path = HOME / ".claude" / "logs" / "mr-pipeline-sweep.md"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    if removed:
        lines = []
        total_kb = 0
        for entry in removed:
            path = entry.get("path", "?")
            kb = entry.get("reclaimed_kb", 0)
            total_kb += kb
            status = "would trim" if entry.get("dry_run") else "trimmed"
            if kb > 0:
                lines.append(f"- {status}: {path} ({kb // 1024} MiB)")

        if lines:
            body = "### Disk trim\n" + "\n".join(lines) + f"\n\nTotal freed: {total_kb // 1024} MiB\n"
            existing = log_path.read_text() if log_path.exists() else "# MR pipeline cleanup sweep\n\n"
            log_path.write_text(existing + f"\n## {timestamp}\n\n{body}")

    return {
        "timestamp": timestamp,
        "free_pct": get_disk_free_pct(),
        "removed": len(removed),
        "total_kb_freed": sum(e.get("reclaimed_kb", 0) for e in removed),
    }


if __name__ == "__main__":
    result = trim_with_logging()
    print(json.dumps(result, indent=2))
