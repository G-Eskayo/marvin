"""rework_status: where a sent-back ticket stands, so a card never just says 'a new version is coming'."""
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import rework_status as rs  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def ticket(n=143, labels=("ready-for-agent", "needs-reengagement")):
    return {"number": n, "labels": [{"name": l} for l in labels], "title": f"T{n}"}


def ctx(**over):
    base = dict(queue=[143, 148, 156], attempts=1, max_attempts=3, claim_started=None, paused=None, blockers=[],
                running=[], project="marvin", machines=["mac-mini-1"], now=NOW)
    base.update(over)
    return base


def test_a_claimed_ticket_is_being_rebuilt_right_now_with_how_long_and_which_attempt():
    s = rs.status_for(ticket(labels=("needs-reengagement", "claimed:mac-mini")), ctx(claim_started=NOW - timedelta(minutes=12), attempts=1))
    assert s["state"] == "running"
    assert "mac-mini" in s["detail"] and "12 min" in s["detail"] and "attempt 2 of 3" in s["detail"]


def test_an_eligible_ticket_is_queued_with_its_position_and_what_is_running_ahead_of_it():
    s = rs.status_for(ticket(143), ctx(queue=[148, 156, 143, 190], running=["#150 Some running ticket"]))
    assert s["state"] == "queued"
    assert s["position"] == 3 and s["of"] == 4
    assert "3rd of 4" in s["headline"]
    assert "#150" in s["detail"]


def test_queued_says_when_nothing_is_running_so_a_stall_is_visible():
    s = rs.status_for(ticket(143), ctx(queue=[143], running=[]))
    assert s["state"] == "queued" and "nothing is running" in s["detail"].lower()


def test_a_paused_project_says_why_it_is_not_starting():
    s = rs.status_for(ticket(), ctx(paused="claude-not-found failed across tickets 148, 156, 157"))
    assert s["state"] == "paused"
    assert "claude-not-found" in s["detail"]


def test_attempts_used_up_means_it_needs_a_person():
    s = rs.status_for(ticket(), ctx(attempts=3))
    assert s["state"] == "needs-person" and "3" in s["detail"]


def test_held_or_pinned_is_untouched_on_purpose():
    for lab in ("hold", "held", "pinned"):  # Test 1: extends to include "hold"
        s = rs.status_for(ticket(labels=("needs-reengagement", lab)), ctx())
        assert s["state"] == "held"


def test_a_ticket_waiting_on_another_names_it():
    s = rs.status_for(ticket(), ctx(blockers=[141]))
    assert s["state"] == "blocked" and "#141" in s["detail"]


def test_a_ticket_that_is_not_in_the_queue_for_no_stated_reason_says_so_honestly():
    s = rs.status_for(ticket(143), ctx(queue=[148, 156]))
    assert s["state"] == "not-queued"
    assert "not in the dispatch queue" in s["detail"].lower()


def test_ordinals():
    assert [rs.ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23)] == ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd"]


def test_a_ticket_the_pipeline_parked_says_so_instead_of_not_queued():
    """#148 failed three automated attempts, so the pipeline removed ready-for-agent and the claim. The card then said
    'Not queued, nothing explains why' although the pipeline had stopped on purpose and the ticket's own comment said so."""
    s = rs.status_for(ticket(148, labels=("needs-reengagement",)), ctx(queue=[143, 156]))
    assert s["state"] == "needs-person" and s["headline"].startswith("Parked")
    assert "ready-for-agent" in s["detail"] and "latest comment" in s["detail"]


def test_parked_beats_a_stale_pause_or_blocker_because_nothing_will_run_either_way():
    assert rs.status_for(ticket(labels=("needs-reengagement",)), ctx(paused="x failed", blockers=[5]))["headline"].startswith("Parked")


def test_a_running_ticket_without_ready_for_agent_is_still_running():
    assert rs.status_for(ticket(labels=("needs-reengagement", "claimed:mac-mini")), ctx())["state"] == "running"


def test_diagnosis_is_included_when_present(monkeypatch, tmp_path):
    """status_for() includes a diagnosis field if one is logged for this ticket."""
    import rework_status as rs_module
    monkeypatch.setattr(rs_module, "_read_diagnosis",
                       lambda ticket_number, repo: {"kind": "missing-tests", "route": "fix_forward"} if ticket_number == 143 else None)

    s = rs.status_for(ticket(143), ctx(queue=[143], project="G-Eskayo/marvin"))
    assert "diagnosis" in s
    assert s["diagnosis"]["kind"] == "missing-tests"
    assert s["diagnosis"]["route"] == "fix_forward"


