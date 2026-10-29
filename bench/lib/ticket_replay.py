"""ticket_replay.py — Git/PR mechanics to replay a ticket scenario.

Given a PR number:
1. Resolves the merge commit's first parent (pre-merge base) via git
2. Creates an isolated git worktree checkout at that base
3. Extracts PR/issue body as the prompt
4. Identifies test file(s) the merge touched via git show --stat
5. Always cleans up the worktree (try/finally), with unique temp path per invocation
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def resolve_merge_commit(pr_number: str, repo_path: str | Path | None = None) -> str | None:
    """Resolve a merged PR's merge commit OID.

    Searches for the merge commit via GitHub API (gh).

    Args:
        pr_number: PR number (e.g., "720")
        repo_path: path to git repo (optional, for cwd context)

    Returns:
        Merge commit hash string, or None if not found / error.
    """
    try:
        repo_path = repo_path or Path.cwd()
        # Find merge commit via gh CLI (more reliable than git grep)
        result = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "mergeCommit", "-q", ".mergeCommit.oid"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None

        return result.stdout.strip()
    except Exception:
        return None


def get_pr_body(pr_number: str, repo_path: str | Path | None = None) -> str:
    """Fetch PR body using gh CLI.

    Args:
        pr_number: PR number (e.g., "720")
        repo_path: path to git repo (optional, for cwd context)

    Returns:
        PR body text as string, empty string on error.
    """
    try:
        repo_path = repo_path or Path.cwd()
        result = subprocess.run(
            ["gh", "pr", "view", pr_number, "--json", "body", "-q", ".body"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception:
        return ""


def get_test_files(base_commit: str, merge_commit: str, repo_path: str | Path) -> list[str]:
    """Identify test files touched by the merge.

    Uses: git diff --name-only <base> <merge> to list changed files,
    filters for *test*.py files.

    Args:
        base_commit: first parent of merge (pre-merge base)
        merge_commit: the merge commit hash
        repo_path: path to git repo

    Returns:
        List of relative file paths that match test patterns.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_commit, merge_commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        files = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line and "test" in line.lower() and ".py" in line:
                files.append(line)
        return files
    except Exception:
        return []


def create_worktree(base_commit: str, repo_path: str | Path) -> Path | None:
    """Create an isolated git worktree at the given commit.

    Args:
        base_commit: commit hash to check out
        repo_path: path to the main git repo

    Returns:
        Path to the new worktree, or None on error.
    """
    try:
        wt_path = Path(tempfile.mkdtemp(prefix="bench-ticket-"))
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), base_commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            shutil.rmtree(wt_path, ignore_errors=True)
            return None
        return wt_path
    except Exception:
        return None


def replay_ticket(
    pr_number: str,
    repo_path: str | Path,
) -> dict[str, Any]:
    """Replay a ticket: extract prompt and identify test scope.

    Resolves the merge commit, creates a worktree at base, extracts PR body,
    identifies touched tests, and returns paths for opencode to use.
    Worktree cleanup is caller's responsibility (via the returned cleanup_fn).

    Args:
        pr_number: PR number (e.g., "720")
        repo_path: path to the git repository

    Returns:
        dict with:
            - "prompt": PR body text (the agent's task)
            - "test_files": list of touched test files
            - "base_commit": commit hash at base
            - "merge_commit": commit hash of the merge
            - "worktree_path": path to the worktree (caller must clean up)
            - "cleanup_fn": function to call to clean up the worktree
            - "error": error message if any step failed
    """
    repo_path = Path(repo_path)

    # Resolve the merge commit
    merge_commit = resolve_merge_commit(pr_number, repo_path)
    if not merge_commit:
        return {"prompt": "", "test_files": [], "error": f"Could not resolve PR #{pr_number}"}

    # Get base (first parent of merge)
    try:
        parent_result = subprocess.run(
            ["git", "rev-parse", f"{merge_commit}^1"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if parent_result.returncode != 0:
            return {"prompt": "", "test_files": [], "error": "Could not resolve merge parent"}
        base_commit = parent_result.stdout.strip()
    except Exception:
        return {"prompt": "", "test_files": [], "error": "Exception resolving merge parent"}

    # Create worktree at base commit
    wt_path = create_worktree(base_commit, repo_path)
    if not wt_path:
        return {"prompt": "", "test_files": [], "error": "Could not create worktree"}

    def cleanup_worktree() -> None:
        """Clean up the worktree."""
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(wt_path)],
                cwd=repo_path,
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
        try:
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=repo_path,
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
        shutil.rmtree(wt_path, ignore_errors=True)

    # Extract prompt and test files
    prompt = get_pr_body(pr_number, repo_path)
    test_files = get_test_files(base_commit, merge_commit, repo_path)

    return {
        "prompt": prompt,
        "test_files": test_files,
        "base_commit": base_commit,
        "merge_commit": merge_commit,
        "pr_number": pr_number,
        "worktree_path": str(wt_path),
        "cleanup_fn": cleanup_worktree,
    }
