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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from task_dispatch import select_machine, dispatch  # noqa: E402
import failure_breaker  # noqa: E402
import ticket_stages as ts  # noqa: E402
import board_registry  # noqa: E402
import ticket_policy  # noqa: E402
import project_profile as pp  # noqa: E402
import ticket_agents  # noqa: E402
import project_catalog  # noqa: E402

VENV_PYTHON = str(Path.home() / ".agents" / "venv" / "bin" / "python")
RUN_TICKET_SCRIPT = str(Path.home() / ".agents" / "lib" / "run_ticket.py")

REPO = "G-Eskayo/marvin"
LOG_PREFIX = "[ticket-pipeline]"


def _label_for_device(device_id: str) -> str:
    return "mac-mini" if device_id.startswith("mac-mini") else "macbook-pro"


UNSCORED_RANK = 2  # a ticket the prioritizer hasn't scored yet counts as middle priority


def _unclaimed_ready_tickets(repo: str = REPO) -> list[dict]:
    """What this machine may dispatch next, in order: ready-for-agent, unclaimed, not pinned, and with
    no open blocker, highest priority first and oldest first among equals. One call fetches every open
    ticket because whether a blocker is still open depends on the others."""
    proc = subprocess.run(
        ["gh", "issue", "list", "--repo", repo, "--state", "open", "--limit", "1000",
         "--json", "number,title,labels,createdAt,body"],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        print(f"{LOG_PREFIX} gh issue list failed: {proc.stderr[:300]}", file=sys.stderr)
        return []
    issues = json.loads(proc.stdout)
    open_numbers = {i["number"] for i in issues}

    def eligible(i):
        names = set(ticket_policy.label_names(i))
        return ("ready-for-agent" in names and "pinned" not in names
                and not any(n.startswith("claimed:") for n in names)
                and not ticket_policy.open_blockers(i, open_numbers))

    def rank(i):
        r = ticket_policy.priority_rank(i)
        return UNSCORED_RANK if r is None else r

    ready = [i for i in issues if eligible(i)]
    ready.sort(key=lambda i: (rank(i), i["createdAt"]))
    return ready


def _refresh_catalog() -> None:
    # The hourly pipeline run also keeps the project catalog (and the master "Where things are"
    # doc built from it) current. Best effort: never let it block dispatch.
    try:
        path = project_catalog.catalog_path()
        if project_catalog.is_stale(path, 50 * 60):
            res = project_catalog.real_refresh(path)
            print(f"{LOG_PREFIX} project catalog: " + (f"{res['count']} projects" if res["ok"] else f"refresh failed, kept last good ({res['error']})"), file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"{LOG_PREFIX} project catalog: {e}", file=sys.stderr)


def _run_ticket_agents(step, summary) -> None:
    """Prioritize / triage / stale-claim / refeed across every board repo (lib/ticket_agents.py), then
    note which projects have ready work this machine cannot execute yet. Best effort, and the agents
    only propose until their date (config/ticket_agents.json), so this never blocks dispatch."""
    try:
        cfg = ticket_agents.load_config()
        snap = ticket_agents.collect(ticket_agents.board_repos())
        executable = {REPO, *pp.dispatchable_repos()}
        res = ticket_agents.run(snap, ticket_agents._gh, cfg, datetime.now(timezone.utc),
                                in_flight=lambda repo: ticket_agents.in_flight_numbers(repo, snap),
                                due_for=ticket_agents.due_for_repo, executable=executable,
                                report=lambda agent, detail: step(f"Ticket agents · {agent}", detail))
        step("Ticket agents", f"{res['applied']} applied, {res['proposed']} proposed, {res['failed']} failed")
        elsewhere = ticket_agents.ready_elsewhere(snap, executable)
        if elsewhere:
            def why(r):
                prof = None
                try:
                    prof = pp.load_profile(r)
                except ValueError:
                    pass
                return "profile ready, dispatch is off" if prof else "no execution profile yet"
            step("Other projects", "ready for an agent but not dispatched: " + ", ".join(f"{r.split('/')[1]} {n} ({why(r)})" for r, n in elsewhere.items()))
    except Exception as e:  # noqa: BLE001
        print(f"{LOG_PREFIX} ticket agents: {e}", file=sys.stderr)
        step("Ticket agents", f"skipped: {e}")


def _active_project_repos() -> list[str]:
    """Repos of the catalog's active and recent projects: each deserves a board even before its first ticket."""
    try:
        cat = project_catalog.read_catalog(project_catalog.catalog_path()) or {}
        return [p["repo"] for p in cat.get("projects", []) if p.get("repo") and p.get("status") in ("active", "recent")]
    except Exception:  # noqa: BLE001
        return []


def _discover_boards() -> list[str]:
    return board_registry.discover(REPO.split("/")[0], extra_repos=_active_project_repos())


def _ensure_board(repo: str = REPO) -> None:
    # MARVIN starting work on a project creates its dashboard board. Best
    # effort: a registry problem must never block or undo a claim.
    try:
        board_registry.ensure_board(repo)
    except Exception as e:  # noqa: BLE001
        print(f"{LOG_PREFIX} board registry: {e}", file=sys.stderr)


def _claim(issue_number: int, label: str, title: str = "", repo: str = REPO) -> bool:
    proc = subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", repo, "--add-label", f"claimed:{label}"],
        capture_output=True, text=True, timeout=15,
    )
    if proc.returncode != 0:
        print(f"{LOG_PREFIX} failed to claim #{issue_number}: {proc.stderr[:300]}", file=sys.stderr)
        return False
    # title threaded through from main()'s own GitHub fetch -- the one
    # place in this flow that already has it, so the Activity tab never
    # has to show a bare number (feedback, 2026-10-01).
    ts.record_stage(issue_number, "claimed", "started", f"claimed:{label}", title=title or None,
                    **({"repo": repo} if repo != REPO else {}))
    _ensure_board(repo)
    return True