def test_diagnosis_is_omitted_when_not_logged(monkeypatch, tmp_path):
    """status_for() doesn't include diagnosis if none is logged."""
    import rework_status as rs_module
    monkeypatch.setattr(rs_module, "_read_diagnosis", lambda ticket_number, repo: None)

    s = rs.status_for(ticket(143), ctx(queue=[143]))
    assert "diagnosis" not in s


def test_collect_reads_each_projects_open_issues_once(monkeypatch):
    # #324: the queue and the sent-back tickets come from one issue list per project, not two.
    import json as _json
    import subprocess as _sp
    import ticket_pipeline as tp
    import rework_status as rs
    calls = []
    issues = [{"number": 5, "title": "Sent back", "labels": [{"name": "needs-reengagement"}], "body": "", "createdAt": "2026-10-01T00:00:00Z"},
              {"number": 6, "title": "Ready", "labels": [{"name": "ready-for-agent"}], "body": "", "createdAt": "2026-10-02T00:00:00Z"}]

    def fake_run(cmd, **kw):
        if cmd[:3] == ["gh", "issue", "list"]:
            calls.append(cmd)
            return _sp.CompletedProcess(cmd, 0, _json.dumps(issues), "")
        return _sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(_sp, "run", fake_run)
    monkeypatch.setattr(tp, "_attempts", lambda repo, n: 0)
    out = rs.collect(repos=["G-Eskayo/marvin", "G-Eskayo/clarity-captions"])
    assert len(calls) == 2
    assert set(out) == {"G-Eskayo/marvin#5", "G-Eskayo/clarity-captions#5"}
    assert out["G-Eskayo/marvin#5"]["state"] in {"queued", "not-queued", "blocked", "paused", "running", "held", "needs-person", "parked"}


# ── hold state with detail (#102, #358, ADR 0062) ────────────────────────────

def test_status_for_with_hold_info_includes_label_date_and_comment():
    """Test 2: status_for with hold_info → detail names label, elapsed time, and comment text."""
    hold_info = {
        "label": "hold",
        "since": (NOW - timedelta(hours=2, minutes=30)).isoformat(),
        "comment": "119 failed pipeline runs, debugging batch timeout issue"
    }
    s = rs.status_for(ticket(labels=("needs-reengagement", "hold")), ctx(hold_info=hold_info))
    assert s["state"] == "held"
    assert "hold" in s["detail"]
    assert "2 h ago" in s["detail"] or "150 min" in s["detail"] or "2h" in s["detail"]  # elapsed time
    assert "119 failed pipeline runs" in s["detail"]  # comment text without ellipsis


def test_status_for_with_hold_info_absent_still_reports_held():
    """Test 3: status_for with hold_info absent (gh unreachable) → state 'held', detail without date."""
    s = rs.status_for(ticket(labels=("needs-reengagement", "hold")), ctx(hold_info=None))
    assert s["state"] == "held"
    assert "not to touch this ticket" in s["detail"]
    assert "ago" not in s["detail"]  # no date


def test_status_for_with_malformed_comment_doesnt_crash():
    """Test 4: status_for with hold_info['comment'] as None/empty/non-string → detail omits without crashing."""
    for comment_val in (None, "", 123, {"bad": "object"}):
        hold_info = {"label": "held", "since": NOW.isoformat(), "comment": comment_val}
        s = rs.status_for(ticket(labels=("held",)), ctx(hold_info=hold_info))
        assert s["state"] == "held"
        assert "detail" in s


def test_status_for_with_both_hold_and_held_labels():
    """Test 5: status_for with both 'hold' and 'held' labels (person's mistake) → still 'held', no crash."""
    hold_info = {"label": "hold", "since": NOW.isoformat()}
    s = rs.status_for(ticket(labels=("hold", "held", "needs-reengagement")), ctx(hold_info=hold_info))
    assert s["state"] == "held"


def test_hold_info_with_gh_exception_returns_none():
    """Test 6: _hold_info when gh raises → returns None."""
    def gh_raises(args):
        raise OSError("Connection refused")

    result = rs._hold_info("G-Eskayo/marvin", 1, "hold", gh=gh_raises)
    assert result is None


def test_hold_info_with_no_labeled_event_returns_none():
    """Test 7: _hold_info when events list has no 'labeled' event for this label → returns None."""
    import json
    import subprocess

    def gh_no_labeled(args):
        if "events" in args[1]:
            # With --slurp, the response is a single flattened array
            return subprocess.CompletedProcess(args, 0, json.dumps([
                {"event": "commented", "created_at": NOW.isoformat()},
                {"event": "labeled", "label": {"name": "other-label"}, "created_at": NOW.isoformat()}
            ]), "")
        return subprocess.CompletedProcess(args, 0, "{}", "")

    result = rs._hold_info("G-Eskayo/marvin", 1, "hold", gh=gh_no_labeled)
    assert result is None


