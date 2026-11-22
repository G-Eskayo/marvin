"""Tests for ticket_evidence.py: does work for a ticket already exist? Pure rules over gathered facts."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ticket_evidence as te  # noqa: E402

FACTS = {
    "prs": [{"number": 28, "body": "Closes #21", "headRefName": "pipeline/21"}],
    "branches": ["origin/pipeline/21", "origin/pipeline/13"],
    "rescue": ["refs/rescue/pipeline/23/20261005T1200"],
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


# 2026-10-09: #213 and #259 were skipped as "looks-done" because docs commits only LISTED them.
def test_a_commit_counts_only_when_it_says_it_did_the_ticket():
    yes = ["Hooks at user level, launch-kind aware (#291)", "Project tagger and archive lifecycle (#298, #299; ADR 0060)",
           "Implement #296 comprehensively", "Fixes #12: board loads", "closes #12", "board refresh (refs #12)"]
    no = ["Plan: steps 1-2 done, tickets #259-#263 for the rest", "docs: ticket triage applied; revisit #213 later",
          "Follow-on filed: #68", "see #12 and #13 for context",
          "docs: ticket triage 2026-10-07 applied; revisit schedule for holds (#213)",
          "Implement G-Eskayo/marvin#296"]  # repo slug #n should not count (#1270)
    import ticket_evidence as te
    for s in yes:
        n = int(__import__("re").findall(r"#(\d+)", s)[0])
        assert te._commit_claims(s, n), s
    for s in no:
        n = int(__import__("re").findall(r"#(\d+)", s)[0])
        assert not te._commit_claims(s, n), s


def test_ticket_number_glued_to_repo_slug_does_not_count_as_evidence():
    # "clarity-captions#10" (single-word slug) should not count, but "#10" alone should
    facts = {"prs": [], "branches": [], "rescue": [], "commits": [("abc", "Implement clarity-captions#10")]}
    assert te.evidence_for(10, facts) == []  # single-word slug#n is not same-repo evidence

    # But the same commit with "#10" alone should count
    facts2 = {"prs": [], "branches": [], "rescue": [], "commits": [("abc", "Implement #10")]}
    assert len(te.evidence_for(10, facts2)) > 0  # bare #n should count


def test_branch_pattern_must_be_pipeline_slash_number_or_pipeline_slash_owner_slash_repo_hash_number():
    facts = {"prs": [], "branches": ["origin/pipeline-21", "origin/pipeline/team-21", "origin/bugfix/21"], "rescue": [], "commits": []}
    assert te.evidence_for(21, facts) == []


def test_branch_pattern_accepts_owner_slash_repo_hash_prefix():
    facts = {"prs": [], "branches": ["origin/pipeline/owner/repo#21"], "rescue": [], "commits": []}
    ev = te.evidence_for(21, facts)
    assert ev[0]["kind"] == "branch" and ev[0]["ref"] == "origin/pipeline/owner/repo#21"


def test_mentions_with_repo_slug_prefix_does_not_match():
    facts = {"prs": [], "branches": [], "rescue": [], "commits": [("abc", "See clarity-captions#21 for details")]}
    assert te.evidence_for(21, facts) == []


def test_branch_matching_is_strict_to_the_number():
    facts = {"prs": [], "branches": ["origin/pipeline/210", "origin/pipeline/2"], "rescue": [], "commits": []}
    assert te.evidence_for(21, facts) == []
    assert te.evidence_for(210, facts)[0]["kind"] == "branch"


def test_rescue_ref_extraction_preserves_the_full_ref_path():
    facts = {**FACTS, "rescue": ["refs/rescue/pipeline/owner/repo#42/20261005T1200"]}
    ev = te.evidence_for(42, facts)
    assert ev[0]["kind"] == "rescue-ref" and ev[0]["ref"] == "refs/rescue/pipeline/owner/repo#42/20261005T1200"


def test_cross_repo_mentions_do_not_count():
    """A PR saying 'Part of G-Eskayo/clarity-captions#10' should not count as evidence for marvin#10."""
    facts = {"prs": [{"number": 5, "body": "Part of G-Eskayo/clarity-captions#10", "headRefName": "feature"}],
             "branches": [], "rescue": [], "commits": [], "merged": []}
    assert te.evidence_for(10, facts) == []


def test_cross_repo_claims_do_not_count():
    """A commit saying 'Closes other-owner/other-repo#10' should not mark the local #10 as done."""
    facts = {"prs": [], "branches": [], "rescue": [], "commits": [("abc", "Closes other-owner/other-repo#10")], "merged": []}
    assert te.evidence_for(10, facts) == []


def test_implement_with_text_before_ticket_counts():
    """'Implement X for #10' should count as a claim on #10."""
    facts = {"prs": [], "branches": [], "rescue": [], "commits": [("abc", "Implement something for #10")], "merged": []}
    ev = te.evidence_for(10, facts)
    assert len(ev) > 0 and ev[0]["kind"] == "commit"


def test_mentions_bare_ticket_in_text_counts():
    """A mention of a bare #N should count as evidence."""
    facts = {"prs": [{"number": 5, "body": "Part of #10", "headRefName": "feature"}],
             "branches": [], "rescue": [], "commits": [], "merged": []}
    ev = te.evidence_for(10, facts)
    assert len(ev) > 0 and ev[0]["kind"] == "open-pr"


