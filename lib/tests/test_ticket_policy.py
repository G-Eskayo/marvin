"""Tests for ticket_policy.py -- the pure rules behind the ticket agents.
Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_policy.py -v
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import ticket_policy as tp  # noqa: E402

NOW = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)


def iso(days_ago=0.0, hours_ago=0.0):
    return (NOW - timedelta(days=days_ago, hours=hours_ago)).isoformat()


def issue(n=1, labels=(), body="", title="T", created=0, updated=0):
    return {"number": n, "title": title, "labels": [{"name": l} for l in labels], "body": body,
            "createdAt": iso(created), "updatedAt": iso(updated)}


# ── blockers ────────────────────────────────────────────────────────────────

def test_blockers_read_both_the_inline_and_the_section_form_and_ignore_none():
    assert tp.parse_blocked_by("Blocked by #7") == {7}
    assert tp.parse_blocked_by("## Blocked by\n\n- #12 the schema\n- #13\n\n## Notes\nsee #99") == {12, 13}
    assert tp.parse_blocked_by("## Blocked by\n\nNone - can start immediately") == set()


def test_open_blockers_only_counts_blockers_that_are_still_open():
    t = issue(body="## Blocked by\n\n- #7\n- #8")
    assert tp.open_blockers(t, {1, 7}) == [7]
    assert tp.open_blockers(t, {1}) == []


# ── stale claims ────────────────────────────────────────────────────────────

def test_a_claim_idle_for_two_days_is_stale_and_names_the_machine():
    s = tp.stale_claim(issue(labels=["claimed:mac-mini"], updated=3), NOW)
    assert s["machine"] == "mac-mini" and s["idle_hours"] >= 72


def test_a_recently_touched_claim_or_an_unclaimed_ticket_is_not_stale():
    assert tp.stale_claim(issue(labels=["claimed:mac-mini"], updated=0.5), NOW) is None
    assert tp.stale_claim(issue(labels=["ready-for-agent"], updated=30), NOW) is None


# ── priority ────────────────────────────────────────────────────────────────

def test_what_a_ticket_unblocks_and_a_hard_deadline_raise_its_priority():
    plain = tp.score_ticket(issue(), blocks_count=0, due=None, now=NOW)[0]
    unblocks = tp.score_ticket(issue(), blocks_count=4, due=None, now=NOW)[0]
    hard_soon = tp.score_ticket(issue(), blocks_count=0, due={"date": "2026-10-08", "hard": True}, now=NOW)[0]
    soft_soon = tp.score_ticket(issue(), blocks_count=0, due={"date": "2026-10-08", "hard": False}, now=NOW)[0]
    assert unblocks > plain
    assert hard_soon > soft_soon > plain


def test_bugs_outrank_enhancements_and_old_tickets_creep_up_but_only_so_far():
    bug = tp.score_ticket(issue(labels=["bug"]), 0, None, NOW)[0]
    enh = tp.score_ticket(issue(labels=["enhancement"]), 0, None, NOW)[0]
    old = tp.score_ticket(issue(created=40), 0, None, NOW)[0]
    ancient = tp.score_ticket(issue(created=4000), 0, None, NOW)[0]
    assert bug > enh
    assert old > tp.score_ticket(issue(created=1), 0, None, NOW)[0]
    assert ancient == tp.score_ticket(issue(created=50), 0, None, NOW)[0]  # age stops counting after 50 days


def test_scores_come_with_human_readable_reasons():
    _score, reasons = tp.score_ticket(issue(labels=["bug"]), blocks_count=3, due={"date": "2026-10-10", "hard": True}, now=NOW)
    text = " ".join(reasons)
    assert "unblocks 3" in text and "hard deadline" in text and "bug" in text


def test_thresholds_map_scores_to_p0_through_p3():
    assert tp.priority_for(25) == "priority:p0"
    assert tp.priority_for(12) == "priority:p1"
    assert tp.priority_for(5) == "priority:p2"
    assert tp.priority_for(0) == "priority:p3"


def test_existing_priority_label_is_read_as_a_rank():
    assert tp.priority_rank(issue(labels=["priority:p1"])) == 1
    assert tp.priority_rank(issue(labels=["bug"])) is None


# ── triage ──────────────────────────────────────────────────────────────────

GOOD = "## What to build\n\nA thing.\n\n## Acceptance criteria\n\n- [ ] works\n- [ ] tested\n"


def test_a_fully_specified_ticket_is_ready_for_an_agent():
    v = tp.triage_verdict(issue(labels=["needs-triage"], body=GOOD, title="Add the thing"))
    assert v["state"] == "ready-for-agent" and v["category"] == "enhancement"


def test_a_ticket_that_needs_a_person_is_ready_for_human_once_it_says_what_to_do():
    task = "\n## Your task\n**What I need from you:** a decision.\n**Where:** here.\n**How:** think.\n**What to send back:** a reply.\n"
    v = tp.triage_verdict(issue(body=GOOD + task, title="Design session: decide on retention"))
    assert v["state"] == "ready-for-human"


def test_a_thin_ticket_needs_info_and_says_what_is_missing():
    v = tp.triage_verdict(issue(body="make it better"))
    assert v["state"] == "needs-info"
    assert "acceptance criteria" in v["missing"]


def test_bug_wording_picks_the_bug_category():
    assert tp.triage_verdict(issue(body=GOOD, title="Crash when the file is empty"))["category"] == "bug"


def test_already_triaged_tickets_are_left_alone():
    for lab in ("ready-for-agent", "ready-for-human", "needs-info", "wontfix", "needs-reengagement"):
        assert tp.triage_verdict(issue(labels=[lab], body=GOOD)) is None
    assert tp.triage_verdict(issue(labels=["pinned"], body=GOOD)) is None


def test_triage_leaves_parent_prds_and_claimed_tickets_alone():
    prd = "## Problem Statement\n\nx\n\n## Solution\n\ny\n\n## User Stories\n\n1. as a user"
    assert tp.triage_verdict(issue(body=prd, title="Add the board")) is None
    assert tp.triage_verdict(issue(body="thin", title="PRD: MARVIN Activity Board")) is None
    assert tp.triage_verdict(issue(labels=["claimed:mac-mini"], body="thin")) is None


# ── tickets marked for a person must say exactly what to do ─────────────────

GOOD_TASK = """## What to build
Check the supported languages on the phone.

