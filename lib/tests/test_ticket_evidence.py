"""Tests for ticket_evidence.py: does work for a ticket already exist? Pure rules over gathered facts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ticket_evidence as te  # noqa: E402

FACTS = {
    "prs": [{"number": 28, "body": "Closes #21", "headRefName": "pipeline/clarity-captions-21"}],
    "branches": ["origin/pipeline/clarity-captions-21", "origin/pipeline/clarity-captions-13"],
    "rescue": ["refs/rescue/pipeline/clarity-captions-23/20261005T1200"],
    "commits": [("abc1234", "Add live mistake highlighting (issue #4)"), ("def5678", "Fix #40 crash"),
                ("0aa1111", "Revert \"Add thing (#9)\"")],
}


def kinds(n):
    return [e["kind"] for e in te.evidence_for(n, FACTS)]


def test_open_pr_is_in_flight():
    ev = te.evidence_for(21, FACTS)
    assert ev[0]["kind"] == "open-pr" and ev[0]["ref"] == "PR #28"
    assert te.verdict(ev) == "in-flight"


def test_branch_and_rescue_ref_are_in_flight():
    assert "branch" in kinds(13)
    assert kinds(23) == ["rescue-ref"] and te.verdict(te.evidence_for(23, FACTS)) == "in-flight"


def test_commit_on_base_means_looks_done():
    ev = te.evidence_for(4, FACTS)
    assert [e["kind"] for e in ev] == ["commit"] and te.verdict(ev) == "looks-done"


def test_number_matching_is_exact_and_reverts_ignored():
    assert te.evidence_for(4, {**FACTS, "commits": [("x", "fix #40")]}) == []
    assert te.evidence_for(9, FACTS) == []  # only a revert mentions it


def test_no_evidence_is_clear():
    assert te.evidence_for(99, FACTS) == [] and te.verdict([]) == "clear"


def test_in_flight_outranks_looks_done():
    f = {**FACTS, "commits": [("x", "part of #21")]}
    assert te.verdict(te.evidence_for(21, f)) == "in-flight"


def test_report_lists_only_tickets_with_evidence():
    r = te.report([21, 4, 99], FACTS)
    assert set(r) == {"21", "4"}
    assert r["21"]["verdict"] == "in-flight" and r["4"]["verdict"] == "looks-done"
    assert r["4"]["evidence"][0]["ref"] == "f34cc8b" or r["4"]["evidence"][0]["kind"] == "commit"


def test_merged_pr_that_refs_the_ticket_means_looks_done():
    facts = {**FACTS, "merged": [{"number": 31, "body": "Refs #7\n\nthe change", "headRefName": "pipeline/x-7"},
                                  {"number": 32, "body": "Refs #70", "headRefName": "feature/other"}]}
    ev = te.evidence_for(7, facts)
    assert [e["kind"] for e in ev] == ["merged-pr"] and ev[0]["ref"] == "PR #31"
    assert te.verdict(ev) == "looks-done"
    assert te.evidence_for(8, facts) == []  # #70 is not #7, nor 8


def test_merged_pr_and_open_pr_together_stay_in_flight():
    facts = {**FACTS, "merged": [{"number": 30, "body": "Refs #21", "headRefName": "a"}]}
    assert te.verdict(te.evidence_for(21, facts)) == "in-flight"



def test_merged_design_pr_that_only_points_forward_at_a_ticket_is_not_done_evidence():
    # clarity-captions PR #70: a design session that says which tickets will implement it.
    body = ("Closes #3.\n\n- **ADR 0018**: four states. Implemented by #9.\n"
            "- **ADR 0022**: retention. Implemented by #8 and #52.\nFollow-on filed: #68")
    facts = {**FACTS, "merged": [{"number": 70, "body": body, "headRefName": "design-3"}]}
    for n in (9, 8, 52, 68):
        assert te.evidence_for(n, facts) == [], n
    assert te.verdict(te.evidence_for(3, facts)) == "looks-done"


def test_merged_pr_work_verbs_count_as_done_evidence():
    for body in ("Fixes #5", "resolved #5", "Implements #5 end to end", "References: #5", "Land work. Refs #5."):
        facts = {**FACTS, "merged": [{"number": 40, "body": body, "headRefName": "x"}]}
        assert te.verdict(te.evidence_for(5, facts)) == "looks-done", body
