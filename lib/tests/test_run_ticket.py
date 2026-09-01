"""Tests for run_ticket.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_run_ticket.py -v
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import run_ticket as rt  # noqa: E402
from rate_limit_backoff import RateLimited  # noqa: E402


def _passing_result(worktree_path=Path("/tmp/fake-worktree")):
    return {
        "passing": True, "worktree_path": worktree_path, "iterations": 1,
        "final_comparison": {"subsystem": "ticket-20", "verdict": "improved", "metrics": {}},
        "explanation": None,
    }


def _failing_result():
    return {
        "passing": False, "worktree_path": Path("/tmp/fake-worktree"), "iterations": 3,
        "final_comparison": {"subsystem": "ticket-20", "verdict": "unchanged", "metrics": {}},
        "explanation": "Did not reach a passing comparison after 3 iterations.",
    }


def test_run_calls_execute_ticket_with_the_right_ticket_ref_and_subsystem(monkeypatch):
    captured = {}

    def fake_execute_ticket(ticket_ref, subsystem, measure_fn):
        captured["ticket_ref"] = ticket_ref
        captured["subsystem"] = subsystem
        captured["measure_fn"] = measure_fn
        return _passing_result()

    monkeypatch.setattr(rt, "execute_ticket", fake_execute_ticket)
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {"suite": "pytest", "passed": 1, "failed": 0, "total": 1})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {"na": True, "reason": "no UI"})
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": True, "pr_url": "http://fake-pr", "reason": None})
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    rt.run(20)

    assert captured["ticket_ref"] == "G-Eskayo/marvin#20"
    assert captured["subsystem"] == "ticket-20"
    assert captured["measure_fn"] is rt.measure


def test_run_captures_test_results_and_dev_evidence_on_a_passing_result(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {"suite": "pytest", "passed": 11, "failed": 0, "total": 11})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {"na": True, "reason": "no UI"})

    captured = {}

    def fake_raise_mr(ticket_ref, execution_result, test_results=None, dev_evidence=None):
        captured["test_results"] = test_results
        captured["dev_evidence"] = dev_evidence
        return {"raised": True, "pr_url": "http://fake-pr", "reason": None}

    monkeypatch.setattr(rt, "raise_mr", fake_raise_mr)
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    rt.run(20)

    assert captured["test_results"] == {"suite": "pytest", "passed": 11, "failed": 0, "total": 11}
    assert captured["dev_evidence"] == {"na": True, "reason": "no UI"}


def test_run_skips_evidence_capture_on_a_failing_result(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    capture_calls = []
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: capture_calls.append("test_results") or {})
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: capture_calls.append("dev_evidence") or {})

    captured = {}

    def fake_raise_mr(ticket_ref, execution_result, test_results=None, dev_evidence=None):
        captured["test_results"] = test_results
        captured["dev_evidence"] = dev_evidence
        return {"raised": False, "pr_url": None, "reason": "did not pass"}

    monkeypatch.setattr(rt, "raise_mr", fake_raise_mr)
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: None)
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    rt.run(20)

    assert capture_calls == []
    assert captured["test_results"] is None
    assert captured["dev_evidence"] is None


def test_run_comments_the_failure_reason_when_not_raised(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "3 iterations exhausted"})
    monkeypatch.setattr(rt, "_release_claim", lambda *a: None)

    comments = []
    monkeypatch.setattr(rt, "_comment_failure", lambda issue_number, reason: comments.append((issue_number, reason)))
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    rt.run(20)

    assert comments == [(20, "3 iterations exhausted")]


def test_run_releases_the_claim_when_not_raised(monkeypatch):
    # G-Eskayo/marvin's real incident: 28 tickets got claimed then hit
    # Claude's own session/usage limit inside the nested planner/executor
    # calls, correctly did no work and returned raised=False -- but nothing
    # released claimed:<machine>, so every one of them was silently starved
    # from ever being retried by ticket_pipeline.py again.
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "nope"})
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: None)
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    released = []
    monkeypatch.setattr(rt, "_release_claim", lambda issue_number: released.append(issue_number))

    rt.run(20)

    assert released == [20]


def test_run_does_not_release_a_claim_on_a_successful_raise(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {})
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": True, "pr_url": "http://fake-pr", "reason": None})
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    released = []
    monkeypatch.setattr(rt, "_release_claim", lambda issue_number: released.append(issue_number))

    rt.run(20)

    assert released == []


def test_release_claim_removes_the_label_for_this_machine(monkeypatch):
    monkeypatch.setattr(rt.machine_profile, "registry_id", lambda: "mac-mini-2")

    released = []
    monkeypatch.setattr(rt, "_release", lambda issue_number, label: released.append((issue_number, label)))

    rt._release_claim(20)

    assert released == [(20, "mac-mini")]


def test_run_does_not_comment_on_a_successful_raise(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {})
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": True, "pr_url": "http://fake-pr", "reason": None})

    comments = []
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: comments.append(a))
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    rt.run(20)

    assert comments == []


def test_comment_failure_calls_gh_issue_comment(monkeypatch):
    calls = []
    monkeypatch.setattr(rt.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    rt._comment_failure(20, "boom")
    assert calls[0][:4] == ["gh", "issue", "comment", "20"]
    assert "boom" in calls[0][-1]


def test_run_triggers_redispatch_on_a_successful_raise(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {})
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": True, "pr_url": "http://fake-pr", "reason": None})

    calls = []
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: calls.append(True))

    rt.run(20)

    assert calls == [True]


def test_run_triggers_redispatch_even_when_not_raised(monkeypatch):
    # The machine is free either way -- a failed/non-passing ticket
    # shouldn't leave it idle until the next hourly cron tick either.
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "nope"})
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: None)

    calls = []
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: calls.append(True))

    rt.run(20)

    assert calls == [True]


def test_trigger_redispatch_spawns_ticket_pipeline_detached(monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            calls.append((cmd, kwargs))

    monkeypatch.setattr(rt.subprocess, "Popen", FakePopen)
    rt._trigger_redispatch()

    cmd, kwargs = calls[0]
    assert cmd[0] == rt.sys.executable
    assert cmd[1].endswith("ticket_pipeline.py")
    assert kwargs.get("start_new_session") is True


def test_run_recovers_when_execute_ticket_raises_unexpectedly(monkeypatch):
    # Real incident, 2026-08-31: the planner subprocess call inside
    # execute_ticket hit its own 300s timeout for two tickets in a row
    # (subprocess.TimeoutExpired, uncaught) -- run() had no try/except
    # around execute_ticket at all, so the whole process crashed before
    # ever reaching raise_mr/_comment_failure/_release_claim/
    # _trigger_redispatch. Both tickets stayed claimed forever, exactly
    # the failure mode _release_claim was built to prevent, just reached
    # through a different, uncaught path.
    def raise_timeout(*a, **kw):
        raise TimeoutExpired(cmd=["claude"], timeout=300)

    monkeypatch.setattr(rt, "execute_ticket", raise_timeout)

    comments = []
    monkeypatch.setattr(rt, "_comment_failure", lambda issue_number, reason: comments.append((issue_number, reason)))
    released = []
    monkeypatch.setattr(rt, "_release_claim", lambda issue_number: released.append(issue_number))
    redispatched = []
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: redispatched.append(True))

    outcome = rt.run(27)

    assert outcome["raised"] is False
    assert "300" in outcome["reason"] or "timed out" in outcome["reason"].lower()
    assert comments == [(27, outcome["reason"])]
    assert released == [27]
    assert redispatched == [True]


def test_run_releases_claim_but_does_not_comment_when_rate_limited(monkeypatch):
    # Real incident, 2026-09-01: ticket #29's session-limit message got
    # threaded through as fake plan content and the normal not-raised path
    # (issue comment + release + immediate redispatch) turned into a
    # redispatch cascade every ~30s. A rate limit isn't a real failure of
    # the ticket, so it shouldn't post a misleading "did not pass
    # verification" comment on the issue the way a genuine failure does.
    backoff_until = datetime(2026, 9, 1, 22, 50, tzinfo=timezone.utc)

    def raise_rate_limited(*a, **kw):
        raise RateLimited(backoff_until, "You've hit your session limit")

    monkeypatch.setattr(rt, "execute_ticket", raise_rate_limited)

    comments = []
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: comments.append(a))
    released = []
    monkeypatch.setattr(rt, "_release_claim", lambda issue_number: released.append(issue_number))
    redispatched = []
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: redispatched.append(True))

    outcome = rt.run(29)

    assert outcome["raised"] is False
    assert "backing off" in outcome["reason"].lower()
    assert comments == []
    assert released == [29]
    assert redispatched == [True]


def test_run_recovers_when_raise_mr_itself_raises_unexpectedly(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {})

    def raise_boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(rt, "raise_mr", raise_boom)

    released = []
    monkeypatch.setattr(rt, "_release_claim", lambda issue_number: released.append(issue_number))
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: None)
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    outcome = rt.run(27)

    assert outcome["raised"] is False
    assert "boom" in outcome["reason"]
    assert released == [27]