## Your task
**What I need from you:** the list of speech languages on your iPhone.
**Where:** your iPhone 17 Pro, in the Seal app, Settings > Speech languages.
**How:**
1. Install the newest build from TestFlight.
2. Open Settings > Speech languages and tap Copy.
**What to send back:** paste the copied text as a reply on this ticket.

## Acceptance criteria
- [ ] The list is recorded
"""


def test_a_complete_your_task_section_has_no_gaps():
    assert tp.human_task_gaps(GOOD_TASK) == []


def test_missing_or_empty_fields_are_named():
    assert tp.human_task_gaps("## What to build\nx\n") == ["a 'Your task' section", ]
    body = GOOD_TASK.replace("**Where:** your iPhone 17 Pro, in the Seal app, Settings > Speech languages.\n", "**Where:**\n")
    assert tp.human_task_gaps(body) == ["Where"]
    body = GOOD_TASK.replace("**What to send back:** paste the copied text as a reply on this ticket.\n", "")
    assert tp.human_task_gaps(body) == ["What to send back"]


def test_triage_sends_a_person_ticket_without_instructions_back_for_info_instead_of_to_the_person():
    issue = {"title": "Decide the launch languages", "labels": [],
             "body": "## What to build\nPick them.\n\n## Acceptance criteria\n- [ ] picked\n"}
    v = tp.triage_verdict(issue)
    assert v["state"] == "needs-info" and "Your task" in v["why"]
    issue["body"] = GOOD_TASK
    assert tp.triage_verdict(issue)["state"] == "ready-for-human"
