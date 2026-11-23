"""Tests for ticket_evidence.py: does work for a ticket already exist? Pure rules over gathered facts."""
import sys
import json
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


# 2026-10-09: #213 and #259 were skipped as "looks-done" because docs commits only LISTED them.
def test_a_commit_counts_only_when_it_says_it_did_the_ticket():
    yes = ["Hooks at user level, launch-kind aware (#291)", "Project tagger and archive lifecycle (#298, #299; ADR 0060)",
           "Implement G-Eskayo/marvin#296", "Fixes #12: board loads", "closes #12", "board refresh (refs #12)"]
    no = ["Plan: steps 1-2 done, tickets #259-#263 for the rest", "docs: ticket triage applied; revisit #213 later",
          "Follow-on filed: #68", "see #12 and #13 for context",
          "docs: ticket triage 2026-10-07 applied; revisit schedule for holds (#213)"]
    import ticket_evidence as te
    for s in yes:
        n = int(__import__("re").findall(r"#(\d+)", s)[0])
        assert te._commit_claims(s, n), s
    for s in no:
        n = int(__import__("re").findall(r"#(\d+)", s)[0])
        assert not te._commit_claims(s, n), s


# ── tightened naming convention (pipeline/ prefix required, cross-repo aware) ─

def test_named_requires_pipeline_prefix_to_match_branch():
    # Must start with "pipeline/" or similar pipeline-style naming
    assert te._named("origin/pipeline/marvin-21", 21) is True
    assert te._named("origin/pipeline/G-Eskayo/marvin-21", 21) is True
    # Non-pipeline branches should not match even if they contain the number
    assert te._named("origin/feature/something-21", 21) is False
    assert te._named("origin/bug-21-fix", 21) is False
    # Edge case: number at word boundary
    assert te._named("origin/pipeline/21", 21) is True


def test_named_rejects_extended_numbers():
    # #21 should not match if followed by digits (e.g., #210, #2100)
    assert te._named("origin/pipeline/marvin-210", 21) is False
    assert te._named("origin/pipeline/marvin-21a", 21) is True  # letter boundary OK


def test_mentions_requires_no_glued_repo_slug_for_bare_hash():
    # A bare #10 should not match if preceded by a repo slug like "clarity-captions#10"
    assert te._mentions("clarity-captions#10", 10) is False
    assert te._mentions("some-repo#10", 10) is False
    # But a bare #10 should still match
    assert te._mentions("#10 is the ticket", 10) is True
    assert te._mentions("fixes #10", 10) is True


def test_claims_requires_no_glued_repo_slug_for_bare_hash():
    # A bare "fixes #10" should match, but "fixes clarity-captions#10" should not
    assert te._claims("fixes #10", 10) is True
    assert te._claims("fixes clarity-captions#10", 10) is False
    assert te._claims("closes some-repo#10", 10) is False
    # Cross-repo refs with explicit # should work
    assert te._claims("closes clarity-captions#10", 10) is False  # Different ticket


def test_work_verb_excludes_part_of():
    # "part of #N" is NOT recognized as a work claim (it blocks parent tickets permanently).
    # Instead, use closingIssuesReferences for multi-PR tickets.
    facts = {**FACTS, "commits": [("x", "part of #99")]}
    assert te.verdict(te.evidence_for(99, facts)) == "clear"

    facts2 = {**FACTS, "merged": [{"number": 50, "body": "part of #88", "headRefName": "feature/x"}]}
    assert te.verdict(te.evidence_for(88, facts2)) == "clear"


# ── Regression tests for the reported bug and latent gaps ─

def test_version_build_number_in_branch_name_is_not_a_ticket_match():
    # gh pr view 267 --repo G-Eskayo/clarity-captions: headRefName="release/1.1.0-10"
    # This is NOT a pipeline branch; it should not block ticket #10
    facts = {**FACTS, "merged": [{"number": 267, "body": "version 1.1.0 (10)", "headRefName": "release/1.1.0-10"}]}
    assert te.evidence_for(10, facts) == [], "release branch names should not trigger _named() false positive"


def test_bare_paren_or_hash_in_a_version_like_title_text_never_marks_done():
    # Title text is never fetched today, but guard against future changes
    # A body with "Build 12 (#12 notes)" or "v2 (#3)" without verb should not match
    facts = {**FACTS, "merged": [{"number": 100, "body": "Build 12 (#12 notes)", "headRefName": "feature/x"}]}
    assert te.evidence_for(12, facts) == [], "#12 without a work verb should not mark done"

    facts2 = {**FACTS, "merged": [{"number": 101, "body": "v2 (#3)", "headRefName": "feature/y"}]}
    assert te.evidence_for(3, facts2) == [], "#3 alone in body should not mark done"


def test_real_closes_in_body_still_counts():
    # Ensure that actual work verbs still function after the branch-name fix
    facts = {**FACTS, "merged": [{"number": 50, "body": "Closes #10", "headRefName": "feature/x"}]}
    ev = te.evidence_for(10, facts)
    assert ev and te.verdict(ev) == "looks-done", "Real 'Closes #N' should still work"


def test_cross_repo_mention_in_body_does_not_mark_the_local_ticket_done():
    # "Part of clarity-captions#10" in an open PR should not match local ticket #10
    facts = {**FACTS, "prs": [{"number": 300, "body": "Part of clarity-captions#10", "headRefName": "feature/x"}]}
    assert te.evidence_for(10, facts) == [], "Cross-repo mention clarity-captions#10 should not match bare #10"


