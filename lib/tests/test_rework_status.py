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