def test_hold_info_partial_degradation_when_comments_fetch_fails():
    """Test 8: _hold_info when events succeed but comments fetch fails → returns partial result."""
    import json
    import subprocess

    def gh_partial_fail(args):
        if "events" in args[1]:
            # With --slurp, events is a flattened array
            return subprocess.CompletedProcess(args, 0, json.dumps([
                {"event": "labeled", "label": {"name": "hold"}, "created_at": NOW.isoformat()}
            ]), "")
        if "issue" in args[1]:
            return subprocess.CompletedProcess(args, 1, "", "Error")  # fail
        return subprocess.CompletedProcess(args, 0, "{}", "")

    result = rs._hold_info("G-Eskayo/marvin", 1, "hold", gh=gh_partial_fail)
    assert result is not None
    assert result["label"] == "hold"
    assert result["since"] is not None
    assert "comment" not in result  # no comment due to failed fetch


def test_hold_info_ignores_comment_outside_window():
    """Test 9: _hold_info with comment outside HOLD_COMMENT_WINDOW_S → no comment key."""
    import json
    import subprocess

    event_time = NOW
    comment_time = NOW - timedelta(minutes=10)  # 10 minutes before event (outside default window)

    def gh_old_comment(args):
        if "events" in args[1]:
            # With --slurp, events is a flattened array
            return subprocess.CompletedProcess(args, 0, json.dumps([
                {"event": "labeled", "label": {"name": "hold"}, "created_at": event_time.isoformat()}
            ]), "")
        if "issue" in args[1]:
            return subprocess.CompletedProcess(args, 0, json.dumps({
                "comments": [{"body": "Old reason", "createdAt": comment_time.isoformat()}]
            }), "")
        return subprocess.CompletedProcess(args, 0, "{}", "")

    result = rs._hold_info("G-Eskayo/marvin", 1, "hold", gh=gh_old_comment)
    assert result is not None
    assert "comment" not in result  # outside window


def test_hold_info_picks_latest_labeled_event():
    """Test 10: _hold_info with repeats of same label → picks latest."""
    import json
    import subprocess

    first_time = NOW - timedelta(hours=1)
    latest_time = NOW

    def gh_repeats(args):
        if "events" in args[1]:
            # With --slurp, events is a flattened array
            return subprocess.CompletedProcess(args, 0, json.dumps([
                {"event": "labeled", "label": {"name": "hold"}, "created_at": first_time.isoformat()},
                {"event": "unlabeled", "label": {"name": "hold"}, "created_at": (NOW - timedelta(minutes=30)).isoformat()},
                {"event": "labeled", "label": {"name": "hold"}, "created_at": latest_time.isoformat()}
            ]), "")
        return subprocess.CompletedProcess(args, 0, json.dumps({"comments": []}), "")

    result = rs._hold_info("G-Eskayo/marvin", 1, "hold", gh=gh_repeats)
    assert result is not None
    assert result["since"] == latest_time.isoformat()


def test_collect_end_to_end_with_hold_ticket():
    """Test 11: collect() end-to-end on needs-reengagement + hold → hold_info populated, state 'held'."""
    import json as _json
    import subprocess as _sp
    import ticket_pipeline as tp
    import rework_status as rs

    calls = []
    issues = [{"number": 5, "title": "On hold", "labels": [{"name": "needs-reengagement"}, {"name": "hold"}], "body": "", "createdAt": "2026-10-01T00:00:00Z"}]
    events = [{"event": "labeled", "label": {"name": "hold"}, "created_at": NOW.isoformat()}]

    def fake_run(cmd, **kw):
        if cmd[:3] == ["gh", "issue", "list"]:
            calls.append(cmd)
            return _sp.CompletedProcess(cmd, 0, _json.dumps(issues), "")
        if "events" in " ".join(cmd):
            return _sp.CompletedProcess(cmd, 0, _json.dumps(events), "")
        return _sp.CompletedProcess(cmd, 0, _json.dumps({"comments": []}), "")

    import subprocess
    original_run = subprocess.run
    try:
        subprocess.run = fake_run
        import ticket_pipeline
        original_attempts = ticket_pipeline._attempts
        ticket_pipeline._attempts = lambda repo, n: 0
        out = rs.collect(repos=["G-Eskayo/marvin"])
        assert "G-Eskayo/marvin#5" in out
        assert out["G-Eskayo/marvin#5"]["state"] == "held"
        assert "hold" in out["G-Eskayo/marvin#5"]["detail"] or "On hold" in out["G-Eskayo/marvin#5"]["headline"]
    finally:
        subprocess.run = original_run
        ticket_pipeline._attempts = original_attempts
