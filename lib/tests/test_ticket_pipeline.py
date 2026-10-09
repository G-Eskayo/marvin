"""Tests for ticket_pipeline.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_pipeline.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import time
import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import ticket_pipeline as tp  # noqa: E402
import ticket_stages as ts  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_ticket_stages(tmp_path, monkeypatch):
    # _claim()'s new ts.record_stage("claimed", ...) call writes real
    # files by default -- same isolation fix as test_run_ticket.py, same
    # root cause.
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path / "ticket-stages")
    # Isolate the scan lock so tests never touch the real production lock file
    monkeypatch.setattr(tp, "SCAN_LOCK_PATH", tmp_path / "scan.lock")


@pytest.fixture(autouse=True)
def _scan_as_the_primary(monkeypatch):
    """main() asks scanner_role whether this machine should scan. On the macbook (the standby, with the mac-mini's heartbeat fresh)
    the answer is no, which made 13 of these tests fail there and not on the mac-mini. The tests are about what a scan does, so
    they scan as the primary; the standby rule has its own tests (test_scanner_role.py)."""
    import scanner_role
    monkeypatch.setattr(scanner_role, "should_scan", lambda: (True, "primary"))
    monkeypatch.setattr(scanner_role, "write_heartbeat", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _parallel_dispatch_off_unless_a_test_says_otherwise(monkeypatch):
    """config/dispatch.json is the dashboard's setting and may be on on this machine; these tests are about what a scan
    does by default. The parallel rules have their own tests below."""
    monkeypatch.setattr(tp.dispatch_concurrency, "load", lambda path=None: json.loads(json.dumps(tp.dispatch_concurrency.DEFAULTS)))


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
        _issue(5, "2026-03-01T00:00:00Z", labels=["ready-for-agent"]),
        _issue(3, "2026-01-01T00:00:00Z", labels=["ready-for-agent"]),
        _issue(4, "2026-02-01T00:00:00Z", labels=["ready-for-agent"]),
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


def test_main_dry_run_does_not_claim_or_dispatch(monkeypatch, capsys):
    import json
    issues = [_issue(20, "2026-01-01T00:00:00Z", labels=["ready-for-agent"])]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    monkeypatch.setattr(tp, "select_machine", lambda target=None: ("mac-mini-1", {"is_self": True}))
    claim_calls = []
    monkeypatch.setattr(tp, "_claim", lambda n, l, **kw: claim_calls.append((n, l)) or True)
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
    monkeypatch.setattr(tp, "select_machine", lambda target=None: None)
    claim_calls = []
    monkeypatch.setattr(tp, "_claim", lambda n, l, **kw: claim_calls.append((n, l)) or True)
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])
    tp.main()
    assert claim_calls == []
    assert "no machine currently available" in capsys.readouterr().err


def test_claim_records_the_title_on_the_claimed_stage_event(monkeypatch, tmp_path):
    # Feedback, 2026-10-01: a bare ticket number is opaque -- this is the
    # one place in the flow that has the real GitHub title, so it's the
    # one place that must pass it through to ticket_stages.
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    tp._claim(20, "mac-mini", title="Versioning: VERSION + CHANGELOG.md bump on merge")
    events = ts.read_stages(20)
    assert events[0]["title"] == "Versioning: VERSION + CHANGELOG.md bump on merge"


def test_main_claims_and_dispatches_oldest_unclaimed(monkeypatch):
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [
        {"number": 20, "title": "paper-graph traversal", "createdAt": "2026-01-01T00:00:00Z", "labels": []}
    ])
    monkeypatch.setattr(tp, "select_machine", lambda target=None: ("mac-mini-1", {"is_self": True}))
    claim_calls = []
    monkeypatch.setattr(tp, "_claim", lambda n, l, **kw: claim_calls.append((n, l, kw.get("title"))) or True)
    dispatch_calls = []
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: dispatch_calls.append((a, kw)) or
                         SimpleNamespace(ok=True, device_id="mac-mini-1"))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    tp.main()

    assert claim_calls == [(20, "mac-mini", "paper-graph traversal")]
    assert len(dispatch_calls) == 1
    args, kwargs = dispatch_calls[0]
    assert kwargs["target"] == "mac-mini-1"
    assert kwargs["mode"] == "async"
    assert "run_ticket.py 20" in args[0]
    assert "claude -p" not in args[0]  # no nested prompt-based session anymore (#95)


def test_main_releases_claim_if_dispatch_fails(monkeypatch):
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [
        {"number": 20, "title": "x", "createdAt": "2026-01-01T00:00:00Z", "labels": []}
    ])
    monkeypatch.setattr(tp, "select_machine", lambda target=None: ("mac-mini-1", {"is_self": True}))
    monkeypatch.setattr(tp, "_claim", lambda n, l, **kw: True)
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: SimpleNamespace(ok=False, error="boom"))
    release_calls = []
    monkeypatch.setattr(tp, "_release", lambda n, l, repo=tp.REPO, run_id=None: release_calls.append((n, l)))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    tp.main()

    assert release_calls == [(20, "mac-mini")]


def test_build_wrapper_command_runs_run_ticket_script():
    command = tp._build_wrapper_command(20)
    assert tp.RUN_TICKET_SCRIPT in command
    assert f"{tp.RUN_TICKET_SCRIPT} 20" in command
    assert "dispatch_issue20.log" in command


# ── dispatch pauses while the cross-ticket circuit breaker is tripped ───────

def test_main_does_not_dispatch_while_the_breaker_is_tripped(monkeypatch, capsys):
    import failure_breaker as fb
    monkeypatch.setattr(fb, "tripped", lambda now=None: [
        {"signature": "measure:vitest-no-summary", "tickets": [32, 35, 37],
         "first_seen": "x", "last_seen": "y", "example": "e"}])
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [{"number": 99, "title": "t", "createdAt": "z", "labels": []}])
    monkeypatch.setattr(tp, "select_machine", lambda: ("mac-mini-1", {}))
    called = []
    monkeypatch.setattr(tp, "_claim", lambda *a, **k: called.append("claim") or True)
    monkeypatch.setattr(tp, "dispatch", lambda *a, **k: called.append("dispatch"))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    tp.main()

    assert called == []
    assert "paused" in capsys.readouterr().err.lower()


# ── run log (Activity tab "Background work") ────────────────────────────────

def test_a_scan_with_nothing_ready_leaves_a_run_log_saying_so(monkeypatch):
    import json
    import job_events
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [])
    monkeypatch.setattr(tp.failure_breaker, "tripped", lambda now=None: [])
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])
    tp.main()
    run = json.loads((job_events.JOBS_DIR / "ticket-pipeline.json").read_text())["runs"][-1]
    assert run["status"] == "passed" and run["summary"] == "no ready tickets"
    steps = [s["step"] for s in run["steps"]]
    assert steps == ["Board discovery", "Onboarding plans", "Project catalog", "Conflicted PRs", "Circuit breaker", "Scanning tickets"]


def test_a_tripped_breaker_is_visible_in_the_run_log(monkeypatch):
    import json
    import job_events
    trip = {"signature": "measure:x", "tickets": [1, 2, 3], "first_seen": "t", "example": "e"}
    monkeypatch.setattr(tp.failure_breaker, "tripped", lambda now=None: [trip])
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])
    tp.main()
    run = json.loads((job_events.JOBS_DIR / "ticket-pipeline.json").read_text())["runs"][-1]
    assert "circuit breaker" in run["summary"]
    # Check that TRIPPED appears in one of the steps' details
    assert any("TRIPPED" in step.get("detail", "") for step in run["steps"])


def test_onboarding_refresh_failure_does_not_abort_scan(monkeypatch):
    """A raising refresh_all_onboarding_plans should not stop the rest of _scan."""
    import json
    import job_events
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [])
    monkeypatch.setattr(tp.failure_breaker, "tripped", lambda now=None: [])
    # Make refresh_all_onboarding_plans raise
    monkeypatch.setattr(tp.project_onboard, "refresh_all_onboarding_plans",
                        lambda repos, gh, dir: (_ for _ in ()).throw(Exception("network error")))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    # Should not raise; scan should complete with "no ready tickets" summary
    tp.main()
    run = json.loads((job_events.JOBS_DIR / "ticket-pipeline.json").read_text())["runs"][-1]
    assert run["status"] == "passed"
    assert "no ready tickets" in run["summary"]


# ── what the dispatcher will and will not pick ──────────────────────────────

def _fake_gh(monkeypatch, issues):
    import json
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=json.dumps(issues), stderr=""))


def test_a_ticket_with_an_open_blocker_is_not_dispatched(monkeypatch):
    issues = [
        _issue(1, "2026-01-01T00:00:00Z", labels=["ready-for-agent"]),
        {**_issue(2, "2026-01-02T00:00:00Z", labels=["ready-for-agent"]), "body": "## Blocked by\n\n- #1"},
        {**_issue(3, "2026-01-03T00:00:00Z", labels=["ready-for-agent"]), "body": "## Blocked by\n\n- #99"},  # #99 is closed/absent
    ]
    _fake_gh(monkeypatch, issues)
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [1, 3]


def test_higher_priority_goes_first_then_oldest(monkeypatch):
    issues = [
        _issue(1, "2026-01-01T00:00:00Z", labels=["ready-for-agent"]),
        _issue(2, "2026-01-02T00:00:00Z", labels=["ready-for-agent", "priority:p0"]),
        _issue(3, "2026-01-03T00:00:00Z", labels=["ready-for-agent", "priority:p0"]),
        _issue(4, "2026-01-04T00:00:00Z", labels=["ready-for-agent", "priority:p3"]),
    ]
    _fake_gh(monkeypatch, issues)
    # p0s first (oldest first among equals); an unscored ticket counts as middle priority, so it comes before p3
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [2, 3, 1, 4]


def test_only_ready_unclaimed_unpinned_tickets_are_candidates(monkeypatch):
    issues = [
        _issue(1, "2026-01-01T00:00:00Z", labels=["bug"]),                                  # not ready
        _issue(2, "2026-01-02T00:00:00Z", labels=["ready-for-agent", "pinned"]),             # a person has it
        _issue(3, "2026-01-03T00:00:00Z", labels=["ready-for-agent"]),
    ]
    _fake_gh(monkeypatch, issues)
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [3]


# ── dispatching other projects' tickets (execution profiles) ────────────────

CC = "G-Eskayo/clarity-captions"
CC_PROFILE = {"repo": CC, "base_branch": "main", "dispatch": "on", "machines": ["mac-mini-1"], "env": {}, "executor": {}, "evidence": {},
              "verify": [{"id": "core", "label": "Core", "command": ["swift", "test"], "required": True, "requires": ["swift"], "parser": "swift-test"}]}


def _ticket(n, created="2026-02-01T00:00:00Z", labels=(), title="t"):
    return {"number": n, "title": title, "createdAt": created, "labels": [{"name": l} for l in labels]}


def _setup_projects(monkeypatch, marvin=(), cc=(), profile=CC_PROFILE, missing_here=()):
    """marvin's tickets come from the zero-argument call exactly as before; another project's from repo=..."""
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda repo=tp.REPO: list(marvin) if repo == tp.REPO else (list(cc) if repo == CC else []))
    monkeypatch.setattr(tp.pp, "dispatchable_repos", lambda directory=None: [CC] if profile and profile["dispatch"] == "on" else [])
    monkeypatch.setattr(tp.pp, "load_profile", lambda repo, directory=None: profile if repo == CC else None)
    monkeypatch.setattr(tp.pp, "missing_here", lambda p: list(missing_here))
    monkeypatch.setattr(tp.failure_breaker, "tripped", lambda now=None, project=None: [])
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])


def _capture(monkeypatch, select=lambda target=None: ("mac-mini-1", {"is_self": True})):
    got = {"claims": [], "dispatches": [], "releases": []}
    monkeypatch.setattr(tp, "select_machine", select)
    monkeypatch.setattr(tp, "_claim", lambda n, l, **kw: got["claims"].append((n, l, kw.get("repo"))) or True)
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: got["dispatches"].append((a, kw)) or SimpleNamespace(ok=True, device_id="mac-mini-1"))
    monkeypatch.setattr(tp, "_release", lambda n, l, repo=tp.REPO, run_id=None: got["releases"].append((n, l, repo)))
    return got


def test_a_ready_clarity_ticket_is_claimed_and_dispatched_with_its_repo_in_the_command(monkeypatch):
    _setup_projects(monkeypatch, cc=[_ticket(17, title="Auto-scroll")])
    got = _capture(monkeypatch)
    tp.main()
    assert got["claims"] == [(17, "mac-mini", CC)]
    args, kw = got["dispatches"][0]
    assert f"run_ticket.py {CC}#17" in args[0]
    assert kw["target"] == "mac-mini-1"
    assert kw["task_label"].startswith(f"ticket {CC}#17")  # qualified, so the dashboard never mistakes it for marvin's #17


def test_the_most_urgent_ticket_across_projects_goes_first(monkeypatch):
    _setup_projects(monkeypatch, marvin=[_ticket(5, "2026-01-01T00:00:00Z", labels=["priority:p3"])], cc=[_ticket(9, "2026-03-01T00:00:00Z", labels=["priority:p0"])])
    got = _capture(monkeypatch)
    tp.main()
    assert got["claims"][0][0] == 9 and got["claims"][0][2] == CC


def test_a_profile_with_dispatch_off_is_never_dispatched(monkeypatch):
    _setup_projects(monkeypatch, cc=[_ticket(17)], profile={**CC_PROFILE, "dispatch": "off"})
    got = _capture(monkeypatch)
    tp.main()
    assert got["claims"] == [] and got["dispatches"] == []


def test_one_projects_tripped_breaker_pauses_only_that_project(monkeypatch):
    _setup_projects(monkeypatch, marvin=[_ticket(5)], cc=[_ticket(9)])
    monkeypatch.setattr(tp.failure_breaker, "tripped", lambda now=None, project=None: [
        {"project": tp.REPO, "signature": "measure:vitest-no-summary", "tickets": [1, 2, 3], "first_seen": "x", "last_seen": "y", "example": "e"}])
    got = _capture(monkeypatch)
    tp.main()
    assert [c[0] for c in got["claims"]] == [9]  # marvin paused, clarity-captions carries on


def test_a_machine_that_cannot_run_the_projects_required_checks_is_not_used(monkeypatch):
    _setup_projects(monkeypatch, cc=[_ticket(17)], missing_here=["xcode"])
    got = _capture(monkeypatch)
    tp.main()
    assert got["claims"] == [] and got["dispatches"] == []


def test_only_machines_the_profile_allows_are_considered(monkeypatch):
    _setup_projects(monkeypatch, cc=[_ticket(17)])
    asked = []
    got = _capture(monkeypatch, select=lambda target=None: asked.append(target) or None)
    tp.main()
    assert asked == ["mac-mini-1"] and got["claims"] == []


def test_a_failed_dispatch_releases_the_claim_in_the_right_repo(monkeypatch):
    _setup_projects(monkeypatch, cc=[_ticket(17)])
    got = _capture(monkeypatch)
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: SimpleNamespace(ok=False, error="boom"))
    tp.main()
    assert got["releases"] == [(17, "mac-mini", CC)]


def test_the_wrapper_command_for_another_project_names_it_and_logs_separately():
    command = tp._build_wrapper_command(7, CC)
    assert f"{tp.RUN_TICKET_SCRIPT} {CC}#7" in command
    assert "dispatch_clarity-captions_issue7.log" in command
    assert tp._build_wrapper_command(7).count("clarity") == 0  # marvin's command is unchanged


# ── a project that has never had a claim label ──────────────────────────────

def test_claiming_creates_the_label_the_first_time_a_project_needs_it(monkeypatch):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        label_missing = cmd[:3] == ["gh", "issue", "edit"] and not any(c[:3] == ["gh", "label", "create"] for c in calls)
        return SimpleNamespace(returncode=1 if label_missing else 0, stdout="", stderr="'claimed:mac-mini' not found" if label_missing else "")

    monkeypatch.setattr(tp.subprocess, "run", fake_run)
    monkeypatch.setattr(tp.ts, "record_stage", lambda *a, **k: None)
    monkeypatch.setattr(tp, "_ensure_board", lambda *a, **k: None)
    assert tp._claim(21, "mac-mini", title="t", repo="G-Eskayo/clarity-captions") is True
    created = [c for c in calls if c[:3] == ["gh", "label", "create"]]
    assert created and created[0][3] == "claimed:mac-mini" and created[0][created[0].index("--repo") + 1] == "G-Eskayo/clarity-captions"
    assert [c[:3] for c in calls].count(["gh", "issue", "edit"]) == 2  # tried, created the label, tried again


def test_a_claim_that_fails_for_another_reason_is_not_retried_or_papered_over(monkeypatch):
    calls = []
    monkeypatch.setattr(tp.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=1, stdout="", stderr="HTTP 403 forbidden"))
    assert tp._claim(21, "mac-mini", repo="G-Eskayo/clarity-captions") is False
    assert not any(c[:3] == ["gh", "label", "create"] for c in calls)


# ── never start a second ticket on a machine that is already running one ────

def test_a_machine_that_is_already_running_a_ticket_is_not_chosen_again_for_another_project(monkeypatch):
    # task_dispatch.select_machine(<explicit device>) skips the busy check for the local machine, so asking for the
    # profile's machine by name let a second ticket start on top of the first (found live 2026-10-05).
    monkeypatch.setattr(tp, "select_machine", lambda target=None: (target, {"is_self": True}))
    monkeypatch.setattr(tp.pp, "missing_here", lambda p: [])
    monkeypatch.setattr(tp, "_local_busy", lambda: True)
    assert tp._select_for_profile({"machines": ["mac-mini-1"]}) is None


def test_the_same_machine_is_chosen_once_it_is_free(monkeypatch):
    monkeypatch.setattr(tp, "select_machine", lambda target=None: (target, {"is_self": True}))
    monkeypatch.setattr(tp.pp, "missing_here", lambda p: [])
    monkeypatch.setattr(tp, "_local_busy", lambda: False)
    assert tp._select_for_profile({"machines": ["mac-mini-1"]})[0] == "mac-mini-1"


def test_a_remote_machine_is_not_blocked_by_this_machines_busy_flag(monkeypatch):
    monkeypatch.setattr(tp, "select_machine", lambda target=None: (target, {"is_self": False}))
    monkeypatch.setattr(tp, "_local_busy", lambda: True)
    assert tp._select_for_profile({"machines": ["macbook-pro-1"]})[0] == "macbook-pro-1"  # select_machine already checked it


# ── "busy" must mean a ticket is actually running, not merely that a flag file says so ─

def test_local_busy_is_true_when_a_ticket_process_is_alive_even_if_the_flag_was_cleared(monkeypatch):
    # The dispatch-state flag is one shared boolean: the first of two overlapping runs to finish resets it while the
    # other is still going, so the next scan saw "idle" and started a third (found live 2026-10-05).
    import importlib
    real = importlib.reload(tp)  # undo the suite-wide stub of _local_busy for this test
    monkeypatch.setattr(real, "_flag_busy", lambda: False)
    monkeypatch.setattr(real, "_ticket_process_alive", lambda: True)
    assert real._local_busy() is True


def test_local_busy_is_false_when_neither_the_flag_nor_a_process_says_so(monkeypatch):
    import importlib
    real = importlib.reload(tp)
    monkeypatch.setattr(real, "_flag_busy", lambda: False)
    monkeypatch.setattr(real, "_ticket_process_alive", lambda: False)
    assert real._local_busy() is False


def test_the_process_check_looks_for_run_ticket_and_treats_an_error_as_busy(monkeypatch):
    import importlib
    real = importlib.reload(tp)
    seen = []
    monkeypatch.setattr(real.subprocess, "run", lambda cmd, **kw: seen.append(cmd) or SimpleNamespace(returncode=0, stdout="123\n"))
    assert real._ticket_process_alive() is True and "run_ticket.py" in " ".join(seen[0])
    monkeypatch.setattr(real.subprocess, "run", lambda cmd, **kw: SimpleNamespace(returncode=1, stdout=""))
    assert real._ticket_process_alive() is False
    monkeypatch.setattr(real.subprocess, "run", lambda cmd, **kw: (_ for _ in ()).throw(OSError("no pgrep")))
    assert real._ticket_process_alive() is True  # cannot tell -> assume busy


def test_unclaimed_ready_skips_tickets_that_already_have_work(monkeypatch):
    import json
    issues = [_issue(1, "2026-01-01T00:00:00Z", labels=["ready-for-agent"]),
              _issue(2, "2026-01-02T00:00:00Z", labels=["ready-for-agent"]),
              _issue(3, "2026-01-03T00:00:00Z", labels=["ready-for-agent"])]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    monkeypatch.setattr(tp, "_evidence_facts", lambda repo: {
        "prs": [{"number": 9, "body": "Closes #1", "headRefName": "x"}], "branches": [], "rescue": [],
        "commits": [("abc", "Add thing (issue #2)")]})
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [3]


def test_unclaimed_ready_still_dispatches_when_evidence_unreadable(monkeypatch):
    import json
    issues = [_issue(1, "2026-01-01T00:00:00Z", labels=["ready-for-agent"])]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    monkeypatch.setattr(tp, "_evidence_facts", lambda repo: None)
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [1]


def _stub_issues(monkeypatch, issues):
    import json
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))


PR_FACTS = {"prs": [{"number": 30, "body": "Closes #7", "headRefName": "pipeline/x-7"}],
            "branches": [], "rescue": [], "commits": []}


def test_a_sent_back_ticket_is_redispatched_even_though_its_old_pr_is_open(monkeypatch):
    _stub_issues(monkeypatch, [_issue(7, "2026-01-01T00:00:00Z", labels=["ready-for-agent", "needs-reengagement"])])
    monkeypatch.setattr(tp, "_evidence_facts", lambda repo: PR_FACTS)
    monkeypatch.setattr(tp, "_attempts", lambda repo, n: 1)
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [7]


def test_a_sent_back_ticket_goes_to_a_person_after_three_attempts(monkeypatch):
    _stub_issues(monkeypatch, [_issue(7, "2026-01-01T00:00:00Z", labels=["ready-for-agent", "needs-reengagement"])])
    monkeypatch.setattr(tp, "_evidence_facts", lambda repo: PR_FACTS)
    monkeypatch.setattr(tp, "_attempts", lambda repo, n: 3)
    assert tp._unclaimed_ready_tickets() == []


def test_a_sent_back_ticket_with_commits_already_on_main_is_still_held(monkeypatch):
    _stub_issues(monkeypatch, [_issue(7, "2026-01-01T00:00:00Z", labels=["ready-for-agent", "needs-reengagement"])])
    monkeypatch.setattr(tp, "_evidence_facts", lambda repo: {**PR_FACTS, "commits": [("abc", "Add it (issue #7)")]})
    monkeypatch.setattr(tp, "_attempts", lambda repo, n: 1)
    assert tp._unclaimed_ready_tickets() == []


def test_attempts_count_finished_attempts_not_claims(tmp_path, monkeypatch):
    """A claim that died before doing anything (a failed git fetch) must not use up a ticket's re-engagement budget."""
    ts.record_stage(7, "claimed", "started", "claimed:mac-mini", machine="m", repo="o/r")
    ts.record_stage(7, "done", "passed", "PR raised: https://github.com/o/r/pull/1", repo="o/r")
    ts.record_stage(7, "claimed", "started", "claimed:mac-mini", machine="m", repo="o/r")
    ts.record_stage(7, "done", "failed", "Unhandled exception: git fetch", repo="o/r")
    assert tp._attempts("o/r", 7) == 1


# ── conflicted PRs are sent back automatically, before a human wastes an approval on them ──

def _pr(number, ticket_ref, mergeable="CONFLICTING", labels=()):
    return {"number": number, "body": f"Closes {ticket_ref}\n\nAutonomously implemented.", "mergeable": mergeable,
            "headRefName": f"pipeline/x-{number}", "labels": [{"name": l} for l in labels]}


def _requeue(prs, issues, calls):
    def fake_run(cmd, **kw):
        calls.append(cmd)
        out = prs if "pr" in cmd and "list" in cmd else issues if "issue" in cmd and "list" in cmd else ""
        return SimpleNamespace(returncode=0, stdout=__import__("json").dumps(out) if out != "" else "", stderr="")
    return fake_run


def test_sending_a_ticket_back_releases_its_claim_or_nothing_would_ever_rebuild_it(monkeypatch):
    """clarity-captions #51 sat 'sent back' for hours: it still carried claimed:mac-mini from the run that raised the PR,
    and the dispatcher only takes tickets with no claim, so the rebuild was never started."""
    calls = []
    issues = [{"number": 34, "labels": [{"name": "ready-for-agent"}, {"name": "claimed:mac-mini"}]}]
    monkeypatch.setattr(tp.subprocess, "run", _requeue([_pr(48, "o/r#34")], issues, calls))
    assert tp._requeue_conflicted_prs("o/r") == [34]
    edit = [c for c in calls if "edit" in c][0]
    assert "needs-reengagement" in edit
    assert edit[edit.index("--remove-label") + 1] == "claimed:mac-mini"


def test_a_conflicting_pr_sends_its_ticket_back_with_a_reason(monkeypatch):
    calls = []
    issues = [{"number": 34, "labels": [{"name": "ready-for-agent"}]}]
    monkeypatch.setattr(tp.subprocess, "run", _requeue([_pr(48, "o/r#34")], issues, calls))
    sent = tp._requeue_conflicted_prs("o/r")
    assert sent == [34]
    assert any("--add-label" in c and "needs-reengagement" in c for c in calls)
    comment = [c for c in calls if "comment" in c][0]
    assert "PR #48" in " ".join(comment) and "main" in " ".join(comment)


def test_only_conflicting_prs_whose_ticket_is_not_already_sent_back_are_touched(monkeypatch):
    calls = []
    prs = [_pr(48, "o/r#34", "MERGEABLE"), _pr(49, "o/r#35", "UNKNOWN"), _pr(50, "o/r#36"), _pr(51, "o/r#37")]
    issues = [{"number": 36, "labels": [{"name": "needs-reengagement"}]},                # already sent back
              {"number": 37, "labels": [{"name": "pinned"}]}]                            # a person's hands off
    monkeypatch.setattr(tp.subprocess, "run", _requeue(prs, issues, calls))
    assert tp._requeue_conflicted_prs("o/r") == []
    assert not any("--add-label" in c for c in calls)


def test_a_pr_with_no_ticket_reference_is_left_alone(monkeypatch):
    calls = []
    pr = {"number": 60, "body": "hand-made PR", "mergeable": "CONFLICTING", "headRefName": "x", "labels": []}
    monkeypatch.setattr(tp.subprocess, "run", _requeue([pr], [], calls))
    assert tp._requeue_conflicted_prs("o/r") == []


def test_a_gh_failure_is_swallowed_not_fatal(monkeypatch):
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    assert tp._requeue_conflicted_prs("o/r") == []


def _pr_ci(number, ticket_ref, rollup, mergeable="MERGEABLE"):
    return {"number": number, "body": f"Closes {ticket_ref}", "mergeable": mergeable, "headRefName": "x", "statusCheckRollup": rollup}


def test_a_pr_with_failing_github_checks_is_sent_back_with_the_check_names(monkeypatch):
    calls = []
    prs = [_pr_ci(57, "o/r#9", [{"__typename": "CheckRun", "name": "swift test", "status": "COMPLETED", "conclusion": "FAILURE"}])]
    monkeypatch.setattr(tp.subprocess, "run", _requeue(prs, [{"number": 9, "labels": [{"name": "ready-for-agent"}]}], calls))
    assert tp._requeue_conflicted_prs("o/r") == [9]
    comment = " ".join([c for c in calls if "comment" in c][0])
    assert "swift test" in comment and "#57" in comment


def test_checks_that_failed_for_the_runners_sake_or_are_still_running_do_not_send_a_pr_back(monkeypatch):
    calls = []
    prs = [_pr_ci(1, "o/r#1", [{"__typename": "CheckRun", "name": "a", "status": "COMPLETED", "conclusion": "CANCELLED"}]),
           _pr_ci(2, "o/r#2", [{"__typename": "CheckRun", "name": "a", "status": "COMPLETED", "conclusion": "TIMED_OUT"}]),
           _pr_ci(3, "o/r#3", [{"__typename": "CheckRun", "name": "a", "status": "IN_PROGRESS", "conclusion": None}]),
           _pr_ci(4, "o/r#4", [{"__typename": "CheckRun", "name": "a", "status": "COMPLETED", "conclusion": "SUCCESS"}]),
           _pr_ci(5, "o/r#5", [])]
    issues = [{"number": n, "labels": [{"name": "ready-for-agent"}]} for n in range(1, 6)]
    monkeypatch.setattr(tp.subprocess, "run", _requeue(prs, issues, calls))
    assert tp._requeue_conflicted_prs("o/r") == []


def test_marvins_own_tickets_are_only_offered_to_the_machines_named_for_them(monkeypatch):
    """Marvin's own tickets name their machines here (the mac-mini first), not in a project profile."""
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda: [{"number": 20, "title": "x", "createdAt": "2026-01-01T00:00:00Z", "labels": []}])
    asked = []
    monkeypatch.setattr(tp, "select_machine", lambda target=None: asked.append(target) or None)
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])
    tp.main()
    assert asked == ["mac-mini-1", "macbook-pro-1"] and tp.MARVIN_MACHINES == ("mac-mini-1", "macbook-pro-1")


