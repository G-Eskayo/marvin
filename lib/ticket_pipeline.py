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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from task_dispatch import select_machine, dispatch  # noqa: E402
import failure_breaker  # noqa: E402
import ticket_stages as ts  # noqa: E402
import board_registry  # noqa: E402
import ticket_policy  # noqa: E402
import project_profile as pp  # noqa: E402
import ticket_agents  # noqa: E402
import project_catalog  # noqa: E402
import ticket_evidence  # noqa: E402

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

    ready = [i for i in issues if eligible(i)]
    _score_ready(ready, issues, open_numbers, repo)
    facts = _evidence_facts(repo) if ready else None
    if facts is not None:  # unreadable evidence must not stall dispatch: fall back to the old behaviour
        kept = []
        for i in ready:
            ev = ticket_evidence.evidence_for(i["number"], facts)
            sent_back = "needs-reengagement" in ticket_policy.label_names(i)
            if sent_back:
                # Its open PR / branch / rescue ref ARE the first attempt, which is what a rework replaces
                # (mr_raiser force-with-lease, the old work kept under refs/rescue). Commits already on the
                # base branch still mean the work landed, and a ticket that keeps bouncing goes to a person.
                ev = [e for e in ev if e["kind"] in ("commit", "merged-pr")]
                if not ev and _attempts(repo, i["number"]) >= MAX_REENGAGE_ATTEMPTS:
                    print(f"{LOG_PREFIX} skip {repo}#{i['number']}: sent back after {MAX_REENGAGE_ATTEMPTS} reworked PRs, needs a person", file=sys.stderr)
                    continue
            if ticket_evidence.verdict(ev) == "clear":
                kept.append(i)
            else:
                print(f"{LOG_PREFIX} skip {repo}#{i['number']}: work already exists "
                      f"({ticket_evidence.verdict(ev)}: {ev[0]['ref']} {ev[0]['detail'][:60]})", file=sys.stderr)
        ready = kept
    ready.sort(key=_order_key)
    return ready


MAX_REENGAGE_ATTEMPTS = 3

# Where marvin's OWN tickets may run (other projects name theirs in config/projects/<repo>.json). The macbook is left out on purpose
# (2026-10-06): its Python test suite has 18 environment-only failures (paper-dive, the portfolio parity check, variable-tracker),
# so a ticket verified there can be read as regressed, and its first marvin ticket (#141) stalled in planning and was finished by
# the mac-mini. Add "macbook-pro-1" here once that suite is clean.
MARVIN_MACHINES = ("mac-mini-1",)


def _requeue_all(repos) -> list[str]:
    return [f"{r.split('/')[-1]}#{n}" for r in repos for n in _requeue_conflicted_prs(r)]

_CLOSES = __import__("re").compile(r"Closes\s+(?:[\w.-]+/[\w.-]+)?#(\d+)")


def _failing_checks(rollup) -> list[str]:
    """Names of checks that genuinely FAILED. Cancelled / timed-out / still-running checks are the runner's
    business, not the code's, and must not trigger a rebuild."""
    out = []
    for c in rollup or []:
        if c.get("__typename") == "StatusContext":
            if c.get("state") in ("FAILURE", "ERROR"):
                out.append(c.get("context") or "status")
        elif c.get("status") == "COMPLETED" and c.get("conclusion") == "FAILURE":
            out.append(c.get("name") or "check")
    return out


