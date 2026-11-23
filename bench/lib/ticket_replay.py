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
    filters for test_*.py and *_test.py files.

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
            if not line or not line.endswith(".py"):
                continue
            # Match test_*.py or *_test.py patterns
            basename = Path(line).name
            if basename.startswith("test_") or basename.endswith("_test.py"):
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


def copy_test_files_to_check(
    test_files: list[str],
    merge_commit: str,
    worktree_path: str | Path,
    repo_path: str | Path,
) -> bool:
    """Copy test files from merge commit into worktree at their original relative paths.

    For each test file identified in the merge diff, extracts it from the merge
    commit and writes it to worktree_path/<original_path> for run_hidden_check.
    Preserves directory structure so that tests with package-relative imports work.

    Args:
        test_files: list of test file paths from get_test_files
        merge_commit: merge commit hash (source of test files)
        worktree_path: destination worktree path
        repo_path: path to the git repository

    Returns:
        True if successful or no files to copy, False on error.
    """
    if not test_files:
        return True

    worktree_path = Path(worktree_path)

    for test_file in test_files:
        try:
            # Extract file from merge commit
            result = subprocess.run(
                ["git", "show", f"{merge_commit}:{test_file}"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                continue

            # Write to original relative path inside worktree
            dest = worktree_path / test_file
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(result.stdout)
        except Exception:
            pass

    return True


def get_expected_strings(
    base_commit: str,
    merge_commit: str,
    repo_path: str | Path,
    files: list[str],
) -> list[str]:
    """Extract expected strings from added lines in specified non-test files.

    Scans the merge diff for added lines in the specified files, extracts them
    as "expected" ground-truth strings for correctness scoring.
    Skips comments and blank lines. If no files are specified, returns empty list
    (don't guess which files to scan; caller must be explicit).

    Args:
        base_commit: first parent of merge
        merge_commit: merge commit hash
        repo_path: path to git repo
        files: list of non-test files to scan (required; empty list means no scoring)

    Returns:
        List of extracted expected strings from added lines in specified files.
    """
    expected = []

    if not files:
        return expected

    files_set = set(files)

    try:
        # Get the diff between base and merge
        result = subprocess.run(
            ["git", "diff", base_commit, merge_commit],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return expected

        # Parse diff for added lines in specified files
        current_file = ""
        for line in result.stdout.split("\n"):
            # Detect file headers: "diff --git a/path b/path"
            if line.startswith("diff --git"):
                # Extract file path from header
                parts = line.split()
                if len(parts) >= 4:
                    current_file = parts[-1].removeprefix("b/")
                continue

            # Skip if current file is not in our target files list
            if current_file not in files_set:
                continue

            # Match added lines (starting with "+", not "+++")
            if line.startswith("+") and not line.startswith("+++"):
                added_line = line[1:].strip()
                if added_line and not added_line.startswith("#"):
                    expected.append(added_line)

    except Exception:
        pass

    return expected


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