def _ready(number, created, labels=()):
    return {**_issue(number, created, labels=("ready-for-agent", *labels)), "body": ""}


def test_a_newer_ticket_on_a_hard_deadline_project_is_picked_before_older_plain_work(monkeypatch):
    import json
    issues = [_ready(1, "2026-09-20T00:00:00Z"), _ready(2, "2026-10-05T00:00:00Z")]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    monkeypatch.setattr(tp, "_due_for", lambda repo: {"date": "2026-10-25", "hard": True} if repo == "G-Eskayo/captions" else None)
    plain = tp._unclaimed_ready_tickets(repo="G-Eskayo/other")
    deadline = tp._unclaimed_ready_tickets(repo="G-Eskayo/captions")
    candidates = [("G-Eskayo/other", plain[0]), ("G-Eskayo/captions", deadline[-1])]  # its NEWEST ticket
    assert min(candidates, key=lambda c: tp._order_key(c[1]))[0] == "G-Eskayo/captions"


def test_a_priority_label_a_person_set_still_wins_over_a_deadline(monkeypatch):
    import json
    issues = [_ready(1, "2026-10-05T00:00:00Z", labels=("priority:p0",)), _ready(2, "2026-09-01T00:00:00Z")]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    monkeypatch.setattr(tp, "_due_for", lambda repo: {"date": "2026-10-08", "hard": True})
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [1, 2]


