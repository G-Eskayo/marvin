#!/usr/bin/env python3
"""Code review gate for merge PRs (ticket #96). A diff-local correctness/quality pass.

Runs after CI and rebase checks pass, before merge. Fetches the PR diff and sends it to a judge
for a one-line verdict (clean or findings). If findings, the PR is sent back for rework.

Usage:
    code_review_gate.py review <pr-url>   # prints JSON result to stdout
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

If you found issues, follow with bullets (one per line, starting with `-`):
- file:line — summary of the issue (one short sentence)

If clean, stop after the VERDICT line."""

    return f"{rubric}\n\nDIFF:\n\n{diff}"


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
        return {"clean": True, "findings": []}
    elif "VERDICT: findings" in verdict_line:
        # Collect subsequent bullet lines
        findings = []
        for line in lines[verdict_idx + 1:]:
            line = line.strip()
            if line.startswith("- "):
                findings.append(line[2:])  # Remove "- " prefix
        return {"clean": False, "findings": findings}
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

    # Empty diff: clean, no model call
    if not diff.strip():
        return {"clean": True, "findings": []}

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
