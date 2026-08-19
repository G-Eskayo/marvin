#!/usr/bin/env python3
"""Daily cleanup sweep for the MR pipeline (G-Eskayo/marvin#9), same shape
as cron_health.py -- silent failure is the recurring real problem in this
codebase, so this exists as the safety net for the non-happy-path, not the
primary cleanup mechanism (that's immediate-on-resolution: ExitWorktree
remove + `gh pr merge --delete-branch` in mr_raiser's flow).

Two independent sweeps:

- **Stale claims**: a `claimed:*` issue whose `updatedAt` hasn't moved in
  over STALE_THRESHOLD_HOURS (a machine crashed, slept, or stalled) gets
  released via ticket_claim.release() -- the existing primitive, not new
  release machinery.
- **Orphaned worktrees**: a worktree under sandbox_orchestration's
  WORKTREES_ROOT whose branch encodes an issue number with no
  corresponding open, claimed issue gets removed, worktree and branch
  both. Issue numbers are parsed back out of the branch name (confirmed
  live against the real repo that ticket refs with `/` and `#` round-trip
  correctly through git worktree/push/gh pr create, so this parsing is
  safe) rather than importing sandbox_orchestration's private naming
  function, keeping the two modules loosely coupled.
"""
from __future__ import annotations
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ticket_claim  # noqa: E402
from sandbox_orchestration import WORKTREES_ROOT  # noqa: E402

OUTPUT_PATH = Path.home() / ".claude" / "logs" / "mr-pipeline-sweep.md"
STALE_THRESHOLD_HOURS = 24
ISSUE_NUMBER_RE = re.compile(r"#(\d+)$")


def _default_list_claimed_open_issues() -> list[dict]:
    result = subprocess.run(
        ["gh", "issue", "list", "--repo", ticket_claim.REPO, "--state", "open",
         "--json", "number,labels,updatedAt"],
        capture_output=True, text=True, check=True,
    )
    import json
    issues = json.loads(result.stdout)
    return [
        issue for issue in issues
        if any(label["name"].startswith("claimed:") for label in issue.get("labels", []))
    ]


def _default_list_worktrees() -> list[tuple[Path, str]]:
    if not WORKTREES_ROOT.exists():
        return []
    out = []
    for entry in WORKTREES_ROOT.iterdir():
        if not entry.is_dir():
            continue
        result = subprocess.run(
            ["git", "branch", "--show-current"], cwd=entry, capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            out.append((entry, result.stdout.strip()))
    return out


def _default_remove_worktree(path: Path, branch: str) -> None:
    subprocess.run(["git", "worktree", "remove", str(path), "--force"], capture_output=True)
    subprocess.run(["git", "branch", "-D", branch], capture_output=True)


def _extract_issue_number(branch: str) -> int | None:
    match = ISSUE_NUMBER_RE.search(branch)
    return int(match.group(1)) if match else None


def find_stale_claims(
    threshold_hours: float = STALE_THRESHOLD_HOURS,
    list_claimed_open_issues: Callable[[], list[dict]] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    list_claimed_open_issues = list_claimed_open_issues or _default_list_claimed_open_issues
    now = now or datetime.now(timezone.utc)

    stale = []
    for issue in list_claimed_open_issues():
        updated_at = datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))
        age_hours = (now - updated_at).total_seconds() / 3600
        if age_hours <= threshold_hours:
            continue
        for label in issue["labels"]:
            if label["name"].startswith("claimed:"):
                stale.append({
                    "issue_number": issue["number"],
                    "machine_id": label["name"].removeprefix("claimed:"),
                    "age_hours": age_hours,
                })
    return stale


def sweep_stale_claims(
    threshold_hours: float = STALE_THRESHOLD_HOURS,
    list_claimed_open_issues: Callable[[], list[dict]] | None = None,
    release: Callable[[int, str], None] | None = None,
    now: datetime | None = None,
) -> list[dict]:
    release = release or ticket_claim.release
    stale = find_stale_claims(threshold_hours, list_claimed_open_issues, now)
    for entry in stale:
        release(entry["issue_number"], entry["machine_id"])
    return stale


def find_orphaned_worktrees(
    list_worktrees: Callable[[], list[tuple[Path, str]]] | None = None,
    list_claimed_open_issues: Callable[[], list[dict]] | None = None,
) -> list[Path]:
    list_worktrees = list_worktrees or _default_list_worktrees
    list_claimed_open_issues = list_claimed_open_issues or _default_list_claimed_open_issues

    open_claimed_numbers = {issue["number"] for issue in list_claimed_open_issues()}

    orphans = []
    for path, branch in list_worktrees():
        issue_number = _extract_issue_number(branch)
        if issue_number is None or issue_number not in open_claimed_numbers:
            orphans.append(path)
    return orphans


def sweep_orphaned_worktrees(
    list_worktrees: Callable[[], list[tuple[Path, str]]] | None = None,
    list_claimed_open_issues: Callable[[], list[dict]] | None = None,
    remove_worktree: Callable[[Path, str], None] | None = None,
) -> list[Path]:
    list_worktrees = list_worktrees or _default_list_worktrees
    remove_worktree = remove_worktree or _default_remove_worktree

    worktrees = list_worktrees()
    branch_by_path = dict(worktrees)
    orphans = find_orphaned_worktrees(lambda: worktrees, list_claimed_open_issues)
    for path in orphans:
        remove_worktree(path, branch_by_path[path])
    return orphans


def _write_log(stale: list[dict], orphans: list[Path]) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    if not stale and not orphans:
        body = "Nothing to clean up — no stale claims, no orphaned worktrees.\n"
    else:
        lines = []
        for entry in stale:
            lines.append(
                f"- Released stale claim: issue #{entry['issue_number']} "
                f"held by `{entry['machine_id']}`, {entry['age_hours']:.1f}h since last update"
            )
        for path in orphans:
            lines.append(f"- Reclaimed orphaned worktree: `{path}`")
        body = "\n".join(lines) + "\n"

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = OUTPUT_PATH.read_text() if OUTPUT_PATH.exists() else "# MR pipeline cleanup sweep\n\n"
    OUTPUT_PATH.write_text(existing + f"\n## {timestamp}\n\n{body}")


def run_daily_sweep(
    list_claimed_open_issues: Callable[[], list[dict]] | None = None,
    list_worktrees: Callable[[], list[tuple[Path, str]]] | None = None,
    release: Callable[[int, str], None] | None = None,
    remove_worktree: Callable[[Path, str], None] | None = None,
    threshold_hours: float = STALE_THRESHOLD_HOURS,
    now: datetime | None = None,
) -> dict:
    """Cron entry point. Runs both sweeps, logs what was removed/released
    (same visibility standard as cron_health.py), returns a summary dict."""
    stale = sweep_stale_claims(threshold_hours, list_claimed_open_issues, release, now)
    orphans = sweep_orphaned_worktrees(list_worktrees, list_claimed_open_issues, remove_worktree)
    _write_log(stale, orphans)
    return {"stale_claims_released": len(stale), "orphaned_worktrees_removed": len(orphans)}