def test_ordering_survives_an_unreadable_deadline_source(monkeypatch):
    import json
    issues = [_ready(4, "2026-02-01T00:00:00Z"), _ready(3, "2026-01-01T00:00:00Z")]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))
    def boom(repo):
        raise OSError("catalog unreadable")
    monkeypatch.setattr(tp, "_due_for", boom)
    assert [i["number"] for i in tp._unclaimed_ready_tickets()] == [3, 4]


def test_the_scan_starts_a_main_health_check_in_the_background_and_never_waits_for_it(monkeypatch):
    started = []
    monkeypatch.setattr(tp.subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw)) or SimpleNamespace())
    tp._refresh_main_health()
    cmd, kw = started[0]
    assert cmd[-2:] == [str(tp.Path(tp.__file__).with_name("main_health.py")), "refresh"]
    assert kw.get("start_new_session") is True       # detached: the scan does not wait on a ~1 minute test run
    monkeypatch.setattr(tp.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(OSError("no")))
    tp._refresh_main_health()                        # a failure to start it never breaks the scan


# ── parallel dispatch: the scan fills free slots (ADR 0052, ticket #195) ────

BOTH = ["mac-mini-1", "macbook-pro-1"]


def _parallel(monkeypatch, marvin=(), cc=(), total=2, per_project=1, local_used=0, inflight=None, disk=100, budget=90):
    both = {**CC_PROFILE, "machines": BOTH}
    _setup_projects(monkeypatch, marvin=marvin, cc=cc, profile=both)
    settings = {**tp.dispatch_concurrency.DEFAULTS, "parallel": True, "max_total": total, "max_per_project": per_project}
    monkeypatch.setattr(tp.dispatch_concurrency, "load", lambda path=None: settings)
    monkeypatch.setattr(tp, "_local_slots_used", lambda: local_used)
    monkeypatch.setattr(tp, "_inflight_by_repo", lambda repos: dict(inflight or {}))
    monkeypatch.setattr(tp, "_free_disk_gb", lambda: disk)
    monkeypatch.setattr(tp, "_github_budget_pct", lambda: budget)
    monkeypatch.setattr(tp, "MARVIN_MACHINES", tuple(BOTH))
    return _capture(monkeypatch, select=lambda target=None: (target, {"is_self": target == "mac-mini-1"}))