def test_closing_issue_reference_is_repo_scoped():
    # A PR's closingIssuesReferences from a different repo should not count for local ticket #N
    facts = {"prs": [], "branches": [], "rescue": [], "commits": [], "repo": "G-Eskayo/marvin",
             "merged": [{"number": 50, "body": "", "headRefName": "x",
                        "closingIssuesReferences": [{"number": 10, "repository": {"name": "clarity-captions", "owner": {"login": "g-eskayo"}}}]}]}
    assert te.evidence_for(10, facts) == [], "PR closing other-repo#10 should not block local #10"


def test_part_of_is_not_a_work_verb():
    # "Part of #N" is NOT a work verb (it blocks parent tickets permanently).
    # Partial PRs should use closingIssuesReferences to link, not text mentions.
    facts = {**FACTS, "merged": [{"number": 50, "body": "Part of #167", "headRefName": "feature/x"}]}
    assert te.verdict(te.evidence_for(167, facts)) == "clear", "'Part of' alone should not mark done"

    facts2 = {**FACTS, "commits": [("abc123", "Part of #168")]}
    assert te.verdict(te.evidence_for(168, facts2)) == "clear", "Commit 'Part of' alone should not mark done"


def test_real_pipeline_branch_naming_convention_is_recognized():
    # pipeline/g-eskayo/marvin#1317 should be recognized (the real live convention with #)
    facts = {**FACTS, "branches": ["origin/pipeline/g-eskayo/clarity-captions#10"]}
    ev = te.evidence_for(10, facts)
    assert ev and ev[0]["kind"] == "branch", "Real pipeline branch with # should match"


def test_old_hyphenated_pipeline_branch_fixture_still_matches():
    # Existing pipeline/clarity-captions-21 style should still work
    facts = {"prs": [], "branches": ["origin/pipeline/clarity-captions-21"], "rescue": [], "commits": []}
    ev = te.evidence_for(21, facts)
    assert ev and [e["kind"] for e in ev] == ["branch"], "Old pipeline/repo-N format should still work"


def test_closing_issues_reference_on_open_pr_means_in_flight():
    # If an open PR has closingIssuesReferences for local ticket #N, it's in-flight
    facts = {"prs": [{"number": 100, "body": "", "headRefName": "x",
                     "closingIssuesReferences": [{"number": 10, "repository": {"name": "marvin", "owner": {"login": "g-eskayo"}}}]}],
            "branches": [], "rescue": [], "commits": [], "repo": "G-Eskayo/marvin", "merged": []}
    ev = te.evidence_for(10, facts)
    assert ev and te.verdict(ev) == "in-flight", "Open PR with closingIssuesReferences should be in-flight"


def test_closing_issues_reference_on_merged_pr_means_looks_done():
    # If a merged PR has closingIssuesReferences for local ticket #N, it's looks-done
    facts = {"prs": [], "branches": [], "rescue": [], "commits": [], "repo": "G-Eskayo/marvin",
            "merged": [{"number": 101, "body": "", "headRefName": "x",
                       "closingIssuesReferences": [{"number": 10, "repository": {"name": "marvin", "owner": {"login": "g-eskayo"}}}]}]}
    ev = te.evidence_for(10, facts)
    assert ev and te.verdict(ev) == "looks-done", "Merged PR with closingIssuesReferences should be looks-done"


def test_evidence_for_tolerates_missing_or_malformed_closing_issues_references():
    # closingIssuesReferences can be missing, None, [], or have bad structure
    facts1 = {**FACTS, "prs": [{"number": 50, "body": "", "headRefName": "x"}]}  # missing field
    assert isinstance(te.evidence_for(10, facts1), list), "Missing closingIssuesReferences should not crash"

    facts2 = {**FACTS, "prs": [{"number": 51, "body": "", "headRefName": "x", "closingIssuesReferences": None}]}
    assert isinstance(te.evidence_for(10, facts2), list), "None closingIssuesReferences should not crash"

    facts3 = {**FACTS, "prs": [{"number": 52, "body": "", "headRefName": "x", "closingIssuesReferences": []}]}
    assert isinstance(te.evidence_for(10, facts3), list), "Empty closingIssuesReferences should not crash"

    facts4 = {**FACTS, "prs": [{"number": 53, "body": "", "headRefName": "x", "closingIssuesReferences": [{"number": 10}]}]}  # missing repo
    assert isinstance(te.evidence_for(10, facts4), list), "Missing repo in closingIssuesReferences should not crash"


def test_repo_matching_is_case_insensitive():
    # Facts repo "G-Eskayo/marvin" should match closingIssuesReferences with "marvin" / "g-eskayo"
    facts = {"prs": [], "branches": [], "rescue": [], "commits": [], "repo": "G-Eskayo/marvin",
            "merged": [{"number": 102, "body": "", "headRefName": "x",
                       "closingIssuesReferences": [{"number": 10, "repository": {"name": "marvin", "owner": {"login": "g-eskayo"}}}]}]}
    ev = te.evidence_for(10, facts)
    assert ev and te.verdict(ev) == "looks-done", "Case-insensitive repo matching should work"


def test_report_and_verdict_are_unaffected_by_the_new_repo_key():
    # Existing code without "repo" key should still work
    facts_no_repo = {**FACTS}  # FACTS doesn't have "repo" key
    r = te.report([21, 4, 99], facts_no_repo)
    assert set(r) == {"21", "4"}, "report() should work without repo key"
    assert r["21"]["verdict"] == "in-flight" and r["4"]["verdict"] == "looks-done"
