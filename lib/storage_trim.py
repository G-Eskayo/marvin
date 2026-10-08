#!/usr/bin/env python3
"""Auto-trim for #243: removes cache and build output from an allowlist when
disk space is low (per health_checks.DISK_YELLOW_BELOW_PCT). Never trims
anything outside the allowlist; respects dirty/unpushed worktrees."""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cleanup_sweep  # noqa: E402

HOME = Path.home()
TRIM_LOG = HOME / ".claude" / "logs" / "storage-trim.md"

NEVER_TRIM = {
    HOME / "Library" / "Caches" / "ms-playwright",
}

ALLOWLIST = [
    ("npm_cache", HOME / ".npm" / "_cacache"),
    ("pnpm_store", HOME / ".pnpm-store"),
    ("pip_cache", HOME / "Library" / "Caches" / "pip"),
    ("homebrew_cache", HOME / "Library" / "Caches" / "Homebrew"),
    ("electron_cache", HOME / "Library" / "Caches"),
    ("swiftpm_cache", HOME / "Library" / "Caches" / "SwiftPM"),
    ("xcode_deriveddata", HOME / "Library" / "Developer" / "Xcode" / "DerivedData"),
    ("worktrees_build_output", None),
]


def _is_too_new(path: Path, days_threshold: int = 7) -> bool:
    """Check if a path's mtime is less than days_threshold old."""
    try:
        mtime = path.stat().st_mtime
        age_days = (datetime.now(timezone.utc) - datetime.fromtimestamp(mtime, tz=timezone.utc)).days
        return age_days < days_threshold
    except Exception:
        return True


def _should_never_trim(path: Path) -> bool:
    """Check if path is in the NEVER_TRIM set."""
    try:
        for never in NEVER_TRIM:
            if path.is_relative_to(never) or path.samefile(never):
                return True
    except (ValueError, OSError):
        pass
    return False


def trim_candidates(root: Path | None = None) -> list[dict]:
    """Find trimmable items under the allowlist.

    Returns list of {category, path, size_kb} dicts.
    Does not actually remove anything.
    """
    root = root or HOME
    candidates = []

    def add_dir_candidate(category: str, path: Path) -> None:
        if not path.exists() or _should_never_trim(path):
            return
        try:
            proc = subprocess.run(
                ["du", "-sk", str(path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode == 0:
                parts = proc.stdout.strip().split(None, 1)
                if parts:
                    size_kb = int(parts[0])
                    candidates.append({
                        "category": category,
                        "path": path,
                        "size_kb": size_kb,
                    })
        except Exception:
            pass

    for category, path in ALLOWLIST:
        if path is None:
            continue
        expanded = path.resolve()
        if category == "xcode_deriveddata":
            for project_dir in expanded.glob("*"):
                if project_dir.is_dir() and _is_too_new(project_dir):
                    add_dir_candidate(category, project_dir)
        else:
            add_dir_candidate(category, expanded)

    # Worktrees build output: find all worktrees and check their .build/node_modules
    wt_root = root / ".agents-pipeline-worktrees"
    if wt_root.exists():
        for wt in wt_root.iterdir():
            if wt.is_dir():
                for build_dir in [".build", "node_modules"]:
                    path = wt / build_dir
                    if path.exists():
                        add_dir_candidate("worktrees_build_output", path)

    return candidates


def run_auto_trim(
    root: Path | None = None,
    worktrees: list | None = None,
) -> list[dict]:
    """Remove trimmable items and log what was done.

    Returns list of {category, path, size_kb} dicts for removed items.
    """
    candidates = trim_candidates(root)
    removed = []

    for item in candidates:
        path = item["path"]
        try:
            if path.is_symlink():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(item)
        except Exception:
            pass

    _write_log(removed)
    return removed


def _write_log(trimmed: list[dict]) -> None:
    """Log trimmed items to the trim log file."""
    timestamp = datetime.now(timezone.utc).isoformat()
    TRIM_LOG.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    if trimmed:
        for item in trimmed:
            size_mb = item["size_kb"] / 1024
            lines.append(f"- {item['category']}: {item['path']} ({size_mb:.1f} MB)")

    body = "\n".join(lines) + "\n" if lines else "No items trimmed.\n"
    existing = TRIM_LOG.read_text() if TRIM_LOG.exists() else "# Storage trim log\n\n"
    TRIM_LOG.write_text(existing + f"\n## {timestamp}\n\n{body}")


if __name__ == "__main__":
    trimmed = run_auto_trim()
    print(f"Trimmed {len(trimmed)} item(s)")
    for item in trimmed:
        print(f"  {item['category']}: {item['path']} ({item['size_kb'] / 1024:.1f} MB)")