def _targets(got):
    return [kw["target"] for _a, kw in got["dispatches"]]


def test_with_parallel_off_a_scan_dispatches_exactly_one_ticket(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5)], cc=[_ticket(9)])
    monkeypatch.setattr(tp.dispatch_concurrency, "load", lambda path=None: dict(tp.dispatch_concurrency.DEFAULTS))
    monkeypatch.setattr(tp, "_local_busy", lambda: False)
    tp.main()
    assert len(got["dispatches"]) == 1


def test_with_parallel_on_two_projects_each_get_a_ticket_in_the_same_scan(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5)], cc=[_ticket(9)])
    tp.main()
    assert sorted(c[0] for c in got["claims"]) == [5, 9]
    assert sorted(_targets(got)) == sorted(BOTH)            # one per machine, never two on the macbook's single slot


def test_two_tickets_of_one_project_are_not_started_together_while_its_limit_is_one(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5), _ticket(6, "2026-02-02T00:00:00Z")])
    tp.main()
    assert [c[0] for c in got["claims"]] == [5]


def test_a_higher_per_project_limit_lets_one_project_use_both_machines(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5), _ticket(6, "2026-02-02T00:00:00Z")], per_project=2)
    tp.main()
    assert [c[0] for c in got["claims"]] == [5, 6] and sorted(_targets(got)) == sorted(BOTH)