def _release(issue_number: int, label: str, repo: str = REPO) -> None:
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", repo, "--remove-label", f"claimed:{label}"],
        capture_output=True, text=True, timeout=15,
    )


def _build_wrapper_command(issue_number: int, repo: str = REPO) -> str:
    """run_ticket.py handles worktree creation (from origin/main, not
    whatever ~/.agents happens to be checked out to) internally via
    execute_ticket -- no git checkout/branch dance needed here, unlike
    the pre-#95 raw-prompt dispatch this replaced. Another project's ticket is named
    `owner/repo#n` and gets its own log file."""
    if repo == REPO:
        return (
            f"{VENV_PYTHON} {RUN_TICKET_SCRIPT} {issue_number} "
            f"> ~/dispatch_issue{issue_number}.log 2>&1"
        )
    slug = repo.split("/")[-1].lower()
    return (
        f"{VENV_PYTHON} {RUN_TICKET_SCRIPT} {repo}#{issue_number} "
        f"> ~/dispatch_{slug}_issue{issue_number}.log 2>&1"
    )


def _order_key(ticket: dict) -> tuple:
    rank = ticket_policy.priority_rank(ticket)
    return (UNSCORED_RANK if rank is None else rank, ticket["createdAt"])


def _select_for_profile(profile: dict):
    """A machine the profile allows, that is free, and (if it is this one) has the tools its required
    checks need. Other machines are trusted to be what the profile says they are; a ticket that proves
    otherwise is released without blame (run_ticket's EnvMissing path)."""
    for device in profile.get("machines", []):
        selected = select_machine(device)
        if selected is None:
            continue
        if selected[1].get("is_self") and pp.missing_here(profile):
            continue
        return selected
    return None


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    if dry_run:  # a preview records nothing
        _scan(lambda *a, **k: None, dry_run=True)
        return
    import job_events
    with job_events.job_run("ticket-pipeline", "Ticket pipeline (hourly scan)") as run:
        _scan(run, dry_run=False)


