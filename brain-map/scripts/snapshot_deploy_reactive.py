#!/usr/bin/env python3
"""
snapshot_deploy_reactive.py — Hourly check: deploy the map snapshot if the system tree changed.

Tracks the last commit the snapshot was built from. On each run:
  1. Check if git HEAD is ahead and touches files that affect the tree (generate.py inputs)
  2. If so, call deploy_snapshot.py to rebuild and deploy
  3. If not, exit quietly (no log spam for no-op runs)

Files that trigger a rebuild:
  - brain-map/generate.py, brain-map/enrichment.json (the tree generator and data)
  - brain-map/export_snapshot.py (privacy filter, snapshot format)
  - lib/project_catalog.py (project list changes)
  - lib/cleanup_sweep.py, config/launchd/*.plist (new agents/changes to agents tracked by the map)
  - Skills' SKILL.md files (skill descriptions)

Log only on deployment or error; no log on "no changes" runs.
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent.parent
SCRIPTS = HERE / "scripts"
REPO_ROOT = HERE.parent
HOME = Path.home()

# File patterns that trigger a snapshot rebuild
TRIGGER_PATTERNS = [
    "brain-map/generate.py",
    "brain-map/enrichment.json",
    "brain-map/export_snapshot.py",
    "lib/project_catalog.py",
    "lib/cleanup_sweep.py",
    "config/launchd/",
    "skills/*/SKILL.md",
]

# Track the last commit we deployed
LAST_DEPLOYED_FILE = HOME / ".claude" / "snapshot" / "last-deployed-commit"


def get_current_commit() -> str | None:
    """Get the current git HEAD commit hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=REPO_ROOT
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def get_last_deployed() -> str | None:
    """Read the last commit we successfully deployed."""
    if LAST_DEPLOYED_FILE.exists():
        try:
            return LAST_DEPLOYED_FILE.read_text(encoding="utf-8").strip()
        except Exception:
            return None
    return None


def files_changed_since(from_commit: str, to_commit: str = "HEAD") -> list[str]:
    """Get list of files changed between two commits."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{from_commit}..{to_commit}"],
            capture_output=True, text=True, timeout=5, cwd=REPO_ROOT
        )
        return result.stdout.strip().split("\n") if result.returncode == 0 else []
    except Exception:
        return []


def should_deploy() -> bool:
    """Check if the system tree has changed since the last deployment."""
    current = get_current_commit()
    last_deployed = get_last_deployed()

    if not current:
        return False

    if not last_deployed:
        # First run; no previous snapshot recorded, so deploy
        return True

    if current == last_deployed:
        # No new commits since last deployment
        return False

    # Check if any trigger files changed
    changed = files_changed_since(last_deployed, current)
    if not changed:
        return False

    # Match against trigger patterns
    import fnmatch
    for file_path in changed:
        for pattern in TRIGGER_PATTERNS:
            if fnmatch.fnmatch(file_path, pattern):
                return True

    return False


def mark_deployed(commit: str) -> None:
    """Record that we've deployed this commit."""
    LAST_DEPLOYED_FILE.parent.mkdir(parents=True, exist_ok=True)
    LAST_DEPLOYED_FILE.write_text(commit + "\n", encoding="utf-8")


def main() -> None:
    if not should_deploy():
        sys.exit(0)  # No-op run; exit quietly

    # Deploy by calling deploy_snapshot.py
    result = subprocess.run(
        [sys.executable or "python3", str(HERE / "deploy_snapshot.py")],
        cwd=REPO_ROOT
    )

    if result.returncode == 0:
        current = get_current_commit()
        if current:
            mark_deployed(current)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
