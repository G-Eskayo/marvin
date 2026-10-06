#!/usr/bin/env python3
"""MR raiser for the MR pipeline (G-Eskayo/marvin#4).

Runs only after sandbox_orchestration.execute_ticket (G-Eskayo/marvin#3)
returns a passing result. Commits and pushes the worktree's branch, opens a
pull request referencing the originating ticket with the metrics
comparison, test results, and dev-environment evidence attached (the fixed
PR evidence schema -- G-Eskayo/marvin#72, ADR 0024), and posts a summary
comment back onto the ticket.

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


def _leave_out_generated(worktree_path: Path, ticket_ref: str) -> None:
    """Files the project declares as generated (profile "generated", see generated_paths.py) change in nearly
    every PR and make unrelated PRs conflict, so they stay out of the pipeline's commit. Best effort: a
    project with no profile or no rules commits everything, exactly as before."""
    try:
        import generated_paths
        import project_profile as pp
        repo = _repo_of(ticket_ref)
        profile = pp.load_profile(repo) if repo else None
        dropped = generated_paths.unstage_generated(worktree_path, (profile or {}).get("generated", []))
        if dropped:
            print(f"[mr_raiser] left {len(dropped)} generated file(s) out of the commit", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        print(f"[mr_raiser] generated-file filter skipped: {exc}", file=sys.stderr)


def _commit_and_push(worktree_path: Path, ticket_ref: str) -> str:
    branch = _current_branch(worktree_path)
    subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True)
    _leave_out_generated(worktree_path, ticket_ref)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=worktree_path, check=True, capture_output=True, text=True,
    ).stdout
    if status.strip():
        subprocess.run(
            ["git", "commit", "-m", f"Implement {ticket_ref}"],
            cwd=worktree_path, check=True, capture_output=True,
        )
    # A ticket sent back and re-dispatched is rebuilt from the current main under the SAME branch name, while
    # origin still holds the first attempt behind its open PR. That attempt is already preserved under
    # refs/rescue/ (sandbox_orchestration._preserve_prior_attempt), so replacing it is safe, and the lease
    # means we only replace the tip we last fetched, never someone else's newer push. Pipeline branches only.
    force = ["--force-with-lease"] if branch.startswith("pipeline/") else []
    subprocess.run(["git", "push", "-u", *force, "origin", branch], cwd=worktree_path, check=True, capture_output=True)
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
    text = (
        f"**Suite**: {test_results['suite']}\n"
        f"**Passed**: {test_results['passed']}\n"
        f"**Failed**: {test_results['failed']}\n"
        f"**Total**: {test_results['total']}"
    )
    if test_results.get("notes"):  # what the project's profile could NOT verify, so the PR never over-claims
        text += f"\n\n{test_results['notes']}"
    return text


def _format_dev_evidence(dev_evidence: dict | None) -> str:
    if not dev_evidence:
        return "Not available."
    if dev_evidence.get("na"):
        return f"N/A — {dev_evidence.get('reason', 'no UI')}"
    screenshot = dev_evidence.get("screenshot_path", "")
    description = dev_evidence.get("description", "")
    return f"![Screenshot]({screenshot})\n\n{description}".strip()


def _repo_of(ticket_ref: str) -> str | None:
    """'G-Eskayo/clarity-captions#7' -> 'G-Eskayo/clarity-captions'. gh must be told which repo: the
    process's own directory is not a reliable stand-in once more than one project is in play."""
    return ticket_ref.rsplit("#", 1)[0] if "/" in ticket_ref and "#" in ticket_ref else None


def _default_open_pr(
    ticket_ref: str,
    branch: str,
    comparison: dict,
    test_results: dict | None = None,
    dev_evidence: dict | None = None,
    base_branch: str = "main",
) -> str:
    body = (
        f"Closes {ticket_ref}\n\n"
        f"Autonomously implemented and verified by the MR pipeline.\n\n"
        f"## Metrics Comparison\n\n"
        f"{_format_comparison(comparison)}\n\n"
        f"## Test Results\n\n"
        f"{_format_test_results(test_results)}\n\n"
        f"## Dev Environment Evidence\n\n"
        f"{_format_dev_evidence(dev_evidence)}"
    )
    repo = _repo_of(ticket_ref)
    repo_args = ["--repo", repo] if repo else []
    try:
        result = subprocess.run(
            ["gh", "pr", "create", *repo_args, "--title", f"Implement {ticket_ref}", "--body", body,
             "--base", base_branch, "--head", branch],
            check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        if "already exists" not in (e.stderr or ""):
            raise
    # A re-engaged ticket's earlier PR is still open on this branch and the push above already updated it:
    # refresh its description with the new results instead of opening a duplicate.
    url = subprocess.run(["gh", "pr", "view", branch, *repo_args, "--json", "url", "-q", ".url"],
                         check=True, capture_output=True, text=True).stdout.strip()
    subprocess.run(["gh", "pr", "edit", url, "--body", body], check=True, capture_output=True, text=True)
    subprocess.run(["gh", "pr", "comment", url, "--body",
                    "Reworked after being sent back: rebuilt on the current base branch and re-verified. The results above are the new ones."],
                   check=True, capture_output=True, text=True)
    return url


def _default_comment_on_ticket(ticket_ref: str, pr_url: str) -> None:
    issue_number = ticket_ref.rsplit("#", 1)[-1]
    repo = _repo_of(ticket_ref)
    subprocess.run(
        ["gh", "issue", "comment", issue_number, *(["--repo", repo] if repo else []), "--body",
         f"Verification passed. Pull request raised: {pr_url}"],
        check=True, capture_output=True,
    )
    # A reworked ticket was tagged needs-reengagement when it was sent back; it has a fresh PR now, so the
    # board should stop calling it "sent back". Best effort: the label may not be there.
    subprocess.run(["gh", "issue", "edit", issue_number, *(["--repo", repo] if repo else []),
                    "--remove-label", "needs-reengagement"], capture_output=True)


def raise_mr(
    ticket_ref: str,
    execution_result: dict,
    test_results: dict | None = None,
    dev_evidence: dict | None = None,
    open_pr: Callable[[str, str, dict, dict | None, dict | None], str] | None = None,
    comment_on_ticket: Callable[[str, str], None] | None = None,
    notify: Callable[[str, str], dict] | None = None,
) -> dict:
    """Given sandbox_orchestration.execute_ticket's result, raise a PR only
    if verification passed. `test_results` and `dev_evidence` are
    caller-supplied (e.g. from evidence_capture.capture_test_results /
    capture_dev_evidence against the same worktree execute_ticket already
    produced) -- this function only formats them into the PR body, it
    doesn't run tests or drive an app itself. If `dev_evidence` carries a
    screenshot file inside the worktree, it must already be written to
    disk before this call, since it's committed as part of the same
    `git add -A` this function makes. Returns
    {"raised", "pr_url", "reason"}."""
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

    pr_url = open_pr(ticket_ref, branch, execution_result["final_comparison"], test_results, dev_evidence)
    comment_on_ticket(ticket_ref, pr_url)
    notify(ticket_ref, pr_url)

    return {"raised": True, "pr_url": pr_url, "reason": None}
