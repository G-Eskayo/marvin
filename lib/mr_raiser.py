#!/usr/bin/env python3
"""MR raiser for the MR pipeline (G-Eskayo/marvin#4).

Runs only after sandbox_orchestration.execute_ticket (G-Eskayo/marvin#3)
returns a passing result. Commits and pushes the worktree's branch, opens a
pull request referencing the originating ticket with the metrics comparison
attached as evidence, and posts a summary comment back onto the ticket.

Deliberately does not know sandbox_orchestration's branch-naming convention
-- reads the worktree's actual current branch via git rather than
duplicating that logic here, so the two modules stay decoupled.

`open_pr` and `comment_on_ticket` are injectable hooks (default: real `gh`
subprocess calls) -- same testability seam as sandbox_orchestration's
`executor` hook, so orchestration logic (the passing-gate, what gets
committed) is testable without hitting the real GitHub API.
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mr_notification import notify_mr_ready as _default_notify_mr_ready  # noqa: E402


def _current_branch(worktree_path: Path) -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=worktree_path, check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _commit_and_push(worktree_path: Path, ticket_ref: str) -> str:
    branch = _current_branch(worktree_path)
    subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=worktree_path, check=True, capture_output=True, text=True,
    ).stdout
    if status.strip():
        subprocess.run(
            ["git", "commit", "-m", f"Implement {ticket_ref}"],
            cwd=worktree_path, check=True, capture_output=True,
        )
    subprocess.run(["git", "push", "-u", "origin", branch], cwd=worktree_path, check=True, capture_output=True)
    return branch


def _format_comparison(comparison: dict) -> str:
    lines = [f"**Subsystem**: {comparison['subsystem']}", f"**Verdict**: {comparison['verdict']}", ""]
    lines.append("| Metric | Baseline | Current | Delta | Direction |")
    lines.append("|---|---|---|---|---|")
    for name, m in comparison.get("metrics", {}).items():
        lines.append(f"| {name} | {m['baseline']} | {m['current']} | {m['delta']:+} | {m['direction']} |")
    return "\n".join(lines)


def _format_test_results(test_results: dict | None) -> str:
    if not test_results or test_results.get("total") is None:
        return "Not available."
    return (
        f"**Suite**: {test_results['suite']}\n"
        f"**Passed**: {test_results['passed']}\n"
        f"**Failed**: {test_results['failed']}\n"
        f"**Total**: {test_results['total']}"
    )


def _default_open_pr(ticket_ref: str, branch: str, comparison: dict, test_results: dict | None = None) -> str:
    body = (
        f"Closes {ticket_ref}\n\n"
        f"Autonomously implemented and verified by the MR pipeline.\n\n"
        f"## Metrics Comparison\n\n"
        f"{_format_comparison(comparison)}\n\n"
        f"## Test Results\n\n"
        f"{_format_test_results(test_results)}"
    )
    result = subprocess.run(
        ["gh", "pr", "create", "--title", f"Implement {ticket_ref}", "--body", body,
         "--base", "main", "--head", branch],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


def _default_comment_on_ticket(ticket_ref: str, pr_url: str) -> None:
    issue_number = ticket_ref.rsplit("#", 1)[-1]
    subprocess.run(
        ["gh", "issue", "comment", issue_number, "--body",
         f"Verification passed. Pull request raised: {pr_url}"],
        check=True, capture_output=True,
    )


def raise_mr(
    ticket_ref: str,
    execution_result: dict,
    test_results: dict | None = None,
    open_pr: Callable[[str, str, dict, dict | None], str] | None = None,
    comment_on_ticket: Callable[[str, str], None] | None = None,
    notify: Callable[[str, str], dict] | None = None,
) -> dict:
    """Given sandbox_orchestration.execute_ticket's result, raise a PR only
    if verification passed. `test_results` is caller-supplied (e.g. from
    evidence_capture.capture_test_results against the same worktree
    execute_ticket already produced) -- this function only formats it into
    the PR body, it doesn't know how to run a project's tests itself.
    Returns {"raised", "pr_url", "reason"}."""
    if not execution_result["passing"]:
        return {
            "raised": False,
            "pr_url": None,
            "reason": execution_result.get("explanation") or "verification did not pass",
        }

    open_pr = open_pr or _default_open_pr
    comment_on_ticket = comment_on_ticket or _default_comment_on_ticket
    notify = notify or _default_notify_mr_ready

    worktree_path = execution_result["worktree_path"]
    branch = _commit_and_push(worktree_path, ticket_ref)

    pr_url = open_pr(ticket_ref, branch, execution_result["final_comparison"], test_results)
    comment_on_ticket(ticket_ref, pr_url)
    notify(ticket_ref, pr_url)

    return {"raised": True, "pr_url": pr_url, "reason": None}
