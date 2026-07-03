#!/usr/bin/env python3
"""Verify retrospective-log.md hasn't been silently altered outside git.

Uses git's own hash chain — no new infrastructure. A log file's only
legitimate change is a new line appended at the end; every earlier commit's
content must be an exact, in-order prefix of every later one, and the
current working tree must be a prefix-preserving extension of the last
commit. Any deviation (an existing line edited, removed, or reordered)
means something touched the file outside of an honest git commit — a
direct edit, a corrupted merge, or a rewritten commit.

Run:
    ~/.agents/venv/bin/python verify_retrospective_integrity.py [path-to-repo]

Exits 0 if the whole history is append-only clean, 1 if any violation is
found (with specifics), 2 on a setup/usage error.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

FILE_REL_PATH = "retrospective-log.md"


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def file_at_commit(repo: Path, commit: str) -> list[str]:
    try:
        text = run_git(repo, "show", f"{commit}:{FILE_REL_PATH}")
    except RuntimeError:
        return []  # file didn't exist yet at this commit
    return text.splitlines()


def is_append_only_extension(older: list[str], newer: list[str]) -> tuple[bool, str]:
    """True if `newer` == `older` + zero or more new lines at the end,
    with every line in `older` matching newer's line at the same index."""
    if len(newer) < len(older):
        return False, f"shrank from {len(older)} to {len(newer)} lines — content was removed"
    for i, old_line in enumerate(older):
        if newer[i] != old_line:
            return False, (
                f"line {i + 1} changed:\n"
                f"    was: {old_line!r}\n"
                f"    now: {newer[i]!r}"
            )
    return True, ""


def main() -> int:
    repo = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / ".agents"
    if not (repo / ".git").exists():
        print(f"error: {repo} is not a git repo root", file=sys.stderr)
        return 2

    try:
        log = run_git(repo, "log", "--follow", "--format=%H", "--", FILE_REL_PATH)
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    commits = log.strip().splitlines()
    if not commits:
        print(f"note: {FILE_REL_PATH} has no commit history in {repo} — nothing to verify")
        return 0
    commits.reverse()  # oldest first

    violations: list[str] = []
    prev_content = file_at_commit(repo, commits[0])
    for commit in commits[1:]:
        content = file_at_commit(repo, commit)
        ok, detail = is_append_only_extension(prev_content, content)
        if not ok:
            violations.append(f"commit {commit[:8]}: {detail}")
        prev_content = content

    # Working tree vs. last commit — catches an uncommitted direct edit,
    # not just a legitimate not-yet-committed append.
    working_path = repo / FILE_REL_PATH
    if working_path.exists():
        working_content = working_path.read_text().splitlines()
        ok, detail = is_append_only_extension(prev_content, working_content)
        if not ok:
            violations.append(f"working tree (uncommitted): {detail}")

    if violations:
        print(f"INTEGRITY VIOLATION in {repo}/{FILE_REL_PATH}:")
        for v in violations:
            print(f"  - {v}")
        return 1

    print(f"OK — {repo}/{FILE_REL_PATH} is append-only clean across "
          f"{len(commits)} commit(s), no out-of-git alteration detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