def test_a_ticket_already_in_flight_counts_against_its_projects_limit(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5)], cc=[_ticket(9)], inflight={tp.REPO: 1})
    tp.main()
    assert [c[0] for c in got["claims"]] == [9]


def test_the_total_limit_counts_tickets_already_running(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5)], cc=[_ticket(9)], total=2, inflight={tp.REPO: 0, CC: 0, "other": 1})
    tp.main()
    assert len(got["claims"]) == 1


def test_a_full_machine_does_not_stop_another_project_that_can_use_a_free_one(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5)], cc=[_ticket(9)], local_used=2)   # the mini is full
    monkeypatch.setattr(tp.pp, "load_profile", lambda repo, directory=None: {**CC_PROFILE, "machines": ["mac-mini-1"]} if repo == CC else None)
    tp.main()
    assert [c[0] for c in got["claims"]] == [5] and _targets(got) == ["macbook-pro-1"]


def test_a_guard_refusal_starts_nothing_and_says_why_in_the_scan_log(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5)], disk=9)
    monkeypatch.setattr(tp, "MARVIN_MACHINES", ("mac-mini-1",))   # the disk guard reads this machine's disk, not the other's
    steps = []
    run = SimpleNamespace(step=lambda name, detail=None: steps.append((name, detail)), summary=lambda *a: None, fail=lambda *a: None)
    tp._scan(run, dry_run=False)
    assert got["claims"] == []
    assert any("disk 9 GB free" in (d or "") for _n, d in steps)


