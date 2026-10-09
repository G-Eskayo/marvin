#!/usr/bin/env python3
"""Code review (ticket #96). A diff-local correctness/quality pass by a judge model.

Runs inside the build loop, before a PR exists (sandbox_orchestration.execute_ticket): must-fix findings go
back to the builder in the same run, notes ride along on the PR. Approve no longer reviews code; it only
checks the PR merges cleanly (2026-10-09: reviewing at Approve spent Gil's click to learn what the build
could have found an hour earlier).

Usage:
    code_review_gate.py review <pr-url>   # prints JSON result to stdout (review an existing PR by hand)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

MAX_DIFF_CHARS = 60000  # Cap diff size sent to judge, same spirit as fit_check.py's MAX_NET_LINES


def fetch_diff(pr_url: str, run=subprocess.run) -> str | None:
    """Fetch the diff for a PR via `gh pr diff`. Returns None on failure, empty string if diff is empty."""
    try:
        result = run(["gh", "pr", "diff", pr_url], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


def build_prompt(diff: str) -> str:
    """Build the judge prompt from the diff. Truncates if needed with a marker."""
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n\n[... diff truncated ...]"

    rubric = """You are a Judge reviewing one pull request's code for correctness bugs and quality issues.
Review the diff below. Look for: logic errors, unhandled edge cases, missing error handling,
security issues, type mismatches, off-by-one errors, race conditions, resource leaks, and clarity problems.
Do NOT report style/linting issues unless they obscure intent. Do NOT report missing tests (that's separate).
Do NOT report cosmetic changes.

Respond with exactly one line: VERDICT: clean  or  VERDICT: findings

If you found issues, follow with bullets (one per line, starting with `-`), each tagged:
- [must-fix] file:line — summary   (a real defect: wrong result, crash, data loss, security hole, a test that
  doesn't test what it claims or that touches real external systems)
- [note] file:line — summary       (worth knowing but not wrong: performance, polish, clarity, missing UI hint)

If clean, stop after the VERDICT line."""

    return f"{rubric}\n\nDIFF:\n\n{diff}"


_TAG = re.compile(r"\[([A-Za-z-]+[^\]]*)\]\s*(.*)")


def parse_verdict(text: str) -> dict:
    """Parse VERDICT line and findings from model output.

    Returns:
    - {"clean": True, "findings": []} if VERDICT: clean
    - {"clean": False, "findings": [list of finding strings]} if VERDICT: findings
    - {"clean": None, "error": "..."} if VERDICT line is unparseable (ambiguity never resolves to safe)
    """
    lines = text.split("\n")
    verdict_line = None
    verdict_idx = -1

    # Find the first VERDICT: line
    for i, line in enumerate(lines):
        if "VERDICT:" in line:
            verdict_line = line.strip()
            verdict_idx = i
            break

    if not verdict_line:
        return {"clean": None, "error": "unparseable judge output: no VERDICT line found"}

    # Parse the verdict
    if "VERDICT: clean" in verdict_line:
        return {"clean": True, "findings": [], "notes": []}
    elif "VERDICT: findings" in verdict_line:
        # Collect subsequent bullet lines
        findings, notes = [], []
        for line in lines[verdict_idx + 1:]:
            line = line.strip()
            if line.startswith("- "):
                m = _TAG.match(line[2:])
                if m and m.group(1).lower() == "note":
                    notes.append(m.group(2))
                else:  # must-fix, untagged, or an unknown tag: ambiguity never resolves to safe
                    findings.append(m.group(2) if m and m.group(1).lower() == "must-fix" else line[2:])
        return {"clean": not findings, "findings": findings, "notes": notes}
    else:
        return {"clean": None, "error": f"unparseable judge output: unexpected VERDICT format: {verdict_line[:100]}"}


def run_review(
    pr_url: str,
    *,
    fetch: Callable[[str], str | None] = fetch_diff,
    launch: Callable | None = None
) -> dict:
    """Run code review on a PR.

    Returns:
    - {"clean": True, "findings": []} if diff is empty or review is clean
    - {"clean": False, "findings": [list]} if review found issues
    - {"clean": None, "error": "..."} if review failed to run
    """
    # Validate PR URL
    if not isinstance(pr_url, str) or not pr_url.startswith("https://github.com/"):
        return {"clean": None, "error": f"invalid PR URL: {pr_url}"}

    # Fetch diff
    diff = fetch(pr_url)
    if diff is None:
        return {"clean": None, "error": "failed to fetch PR diff"}
    return review_diff(diff, launch=launch)


def worktree_diff(worktree: Path, base: str = "main", run=subprocess.run) -> str | None:
    """Everything the build changed against origin/<base> (or <base>): committed, uncommitted and new files.
    None when git can't produce it (missing base, not a repo)."""
    def git(*a, check=True):
        return run(["git", *a], cwd=worktree, capture_output=True, text=True, check=check, timeout=60)
    try:
        ref = f"origin/{base}" if git("rev-parse", "--verify", "-q", f"origin/{base}", check=False).returncode == 0 else base
        mb = git("merge-base", ref, "HEAD").stdout.strip()
        out = git("diff", "-M", mb).stdout
        for path in git("ls-files", "--others", "--exclude-standard").stdout.splitlines():
            # --no-index exits 1 when the files differ, which they always do here
            out += git("diff", "--no-index", "--", "/dev/null", path, check=False).stdout
        return out
    except (subprocess.SubprocessError, OSError):
        return None


def review_worktree(worktree: Path, base: str = "main", *, launch: Callable | None = None) -> dict:
    """Review a build's changes before any PR exists."""
    diff = worktree_diff(worktree, base)
    if diff is None:
        return {"clean": None, "error": f"could not diff the worktree against {base}"}
    return review_diff(diff, launch=launch)


def review_diff(diff: str, *, launch: Callable | None = None) -> dict:
    """Judge one diff. {"clean": True|False, "findings": [must-fix], "notes": [...]} or {"clean": None, "error"}."""
    # Empty diff: clean, no model call
    if not diff.strip():
        return {"clean": True, "findings": [], "notes": []}

    # Import marvin_launcher here to avoid circular dependency
    if launch is None:
        import marvin_launcher
        launch = marvin_launcher.launch

    # Call the judge
    try:
        result = launch(
            "judge",
            build_prompt(diff),
            model="claude-opus-5-5",
            tools="",
            permission_mode=None,
            timeout=300
        )
    except Exception as e:
        return {"clean": None, "error": f"judge call failed: {str(e)[:200]}"}

    if result.exit_code != 0:
        return {"clean": None, "error": f"judge exited non-zero: {result.stderr[:200]}"}

    return parse_verdict(result.text.strip())


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "review":
        sys.exit("usage: code_review_gate.py review <pr-url>")

    pr_url = sys.argv[2]
    result = run_review(pr_url)
    print(json.dumps(result))
