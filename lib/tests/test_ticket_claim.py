"""Tests for ticket_claim.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_claim.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import ticket_claim as tc  # noqa: E402


def _issue(number, labels):
    return {"number": number, "labels": labels}


# ── queue-depth cap ──────────────────────────────────────────────────────────

def test_claims_nothing_when_at_cap(monkeypatch):
    add_calls = []
    result = tc.claim_next_ticket(
        "mac-mini",
        list_claimed=lambda machine: [_issue(1, []), _issue(2, []), _issue(3, [])],
        list_unclaimed_ready=lambda: [_issue(4, [])],
        add_claim_label=lambda n, m: add_calls.append((n, m)),
    )
    assert result is None
    assert add_calls == []


def test_claims_when_under_cap(monkeypatch):
    add_calls = []
    result = tc.claim_next_ticket(
        "mac-mini",
        list_claimed=lambda machine: [_issue(1, [])],
        list_unclaimed_ready=lambda: [_issue(5, [])],
        add_claim_label=lambda n, m: add_calls.append((n, m)),
    )
    assert result == 5
    assert add_calls == [(5, "mac-mini")]


def test_cap_is_exactly_three(monkeypatch):
    # exactly 3 claimed -> still at cap, claims nothing
    result_at_3 = tc.claim_next_ticket(
        "mac-mini",
        list_claimed=lambda machine: [_issue(1, []), _issue(2, []), _issue(3, [])],
        list_unclaimed_ready=lambda: [_issue(4, [])],
        add_claim_label=lambda n, m: None,
    )
    assert result_at_3 is None

    # exactly 2 claimed -> under cap, claims
    result_at_2 = tc.claim_next_ticket(
        "mac-mini",
        list_claimed=lambda machine: [_issue(1, []), _issue(2, [])],
        list_unclaimed_ready=lambda: [_issue(4, [])],
        add_claim_label=lambda n, m: None,
    )
    assert result_at_2 == 4


# ── priority-ordered claim selection (oldest issue number first) ───────────

def test_claims_lowest_issue_number_first():
    result = tc.claim_next_ticket(
        "mac-mini",
        list_claimed=lambda machine: [],
        list_unclaimed_ready=lambda: [_issue(9, []), _issue(3, []), _issue(7, [])],
        add_claim_label=lambda n, m: None,
    )
    assert result == 3


def test_returns_none_when_nothing_unclaimed_available():
    result = tc.claim_next_ticket(
        "mac-mini",
        list_claimed=lambda machine: [],
        list_unclaimed_ready=lambda: [],
        add_claim_label=lambda n, m: None,
    )
    assert result is None


# ── claim isolation per machine ─────────────────────────────────────────────

def test_count_claimed_only_counts_this_machines_claims():
    captured = {}
    tc.claim_next_ticket(
        "mac-mini",
        list_claimed=lambda machine: captured.setdefault("machine_arg", machine) or [],
        list_unclaimed_ready=lambda: [_issue(1, [])],
        add_claim_label=lambda n, m: None,
    )
    assert captured["machine_arg"] == "mac-mini"


# ── release ──────────────────────────────────────────────────────────────────

def test_release_calls_remove_claim_label():
    calls = []
    tc.release(42, "mac-mini", remove_claim_label=lambda n, m: calls.append((n, m)))
    assert calls == [(42, "mac-mini")]


# ── default gh-backed hooks (mocked subprocess) ─────────────────────────────

def test_default_list_claimed_filters_by_claim_label(monkeypatch):
    def fake_run(cmd, **kwargs):
        class R:
            stdout = '[{"number": 7, "labels": [{"name": "claimed:mac-mini"}, {"name": "ready-for-agent"}]}]'
            returncode = 0
        return R()
    monkeypatch.setattr(tc.subprocess, "run", fake_run)
    result = tc._default_list_claimed("mac-mini")
    assert result == [{"number": 7, "labels": [{"name": "claimed:mac-mini"}, {"name": "ready-for-agent"}]}]


def test_default_list_unclaimed_ready_excludes_any_claimed_label(monkeypatch):
    def fake_run(cmd, **kwargs):
        class R:
            stdout = (
                '[{"number": 1, "labels": [{"name": "ready-for-agent"}], "body": "## Parent\\n#1"},'
                ' {"number": 2, "labels": [{"name": "ready-for-agent"}, {"name": "claimed:macbook-pro"}], "body": "## Parent\\n#1"}]'
            )
            returncode = 0
        return R()
    monkeypatch.setattr(tc.subprocess, "run", fake_run)
    result = tc._default_list_unclaimed_ready()
    assert [i["number"] for i in result] == [1]


def test_default_list_unclaimed_ready_excludes_parent_prds_without_parent_section(monkeypatch):
    # found via a real live-fire test: claim_next_ticket claimed #1, the
    # parent PRD itself, because it still had ready-for-agent and nothing
    # distinguished it from a real, atomic, executable ticket.
    def fake_run(cmd, **kwargs):
        class R:
            stdout = (
                '[{"number": 1, "labels": [{"name": "ready-for-agent"}], "body": "## Problem Statement\\n..."},'
                ' {"number": 2, "labels": [{"name": "ready-for-agent"}], "body": "## Parent\\nG-Eskayo/marvin#1"}]'
            )
            returncode = 0
        return R()
    monkeypatch.setattr(tc.subprocess, "run", fake_run)
    result = tc._default_list_unclaimed_ready()
    assert [i["number"] for i in result] == [2]


def test_default_add_claim_label_invokes_gh(monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()
    monkeypatch.setattr(tc.subprocess, "run", fake_run)
    tc._default_add_claim_label(5, "mac-mini")
    cmd = calls[0]
    assert "5" in cmd
    assert "claimed:mac-mini" in cmd


def test_default_add_claim_label_creates_label_if_missing(monkeypatch):
    # found via a real live-fire test: gh issue edit --add-label fails
    # outright if the label doesn't already exist as a real repo label.
    calls = []
    attempts = {"edit": 0}

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            pass
        r = R()
        r.stdout = ""
        if cmd[1] == "issue":
            attempts["edit"] += 1
            if attempts["edit"] == 1:
                r.returncode = 1
                r.stderr = "gh: label 'claimed:mac-mini' not found"
            else:
                r.returncode = 0
                r.stderr = ""
        else:
            r.returncode = 0
            r.stderr = ""
        return r

    monkeypatch.setattr(tc.subprocess, "run", fake_run)
    tc._default_add_claim_label(5, "mac-mini")

    assert any(cmd[1] == "label" and cmd[2] == "create" for cmd in calls)
    assert attempts["edit"] == 2  # first failed, retried after label create succeeded


def test_default_remove_claim_label_invokes_gh(monkeypatch):
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
        return R()
    monkeypatch.setattr(tc.subprocess, "run", fake_run)
    tc._default_remove_claim_label(5, "mac-mini")
    cmd = calls[0]
    assert "5" in cmd
    assert "claimed:mac-mini" in cmd


# ── run_claim_cycle: hands claimed ticket to sandbox orchestration ─────────

def test_run_claim_cycle_hands_off_to_execute_when_claimed():
    execute_calls = []
    result = tc.run_claim_cycle(
        machine_id="mac-mini",
        claim=lambda machine_id: 5,
        execute=lambda ticket_ref: execute_calls.append(ticket_ref) or {"passing": True},
    )
    assert execute_calls == ["G-Eskayo/marvin#5"]
    assert result["claimed"] == "G-Eskayo/marvin#5"
    assert result["execution_result"] == {"passing": True}


def test_run_claim_cycle_does_nothing_when_nothing_claimed():
    execute_calls = []
    result = tc.run_claim_cycle(
        machine_id="mac-mini",
        claim=lambda machine_id: None,
        execute=lambda ticket_ref: execute_calls.append(ticket_ref),
    )
    assert execute_calls == []
    assert result["claimed"] is None
    assert result["execution_result"] is None