def test_a_failed_dispatch_in_one_project_does_not_stop_the_other(monkeypatch):
    got = _parallel(monkeypatch, marvin=[_ticket(5)], cc=[_ticket(9)])
    calls = []
    def flaky(*a, **kw):
        calls.append(kw["target"])
        return SimpleNamespace(ok=len(calls) > 1, error="boom")
    monkeypatch.setattr(tp, "dispatch", flaky)
    # The test capture's _release mock needs to accept the run_id parameter now
    monkeypatch.setattr(tp, "_release", lambda n, l, repo=tp.REPO, run_id=None: got["releases"].append((n, l, repo)))
    tp.main()
    assert len(calls) == 2 and len(got["releases"]) == 1


def test_in_flight_means_a_live_run_not_a_claim_label_that_outlives_it(monkeypatch):
    """Seven claimed tickets (six of them waiting in review) made the scan think parallel dispatch was already full."""
    import running_tickets
    monkeypatch.undo()   # the autouse fixtures stub scanning; this reads only running_tickets, which is stubbed next
    monkeypatch.setattr(running_tickets, "current", lambda: [{"machine": "mac-mini-1", "repo": tp.REPO, "number": 193}])
    assert tp._inflight_by_repo([tp.REPO, CC]) == {tp.REPO: 1, CC: 0}


def test_in_flight_counts_nothing_when_the_process_tables_cannot_be_read(monkeypatch):
    import running_tickets
    monkeypatch.setattr(running_tickets, "current", lambda: (_ for _ in ()).throw(OSError("boom")))
    assert tp._inflight_by_repo([tp.REPO]) == {tp.REPO: 0}


# ── bugs first (#237) ───────────────────────────────────────────────────────

from datetime import datetime, timezone  # noqa: E402


def _scored(number, labels=(), blocks=0, due=None, created="2026-10-01T00:00:00Z"):
    t = {"number": number, "createdAt": created, "labels": [{"name": l} for l in labels], "title": "t", "body": ""}
    now = datetime(2026, 10, 7, tzinfo=timezone.utc)
    t["_score"] = tp.ticket_policy.score_ticket(t, blocks, due, now)[0]
    return t


def _first(*tickets):
    return min(tickets, key=tp._order_key)["number"]


def test_a_bare_bug_is_picked_before_a_feature_that_unblocks_two():
    assert _first(_scored(1, ["enhancement"], blocks=2), _scored(2, ["bug"])) == 2


def test_with_the_same_priority_label_a_bug_is_picked_before_a_non_bug():
    older_feature = _scored(1, ["priority:p2", "enhancement"], blocks=3, created="2026-09-01T00:00:00Z")
    assert _first(older_feature, _scored(2, ["priority:p2", "bug"])) == 2


def test_a_feature_with_a_hard_deadline_three_days_away_still_beats_a_bare_bug():
    due = {"date": "2026-10-10", "hard": True}
    assert _first(_scored(1, ["bug"]), _scored(2, ["enhancement"], due=due)) == 2


import ticket_pipeline as _tp_for_refresh  # noqa: E402
_REAL_REFRESH_CATALOG = _tp_for_refresh._refresh_catalog  # captured before the autouse isolation fixture swaps it out


# 2026-10-07: on the mini the in-process catalog refresh blocked in opendir() on ~/Documents (a TCC prompt nobody
# can answer on a headless Mac) and the whole pipeline run hung for hours: no dispatch, no Activity updates.
# The refresh now runs as a child process with a time limit; a hang costs one refresh, never the run.
def test_catalog_refresh_runs_in_a_child_process_with_a_time_limit(monkeypatch, capsys):
    import subprocess
    import ticket_pipeline as tp
    monkeypatch.setattr(tp.project_catalog, "is_stale", lambda path, age: True)
    calls = []

    def hung(args, **kw):
        calls.append((args, kw.get("timeout")))
        raise subprocess.TimeoutExpired(args, kw.get("timeout"))
    _REAL_REFRESH_CATALOG(run=hung)
    assert calls and calls[0][0][-1] == "refresh" and calls[0][1] and calls[0][1] <= 300
    assert "timed out" in capsys.readouterr().err


def test_catalog_refresh_is_skipped_when_fresh(monkeypatch):
    import ticket_pipeline as tp
    monkeypatch.setattr(tp.project_catalog, "is_stale", lambda path, age: False)
    calls = []
    _REAL_REFRESH_CATALOG(run=lambda *a, **k: calls.append(a))
    assert calls == []


# ── scan summary with circuit breaker ───────────────────────────────────────

def test_scan_summary_reports_breaker_even_when_dispatchable_project_has_no_ready_tickets(monkeypatch):
    """2026-10-07: breaker tripped for one project, another project has zero ready tickets.
    The summary must report "stopped by circuit breaker", not "no ready tickets" (which is true but
    misleading when the real stopper is the breaker)."""
    import failure_breaker as fb

    monkeypatch.setattr(fb, "tripped", lambda now=None: [
        {"project": "owner/other-project", "signature": "failure", "tickets": [1, 2, 3],
         "first_seen": "2026-10-07T00:00:00Z", "example": "error"}])

    summaries = []

    def capture_summary(msg):
        summaries.append(msg)

    # Simulate the scenario: breaker tripped for 'owner/other-project', but we're checking
    # G-Eskayo/marvin which has zero ready tickets.
    run = SimpleNamespace(
        step=lambda *a, **k: None,
        summary=capture_summary,
        fail=lambda *a: None
    )

    # Mock the conditions that trigger the fix:
    # - failure_breaker.tripped() returns one trip
    # - repos list is not empty (G-Eskayo/marvin is dispatchable and not paused)
    # - pools is empty (no ready tickets in G-Eskayo/marvin or other dispatchable repos)

    monkeypatch.setattr(tp, "REPO", "G-Eskayo/marvin")
    monkeypatch.setattr(tp.pp, "dispatchable_repos", lambda: ["owner/other-project"])
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda repo=None: [])
    monkeypatch.setattr(tp.dispatch_concurrency, "load", lambda path=None: {"parallel": False})

    tp._scan(run, dry_run=False)

    # Check that the summary mentions the breaker, not merely "no ready tickets".
    assert any("circuit breaker" in s.lower() for s in summaries)


# ── ADR 0058: the hourly onboarding pass applies the safe pieces, and stands down when GitHub's budget is low ──

def test_onboarding_pass_applies_safe_pieces_and_reports_them(monkeypatch):
    calls = {}
    monkeypatch.setattr(tp.board_registry, "list_boards", lambda: [{"repo": "o/a"}, {"repo": "o/b"}])
    monkeypatch.setattr(tp.project_onboard, "refresh_all_onboarding_plans",
                        lambda repos, apply_safe=False: calls.update(repos=repos, apply_safe=apply_safe) or
                        {"ok": ["o/a"], "failed": [("o/b", "x")], "applied": {"o/a": ["labels"]}})
    msg = tp._refresh_onboarding_plans(budget=lambda: 80.0, min_pct=20)
    assert calls == {"repos": ["o/a", "o/b"], "apply_safe": True}
    assert "1 refreshed" in msg and "1 failed" in msg and "applied: a (labels)" in msg


def test_onboarding_pass_stands_down_when_the_github_budget_is_low(monkeypatch):
    monkeypatch.setattr(tp.board_registry, "list_boards", lambda: [{"repo": "o/a"}])
    called = []
    monkeypatch.setattr(tp.project_onboard, "refresh_all_onboarding_plans", lambda *a, **k: called.append(1))
    msg = tp._refresh_onboarding_plans(budget=lambda: 5.0, min_pct=20)
    assert called == [] and "budget" in msg


