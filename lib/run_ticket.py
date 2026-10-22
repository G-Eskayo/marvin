#!/usr/bin/env python3
"""Drives one ticket through execute_ticket -> raise_mr end to end
(G-Eskayo/marvin#95). This is the actual shell command ticket_pipeline.py
hands to task_dispatch -- split into its own script rather than inlined
into ticket_pipeline.py's dispatch command, since task_dispatch runs an
arbitrary shell command (potentially over SSH on a remote machine), not a
local Python function call.

Run standalone: ~/.agents/venv/bin/python run_ticket.py <issue_number>
"""
from __future__ import annotations
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import functools  # noqa: E402
import machine_profile  # noqa: E402
import project_profile as pp  # noqa: E402
from build_type_measure import measure, test_command_for  # noqa: E402
from evidence_capture import capture_dev_evidence, capture_test_results, ticket_touches_ui, TestTimedOut  # noqa: E402
from mr_raiser import raise_mr  # noqa: E402
from sandbox_orchestration import execute_ticket, _default_executor, TaskListTooVague, ModelRunFailed  # noqa: E402
from cleanup_sweep import drop_build_output  # noqa: E402
from ticket_pipeline import _label_for_device, _release  # noqa: E402
import failure_breaker  # noqa: E402
import ticket_stages as ts  # noqa: E402
import redispatch_trigger  # noqa: E402
import ticket_policy  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402

REPO = "G-Eskayo/marvin"
FAILURE_MARKER = "Automated implementation did not pass verification"
TIMEOUT_MARKER = "Automated verification timed out"
MODEL_MARKER = "The model service was unavailable"
MAX_CONSECUTIVE_FAILURES = 3
MAX_CONSECUTIVE_RETRIES = 5   # failures and verify timeouts together: a timeout is no strike, but retries still end
DEFAULT_REVISIT_DAYS = 7  # how far in the future to park a ticket by default


def _machine_load() -> float | None:
    """This machine's 1-minute load average per core, or None when unreadable. A verify that timed out while the
    machine was loaded (#563: the M4 running a long engine test) should wait longer before trying again."""
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except (OSError, AttributeError):
        return None


def _retry_line(attempt: int) -> tuple[str, str]:
    """(when, hidden marker) for retry number `attempt`, stretched by this machine's load (ticket_policy)."""
    load = _machine_load()
    wait = ticket_policy.retry_backoff_s(attempt, load)
    at = datetime.now(timezone.utc) + timedelta(seconds=wait)
    when = f"{at.strftime('%H:%M UTC')} (in {round(wait / 60)} min" + (f", machine load {load:.1f}/core" if load and load > 1 else "") + ")"
    return when, ticket_policy.retry_marker(at)


def _comment_failure(issue_number: int, reason: str, repo: str = REPO, retry: tuple[str, str] | None = None) -> None:
    tail = f"\n\nIt goes back to the queue, not before {retry[0]}.\n{retry[1]}" if retry else ""
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body",
         f"{FAILURE_MARKER}: {reason}{tail}"],
        check=False,
    )


