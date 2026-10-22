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
    for lab in ("held", "pinned"):
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


def test_hold_detail_includes_who_held_it_when_provided():
    """When hold info is provided, the detail should mention who held it and when."""
    hold_info = {"who": "test-user", "when": datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc), "comment": None}
    s = rs.status_for(ticket(labels=("needs-reengagement", "held")), ctx(hold=hold_info))
    assert s["state"] == "held"
    assert "test-user" in s["detail"]
    assert "2026-10-07" in s["detail"]


def test_hold_detail_is_generic_when_no_hold_info_provided():
    """When no hold info is provided, use the generic message."""
    s = rs.status_for(ticket(labels=("needs-reengagement", "held")), ctx(hold=None))
    assert s["state"] == "held"
    assert "person asked the pipeline not to touch this ticket" in s["detail"]


def test_parse_iso_handles_valid_dates():
    """_parse_iso should parse valid ISO 8601 timestamps with Z suffix."""
    dt = rs._parse_iso("2026-10-07T12:00:00Z")
    assert dt == datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)


def test_parse_iso_returns_none_for_invalid_input():
    """_parse_iso should return None for invalid input."""
    assert rs._parse_iso(None) is None
    assert rs._parse_iso("invalid-date") is None
    assert rs._parse_iso(12345) is None


def test_latest_hold_event_returns_most_recent_event():
    """_latest_hold_event() should return the event with the latest created_at timestamp."""
    import json
    events = [
        json.dumps({"actor": "user1", "created_at": "2026-10-07T10:00:00Z"}),
        json.dumps({"actor": "user2", "created_at": "2026-10-07T12:00:00Z"}),
        json.dumps({"actor": "user3", "created_at": "2026-10-07T11:00:00Z"}),
    ]
    stdout = "\n".join(events)
    result = rs._latest_hold_event(stdout)
    assert result is not None
    assert result["actor"] == "user2"


def test_latest_hold_event_skips_malformed_lines():
    """_latest_hold_event() should skip malformed JSON lines."""
    import json
    events = [
        json.dumps({"actor": "user1", "created_at": "2026-10-07T10:00:00Z"}),
        "not valid json",
        json.dumps({"actor": "user2", "created_at": "2026-10-07T12:00:00Z"}),
    ]
    stdout = "\n".join(events)
    result = rs._latest_hold_event(stdout)
    assert result is not None
    assert result["actor"] == "user2"


def test_latest_hold_event_returns_none_for_empty_input():
    """_latest_hold_event() should return None for empty input."""
    assert rs._latest_hold_event("") is None
    assert rs._latest_hold_event("\n\n") is None


def test_comment_near_finds_comment_within_window():
    """_comment_near() should find a comment within HOLD_COMMENT_WINDOW_S."""
    import json
    import subprocess as sp

    gh_output = json.dumps({
        "comments": [
            {"body": "Old comment", "createdAt": "2026-10-07T10:00:00Z"},
            {"body": "Recent comment", "createdAt": "2026-10-07T12:04:00Z"},
        ]
    })

    def fake_gh(args):
        return gh_output

    when = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    result = rs._comment_near(fake_gh, "repo", 123, when)
    assert result == "Recent comment"


def test_comment_near_returns_none_outside_window():
    """_comment_near() should return None if no comment is within the window."""
    import json

    gh_output = json.dumps({
        "comments": [
            {"body": "Old comment", "createdAt": "2026-10-07T10:00:00Z"},
            {"body": "Too late", "createdAt": "2026-10-07T12:10:00Z"},
        ]
    })

    def fake_gh(args):
        return gh_output

    when = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    result = rs._comment_near(fake_gh, "repo", 123, when)
    assert result is None


def test_comment_near_returns_none_on_error():
    """_comment_near() should return None if gh call fails."""
    def fake_gh(args):
        raise Exception("gh call failed")

    when = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
    result = rs._comment_near(fake_gh, "repo", 123, when)
    assert result is None


def test_hold_info_returns_dict_with_comment():
    """_hold_info() should return dict with who, when, and comment."""
    import json

    events_output = json.dumps({"actor": "test-user", "created_at": "2026-10-07T12:00:00Z"})
    comments_output = json.dumps({
        "comments": [
            {"body": "Hold this", "createdAt": "2026-10-07T12:02:00Z"}
        ]
    })

    def fake_gh(args):
        # args is a list like ["api", "repos/...", ...] or ["issue", "view", ...]
        if len(args) > 0 and "events" in "".join(args):
            return events_output
        elif len(args) > 1 and args[0] == "issue" and args[1] == "view":
            return comments_output
        return ""

    result = rs._hold_info("repo", 123, gh=fake_gh)
    assert result is not None
    assert result["who"] == "test-user"
    assert result["comment"] == "Hold this"


def test_hold_comment_truncates_at_max_chars():
    """status_for() should truncate long hold comments."""
    # Use a more distinctive comment to verify truncation
    long_comment = "a" * 200 + "b" * 150 + "c" * 100
    hold_info = {
        "who": "test-user",
        "when": datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc),
        "comment": long_comment
    }
    s = rs.status_for(ticket(labels=("needs-reengagement", "held")), ctx(hold=hold_info))
    assert s["state"] == "held"
    assert "…" in s["detail"]
    # Check that the comment is included but truncated at 300 chars
    assert "a" * 100 in s["detail"]  # Part of the 'a' section is included
    # The 'c' section should not be fully present (it starts at position 350)
    assert "c" * 50 not in s["detail"]


def test_hold_detail_without_comment():
    """status_for() should handle hold info without comment gracefully."""
    hold_info = {
        "who": "test-user",
        "when": datetime(2026, 10, 7, 10, 30, tzinfo=timezone.utc),
        "comment": None
    }
    s = rs.status_for(ticket(labels=("needs-reengagement", "held")), ctx(hold=hold_info))
    assert s["state"] == "held"
    assert "test-user" in s["detail"]
    assert "2026-10-07" in s["detail"]
    assert "Comment:" not in s["detail"]
