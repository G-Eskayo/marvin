#!/usr/bin/env python3
"""Select tickets for the opencode+Ollama spike.

Queries merged PRs from G-Eskayo/marvin, filters by size/kind, and packages
them as bench tasks in bench/tasks/spike-opencode-ollama/<ticket-id>/.

Usage:
    python3 select_spike_tickets.py
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent


@dataclass
class TicketCandidate:
    """A candidate PR for the spike."""
    pr_number: int
    pr_title: str
    pr_url: str
    issue_number: int | None
    issue_title: str | None
    issue_body: str | None
    merge_commit: str
    base_branch: str
    diff_size: int  # lines changed
    kind: str  # 'docs-fix', 'one-line-bugfix', 'test-addition', 'other'

    def __lt__(self, other):
        """Sort by kind (diversity) then size (prefer larger/more interesting)."""
        kind_order = {'docs-fix': 0, 'one-line-bugfix': 1, 'test-addition': 2, 'other': 3}
        if kind_order.get(self.kind) != kind_order.get(other.kind):
            return kind_order.get(self.kind, 99) < kind_order.get(other.kind, 99)
        return self.diff_size > other.diff_size


def _run_gh(cmd: list[str]) -> str:
    """Run a gh command and return stdout."""
    result = subprocess.run(
        ["gh"] + cmd,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError(f"gh command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def _get_merged_prs(limit: int = 50) -> list[dict]:
    """Fetch recently merged PRs from G-Eskayo/marvin."""
    output = _run_gh([
        "pr", "list",
        "-R", "G-Eskayo/marvin",
        "--state", "merged",
        "--limit", str(limit),
        "--json", "number,title,url,mergeCommit,baseRefName,additions,deletions",
    ])
    try:
        prs = json.loads(output)
        return prs
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse PR list: {e}")


def _get_pr_body(pr_number: int) -> dict:
    """Fetch PR detail including linked issue and body."""
    output = _run_gh([
        "pr", "view",
        "-R", "G-Eskayo/marvin",
        str(pr_number),
        "--json", "body,title,closingIssuesReferences",
    ])
    try:
        return json.loads(output)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse PR detail: {e}")


def _get_issue_body(issue_number: int) -> str:
    """Fetch issue body."""
    output = _run_gh([
        "issue", "view",
        "-R", "G-Eskayo/marvin",
        str(issue_number),
        "--json", "body",
    ])
    try:
        data = json.loads(output)
        return data.get("body", "")
    except json.JSONDecodeError:
        return ""


def _classify_kind(title: str, body: str, additions: int, deletions: int) -> str:
    """Classify PR kind based on title, body, and diff size."""
    combined = (title + " " + body).lower()
    diff_total = additions + deletions

    if "docs" in combined or "readme" in combined:
        return "docs-fix"
    if "test" in combined and diff_total < 100:
        return "test-addition"
    if diff_total < 20 and ("fix" in combined or "bug" in combined):
        return "one-line-bugfix"
    return "other"


def _get_single_parent_base(merge_commit: str) -> str | None:
    """Resolve the true single-parent base commit of a merge commit.

    For a normal merge: returns the non-main parent.
    For a squash: returns the first parent (the base).
    Returns None if unresolvable.
    """
    try:
        # Get parents of the merge commit
        output = subprocess.run(
            ["git", "rev-parse", f"{merge_commit}^@"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if output.returncode != 0:
            return None

        parents = output.stdout.strip().split()
        if len(parents) == 0:
            return None
        if len(parents) == 1:
            # Squash merge: first parent is the base
            return parents[0]
        if len(parents) == 2:
            # Normal merge: find the non-main parent
            # Parent 0 is usually main, parent 1 is the feature branch
            # We want the feature branch's base, which is parent 0
            return parents[0]
        # More complex merge; use first parent
        return parents[0]
    except Exception:
        return None


def select_candidates(limit_per_kind: int = 2, total_limit: int = 5) -> list[TicketCandidate]:
    """Select diverse candidates for the spike.

    Fetches merged PRs, filters to small ones, and selects a balanced set
    favoring diversity across kinds (docs-fix, one-line-bugfix, test-addition).
    """
    prs = _get_merged_prs(limit=50)
    candidates: list[TicketCandidate] = []

    for pr in prs:
        pr_number = pr["number"]
        pr_title = pr["title"]
        additions = pr.get("additions", 0)
        deletions = pr.get("deletions", 0)
        diff_size = additions + deletions

        # Filter: only small diffs
        if diff_size > 500:
            continue

        merge_commit = pr.get("mergeCommit")
        if not merge_commit:
            continue

        try:
            # Get PR body and linked issues
            pr_detail = _get_pr_body(pr_number)
            pr_body = pr_detail.get("body", "")
            closing_issues = pr_detail.get("closingIssuesReferences", [])

            # Get issue details if one is linked
            issue_number = None
            issue_title = None
            issue_body = None
            if closing_issues:
                issue_number = closing_issues[0]["number"]
                issue_title = closing_issues[0].get("title", "")
                issue_body = _get_issue_body(issue_number)
            elif not pr_body or pr_body.strip() == "":
                # Skip PRs with no linked issue and no body
                continue

            kind = _classify_kind(pr_title, pr_body or "", additions, deletions)
            base_commit = _get_single_parent_base(merge_commit)
            if not base_commit:
                continue

            candidate = TicketCandidate(
                pr_number=pr_number,
                pr_title=pr_title,
                pr_url=pr.get("url", ""),
                issue_number=issue_number,
                issue_title=issue_title,
                issue_body=issue_body,
                merge_commit=merge_commit,
                base_branch=pr.get("baseRefName", "main"),
                diff_size=diff_size,
                kind=kind,
            )
            candidates.append(candidate)
        except Exception as e:
            print(f"Warning: failed to process PR #{pr_number}: {e}", file=sys.stderr)
            continue

    # Select balanced set: favor diversity across kinds
    selected = []
    kind_counts = {"docs-fix": 0, "one-line-bugfix": 0, "test-addition": 0, "other": 0}

    for candidate in sorted(candidates):
        if len(selected) >= total_limit:
            break
        if kind_counts[candidate.kind] < limit_per_kind:
            selected.append(candidate)
            kind_counts[candidate.kind] += 1

    return selected


def write_task_dirs(candidates: list[TicketCandidate], tasks_dir: Path = ROOT / "bench" / "tasks") -> None:
    """Write task directories for each candidate."""
    spike_dir = tasks_dir / "spike-opencode-ollama"
    spike_dir.mkdir(parents=True, exist_ok=True)

    for candidate in candidates:
        task_id = f"spike-{candidate.pr_number}"
        task_dir = spike_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Write task.json
        task_json = {
            "id": task_id,
            "type": "fs",  # file-system task (involves code changes)
            "prompt_file": "prompt.md",
            "timeout": 600,
        }
        (task_dir / "task.json").write_text(json.dumps(task_json, indent=2) + "\n")

        # Write prompt.md from issue body
        prompt = candidate.issue_body or candidate.pr_title
        if not prompt:
            prompt = f"[Issue #{candidate.issue_number}] Fix from PR #{candidate.pr_number}"
        (task_dir / "prompt.md").write_text(prompt + "\n")

        print(f"✓ {task_id} (PR #{candidate.pr_number}, {candidate.diff_size} lines, {candidate.kind})")


if __name__ == "__main__":
    try:
        candidates = select_candidates()
        if not candidates:
            print("No suitable candidates found")
            sys.exit(1)
        print(f"Selected {len(candidates)} candidates:")
        write_task_dirs(candidates)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
