"""Tests for ticket_pipeline.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_pipeline.py -v
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import pytest  # noqa: E402

import ticket_pipeline as tp  # noqa: E402


@pytest.fixture(autouse=True)
def _no_rate_limit_backoff_by_default(monkeypatch):
    # Every test below exercises the claim/dispatch path, not the backoff
    # gate itself -- default to "no backoff active" so they don't depend on
    # this machine's real ~/.claude/rate-limit-backoff.json state. The
    # backoff-specific tests override this explicitly.
    monkeypatch.setattr(tp.rate_limit_backoff, "active_backoff", lambda: None)


def _issue(number, created, labels=(), title="a ticket"):
    return {"number": number, "title": title, "createdAt": created,
            "labels": [{"name": l} for l in labels]}


def test_unclaimed_ready_tickets_filters_out_claimed(monkeypatch):
    import json
    issues = [
        _issue(1, "2026-01-01T00:00:00Z", labels=["ready-for-agent", "claimed:mac-mini"]),
        _issue(2, "2026-01-02T00:00:00Z", labels=["ready-for-agent"]),
    ]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    result = tp._unclaimed_ready_tickets()
    assert [i["number"] for i in result] == [2]


def test_unclaimed_ready_tickets_sorted_oldest_first(monkeypatch):
    import json
    issues = [
        _issue(5, "2026-03-01T00:00:00Z"),
        _issue(3, "2026-01-01T00:00:00Z"),
        _issue(4, "2026-02-01T00:00:00Z"),
    ]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    result = tp._unclaimed_ready_tickets()
    assert [i["number"] for i in result] == [3, 4, 5]


def test_unclaimed_ready_tickets_returns_empty_on_gh_failure(monkeypatch):
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=1, stdout="", stderr="not authenticated"))
    assert tp._unclaimed_ready_tickets() == []


def test_label_for_device():
    assert tp._label_for_device("mac-mini-1") == "mac-mini"
    assert tp._label_for_device("macbook-pro-1") == "macbook-pro"


def test_main_skips_dispatch_entirely_when_rate_limit_backoff_is_active(monkeypatch, capsys):
    # Real incident, 2026-09-01: without this check, a rate-limited ticket's
    # released claim was immediately picked back up by the very next
    # ticket_pipeline.py run (fired via run_ticket.py's own
    # _trigger_redispatch), re-hitting the identical account-wide limit
    # every ~30s -- checked before the `gh issue list` scan so a backoff
    # window doesn't even cost an API call.
    backoff_until = datetime(2026, 9, 1, 22, 50, tzinfo=timezone.utc)
    monkeypatch.setattr(tp.rate_limit_backoff, "active_backoff", lambda: backoff_until)
    scan_calls = []
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: scan_calls.append(True) or [])
    dispatch_calls = []
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: dispatch_calls.append((a, kw)))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    tp.main()

    assert scan_calls == []
    assert dispatch_calls == []
    assert "backoff" in capsys.readouterr().err.lower()


def test_main_dispatches_normally_when_no_backoff_is_active(monkeypatch):
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [
        {"number": 20, "title": "x", "createdAt": "2026-01-01T00:00:00Z", "labels": []}
    ])
    monkeypatch.setattr(tp, "select_machine", lambda: ("macbook-pro-1", {"is_self": True}))
    monkeypatch.setattr(tp, "_claim", lambda n, l: True)
    dispatch_calls = []
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: dispatch_calls.append((a, kw)) or
                         SimpleNamespace(ok=True, device_id="macbook-pro-1"))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    tp.main()

    assert len(dispatch_calls) == 1


def test_main_dry_run_does_not_claim_or_dispatch(monkeypatch, capsys):
    import json
    issues = [_issue(20, "2026-01-01T00:00:00Z", labels=["ready-for-agent"])]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    monkeypatch.setattr(tp, "select_machine", lambda: ("macbook-pro-1", {"is_self": True}))
    claim_calls = []
    monkeypatch.setattr(tp, "_claim", lambda n, l: claim_calls.append((n, l)) or True)
    dispatch_calls = []
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: dispatch_calls.append((a, kw)))

    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py", "--dry-run"])
    tp.main()

    assert claim_calls == []
    assert dispatch_calls == []
    assert "dry-run" in capsys.readouterr().err


def test_main_no_tickets_does_nothing(monkeypatch, capsys):
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [])
    dispatch_calls = []
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: dispatch_calls.append((a, kw)))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])
    tp.main()
    assert dispatch_calls == []
    assert "no unclaimed" in capsys.readouterr().err


def test_main_no_machine_available_does_not_claim(monkeypatch, capsys):
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [
        {"number": 20, "title": "x", "createdAt": "2026-01-01T00:00:00Z", "labels": []}
    ])
    monkeypatch.setattr(tp, "select_machine", lambda: None)
    claim_calls = []
    monkeypatch.setattr(tp, "_claim", lambda n, l: claim_calls.append((n, l)) or True)
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])
    tp.main()
    assert claim_calls == []
    assert "no machine currently available" in capsys.readouterr().err


def test_main_claims_and_dispatches_oldest_unclaimed(monkeypatch):
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [
        {"number": 20, "title": "paper-graph traversal", "createdAt": "2026-01-01T00:00:00Z", "labels": []}
    ])
    monkeypatch.setattr(tp, "select_machine", lambda: ("macbook-pro-1", {"is_self": True}))
    claim_calls = []
    monkeypatch.setattr(tp, "_claim", lambda n, l: claim_calls.append((n, l)) or True)
    dispatch_calls = []
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: dispatch_calls.append((a, kw)) or
                         SimpleNamespace(ok=True, device_id="macbook-pro-1"))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    tp.main()

    assert claim_calls == [(20, "macbook-pro")]
    assert len(dispatch_calls) == 1
    args, kwargs = dispatch_calls[0]
    assert kwargs["target"] == "macbook-pro-1"
    assert kwargs["mode"] == "async"
    assert "run_ticket.py 20" in args[0]
    assert "claude -p" not in args[0]  # no nested prompt-based session anymore (#95)


def test_main_releases_claim_if_dispatch_fails(monkeypatch):
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [
        {"number": 20, "title": "x", "createdAt": "2026-01-01T00:00:00Z", "labels": []}
    ])
    monkeypatch.setattr(tp, "select_machine", lambda: ("macbook-pro-1", {"is_self": True}))
    monkeypatch.setattr(tp, "_claim", lambda n, l: True)
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: SimpleNamespace(ok=False, error="boom"))
    release_calls = []
    monkeypatch.setattr(tp, "_release", lambda n, l: release_calls.append((n, l)))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    tp.main()

    assert release_calls == [(20, "macbook-pro")]


def test_build_wrapper_command_runs_run_ticket_script():
    command = tp._build_wrapper_command(20)
    assert tp.RUN_TICKET_SCRIPT in command
    assert f"{tp.RUN_TICKET_SCRIPT} 20" in command
    assert "dispatch_issue20.log" in command
