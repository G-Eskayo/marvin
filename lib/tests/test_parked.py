"""Parked choices (marvin#1222): every "until Gil decides" names a ticket with a Decisions block and a review-by date,
and surfaces when it's due or its blocker clears. One grammar (ticket_policy.parse_revisit's rules), one overdue
check (health row parked:overdue), one sweep on the hourly scan that puts the decision ticket in Needs you.

Tests try to break it (ADR 0063): a review_by already past on the first run (fires once, not hourly), a condition in
another repo or on a deleted ticket, a decision ticket with no Decisions block, the same park in two files, garbled
entries, GitHub down, both Macs running the sweep. GitHub is a fake answering the real query. Temp dirs only.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_parked.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(LIB / "tests"))

import parked  # noqa: E402
from test_resume_check import FakeGitHub, issue  # noqa: E402

pytestmark = pytest.mark.requires_tool("node")
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
DECISIONS = "## Decisions\n<!-- marvin:decisions -->\n### triage-act: Act on triage again?\n- [ ] Yes\n- [ ] No\n"


def ticket(body=DECISIONS, state="OPEN", labels=("hold",), title="Triage: act or propose"):
    t = issue(title, state=state)
    t["body"] = body
    t["labels"] = {"nodes": [{"name": n} for n in labels]}
    return t


@pytest.fixture
def roots(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    mem = tmp_path / "memory"
    mem.mkdir()
    return {"config_dirs": [cfg], "memory_dir": mem}


def park(roots, name="ticket_agents.json", **entries):
    p = roots["config_dirs"][0] / name
    p.write_text(json.dumps({"mode": "propose", "parked": entries}))
    return p


def run(roots, items=None, gh=None, **kw):
    return parked.report(**roots, run=gh or FakeGitHub(items), now=NOW, **kw)


# ── the grammar ──────────────────────────────────────────────────────────────

def test_a_config_park_is_read_with_its_ticket_and_date(roots):
    park(roots, triage={"decision": "G-Eskayo/marvin#1220", "review_by": "2026-11-16", "what": "triage acts again"})
    [e] = parked.entries(**roots)
    assert e["id"] == "triage" and e["decision"] == "G-Eskayo/marvin#1220" and e["revisit"]["date"] == "2026-11-16"
    assert e["source"].endswith("ticket_agents.json") and e["problems"] == []


def test_a_memory_park_is_read_from_front_matter(roots):
    (roots["memory_dir"] / "feedback-x.md").write_text(
        "---\nname: feedback-x\ndescription: d\nopen_question: G-Eskayo/marvin#715\nreview_by: 2026-11-12\n"
        "condition: \"#715 closes\"\nmetadata:\n  type: feedback\n---\nbody\n")
    [e] = parked.entries(**roots)
    assert e["decision"] == "G-Eskayo/marvin#715" and e["revisit"]["condition"] == "#715 closes"


@pytest.mark.parametrize("entry,problem", [
    ({"review_by": "2026-11-16"}, "names no decision ticket"),
    ({"decision": "marvin 1220", "review_by": "2026-11-16"}, "not owner/repo#N"),
    ({"decision": "G-Eskayo/marvin#1220"}, "no review_by"),
    ({"decision": "G-Eskayo/marvin#1220", "review_by": "next week"}, "not YYYY-MM-DD"),
    ({"decision": "G-Eskayo/marvin#1220", "review_by": "2026-02-31"}, "not YYYY-MM-DD"),
    ("just a string", "not an object"),
])
def test_a_garbled_park_is_flagged_not_dropped(roots, entry, problem):
    park(roots, x=entry)
    [e] = parked.entries(**roots)
    assert any(problem in p for p in e["problems"])


def test_a_config_file_that_isnt_json_is_skipped_never_raises(roots):
    (roots["config_dirs"][0] / "broken.json").write_text("{nope")
    assert parked.entries(**roots) == []


# ── the overdue check ────────────────────────────────────────────────────────

def test_a_review_by_already_past_is_overdue_and_names_the_ticket(roots):
    park(roots, triage={"decision": "G-Eskayo/marvin#1220", "review_by": "2026-10-28", "what": "triage acts again"})
    r = run(roots, {"G-Eskayo/marvin#1220": ticket()})
    [o] = r["overdue"]
    assert o["id"] == "triage" and o["days_over"] == 13 and o["why"] == "review-by passed"
    row = parked.row(r, now=NOW)
    assert row["id"] == "parked:overdue" and row["severity"] == "yellow"
    assert "triage acts again" in row["detail"] and "G-Eskayo/marvin#1220" in row["detail"]


def test_not_yet_due_is_green(roots):
    park(roots, triage={"decision": "G-Eskayo/marvin#1220", "review_by": "2026-11-16"})
    r = run(roots, {"G-Eskayo/marvin#1220": ticket()})
    assert r["overdue"] == [] and parked.row(r, now=NOW)["severity"] == "green"


def test_a_condition_that_came_true_makes_it_due_early(roots):
    park(roots, review={"decision": "G-Eskayo/marvin#1300", "review_by": "2026-12-01", "condition": "#715 closes"})
    r = run(roots, {"G-Eskayo/marvin#1300": ticket(), "G-Eskayo/marvin#715": ticket(state="CLOSED", body="")})
    assert r["overdue"][0]["why"] == "its condition came true (G-Eskayo/marvin#715 closed)"


def test_a_condition_in_another_repo_is_followed(roots):
    park(roots, x={"decision": "G-Eskayo/marvin#1300", "review_by": "2026-12-01", "condition": "G-Eskayo/clarity-captions#9 closes"})
    r = run(roots, {"G-Eskayo/marvin#1300": ticket(), "G-Eskayo/clarity-captions#9": ticket(state="CLOSED", body="")})
    assert "clarity-captions#9 closed" in r["overdue"][0]["why"]


def test_a_deleted_condition_or_decision_ticket_is_flagged(roots):
    park(roots, x={"decision": "G-Eskayo/marvin#1300", "review_by": "2026-12-01", "condition": "#999 closes"},
         y={"decision": "G-Eskayo/marvin#404", "review_by": "2026-12-01"})
    r = run(roots, {"G-Eskayo/marvin#1300": ticket()})
    probs = {f["id"]: f["problem"] for f in r["flagged"]}
    assert "G-Eskayo/marvin#999" in probs["x"] and "couldn't be read" in probs["x"]
    assert "couldn't be read" in probs["y"]


def test_a_decision_ticket_with_no_decisions_block_is_flagged(roots):
    park(roots, x={"decision": "G-Eskayo/marvin#1300", "review_by": "2026-12-01"})
    r = run(roots, {"G-Eskayo/marvin#1300": ticket(body="Should we do it? Not sure.")})
    assert "no Decisions block" in r["flagged"][0]["problem"]


def test_a_closed_decision_ticket_means_the_park_is_answered_and_should_go(roots):
    park(roots, x={"decision": "G-Eskayo/marvin#1300", "review_by": "2026-12-01"})
    r = run(roots, {"G-Eskayo/marvin#1300": ticket(state="CLOSED")})
    assert "is closed: answered" in r["flagged"][0]["problem"]


def test_the_same_park_in_two_files_is_flagged_once_each_and_checked_once(roots):
    park(roots, triage={"decision": "G-Eskayo/marvin#1220", "review_by": "2026-10-28"})
    park(roots, "parked.json", triage={"decision": "G-Eskayo/marvin#1220", "review_by": "2026-10-28"})
    gh = FakeGitHub({"G-Eskayo/marvin#1220": ticket()})
    r = run(roots, gh=gh)
    assert len(gh.calls) == 1 and len(r["overdue"]) == 1
    assert any("also parked in" in f["problem"] for f in r["flagged"])


def test_github_down_is_unknown_never_green(roots):
    park(roots, x={"decision": "G-Eskayo/marvin#1300", "review_by": "2026-12-01"})
    r = run(roots, gh=FakeGitHub(raises=subprocess.TimeoutExpired("gh", 5)))
    row = parked.row(r, now=NOW)
    assert r["status"] == "unverified" and row["severity"] == "unknown" and "couldn't check" in row["detail"]


def test_a_date_only_park_still_fires_when_github_is_down(roots):
    park(roots, x={"decision": "G-Eskayo/marvin#1300", "review_by": "2026-11-01"})
    r = run(roots, gh=FakeGitHub(raises=subprocess.TimeoutExpired("gh", 5)))
    assert [o["id"] for o in r["overdue"]] == ["x"] and parked.row(r, now=NOW)["severity"] == "yellow"


# ── the sweep: the decision ticket goes to Needs you, once ───────────────────

def _gh_recorder(labels):
    calls = []

    def gh(args):
        calls.append(args)
        if args[:2] == ["issue", "view"]:
            return json.dumps({"labels": [{"name": n} for n in labels]})
        return ""
    return gh, calls


def test_the_sweep_moves_an_overdue_decision_into_needs_you_once(roots):
    park(roots, triage={"decision": "G-Eskayo/marvin#1220", "review_by": "2026-10-28", "what": "triage acts again"})
    r = run(roots, {"G-Eskayo/marvin#1220": ticket(labels=("hold",))})
    gh, calls = _gh_recorder(["hold"])
    done = parked.sweep(r, gh=gh)
    assert done == ["G-Eskayo/marvin#1220"]
    edit = next(c for c in calls if c[:2] == ["issue", "edit"])
    assert "--add-label" in edit and "needs-info" in edit and "--remove-label" in edit and "hold" in edit
    comment = next(c for c in calls if c[:2] == ["issue", "comment"])
    assert any("review-by passed" in a for a in comment)


def test_the_sweep_does_nothing_when_the_ticket_is_already_in_needs_you(roots):
    park(roots, triage={"decision": "G-Eskayo/marvin#1220", "review_by": "2026-10-28"})
    r = run(roots, {"G-Eskayo/marvin#1220": ticket(labels=("needs-info",))})
    gh, calls = _gh_recorder(["needs-info"])
    assert parked.sweep(r, gh=gh) == [] and not any(c[:2] in (["issue", "edit"], ["issue", "comment"]) for c in calls)


def test_the_sweep_never_touches_a_flagged_park(roots):
    park(roots, x={"decision": "G-Eskayo/marvin#1300", "review_by": "2026-10-01"})
    r = run(roots, {"G-Eskayo/marvin#1300": ticket(body="no decisions here")})
    gh, calls = _gh_recorder(["hold"])
    assert parked.sweep(r, gh=gh) == [] and calls == []
