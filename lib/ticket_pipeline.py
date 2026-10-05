#!/usr/bin/env python3
"""Ticket pipeline: scans G-Eskayo/marvin for `ready-for-agent` issues with
no existing claim, and dispatches the oldest one to an available machine,
which runs it through run_ticket.py's execute_ticket -> raise_mr flow
(G-Eskayo/marvin#95). Each ticket gets a real isolated git worktree
(sandbox_orchestration._create_worktree), not the shared ~/.agents
checkout -- eliminates the collision risk between a dispatched ticket and
whatever an interactive session happens to be doing in that same checkout
at the same moment. git/gh work (commit, push, `gh pr create`) happens as
plain subprocess calls from mr_raiser.py, not from inside a nested Claude
session, so it was never subject to the headless permission wall ADR 0030
documents -- run_ticket.py only needs a flagship+Haiku pair of nested
`claude -p` calls (sandbox_orchestration._default_executor), both already
scoped with `dontAsk` + an explicit allowlist.

Supersedes the raw `claude -p --permission-mode acceptEdits` dispatch this
module used before #95 -- see dispatch_ticket.sh for that older, still-
valid manual-dispatch pattern (a different, non-worktree-isolated tool,
kept for ad hoc one-off use, not rewired here).

One ticket per run, by design: keeps blast radius small and lets
task_dispatch's per-machine busy-lock do the concurrency control -- a
still-running ticket keeps its machine "busy" (dispatch-state.json), so
the next scan naturally skips it or picks the other machine instead.

Claiming (adding claimed:<machine> label) happens right before dispatch,
not earlier -- a small TOCTOU race against a concurrent scan on the other
machine is possible but low-stakes for a 2-machine personal setup: worst
case is a wasted duplicate PR, and every PR still needs human approval
before merge regardless (the MR-review tab's whole reason to exist).

Run standalone: ~/.agents/venv/bin/python ticket_pipeline.py [--dry-run]
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from task_dispatch import select_machine, dispatch  # noqa: E402
import failure_breaker  # noqa: E402
import ticket_stages as ts  # noqa: E402
import board_registry  # noqa: E402
import project_catalog  # noqa: E402

VENV_PYTHON = str(Path.home() / ".agents" / "venv" / "bin" / "python")
RUN_TICKET_SCRIPT = str(Path.home() / ".agents" / "lib" / "run_ticket.py")

REPO = "G-Eskayo/marvin"
LOG_PREFIX = "[ticket-pipeline]"


def _label_for_device(device_id: str) -> str:
    return "mac-mini" if device_id.startswith("mac-mini") else "macbook-pro"


def _unclaimed_ready_tickets() -> list[dict]:
    proc = subprocess.run(
        ["gh", "issue", "list", "--repo", REPO, "--label", "ready-for-agent",
         "--state", "open", "--json", "number,title,labels,createdAt"],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        print(f"{LOG_PREFIX} gh issue list failed: {proc.stderr[:300]}", file=sys.stderr)
        return []
    issues = json.loads(proc.stdout)
    unclaimed = [
        i for i in issues
        if not any(l["name"].startswith("claimed:") for l in i["labels"])
    ]
    unclaimed.sort(key=lambda i: i["createdAt"])
    return unclaimed


def _refresh_catalog() -> None:
    # The hourly pipeline run also keeps the project catalog (and the master "Where things
    # are" doc built from it) current. Best effort: never let it block dispatch.
    try:
        path = project_catalog.catalog_path()
        if project_catalog.is_stale(path, 50 * 60):
            res = project_catalog.real_refresh(path)
            print(f"{LOG_PREFIX} project catalog: " + (f"{res['count']} projects" if res["ok"] else f"refresh failed, kept last good ({res['error']})"), file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"{LOG_PREFIX} project catalog: {e}", file=sys.stderr)


def _discover_boards() -> list[str]:
    return board_registry.discover(REPO.split("/")[0])


def _ensure_board() -> None:
    # MARVIN starting work on a project creates its dashboard board. Best
    # effort: a registry problem must never block or undo a claim.
    try:
        board_registry.ensure_board(REPO)
    except Exception as e:  # noqa: BLE001
        print(f"{LOG_PREFIX} board registry: {e}", file=sys.stderr)


def _claim(issue_number: int, label: str, title: str = "") -> bool:
    proc = subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--add-label", f"claimed:{label}"],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        print(f"{LOG_PREFIX} failed to claim #{issue_number}: {proc.stderr[:300]}", file=sys.stderr)
        return False
    # title threaded through from main()'s own GitHub fetch -- the one
    # place in this flow that already has it, so the Activity tab never
    # has to show a bare number (feedback, 2026-10-01).
    ts.record_stage(issue_number, "claimed", "started", f"claimed:{label}", title=title or None)
    _ensure_board()
    return True


def _release(issue_number: int, label: str) -> None:
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", REPO, "--remove-label", f"claimed:{label}"],
        capture_output=True, text=True, timeout=15,
    )


def _build_wrapper_command(issue_number: int) -> str:
    """run_ticket.py handles worktree creation (from origin/main, not
    whatever ~/.agents happens to be checked out to) internally via
    execute_ticket -- no git checkout/branch dance needed here, unlike
    the pre-#95 raw-prompt dispatch this replaced."""
    return (
        f"{VENV_PYTHON} {RUN_TICKET_SCRIPT} {issue_number} "
        f"> ~/dispatch_issue{issue_number}.log 2>&1"
    )


