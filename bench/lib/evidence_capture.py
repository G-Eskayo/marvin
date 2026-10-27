"""Capture evidence of code changes before and after a task.

Used to record file snapshots, diffs, and other evidence of what changed.
"""
from __future__ import annotations
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CodeSnapshot:
    """Snapshot of code state."""
    git_status: str
    git_diff: str
    changed_files: list[str]

    def to_dict(self) -> dict:
        return {
            "git_status": self.git_status,
            "git_diff": self.git_diff[:10000],  # Truncate large diffs
            "changed_files": self.changed_files,
        }


def capture_snapshot(workdir: Path) -> CodeSnapshot | None:
    """Capture current code state via git status and diff.

    Returns None if workdir is not a git repository.
    """
    try:
        # Check if it's a git repo
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=workdir,
            capture_output=True,
            timeout=5,
            check=True,
        )
    except Exception:
        return None

    status = ""
    diff = ""
    changed = []

    try:
        # Get git status
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status = result.stdout
        changed = [line.split()[-1] for line in status.splitlines() if line.strip()]
    except Exception as e:
        status = f"Error: {e}"

    try:
        # Get git diff
        result = subprocess.run(
            ["git", "diff", "--no-color"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        diff = result.stdout
    except Exception as e:
        diff = f"Error: {e}"

    return CodeSnapshot(
        git_status=status,
        git_diff=diff,
        changed_files=changed,
    )