def test_onboarding_pass_reports_skipped_count(monkeypatch):
    """When repos are skipped due to unchanged pushedAt, the message should report skip count."""
    monkeypatch.setattr(tp.board_registry, "list_boards", lambda: [{"repo": "o/a"}, {"repo": "o/b"}])
    monkeypatch.setattr(tp.project_onboard, "refresh_all_onboarding_plans",
                        lambda repos, apply_safe=False:
                        {"ok": ["o/a"], "failed": [], "applied": {}, "skipped": ["o/b"]})
    msg = tp._refresh_onboarding_plans(budget=lambda: 80.0, min_pct=20)
    assert "1 refreshed" in msg and "1 skipped (unchanged since last plan)" in msg


# ── cheap repair before any rebuild (2026-10-09, #314) ──────────────────────

def _repair(monkeypatch, outcome):
    seen = []
    def fake(repo, pr):
        seen.append(pr["number"])
        return outcome
    monkeypatch.setattr(tp, "_try_conflict_repair", fake)
    return seen


def test_a_conflict_the_repair_resolves_is_pushed_and_never_sent_back(monkeypatch):
    calls = []
    seen = _repair(monkeypatch, {"outcome": "repaired", "detail": "both sides added to lib/tests/test_x.py; tests pass"})
    monkeypatch.setattr(tp.subprocess, "run", _requeue([_pr(48, "o/r#34")], [{"number": 34, "labels": []}], calls))
    assert tp._requeue_conflicted_prs("o/r") == []
    assert seen == [48]
    assert not any("needs-reengagement" in c for c in calls)
    comment = [c for c in calls if "comment" in c][0]
    assert comment[1:4] == ["pr", "comment", "48"] and "both sides added" in " ".join(comment)


def test_a_hand_made_pr_is_never_sent_for_an_agent_rebuild_it_is_flagged_once(monkeypatch):
    calls = []
    _repair(monkeypatch, {"outcome": "rebuild", "files": ["lib/x.py"]})
    pr = {**_pr(48, "o/r#34"), "headRefName": "marvin-304-purpose-metrics"}
    monkeypatch.setattr(tp.subprocess, "run", _requeue([pr], [{"number": 34, "labels": []}], calls))
    monkeypatch.setattr(tp, "_flagged_before", lambda url, sha: False)
    marks = []
    monkeypatch.setattr(tp, "_mark_flagged", lambda url, sha: marks.append(url))
    assert tp._requeue_conflicted_prs("o/r") == []
    assert not any("needs-reengagement" in c for c in calls)
    comment = " ".join([c for c in calls if "comment" in c][0])
    assert "lib/x.py" in comment and "by hand" in comment
    assert marks


def test_a_hand_made_pr_already_flagged_for_this_commit_is_not_commented_again(monkeypatch):
    calls = []
    _repair(monkeypatch, {"outcome": "rebuild", "files": ["lib/x.py"]})
    pr = {**_pr(48, "o/r#34"), "headRefName": "marvin-304-purpose-metrics"}
    monkeypatch.setattr(tp.subprocess, "run", _requeue([pr], [{"number": 34, "labels": []}], calls))
    monkeypatch.setattr(tp, "_flagged_before", lambda url, sha: True)
    tp._requeue_conflicted_prs("o/r")
    assert not any("comment" in c for c in calls)


def test_a_pipeline_pr_with_a_real_conflict_is_sent_back_naming_the_files(monkeypatch):
    calls = []
    _repair(monkeypatch, {"outcome": "rebuild", "files": ["lib/a.py", "lib/b.py"]})
    monkeypatch.setattr(tp.subprocess, "run", _requeue([_pr(48, "o/r#34")], [{"number": 34, "labels": []}], calls))
    assert tp._requeue_conflicted_prs("o/r") == [34]
    comment = " ".join([c for c in calls if "comment" in c][0])
    assert "lib/a.py" in comment and "lib/b.py" in comment


def test_out_of_repair_budget_waits_for_the_next_scan_instead_of_rebuilding(monkeypatch):
    calls = []
    _repair(monkeypatch, {"outcome": "later"})
    monkeypatch.setattr(tp.subprocess, "run", _requeue([_pr(48, "o/r#34")], [{"number": 34, "labels": []}], calls))
    assert tp._requeue_conflicted_prs("o/r") == []
    assert not any("needs-reengagement" in c or "comment" in c for c in calls)


def test_failing_checks_are_not_a_conflict_and_skip_the_repair(monkeypatch):
    calls = []
    seen = _repair(monkeypatch, {"outcome": "repaired", "detail": "x"})
    pr = {**_pr(48, "o/r#34", "MERGEABLE"), "statusCheckRollup": [{"name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"}]}
    monkeypatch.setattr(tp.subprocess, "run", _requeue([pr], [{"number": 34, "labels": []}], calls))
    assert tp._requeue_conflicted_prs("o/r") == [34]
    assert seen == []


def test_a_sent_back_ticket_whose_pr_still_conflicts_gets_the_repair_and_the_flag_cleared(monkeypatch):
    """#257 sat 12 hours: sent back a minute after its PR was raised, still claimed, so never rebuilt -- and the scan
    skipped it because it was already sent back. A repair needs no rebuild at all."""
    calls = []
    seen = _repair(monkeypatch, {"outcome": "repaired", "detail": "both sides only added lines in lib/tests/x.py"})
    issues = [{"number": 255, "labels": [{"name": "needs-reengagement"}, {"name": "claimed:mac-mini"}]}]
    monkeypatch.setattr(tp.subprocess, "run", _requeue([_pr(257, "o/r#255")], issues, calls))
    assert tp._requeue_conflicted_prs("o/r") == []
    assert seen == [257]
    edit = [c for c in calls if "edit" in c and "issue" in c][0]
    assert edit[edit.index("--remove-label") + 1] == "needs-reengagement"


def test_a_sent_back_ticket_the_repair_cannot_fix_is_left_as_it_is(monkeypatch):
    calls = []
    _repair(monkeypatch, {"outcome": "rebuild", "files": ["a.py"]})
    issues = [{"number": 255, "labels": [{"name": "needs-reengagement"}]}]
    monkeypatch.setattr(tp.subprocess, "run", _requeue([_pr(257, "o/r#255")], issues, calls))
    assert tp._requeue_conflicted_prs("o/r") == []
    assert not any("comment" in c or "edit" in c for c in calls)


# ── scan lock: prevent concurrent scans from claiming the same ticket (#255) ──

def test_scan_lock_reads_the_patched_path_at_call_time(tmp_path, monkeypatch):
    # 2026-10-09: the default was bound at import, so patching SCAN_LOCK_PATH did nothing and every test that ran
    # main() took the REAL ~/.claude/dispatch/scan.lock -- waiting out the 120 s timeout whenever the live pipeline
    # held it, which stalled merge-gate test runs (and the owner's Approve) for many minutes.
    lock = tmp_path / "isolated" / "scan.lock"
    monkeypatch.setattr(tp, "SCAN_LOCK_PATH", lock)
    with tp._scan_lock():
        assert lock.exists()


def test_scan_lock_reads_the_patched_timeout_at_call_time(tmp_path, monkeypatch):
    import fcntl
    lock = tmp_path / "scan.lock"
    monkeypatch.setattr(tp, "SCAN_LOCK_PATH", lock)
    monkeypatch.setattr(tp, "SCAN_LOCK_TIMEOUT_S", 0.2)
    holder = open(lock, "w")
    fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)   # someone else holds it
    try:
        start = time.time()
        with tp._scan_lock():
            pass
        assert time.time() - start < 5, "must honor the patched timeout, not the 120 s default"
    finally:
        holder.close()


