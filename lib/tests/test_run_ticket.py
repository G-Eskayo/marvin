"""Tests for run_ticket.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_run_ticket.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from subprocess import TimeoutExpired

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import run_ticket as rt  # noqa: E402
import ticket_stages as ts  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_ticket_stages(tmp_path, monkeypatch):
    # run()'s new ts.record_stage("done", ...) call writes to real
    # ~/.claude/logs/ticket-stages/<n>.json by default -- found live
    # 2026-10-01: every test here uses real-looking ticket numbers (20,
    # 27, 28...), and ran unmocked they wrote real files under the
    # account's actual ticket-stages directory.
    monkeypatch.setattr(ts, "STAGES_DIR", tmp_path / "ticket-stages")


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
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda *a: 0)

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
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda *a: 0)

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
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda *a: 0)
    monkeypatch.setattr(rt, "_release_claim", lambda *a: None)

    calls = []
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: calls.append(True))

    rt.run(20)

    assert calls == [True]


def test_trigger_redispatch_calls_request_scan(monkeypatch):
    calls = []

    def fake_request_scan():
        calls.append(True)

    monkeypatch.setattr(rt.redispatch_trigger, "request_scan", fake_request_scan)
    rt._trigger_redispatch()

    assert len(calls) == 1


def test_run_recovers_when_execute_ticket_raises_unexpectedly(monkeypatch):
    # Real incident, 2026-08-31: the planner subprocess call inside
    # execute_ticket hit its own 300s timeout for two tickets in a row
    # (subprocess.TimeoutExpired, uncaught) -- run() had no try/except
    # around execute_ticket at all, so the whole process crashed before
    # ever reaching raise_mr/_comment_failure/_release_claim/
    # _trigger_redispatch. Both tickets stayed claimed forever, exactly
    # the failure mode _release_claim was built to prevent, reached
    # through a different, uncaught path.
    def raise_timeout(*a, **kw):
        raise TimeoutExpired(cmd=["claude"], timeout=300)

    monkeypatch.setattr(rt, "execute_ticket", raise_timeout)
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda *a: 0)

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


def test_run_parks_the_ticket_instead_of_releasing_at_the_failure_cap(monkeypatch):
    # G-Eskayo/marvin#28, 2026-09-04..06: release-claim-then-immediate-
    # redispatch with no cross-call cap spun ~6,900 back-to-back headless
    # sessions in 3 days on a ticket that never once made progress. This is
    # the guard: the 3rd consecutive identical-failure comment parks it
    # instead of releasing it back for another immediate re-claim.
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "unchanged"})
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda issue_number: rt.MAX_CONSECUTIVE_FAILURES - 1)
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: None)
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    released = []
    monkeypatch.setattr(rt, "_release_claim", lambda issue_number: released.append(issue_number))
    parked = []
    monkeypatch.setattr(rt, "_park_stuck_ticket", lambda issue_number, streak: parked.append((issue_number, streak)))

    rt.run(28)

    assert released == []
    assert parked == [(28, rt.MAX_CONSECUTIVE_FAILURES)]


def test_run_still_releases_below_the_failure_cap(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "unchanged"})
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda issue_number: 0)
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: None)
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    released = []
    monkeypatch.setattr(rt, "_release_claim", lambda issue_number: released.append(issue_number))
    parked = []
    monkeypatch.setattr(rt, "_park_stuck_ticket", lambda issue_number, streak: parked.append((issue_number, streak)))

    rt.run(28)

    assert released == [28]
    assert parked == []


def test_consecutive_failure_streak_counts_trailing_failure_comments(monkeypatch):
    comments = [
        {"body": "some unrelated human comment"},
        {"body": f"{rt.FAILURE_MARKER}: unchanged"},
        {"body": f"{rt.FAILURE_MARKER}: unchanged"},
    ]

    class FakeResult:
        returncode = 0
        stdout = __import__("json").dumps({"comments": comments})

    monkeypatch.setattr(rt.subprocess, "run", lambda *a, **kw: FakeResult())

    assert rt._consecutive_failure_streak(28) == 2


def test_consecutive_failure_streak_resets_on_a_human_comment(monkeypatch):
    comments = [
        {"body": f"{rt.FAILURE_MARKER}: unchanged"},
        {"body": "ok, I re-scoped this, try again"},
        {"body": f"{rt.FAILURE_MARKER}: unchanged"},
        {"body": f"{rt.FAILURE_MARKER}: unchanged"},
    ]

    class FakeResult:
        returncode = 0
        stdout = __import__("json").dumps({"comments": comments})

    monkeypatch.setattr(rt.subprocess, "run", lambda *a, **kw: FakeResult())

    assert rt._consecutive_failure_streak(28) == 2


def test_park_stuck_ticket_removes_ready_for_agent_label(monkeypatch):
    monkeypatch.setattr(rt.machine_profile, "registry_id", lambda: "mac-mini-1")
    calls = []
    monkeypatch.setattr(rt.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    rt._park_stuck_ticket(28, 3)

    assert calls[0][:3] == ["gh", "issue", "edit"]
    assert "--remove-label" in calls[0] and "ready-for-agent" in calls[0]
    # Also drops the claim: ticket_pipeline only dispatches ready-for-agent
    # tickets with NO claimed:* label, so a parked ticket that kept its claim
    # could never be revived by a human re-adding ready-for-agent (found
    # 2026-10-01 re-releasing parked tickets -- the label alone did nothing).
    assert "claimed:mac-mini" in calls[0]
    assert calls[1][:3] == ["gh", "issue", "comment"]
    assert "Still labeled" not in calls[1][-1]
    assert "re-add `ready-for-agent`" in calls[1][-1]


def test_run_recovers_when_raise_mr_itself_raises_unexpectedly(monkeypatch):
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {})

    def raise_boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(rt, "raise_mr", raise_boom)
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda *a: 0)

    released = []
    monkeypatch.setattr(rt, "_release_claim", lambda issue_number: released.append(issue_number))
    monkeypatch.setattr(rt, "_comment_failure", lambda *a: None)
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)

    outcome = rt.run(27)

    assert outcome["raised"] is False
    assert "boom" in outcome["reason"]
    assert released == [27]


# ── failures/successes feed the cross-ticket circuit breaker ────────────────

def test_a_failed_run_records_a_failure_for_the_circuit_breaker(monkeypatch):
    import failure_breaker as fb
    seen = []
    monkeypatch.setattr(fb, "record_failure", lambda ticket, reason, now=None: seen.append((ticket, reason)))
    monkeypatch.setattr(rt, "execute_ticket", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda n: 0)
    for name in ("_comment_failure", "_release_claim", "_park_stuck_ticket", "_trigger_redispatch"):
        monkeypatch.setattr(rt, name, lambda *a, **k: None)

    rt.run(42)

    assert seen and seen[0][0] == 42 and "boom" in seen[0][1]


def test_a_successful_run_records_a_success_which_clears_the_breaker(monkeypatch):
    import failure_breaker as fb
    seen = []
    monkeypatch.setattr(fb, "record_success", lambda ticket, now=None: seen.append(ticket))
    monkeypatch.setattr(rt, "execute_ticket", lambda *a, **k: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {})
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **k: {"raised": True, "pr_url": "https://x/pr/1", "reason": None})
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda *a, **k: None)

    rt.run(43)

    assert seen == [43]


# ── tickets of another project (execution profile) ──────────────────────────

CC = "G-Eskayo/clarity-captions"
PROFILE = {"repo": CC, "base_branch": "main", "dispatch": "on", "machines": ["mac-mini-1"], "env": {}, "executor": {},
           "evidence": {"dev": {"na": "no simulator capture"}},
           "verify": [{"id": "core", "label": "Core tests", "command": ["swift", "test"], "required": True, "requires": ["swift"], "parser": "swift-test"}]}


class FakeMeasurer:
    def __init__(self, profile):
        self.profile = profile
        self.env = {"DEVELOPER_DIR": "/xcode"}
        self.report = {"tiers": [], "notes": []}

    def __call__(self, worktree):
        return {}

    def evidence(self):
        return {"suite": "Core tests", "passed": 60, "failed": 0, "total": 61}, {"na": True, "reason": "no simulator capture"}

    def pr_note(self):
        return "App build: not verified (needs xcodegen)"


def _profile_run_setup(monkeypatch, profile=PROFILE, clone=Path("/Users/me/Developer/clarity-captions")):
    import project_profile as pp
    monkeypatch.setattr(rt.pp, "load_profile", lambda repo, directory=None: profile if repo == CC else None)
    monkeypatch.setattr(rt.pp, "resolve_clone", lambda p, catalog=None, ensure=False: clone)
    monkeypatch.setattr(rt.pp, "Measurer", FakeMeasurer)
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)
    monkeypatch.setattr(rt, "_load_catalog", lambda: {"projects": []})


def test_a_profile_ticket_runs_in_the_projects_clone_on_its_base_branch_with_its_own_measure(monkeypatch):
    _profile_run_setup(monkeypatch)
    seen = {}

    def fake_execute(ticket_ref, subsystem, measure, **kw):
        seen.update(ticket_ref=ticket_ref, subsystem=subsystem, measure=measure, **kw)
        return _passing_result()

    monkeypatch.setattr(rt, "execute_ticket", fake_execute)
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": True, "pr_url": "http://pr", "reason": None})
    rt.run(7, repo=CC)
    assert seen["ticket_ref"] == f"{CC}#7"
    assert seen["subsystem"] == "clarity-captions-ticket-7"  # not "ticket-7": that name belongs to marvin's #7
    assert isinstance(seen["measure"], FakeMeasurer)
    assert seen["repo_path"] == Path("/Users/me/Developer/clarity-captions") and seen["base_branch"] == "main"
    assert callable(seen["executor"])


def test_a_profile_ticket_pr_carries_the_profiles_test_results_notes_and_dev_evidence(monkeypatch):
    _profile_run_setup(monkeypatch)
    monkeypatch.setattr(rt, "execute_ticket", lambda *a, **k: _passing_result())
    got = {}
    monkeypatch.setattr(rt, "raise_mr", lambda ref, result, test_results=None, dev_evidence=None, **kw: got.update(t=test_results, d=dev_evidence) or {"raised": True, "pr_url": "u", "reason": None})
    rt.run(7, repo=CC)
    assert got["t"]["suite"] == "Core tests" and "not verified" in got["t"]["notes"]
    assert got["d"] == {"na": True, "reason": "no simulator capture"}


def test_a_failed_profile_ticket_is_handled_in_its_own_repo_and_feeds_its_own_breaker(monkeypatch):
    _profile_run_setup(monkeypatch)
    monkeypatch.setattr(rt, "execute_ticket", lambda *a, **k: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "tests regressed"})
    calls = {}
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda n, repo=rt.REPO: calls.setdefault("streak", (n, repo)) and 0)
    monkeypatch.setattr(rt, "_comment_failure", lambda n, reason, repo=rt.REPO: calls.update(comment=(n, repo)))
    monkeypatch.setattr(rt, "_release_claim", lambda n, repo=rt.REPO: calls.update(release=(n, repo)))
    import failure_breaker as fb
    monkeypatch.setattr(fb, "record_failure", lambda ticket, reason, now=None, project=fb.MARVIN: calls.update(breaker=(ticket, project)))
    rt.run(7, repo=CC)
    assert calls["comment"] == (7, CC) and calls["release"] == (7, CC) and calls["breaker"] == (7, CC)


def test_a_machine_without_the_toolchain_releases_the_claim_without_blaming_the_ticket(monkeypatch):
    _profile_run_setup(monkeypatch)
    import project_profile as pp

    def boom(*a, **k):
        raise pp.EnvMissing("core", ["xcode"])

    monkeypatch.setattr(rt, "execute_ticket", boom)
    calls = {"comment": 0, "breaker": 0, "park": 0}
    monkeypatch.setattr(rt, "_release_claim", lambda n, repo=rt.REPO: calls.update(release=(n, repo)))
    monkeypatch.setattr(rt, "_comment_failure", lambda *a, **k: calls.update(comment=calls["comment"] + 1))
    monkeypatch.setattr(rt, "_park_stuck_ticket", lambda *a, **k: calls.update(park=calls["park"] + 1))
    import failure_breaker as fb
    monkeypatch.setattr(fb, "record_failure", lambda *a, **k: calls.update(breaker=calls["breaker"] + 1))
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda *a, **k: 2)  # even at the cap, this is not a strike
    out = rt.run(7, repo=CC)
    assert calls["release"] == (7, CC)
    assert (calls["comment"], calls["breaker"], calls["park"]) == (0, 0, 0)
    assert out["raised"] is False and "xcode" in out["reason"]


def test_a_timed_out_test_releases_the_claim_without_blaming_the_ticket(monkeypatch):
    _profile_run_setup(monkeypatch)

    def boom(*a, **k):
        raise rt.TestTimedOut(["pytest", "-q"], 1200, "partial output")

    monkeypatch.setattr(rt, "execute_ticket", boom)
    calls = {"gh_comment": 0, "breaker": 0, "park": 0}
    monkeypatch.setattr(rt, "_release_claim", lambda n, repo=rt.REPO: calls.update(release=(n, repo)))
    monkeypatch.setattr(rt.subprocess, "run", lambda cmd, **kw: calls.update(gh_comment=calls["gh_comment"] + 1) if "issue" in cmd else None)
    monkeypatch.setattr(rt, "_park_stuck_ticket", lambda *a, **k: calls.update(park=calls["park"] + 1))
    import failure_breaker as fb
    monkeypatch.setattr(fb, "record_failure", lambda *a, **k: calls.update(breaker=calls["breaker"] + 1))
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda *a, **k: 2)  # timeout is never a strike, even at the cap
    out = rt.run(7)
    assert calls["release"] == (7, rt.REPO)
    assert (calls["gh_comment"], calls["breaker"], calls["park"]) == (1, 0, 0)  # posts a comment but no strike
    assert out["raised"] is False and "timed out" in out["reason"]


def test_a_repo_without_a_profile_is_refused_not_run_with_marvins_assumptions(monkeypatch):
    _profile_run_setup(monkeypatch)
    monkeypatch.setattr(rt, "execute_ticket", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    monkeypatch.setattr(rt, "_release_claim", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_comment_failure", lambda *a, **k: None)
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda *a, **k: 0)
    out = rt.run(3, repo="G-Eskayo/other")
    assert out["raised"] is False and "profile" in out["reason"]


def test_the_command_line_takes_a_plain_number_or_owner_repo_hash_number():
    assert rt.parse_ticket_arg("123") == (rt.REPO, 123)
    assert rt.parse_ticket_arg("G-Eskayo/clarity-captions#7") == ("G-Eskayo/clarity-captions", 7)
    with pytest.raises(ValueError):
        rt.parse_ticket_arg("not a ticket")


def test_gh_calls_for_another_project_name_that_project(monkeypatch):
    calls = []
    monkeypatch.setattr(rt.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    rt._comment_failure(7, "why", repo=CC)
    assert calls[0][calls[0].index("--repo") + 1] == CC


# ── build output is dropped when a run ends (storage plan C3): a worktree otherwise keeps its
# dashboard/node_modules (marvin) or SwiftPM .build (clarity, 2.1 GiB) until the PR merges.

def _capture_drops(monkeypatch):
    drops = []
    monkeypatch.setattr(rt, "drop_build_output", lambda wt, rels: drops.append((wt, list(rels))) or [])
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)
    return drops


def test_build_output_dropped_after_a_raised_pr(monkeypatch):
    drops = _capture_drops(monkeypatch)
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _passing_result())
    monkeypatch.setattr(rt, "test_command_for", lambda wt: ["pytest", "-q"])
    monkeypatch.setattr(rt, "capture_test_results", lambda wt, cmd: {"suite": "pytest", "passed": 1, "failed": 0, "total": 1})
    monkeypatch.setattr(rt, "ticket_touches_ui", lambda wt: False)
    monkeypatch.setattr(rt, "capture_dev_evidence", lambda wt, touches_ui: {"na": True})
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": True, "pr_url": "http://fake-pr", "reason": None})
    rt.run(20)
    assert drops == [(Path("/tmp/fake-worktree"), rt.MARVIN_BUILD_OUTPUT)]


def test_build_output_dropped_after_a_failed_run(monkeypatch):
    drops = _capture_drops(monkeypatch)
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "no"})
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda n, **kw: 0)
    monkeypatch.setattr(rt, "_comment_failure", lambda *a, **kw: None)
    monkeypatch.setattr(rt.failure_breaker, "record_failure", lambda *a, **kw: None)
    monkeypatch.setattr(rt, "_release_claim", lambda *a, **kw: None)
    rt.run(20)
    assert drops == [(Path("/tmp/fake-worktree"), rt.MARVIN_BUILD_OUTPUT)]


def test_no_worktree_means_nothing_to_drop(monkeypatch):
    drops = _capture_drops(monkeypatch)
    def boom(*a):
        raise RuntimeError("worktree creation failed")
    monkeypatch.setattr(rt, "execute_ticket", boom)
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda n, **kw: 0)
    monkeypatch.setattr(rt, "_comment_failure", lambda *a, **kw: None)
    monkeypatch.setattr(rt.failure_breaker, "record_failure", lambda *a, **kw: None)
    monkeypatch.setattr(rt, "_release_claim", lambda *a, **kw: None)
    rt.run(20)
    assert drops == []


def test_a_crash_while_dropping_never_breaks_the_run(monkeypatch):
    monkeypatch.setattr(rt, "drop_build_output", lambda wt, rels: (_ for _ in ()).throw(OSError("busy")))
    monkeypatch.setattr(rt, "_trigger_redispatch", lambda: None)
    monkeypatch.setattr(rt, "execute_ticket", lambda *a: _failing_result())
    monkeypatch.setattr(rt, "raise_mr", lambda *a, **kw: {"raised": False, "pr_url": None, "reason": "no"})
    monkeypatch.setattr(rt, "_consecutive_failure_streak", lambda n, **kw: 0)
    monkeypatch.setattr(rt, "_comment_failure", lambda *a, **kw: None)
    monkeypatch.setattr(rt.failure_breaker, "record_failure", lambda *a, **kw: None)
    monkeypatch.setattr(rt, "_release_claim", lambda *a, **kw: None)
    assert rt.run(20)["raised"] is False