def _scan(run, dry_run: bool) -> None:
    """One scan. `run` is the job's run log (job_events): each phase is reported so the
    dashboard's Activity tab can show where this hourly job is and what it decided."""
    step = run.step if hasattr(run, "step") else run
    summary = run.summary if hasattr(run, "summary") else (lambda *a: None)
    fail = run.fail if hasattr(run, "fail") else (lambda *a: None)

    # Hourly run doubles as board discovery, before any early return below, so a
    # project set up anywhere gets its dashboard board without being asked for.
    if not dry_run:
        step("Board discovery")
        added = _discover_boards()
        for repo in added:
            print(f"{LOG_PREFIX} registered dashboard board for {repo}", file=sys.stderr)
        step("Board discovery", f"{len(added)} new" if added else "no new projects")
        step("Project catalog", "refresh if older than 50 min")
        _refresh_catalog()
        _run_ticket_agents(step, summary)

    # Cross-ticket circuit breaker, per project: the same failure across different tickets of one
    # project means ITS environment is broken, not the tickets -- stop feeding that project more
    # (each would just burn its own strikes) until a success or a manual clear. The others carry on.
    step("Circuit breaker")
    trips = failure_breaker.tripped()
    if trips:
        for t in trips:
            print(f"{LOG_PREFIX} dispatch PAUSED by circuit breaker ({t.get('project', REPO)}): {t['signature']} failed across "
                  f"tickets {t['tickets']} (since {t['first_seen']}); e.g. {t['example'][:140]}. "
                  f"Fix the cause, then `failure_breaker.py clear`.", file=sys.stderr)
        step("Circuit breaker", "TRIPPED: " + "; ".join(f"{t.get('project', REPO).split('/')[-1]} {t['signature']}" for t in trips))
    else:
        step("Circuit breaker", "clear")
    paused = {t.get("project", REPO) for t in trips}
    repos = [r for r in [REPO, *pp.dispatchable_repos()] if r not in paused]
    if not repos:
        summary("dispatch paused by the circuit breaker")
        return

    step("Scanning tickets", ", ".join(r.split("/")[-1] for r in repos) + ": ready-for-agent, unclaimed, unblocked")
    candidates = []
    for r in repos:
        ready = _unclaimed_ready_tickets() if r == REPO else _unclaimed_ready_tickets(repo=r)
        if ready:
            candidates.append((r, ready[0], len(ready)))
    if not candidates:
        print(f"{LOG_PREFIX} no unclaimed ready-for-agent tickets", file=sys.stderr)
        step("Scanning tickets", "none ready")
        summary("no ready tickets")
        return

    repo, ticket, _count = min(candidates, key=lambda c: _order_key(c[1]))
    other = repo != REPO
    issue_number = ticket["number"]
    where = f"{repo.split('/')[-1]} " if other else ""
    step("Scanning tickets", f"{sum(c[2] for c in candidates)} ready; next is {where}#{issue_number} {ticket['title']}")

    profile = pp.load_profile(repo) if other else None
    step("Choosing a machine")
    selected = select_machine() if not other else _select_for_profile(profile)
    if selected is None:
        print(f"{LOG_PREFIX} {where}#{issue_number} ready but no {'suitable ' if other else ''}machine currently available", file=sys.stderr)
        step("Choosing a machine", "none available" if not other else f"none free that can run {repo.split('/')[-1]} ({', '.join(profile.get('machines', [])) or 'no machines listed'})")
        summary(f"{where}#{issue_number} {ticket['title']} is ready but no suitable machine is available")
        return
    device_id, _info = selected
    claim_label = _label_for_device(device_id)
    step("Choosing a machine", device_id)

    if dry_run:
        print(f"{LOG_PREFIX} [dry-run] would claim {where}#{issue_number} ({ticket['title']}) "
              f"and dispatch to {device_id} as claimed:{claim_label}", file=sys.stderr)
        return

    step("Claiming ticket", f"{where}#{issue_number} {ticket['title']}")
    claimed = _claim(issue_number, claim_label, title=ticket["title"], **({"repo": repo} if other else {}))
    if not claimed:
        fail(f"could not claim {where}#{issue_number}")
        return

    command = _build_wrapper_command(issue_number, repo) if other else _build_wrapper_command(issue_number)

    step("Dispatching", f"to {device_id}")
    label = f"ticket {repo}#{issue_number}: {ticket['title'][:40]}" if other else f"ticket #{issue_number}: {ticket['title'][:40]}"
    result = dispatch(command, target=device_id, mode="async", task_label=label)
    if result.ok:
        print(f"{LOG_PREFIX} dispatched {where}#{issue_number} to {device_id}", file=sys.stderr)
        summary(f"dispatched {where}#{issue_number} {ticket['title']} to {device_id}")
    else:
        print(f"{LOG_PREFIX} dispatch failed for {where}#{issue_number}: {result.error} -- releasing claim", file=sys.stderr)
        _release(issue_number, claim_label, repo) if other else _release(issue_number, claim_label)
        fail(f"dispatch of {where}#{issue_number} to {device_id} failed: {result.error}")


if __name__ == "__main__":
    main()
