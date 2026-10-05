"""Tests for ticket_pipeline.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_pipeline.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from types import SimpleNamespace

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
    monkeypatch.setattr(tp, "select_machine", lambda: ("macbook-pro-1", {"is_self": True}))
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
    monkeypatch.setattr(tp, "select_machine", lambda: None)
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
    monkeypatch.setattr(tp, "select_machine", lambda: ("macbook-pro-1", {"is_self": True}))
    claim_calls = []
    monkeypatch.setattr(tp, "_claim", lambda n, l, **kw: claim_calls.append((n, l, kw.get("title"))) or True)
    dispatch_calls = []
    monkeypatch.setattr(tp, "dispatch", lambda *a, **kw: dispatch_calls.append((a, kw)) or
                         SimpleNamespace(ok=True, device_id="macbook-pro-1"))
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])

    tp.main()

    assert claim_calls == [(20, "macbook-pro", "paper-graph traversal")]
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
    monkeypatch.setattr(tp, "_claim", lambda n, l, **kw: True)
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
    assert steps == ["Board discovery", "Project catalog", "Conflicted PRs", "Circuit breaker", "Scanning tickets"]


def test_a_tripped_breaker_is_visible_in_the_run_log(monkeypatch):
    import json
    import job_events
    trip = {"signature": "measure:x", "tickets": [1, 2, 3], "first_seen": "t", "example": "e"}
    monkeypatch.setattr(tp.failure_breaker, "tripped", lambda now=None: [trip])
    monkeypatch.setattr(sys, "argv", ["ticket_pipeline.py"])
    tp.main()
    run = json.loads((job_events.JOBS_DIR / "ticket-pipeline.json").read_text())["runs"][-1]
    assert "circuit breaker" in run["summary"] and "TRIPPED" in run["steps"][-1]["detail"]


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
    monkeypatch.setattr(tp, "_release", lambda n, l, repo=None: got["releases"].append((n, l, repo)))
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


# ── "busy" must mean a ticket is actually running, not just that a flag file says so ─

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