def _issue_comments(issue_number: int, repo: str = REPO) -> list | None:
    """The ticket's comments, or None when they can't be read (no gh, offline, garbage): callers then count nothing."""
    try:
        proc = subprocess.run(
            ["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", "comments"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if proc.returncode != 0:
            return None
        comments = json.loads(proc.stdout)["comments"]
    except Exception:  # noqa: BLE001 -- unreadable history must never crash the cleanup that follows
        return None
    return comments if isinstance(comments, list) else None


def _trailing_model_failures(issue_number: int, repo: str = REPO) -> int:
    """How many model-unavailable releases in a row this ticket has had (most recent first), for its backoff."""
    n = 0
    for c in reversed(_issue_comments(issue_number, repo) or []):
        if isinstance(c, dict) and MODEL_MARKER in str(c.get("body", "")):
            n += 1
        else:
            break
    return n


def _consecutive_failure_streak(issue_number: int, repo: str = REPO) -> int:
    """Count trailing automated-failure comments on this issue, most-recent
    first, stopping at the first non-matching comment (a human reply, a
    passing run, anything else). This is the cross-dispatch retry counter --
    deliberately not a local state file, so both machines agree on it for
    free via the shared issue thread, and a human commenting on the ticket
    (to redirect it, add context, anything) naturally resets the streak.

    Found live 2026-09-04..06: with no cap across separate run_ticket.py
    invocations, a release-claim-then-immediate-redispatch cycle on a
    genuinely-too-ambiguous ticket (#28) spun ~6,900 back-to-back headless
    sessions over 3 days with every attempt reaching an identical
    'unchanged' verdict -- max_iterations=3 only bounds iterations *inside*
    one execute_ticket call, nothing bounded the outer release/redispatch
    loop across calls.

    Timeouts are not strikes, but no longer reset the count either (P6, 2026-10-21); see _trailing_streaks."""
    return failure_breaker.ticket_streak(issue_number, project=repo)["count"]


def _trailing_streaks(issue_number: int, repo: str = REPO) -> tuple[int, int]:
    """(failures, verify timeouts) in the trailing run of automated comments, most recent first, up to the first
    comment from anyone else. Timeouts used to be free and to reset the failure count, so a ticket whose verify
    always times out was retried for ever (#563: three runs in 46 minutes on a loaded M4); now they have their own
    cap (MAX_CONSECUTIVE_RETRIES, with failures). A model-unavailable release is about the service: it is skipped,
    neither counted nor a reset."""
    failures = timeouts = 0
    for c in reversed(_issue_comments(issue_number, repo) or []):
        body = str(c.get("body", "")) if isinstance(c, dict) else ""
        if MODEL_MARKER in body:
            continue
        if FAILURE_MARKER in body:
            failures += 1
        elif TIMEOUT_MARKER in body:
            timeouts += 1
        else:
            break
    return failures, timeouts


PARKED_MARKER = "Parked after repeated failed builds"
MAX_PARK_FINDINGS = 15


def _park_stuck_ticket(issue_number: int, streak: int, repo: str = REPO, reason: str = "",
                       findings: list[str] | tuple = (), headline: str | None = None,
                       hold_data: dict | None = None) -> None:
    """Stop re-dispatching a ticket that keeps failing, and hand it to a person WITH the cause.

    When hold_data is set (from failure_breaker.should_hold), use 'hold' label (reuses the revisit system)
    instead of 'needs-info' (human action).
    needs-info is added before ready-for-agent comes off, so the ticket is never stateless: the triage agent treats
    a ticket with no state label as new, and would put a well-written one straight back to ready-for-agent (another
    round of builds; this comment resets the failure streak) or bury the cause under a template complaint (#133,
    2026-10-09). Triage only re-checks needs-info it set itself, so this one stays until a person acts."""
    label = _label_for_device(machine_profile.registry_id())
    state_label = "hold" if hold_data else "needs-info"
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", repo, "--add-label", state_label],
        capture_output=True, text=True, timeout=15, check=False,
    )
    subprocess.run(
        ["gh", "issue", "edit", str(issue_number), "--repo", repo,
         "--remove-label", "ready-for-agent",
         "--remove-label", f"claimed:{label}"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    # The claim is dropped too, not only ready-for-agent: ticket_pipeline only
    # dispatches ready-for-agent tickets with no claimed:* label, so a parked
    # ticket that kept its claim could never be revived by re-adding the label.
    shown = list(findings)[:MAX_PARK_FINDINGS]
    more = len(findings) - len(shown)
    lines = [headline or f"**{PARKED_MARKER}** ({streak} in a row), so it stops being re-dispatched.", "",
             f"**Why it's stuck:** {(reason or 'no reason was recorded')[:500]}"]
    if hold_data:
        # Retry storm: list the failure signatures that tripped the hold
        sigs = hold_data.get("signatures", [])
        if sigs:
            sig_summary = "; ".join(s["sig"] for s in sigs[-3:])
            lines += ["", f"**Failure patterns:** {sig_summary}"]
    if shown:
        lines += ["", "**Must-fix findings the builder could not clear:**", *[f"- {f}" for f in shown]]
        if more:
            lines.append(f"- ... and {more} more")
    lines += [""]
    if hold_data:
        # Use the revisit system for hold label
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        revisit_date = (datetime.now(timezone.utc) + timedelta(days=DEFAULT_REVISIT_DAYS)).strftime("%Y-%m-%d")
        lines.append(ticket_policy.format_revisit(revisit_date, hold_data.get("condition")))
    else:
        lines.append("**What it needs:** re-scope or split it, answer what's unclear, or build it by hand. "
                     "To send it back to the pipeline, remove `needs-info` and add `ready-for-agent`.")
    subprocess.run(
        ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body", "\n".join(lines)],
        capture_output=True, text=True, timeout=15, check=False,
    )
    # It is in the dashboard's Needs you now (needs-info) or on Hold; say so where Gil will see it, not only on the ticket.
    if not hold_data:
        try:
            import mr_notification
            mr_notification.notify_needs_you(f"{repo.split('/')[-1]}#{issue_number}", reason or "parked",
                                             f"https://github.com/{repo}/issues/{issue_number}")
        except Exception as exc:  # noqa: BLE001 -- a notification must never break the run's cleanup
            print(f"[run_ticket] needs-you notification failed: {exc}", file=sys.stderr)


def _release_claim(issue_number: int, repo: str = REPO, run_id: str | None = None) -> None:
    """A ticket that didn't raise a PR -- rate-limited, a worktree-creation
    failure, or genuinely never reached a passing comparison -- leaves this
    machine free again, but ticket_pipeline.py's claim happens before
    dispatch, with no way to know in advance whether the dispatch will
    actually produce anything. Without this, the claimed:<machine> label
    sticks around forever and the ticket is silently starved from ever
    being retried. Found live 2026-08-29: a redispatch cascade during a
    Claude usage-limit window left 28 tickets claimed with zero real work
    done, none of them ever eligible for retry again."""
    label = _label_for_device(machine_profile.registry_id())
    _release(issue_number, label, run_id=run_id) if repo == REPO else _release(issue_number, label, repo, run_id=run_id)


def _trigger_redispatch() -> None:
    """This machine has been free since execute_ticket returned above --
    win or lose, rather than sit idle until the next hourly
    ticket_pipeline.py cron tick, check for more unclaimed work right
    now. Uses redispatch_trigger's debounce so N simultaneous exits
    don't spawn N separate full scans, just one after a short delay.
    Fire-and-forget: ticket_pipeline.py already no-ops safely if
    nothing's unclaimed or no machine is free."""
    redispatch_trigger.request_scan()


def _load_catalog() -> dict:
    try:
        import project_catalog
        return project_catalog.read_catalog(project_catalog.catalog_path()) or {"projects": []}
    except Exception:  # noqa: BLE001 -- the profile's clone_hints still work without a catalog
        return {"projects": []}


def parse_ticket_arg(arg: str) -> tuple[str, int]:
    """'123' (marvin's, as before) or 'owner/repo#123'."""
    m = re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", arg.strip())
    if m:
        return m.group(1), int(m.group(2))
    if arg.strip().isdigit():
        return REPO, int(arg)
    raise ValueError(f"expected a ticket number or owner/repo#number, got {arg!r}")


# marvin has no profile (project_profile.py), so its regenerable build output is listed here; another
# project lists its own under "build_output" in config/projects/<name>.json.
MARVIN_BUILD_OUTPUT = ["dashboard/node_modules"]


def _drop_build_output(worktree_path, profile: dict | None) -> None:
    """A finished run's worktree stays until its PR merges (cleanup_sweep), so drop the build output now:
    found 2026-10-06, 2.1 GiB of SwiftPM .build per clarity worktree. Best effort: never fails the run."""
    if worktree_path is None:
        return
    try:
        drop_build_output(Path(worktree_path), profile.get("build_output", []) if profile else MARVIN_BUILD_OUTPUT)
    except Exception as exc:
        print(f"[run_ticket] could not drop build output in {worktree_path}: {exc}", file=sys.stderr)


def run(issue_number: int, repo: str = REPO) -> dict:
    ticket_ref = f"{repo}#{issue_number}"
    other = repo != REPO
    # marvin's path is called exactly as it always was; another project's calls carry its repo so its
    # stage records, claim label, comments and breaker entries stay its own.
    kw = {"repo": repo} if other else {}
    run_id = os.environ.get("MARVIN_RUN_ID")
    profile = pp.load_profile(repo) if other else None
    subsystem = f"ticket-{issue_number}" if not other else f"{repo.split('/')[-1].lower()}-ticket-{issue_number}"
    measurer = None
    worktree_path = None
    findings: list[str] = []  # the last must-fix review findings, for the park comment

    try:
        if other and profile is None:
            outcome = {"raised": False, "pr_url": None, "reason": f"{repo} has no execution profile (config/projects/), so the pipeline cannot run its tickets"}
        else:
            if profile is None:
                result = execute_ticket(ticket_ref, subsystem, measure)
            else:
                clone = pp.resolve_clone(profile, _load_catalog(), ensure=True)
                if clone is None:
                    raise RuntimeError(f"no local clone of {repo} found on this machine (catalog and clone_hints)")
                measurer = pp.Measurer(profile)
                result = execute_ticket(
                    ticket_ref, subsystem, measurer,
                    executor=functools.partial(_default_executor, profile=profile, clone=clone, env=measurer.env),
                    repo_path=clone, base_branch=profile["base_branch"],
                )

            worktree_path = result.get("worktree_path")
            findings = list((result.get("final_comparison") or {}).get("fix_these") or [])
            test_results = None
            dev_evidence = None
            if result["passing"]:
                if measurer is None:
                    command = test_command_for(worktree_path)
                    test_results = capture_test_results(worktree_path, command)
                    dev_evidence = capture_dev_evidence(worktree_path, ticket_touches_ui(worktree_path))
                else:
                    test_results, dev_evidence = measurer.evidence(worktree_path)
                    if test_results is not None:
                        test_results["notes"] = measurer.pr_note()

            outcome = raise_mr(ticket_ref, result, test_results=test_results, dev_evidence=dev_evidence)
    except pp.EnvMissing as exc:
        # This machine lacks a tool the project's required check needs. That is about the machine, not the
        # ticket: no comment, no strike, no breaker entry; the claim goes back so a capable machine can take it.
        outcome = {"raised": False, "pr_url": None, "reason": str(exc), "env_missing": True}
    except TestTimedOut as exc:
        # A test or setup step exceeded its timeout: the BUILD MACHINE ran out of time, not the PR's code.
        # Like env_missing, this is not a ticket failure: release the claim, post a timeout comment (for
        # visibility), and redispatch so another machine can try.
        reason = str(exc)
        outcome = {"raised": False, "pr_url": None, "reason": reason, "timed_out": True}
    except ModelRunFailed as exc:
        # The model service failed (a usage limit, an outage): not the ticket's fault, so no strike. Release the
        # claim with a backoff; the breaker still counts it, so a window that fails every ticket pauses dispatch.
        outcome = {"raised": False, "pr_url": None, "reason": str(exc), "model_unavailable": True}
    except TaskListTooVague as exc:
        # The planner said the ticket is too vague: a person must answer, so it is parked in Needs you. It used to
        # keep its claim "so it isn't re-dispatched", which hid it from everyone: ten tickets sat 5-11 days (P6).
        # A plan that merely lacks its Task List is a bad run, handled like any failure below.
        outcome = {"raised": False, "pr_url": None, "reason": str(exc), "too_vague": exc.needs_person}
    except Exception as exc:
        # A crash anywhere in execute_ticket/raise_mr (a planner timeout, a
        # worktree-creation failure, anything) must never skip the cleanup
        # below -- found live 2026-08-31: two tickets in a row hit the
        # planner's 300s subprocess timeout, an uncaught exception that
        # crashed the whole process before it ever reached
        # raise_mr/_comment_failure/_release_claim/_trigger_redispatch,
        # leaving both permanently claimed with no way to retry.
        outcome = {"raised": False, "pr_url": None, "reason": f"Unhandled exception: {exc}"}

    _drop_build_output(worktree_path, profile)

    if not outcome["raised"]:
        if outcome.get("env_missing"):
            _release_claim(issue_number, **kw, run_id=run_id)
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
            _trigger_redispatch()
            return outcome
        if outcome.get("model_unavailable"):
            when, marker = _retry_line(_trailing_model_failures(issue_number, **kw) + 1)
            _release_claim(issue_number, **kw, run_id=run_id)
            subprocess.run(
                ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body",
                 f"{MODEL_MARKER}: {outcome['reason'][:300]}\n\nNothing is wrong with this ticket: the claim is released "
                 f"and it goes back to the queue, not before {when}.\n{marker}"],
                check=False,
            )
            failure_breaker.record_failure(issue_number, outcome["reason"], **({"project": repo} if other else {}))
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
            _trigger_redispatch()
            return outcome
        if outcome.get("timed_out"):
            tries = sum(_trailing_streaks(issue_number, **kw)) + 1
            ts.record_stage(issue_number, "verifying", "failed", outcome["reason"][:300], **kw)
            if tries >= MAX_CONSECUTIVE_RETRIES:
                _park_stuck_ticket(issue_number, tries, **kw, reason=outcome["reason"])
                ts.record_stage(issue_number, "done", "failed", f"parked after {tries} consecutive failed or timed-out runs", **kw)
                _trigger_redispatch()
                return outcome
            when, marker = _retry_line(tries)
            _release_claim(issue_number, **kw, run_id=run_id)
            subprocess.run(
                ["gh", "issue", "comment", str(issue_number), "--repo", repo, "--body",
                 f"{TIMEOUT_MARKER}: {outcome['reason']}\n\nIt goes back to the queue, not before {when}.\n{marker}"],
                check=False,
            )
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
            _trigger_redispatch()
            return outcome
        if outcome.get("too_vague"):
            _park_stuck_ticket(issue_number, 1, **kw, reason=outcome["reason"],
                               headline="**The planner says this ticket is too vague to build**, so it is handed to a person "
                                        "instead of being retried.")
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
            _trigger_redispatch()
            return outcome
        prior_streak = _consecutive_failure_streak(issue_number, **kw)
        # Record this failure immediately.
        failure_breaker.record_failure(issue_number, outcome["reason"], **({"project": repo} if other else {}))
        # Check if the retry-storm detector should hold this ticket.
        threshold = (profile or {}).get("failure_threshold") or MAX_CONSECUTIVE_FAILURES
        new_count = prior_streak + 1
        # Read streak info once for both checks
        streak_info = failure_breaker.ticket_streak(issue_number, project=repo)
        sigs = streak_info.get("signatures", [])
        # Count-based threshold check: the primary guard
        parking = new_count >= threshold
        # Repeated-signature check: adds to, never replaces, the count-based decision
        if not parking and len(sigs) >= 2 and sigs[-2].get("sig") == sigs[-1].get("sig"):
            parking = True
        # Construct hold_data locally if parking
        hold_data = None
        if parking:
            sig_names = [s.get("sig", "unknown") for s in sigs[-threshold:]] if threshold and sigs else []
            hold_data = {
                "count": new_count,
                "condition": f"failed {new_count} times with {', '.join(set(sig_names))}" if new_count >= threshold else "repeated failure: " + (sigs[-1].get("sig", "unknown") if sigs else "unknown")
            }
        _comment_failure(issue_number, outcome["reason"], **kw, **({} if parking else {"retry": _retry_line(new_count)}))
        if parking:
            _park_stuck_ticket(issue_number, new_count, **kw, reason=outcome["reason"], findings=findings, hold_data=hold_data)
            ts.record_stage(issue_number, "done", "failed", f"parked after {new_count} consecutive failures", **kw)
        else:
            _release_claim(issue_number, **kw, run_id=run_id)
            ts.record_stage(issue_number, "done", "failed", outcome["reason"][:300], **kw)
    else:
        ts.record_stage(issue_number, "done", "passed", f"PR raised: {outcome['pr_url']}", **kw)
        failure_breaker.record_success(issue_number, **({"project": repo} if other else {}))  # proves this project's environment works

    _trigger_redispatch()

    return outcome


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: run_ticket.py <issue_number | owner/repo#issue_number>", file=sys.stderr)
        sys.exit(1)
    try:
        repo, number = parse_ticket_arg(sys.argv[1])
    except ValueError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    outcome = run(number, repo) if repo != REPO else run(number)
    print(outcome)
    sys.exit(0 if outcome["raised"] else 1)


if __name__ == "__main__":
    main()