def test_scan_lock_acquires_and_releases_exclusive_access(tmp_path, monkeypatch):
    monkeypatch.setattr(tp, "SCAN_LOCK_PATH", tmp_path / "scan.lock")
    acquired = []
    with tp._scan_lock():
        acquired.append(True)
    assert acquired == [True]


def test_scan_lock_has_configurable_timeout(tmp_path, monkeypatch):
    # The timeout is configurable via SCAN_LOCK_TIMEOUT_S
    monkeypatch.setattr(tp, "SCAN_LOCK_PATH", tmp_path / "scan.lock")
    monkeypatch.setattr(tp, "SCAN_LOCK_TIMEOUT_S", 42)
    # If timeout works, this should acquire the lock immediately
    with tp._scan_lock():
        pass


def test_claim_records_run_id_in_the_stage_event(monkeypatch, tmp_path):
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    tp._claim(20, "mac-mini", title="t", run_id="abc123")
    events = ts.read_stages(20)
    assert events[0]["run_id"] == "abc123"


def test_dispatch_one_generates_a_run_id_and_passes_it_to_claim_and_command(monkeypatch, tmp_path):
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="", stderr=""))
    calls = {"claims": [], "commands": []}

    def mock_claim(n, l, **kw):
        calls["claims"].append(kw.get("run_id"))
        return True

    def mock_dispatch(cmd, **kw):
        calls["commands"].append(cmd)
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(tp, "_claim", mock_claim)
    monkeypatch.setattr(tp, "dispatch", mock_dispatch)
    monkeypatch.setattr(tp, "select_machine", lambda target=None: ("mac-mini-1", {"is_self": True}))

    run = SimpleNamespace(step=lambda *a: None, summary=lambda *a: None, fail=lambda *a: None)
    ticket = {"number": 20, "title": "t"}

    tp._dispatch_one(tp.REPO, ticket, 1, run.step, run.summary, run.fail, False, {}, {}, 0, [])

    assert len(calls["claims"]) == 1
    assert len(calls["commands"]) == 1
    assert calls["claims"][0] is not None and len(calls["claims"][0]) == 12  # uuid hex[:12]
    assert f"MARVIN_RUN_ID={calls['claims'][0]}" in calls["commands"][0]


def test_release_with_matching_run_id_releases_the_claim(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path / "stages")
    ts.record_stage(20, "claimed", "started", run_id="run123")

    calls = []
    monkeypatch.setattr(tp.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    tp._release(20, "mac-mini", run_id="run123")

    assert len(calls) == 1
    assert "--remove-label" in calls[0]


def test_release_with_mismatched_run_id_skips_the_release(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path / "stages")
    ts.record_stage(20, "claimed", "started", run_id="run123")

    calls = []
    monkeypatch.setattr(tp.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    tp._release(20, "mac-mini", run_id="other_run")

    assert not calls
    assert "skipping release" in capsys.readouterr().err


def test_release_without_run_id_always_releases(monkeypatch, tmp_path):
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path / "stages")
    ts.record_stage(20, "claimed", "started", run_id="run123")

    calls = []
    monkeypatch.setattr(tp.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    tp._release(20, "mac-mini")

    assert len(calls) == 1
    assert "--remove-label" in calls[0]


def test_two_concurrent_scans_dispatch_a_ticket_only_once(monkeypatch, tmp_path):
    """Regression test for #255: concurrent scans must not both claim the same ticket.
    The second scan should see the first scan's claim and skip the ticket."""
    import threading
    import time

    monkeypatch.setattr(tp.failure_breaker, "tripped", lambda now=None: [])
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    # State: the ticket starts unclaimed
    ticket_state = {"claimed": False}
    claim_order = []

    def stateful_unclaimed_ready_tickets():
        # The ticket is only "unclaimed ready" until someone claims it
        if ticket_state["claimed"]:
            return []
        return [{"number": 20, "title": "x", "createdAt": "2026-01-01T00:00:00Z", "labels": []}]

    def mock_select_machine(target=None):
        return ("mac-mini-1", {"is_self": True})

    def mock_claim(n, l, **kw):
        claim_order.append(("claim", n, kw.get("run_id")))
        # Simulate a race window: the claim takes time, during which the second
        # scan could try to claim the same ticket if the lock weren't held
        time.sleep(0.05)
        ticket_state["claimed"] = True
        return True

    def mock_dispatch(cmd, **kw):
        claim_order.append(("dispatch", cmd))
        return SimpleNamespace(ok=True, device_id="mac-mini-1")

    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", stateful_unclaimed_ready_tickets)
    monkeypatch.setattr(tp, "select_machine", mock_select_machine)
    monkeypatch.setattr(tp, "_claim", mock_claim)
    monkeypatch.setattr(tp, "dispatch", mock_dispatch)
    monkeypatch.setattr(tp, "SCAN_LOCK_PATH", tmp_path / "scan.lock")
    monkeypatch.setattr(tp, "SCAN_LOCK_TIMEOUT_S", 1)

    # Run two scans concurrently: the lock should serialize them
    results = []

    def run_scan():
        try:
            with tp._scan_lock(tmp_path / "scan.lock", 1):
                tp._scan(
                    SimpleNamespace(
                        step=lambda *a, **k: None,
                        summary=lambda *a: None,
                        fail=lambda *a: None,
                    ),
                    dry_run=False,
                )
            results.append("completed")
        except Exception as e:
            results.append(f"failed: {e}")

    t1 = threading.Thread(target=run_scan)
    t2 = threading.Thread(target=run_scan)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    # Both threads should have completed
    assert len(results) == 2, f"Threads did not complete: {results}"

    # The ticket should have been claimed exactly once (not twice)
    claims = [x for x in claim_order if x[0] == "claim"]
    assert len(claims) == 1, f"Ticket was claimed {len(claims)} times, expected 1: {claims}"
    assert claims[0][1] == 20, "Claim should be for ticket #20"

    # The dispatch should have happened exactly once
    dispatches = [x for x in claim_order if x[0] == "dispatch"]
    assert len(dispatches) == 1, f"Dispatch happened {len(dispatches)} times, expected 1"


# Research tickets (Gil 2026-10-09): one at a time, only when no build work is waiting.
def test_research_waits_while_any_build_ticket_is_ready():
    issues = [_issue(1, "2026-01-01T00:00:00Z", labels=["ready-for-agent", "research"]),
              _issue(2, "2026-01-02T00:00:00Z", labels=["ready-for-agent"])]
    assert [i["number"] for i in tp._unclaimed_ready_tickets(issues=issues)] == [2]


def test_research_runs_when_nothing_else_is_ready_one_at_a_time():
    issues = [_issue(1, "2026-01-01T00:00:00Z", labels=["ready-for-agent", "research"]),
              _issue(3, "2026-01-03T00:00:00Z", labels=["ready-for-agent", "research"])]
    assert [i["number"] for i in tp._unclaimed_ready_tickets(issues=issues)] == [1]
    running = issues + [_issue(5, "2026-01-05T00:00:00Z", labels=["ready-for-agent", "research", "claimed:mac-mini"])]
    assert tp._unclaimed_ready_tickets(issues=running) == []