def main() -> None:
    dry_run = "--dry-run" in sys.argv

    # Hourly run doubles as board discovery, before any early return below, so a
    # project set up anywhere gets its dashboard board without being asked for.
    if not dry_run:
        for repo in _discover_boards():
            print(f"{LOG_PREFIX} registered dashboard board for {repo}", file=sys.stderr)
        _refresh_catalog()

    # Cross-ticket circuit breaker: the same failure across different tickets means
    # the environment is broken, not the tickets -- stop feeding it more tickets
    # (each would just burn its own strikes) until a success or a manual clear.
    trips = failure_breaker.tripped()
    if trips:
        for t in trips:
            print(f"{LOG_PREFIX} dispatch PAUSED by circuit breaker: {t['signature']} failed across "
                  f"tickets {t['tickets']} (since {t['first_seen']}); e.g. {t['example'][:140]}. "
                  f"Fix the cause, then `failure_breaker.py clear`.", file=sys.stderr)
        return

    tickets = _unclaimed_ready_tickets()
    if not tickets:
        print(f"{LOG_PREFIX} no unclaimed ready-for-agent tickets", file=sys.stderr)
        return

    ticket = tickets[0]
    issue_number = ticket["number"]

    selected = select_machine()
    if selected is None:
        print(f"{LOG_PREFIX} #{issue_number} ready but no machine currently available", file=sys.stderr)
        return
    device_id, _info = selected
    claim_label = _label_for_device(device_id)

    if dry_run:
        print(f"{LOG_PREFIX} [dry-run] would claim #{issue_number} ({ticket['title']}) "
              f"and dispatch to {device_id} as claimed:{claim_label}", file=sys.stderr)
        return

    if not _claim(issue_number, claim_label, title=ticket["title"]):
        return

    command = _build_wrapper_command(issue_number)

    result = dispatch(command, target=device_id, mode="async",
                       task_label=f"ticket #{issue_number}: {ticket['title'][:40]}")
    if result.ok:
        print(f"{LOG_PREFIX} dispatched #{issue_number} to {device_id}", file=sys.stderr)
    else:
        print(f"{LOG_PREFIX} dispatch failed for #{issue_number}: {result.error} -- releasing claim", file=sys.stderr)
        _release(issue_number, claim_label)


if __name__ == "__main__":
    main()
