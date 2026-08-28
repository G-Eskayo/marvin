"""Tests for run_ticket.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_run_ticket.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import run_ticket as rt  # noqa: E402


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

    rt.run(20)

    assert capture_calls == []
    assert captured["test_results"] is None
    assert captured["dev_evidence"] is None


def test_run_comments_the_failure_reason_when_not_raised(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "3 iterations exhausted"})

    comments = []
    monkeypatch.setattr(rt, "_comment_failure", lambda issue_number, reason: comments.append((issue_number, reason)))

    rt.run(20)

    assert comments == [(20, "3 iterations exhausted")]


def test_run_does_not_comment_on_a_successful_raise(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {})
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": True, "pr_url": "http://fake-pr", "reason": None})

    comments = []
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: comments.append(a))

    rt.run(20)

    assert comments == []


def test_comment_failure_calls_gh_issue_comment(monkeypatch):
    calls = []
    monkeypatch.setattr(rt.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    rt._comment_failure(20, "boom")
    assert calls[0][:4] == ["gh", "issue", "comment", "20"]
    assert "boom" in calls[0][-1]