def _requeue_conflicted_prs(repo: str) -> list[int]:
    """A PR that GitHub says CONFLICTS with its base can never be merged as it stands, and the first anyone
    learned was a human clicking Approve (finance-os #9, clarity #48). So the pipeline sends the ticket back
    by itself: label `needs-reengagement` + a comment saying why, and the existing sent-back loop rebuilds it
    on the current main. Tickets already sent back, or protected by `pinned`/`held`, are left alone, and any
    gh failure just means 'try again next scan'."""
    def gh(*args):
        return subprocess.run(["gh", *args], capture_output=True, text=True, timeout=30)

    prs = gh("pr", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,body,mergeable,headRefName,statusCheckRollup")
    issues = gh("issue", "list", "--repo", repo, "--state", "open", "--limit", "1000", "--json", "number,labels")
    if prs.returncode != 0 or issues.returncode != 0:
        return []
    try:
        labels_of = {i["number"]: set(ticket_policy.label_names(i)) for i in json.loads(issues.stdout)}
        pr_list = json.loads(prs.stdout)
    except (ValueError, KeyError, TypeError):
        return []
    sent: list[int] = []
    for pr in pr_list:
        m = _CLOSES.search(pr.get("body") or "")
        red = _failing_checks(pr.get("statusCheckRollup"))
        if not m or not (pr.get("mergeable") == "CONFLICTING" or red):
            continue
        n = int(m.group(1))
        names = labels_of.get(n)
        if names is None or names & {"needs-reengagement", "pinned", "held"}:
            continue
        # The claim from the run that raised this PR must go too: the dispatcher only takes tickets with no claim, so a
        # sent-back ticket that kept it would never be rebuilt (clarity-captions #51).
        edit_args = ["issue", "edit", str(n), "--repo", repo, "--add-label", "needs-reengagement"]
        for claim in sorted(l for l in names if l.startswith("claimed:")):
            edit_args += ["--remove-label", claim]
        add = gh(*edit_args)
        if add.returncode != 0:  # the label may not exist on this repo yet
            gh("label", "create", "needs-reengagement", "--repo", repo, "--color", "d93f0b", "--description", "Sent back: rebuild on the current base branch")
            add = gh(*edit_args)
        if add.returncode != 0:
            continue
        gh("issue", "comment", str(n), "--repo", repo, "--body",
           (f"PR #{pr['number']}'s GitHub checks failed: {', '.join(red)}. " if red else
            f"PR #{pr['number']} now conflicts with main (something it touches changed after this was built). ") +
           "Sent back automatically: the pipeline will rebuild it on the current main and update the same PR.")
        print(f"{LOG_PREFIX} {repo}#{n}: PR #{pr['number']} {'failed its checks' if red else 'conflicts with main'}, sent back for rework", file=sys.stderr)
        sent.append(n)
    return sent


def _attempts(repo: str, number: int) -> int:
    """How many attempts at this ticket got as far as raising a PR. A claim that died earlier (a failed
    fetch, a missing tool) is not an attempt: those are the failure breaker's business, not this budget's."""
    stages = ts.read_stages(number, None if repo == REPO else repo)
    return sum(1 for e in stages if e.get("stage") == "done" and e.get("status") == "passed"
               and str(e.get("detail", "")).startswith("PR raised"))


def _evidence_facts(repo: str):
    """Git/PR facts for the pre-dispatch guard (ticket_evidence), or None if unreadable."""
    try:
        if repo == REPO:
            clone = str(Path.home() / ".agents")
        else:
            prof = pp.load_profile(repo)
            c = pp.resolve_clone(prof) if prof else None
            clone = str(c) if c else None
        return ticket_evidence.gather(repo, clone)
    except Exception as e:  # noqa: BLE001
        print(f"{LOG_PREFIX} evidence check failed for {repo}: {e}", file=sys.stderr)
        return None


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
    cmd = ["gh", "issue", "edit", str(issue_number), "--repo", repo, "--add-label", f"claimed:{label}"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if proc.returncode != 0 and "not found" in (proc.stderr or "").lower():
        # First claim in a project that has never had this machine's claim label: create it, then retry
        # (marvin's repo already has them, which is why this only shows up for other projects).
        subprocess.run(["gh", "label", "create", f"claimed:{label}", "--repo", repo, "--color", "5319E7",
                        "--description", "Being worked on by this machine's ticket pipeline"],
                       capture_output=True, text=True, timeout=15)
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
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


def _due_for(repo: str) -> dict | None:
    """The project's deadline, from the shared catalog overrides (the same source the ticket agents and the dashboard read)."""
    import ticket_agents
    return ticket_agents.due_for_repo(repo)


def _score_ready(ready: list[dict], issues: list[dict], open_numbers: set[int], repo: str) -> None:
    """Stamp each ready ticket with its urgency score (what it unblocks, its project's deadline, type, age), so ordering within
    a repo and across repos weighs deadlines (ADR 0047). An unreadable deadline must not stall dispatch: score without it."""
    try:
        due = _due_for(repo)
    except Exception:  # noqa: BLE001
        due = None
    blocks: dict[int, int] = {}
    for i in issues:
        for b in ticket_policy.open_blockers(i, open_numbers):
            blocks[b] = blocks.get(b, 0) + 1
    now = datetime.now(timezone.utc)
    for i in ready:
        i["_score"] = ticket_policy.score_ticket(i, blocks.get(i["number"], 0), due, now)[0]


def _order_key(ticket: dict) -> tuple:
    """A priority label a person (or the prioritizer) set wins; then the urgency score, deadlines weighing heavily; then age."""
    rank = ticket_policy.priority_rank(ticket)
    return (UNSCORED_RANK if rank is None else rank, -ticket.get("_score", 0.0), ticket["createdAt"])


def _flag_busy() -> bool:
    try:
        from task_dispatch import _read_local_dispatch_state
        return bool(_read_local_dispatch_state().get("busy"))
    except Exception:  # noqa: BLE001
        return True


def _ticket_process_alive() -> bool:
    """Is a ticket actually being worked on right now? The dispatch-state flag is one shared boolean that the
    first of two overlapping runs to finish clears while the other is still going, so it alone can say
    "idle" mid-ticket. A live run_ticket process cannot lie."""
    try:
        return subprocess.run(["pgrep", "-f", "lib/run_ticket.py"], capture_output=True, text=True, timeout=10).returncode == 0
    except Exception:  # noqa: BLE001 -- cannot tell: assume busy (a missed scan is cheap, a double run is not)
        return True


def _local_busy() -> bool:
    return _flag_busy() or _ticket_process_alive()


def _select_for_profile(profile: dict):
    """A machine the profile allows, that is free, and (if it is this one) has the tools its required
    checks need. Other machines are trusted to be what the profile says they are; a ticket that proves
    otherwise is released without blame (run_ticket's EnvMissing path)."""
    for device in profile.get("machines", []):
        selected = select_machine(device)
        if selected is None:
            continue
        if selected[1].get("is_self"):
            # An explicit target skips the busy check for THIS machine (select_machine only checks other
            # machines then), so check it here: never start a second ticket on top of a running one.
            if _local_busy() or pp.missing_here(profile):
                continue
        return selected
    return None


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    if dry_run:  # a preview records nothing
        _scan(lambda *a, **k: None, dry_run=True)
        return
    import job_events
    import machine_profile
    import scanner_role
    go, why = scanner_role.should_scan()   # primary/standby: the standby only scans when the primary has gone quiet
    if not go:
        print(f"{LOG_PREFIX} not scanning ({why})", file=sys.stderr)
        return
    print(f"{LOG_PREFIX} scanning ({why})", file=sys.stderr)
    with job_events.job_run("ticket-pipeline", "Ticket pipeline (hourly scan)") as run:
        _scan(run, dry_run=False)
    scanner_role.write_heartbeat(machine_profile.registry_id())


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

    if not dry_run:
        step("Conflicted PRs", "sending back PRs that no longer merge")
        sent = _requeue_all([REPO, *pp.dispatchable_repos()])
        step("Conflicted PRs", ", ".join(sent) + " sent back" if sent else "none")

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
    selected = _select_for_profile(profile if other else {"machines": list(MARVIN_MACHINES)})
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
