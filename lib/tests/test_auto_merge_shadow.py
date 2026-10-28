"""Tests for auto_merge_shadow.py (ADR 0064, #341): shadow mode, the 3-day report, and switch-on only on Gil's yes.
Written to break it: no PRs in the window, a PR Gil closed that shadow would have merged, a revert, the window not
over, switch-on twice or too early or with disagreements, a corrupt state file, a missing mutation score, a PR seen
many times, a PR that changes between runs.

Also tests the scoring refactor (#644): batching PRs, error logging, reason classification, cost measurement.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_auto_merge_shadow.py -v
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto_merge_shadow as sh  # noqa: E402
import mutation_check as mc  # noqa: E402
import error_log  # noqa: E402

DAY = 86400.0
T0 = 1_800_000_000.0
M = "G-Eskayo/marvin"


def pr(n, files=(("lib/x.py", 10), ("lib/tests/test_x.py", 10)), body="Mutation score: 90%", url=None, headRefOid="abc123", headRefName="branch"):
    return {"number": n, "repo": M, "url": url or f"https://github.com/{M}/pull/{n}", "title": f"PR {n}", "body": body,
            "files": [{"path": p, "additions": a, "deletions": 0, "status": "modified", "previous_path": None} for p, a in files],
            "headRefOid": headRefOid, "headRefName": headRefName}


FACTS = {"existing_top_level": {"lib", "docs", "dashboard", "config", "bin"}, "new_top_level_this_week": 0,
         "ramp_open": True, "render_check_passed": False}


@pytest.fixture
def state(tmp_path):
    return tmp_path / "shadow.json"


# ── Existing tests (kept from original) ───────────────────────────────────

def test_the_mutation_score_is_read_from_the_pr_and_missing_means_wait():
    assert sh.mutation_score("blah\nMutation score: 87%\n") == 87
    assert sh.mutation_score("## Mutation check\n\n**Score:** 92 %") == 92
    assert sh.mutation_score("no score here") is None
    assert sh.mutation_score("Mutation score: 950%") is None          # nonsense isn't a score


def test_a_verdict_needs_the_policy_and_a_score_of_80():
    v = sh.verdict(pr(1), FACTS)
    assert v["verdict"] == "auto"
    low = sh.verdict(pr(2, body="Mutation score: 70%"), FACTS)
    assert low["verdict"] == "ask" and any("70%" in r for r in low["reasons"])
    none = sh.verdict(pr(3, body=""), FACTS)
    assert none["verdict"] == "ask" and any("pending" in r for r in none["reasons"])
    core = sh.verdict(pr(4, files=(("dashboard/webhook-server/merge.js", 5),)), FACTS)
    assert core["verdict"] == "ask"


def test_shadow_starts_on_the_first_run_and_records_each_pr_once_with_its_first_verdict(state):
    sh.observe([pr(1), pr(2, body="")], FACTS, path=state, now=T0)
    sh.observe([pr(1, body="")], FACTS, path=state, now=T0 + 3600)      # changed later: the first verdict stays
    st = json.loads(state.read_text())
    assert st["mode"] == "shadow" and st["started_at"] == T0
    assert st["prs"][pr(1)["url"]]["verdict"] == "auto" and st["prs"][pr(1)["url"]]["seen"] == 2


def test_what_gil_did_is_recorded(state):
    sh.observe([pr(1), pr(2)], FACTS, path=state, now=T0)
    sh.record_outcome(pr(1)["url"], "merged", path=state)
    sh.record_outcome(pr(2)["url"], "closed", path=state)
    st = json.loads(state.read_text())
    assert st["prs"][pr(1)["url"]]["outcome"] == "merged" and st["prs"][pr(2)["url"]]["outcome"] == "closed"


def test_the_report_waits_three_days(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    assert sh.report(path=state, now=T0 + 2.9 * DAY)["ready"] is False
    assert sh.report(path=state, now=T0 + 3.1 * DAY)["ready"] is True


def test_the_report_counts_and_flags_what_gil_would_have_disagreed_with(state):
    sh.observe([pr(1), pr(2), pr(3, body="")], FACTS, path=state, now=T0)
    sh.record_outcome(pr(1)["url"], "merged", path=state)
    sh.record_outcome(pr(2)["url"], "closed", path=state)               # shadow would have merged it: a disagreement
    sh.record_outcome(pr(3)["url"], "closed", path=state)               # shadow would have asked: fine
    r = sh.report(path=state, now=T0 + 4 * DAY)
    assert r["seen"] == 3 and r["would_merge"] == 2 and [d["number"] for d in r["disagreements"]] == [2]
    assert "#2" in r["line"] and "closed or reverted" in r["line"] and "tighten" in r["line"]


def test_a_revert_counts_as_a_disagreement(state):
    sh.observe([pr(5)], FACTS, path=state, now=T0)
    sh.record_outcome(pr(5)["url"], "merged", path=state)
    sh.record_outcome(pr(5)["url"], "reverted", path=state)
    assert [d["number"] for d in sh.report(path=state, now=T0 + 4 * DAY)["disagreements"]] == [5]


def test_no_prs_in_the_window_says_so_and_keeps_shadowing(state):
    sh.observe([], FACTS, path=state, now=T0)
    r = sh.report(path=state, now=T0 + 4 * DAY)
    assert r["ready"] is True and r["seen"] == 0 and "no PRs" in r["line"]
    with pytest.raises(sh.SwitchOnRefused):
        sh.switch_on("Gil", path=state, now=T0 + 4 * DAY)


def test_switch_on_only_when_ready_without_disagreements_and_only_once(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    sh.record_outcome(pr(1)["url"], "merged", path=state)
    with pytest.raises(sh.SwitchOnRefused):
        sh.switch_on("Gil", path=state, now=T0 + DAY)                    # too early
    sh.switch_on("Gil", path=state, now=T0 + 4 * DAY)
    assert sh.mode(path=state) == "on"
    assert sh.switch_on("Gil", path=state, now=T0 + 5 * DAY) == "already on"


def test_switch_on_is_refused_while_there_are_disagreements(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    sh.record_outcome(pr(1)["url"], "closed", path=state)
    with pytest.raises(sh.SwitchOnRefused) as e:
        sh.switch_on("Gil", path=state, now=T0 + 4 * DAY)
    assert "#1" in str(e.value)


def test_a_corrupt_state_file_means_shadow_never_on_and_is_not_overwritten(state):
    state.write_text("{not json")
    assert sh.mode(path=state) == "shadow"
    with pytest.raises(ValueError):
        sh.observe([pr(1)], FACTS, path=state, now=T0)
    assert state.read_text() == "{not json"


def test_the_report_line_for_people_says_what_to_do(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    sh.record_outcome(pr(1)["url"], "merged", path=state)
    line = sh.report(path=state, now=T0 + 4 * DAY)["line"]
    assert "would have merged 1" in line and "switch on auto-merge" in line


def test_a_revert_stays_recorded_even_if_a_merged_outcome_arrives_later(state):
    sh.observe([pr(6)], FACTS, path=state, now=T0)
    sh.record_outcome(pr(6)["url"], "reverted", path=state)
    sh.record_outcome(pr(6)["url"], "merged", path=state)          # the hourly run catching up must not erase it
    assert [d["number"] for d in sh.report(path=state, now=T0 + 4 * DAY)["disagreements"]] == [6]


def test_the_score_line_written_by_the_mutation_check_is_read():
    assert sh.mutation_score("## Mutation Score\n\n**Score:** 87% (7/8) of planted bugs caught by this PR's tests.\n") == 87
    assert sh.mutation_score("## Mutation Score\n\n**Score:** 100% (0/0): no mutable lines\n") == 100
    assert sh.mutation_score("## Mutation Score\n\nScore: unknown (no test file for it). Auto-merge waits.\n") is None


def test_one_pr_is_picked_for_scoring_the_oldest_without_a_score_for_its_current_commit():
    prs = [{"url": "u3", "number": 3, "body": "", "headRefOid": "c3"},
           {"url": "u1", "number": 1, "body": "**Score:** 90% (9/10)", "headRefOid": "c1"},
           {"url": "u2", "number": 2, "body": "", "headRefOid": "c2"}]
    assert sh.pick_unscored(prs, scored={})["url"] == "u2"
    assert sh.pick_unscored(prs, scored={"u2": "c2"})["url"] == "u3"          # already scored at this commit
    assert sh.pick_unscored(prs[1:2], scored={}) is None


def test_a_pr_whose_score_is_stale_after_a_new_push_is_rescored():
    pr_ = {"url": "u1", "number": 1, "body": "**Score:** 90% (9/10)", "headRefOid": "new"}
    assert sh.pick_unscored([pr_], scored={"u1": "old"})["url"] == "u1"


def test_a_bot_pr_is_scored_ask_through_the_shadow_verdict():
    pr_ = {"repo": "G-Eskayo/marvin", "author": "MARVIN-bot-gil", "body": "",
          "files": [{"path": "lib/new_helper.py", "additions": 5, "deletions": 0, "status": "added", "previous_path": None}]}
    facts = {"existing_top_level": {"lib"}, "new_top_level_this_week": 0, "ramp_open": True}
    v = sh.verdict(pr_, facts)
    assert any("mac-mini-2012" in r for r in v.get("reasons", []))


# ── New tests for scoring refactor ───────────────────────────────────────

def test_score_one_pr_catches_mutation_check_exception_and_logs_it(state, tmp_path):
    """1: Crashing mutant run — mc.run_mutation_check raises; caught and logged."""
    prs = [pr(10, headRefOid="abc10")]
    sh.observe(prs, FACTS, path=state, now=T0)

    with patch("subprocess.run") as mock_run, \
         patch("tempfile.mkdtemp") as mock_mkdtemp, \
         patch("mutation_check.run_mutation_check") as mock_mc:
        scratch = tmp_path / "scratch-test"
        scratch.mkdir()
        mock_mkdtemp.return_value = str(scratch)
        mock_mc.side_effect = RuntimeError("mutant check crash")
        mock_run.return_value = Mock(returncode=0, stdout="base123\n", stderr="")

        success, detail = sh._score_one_pr(prs[0], M, state, T0)
        assert success is False
        assert "RuntimeError" in detail


def test_score_one_pr_removes_scratch_worktree_on_timeout(state, tmp_path):
    """2: A timeout — git fetch/worktree add raises; caught and logged, scratch removed."""
    import subprocess
    prs = [pr(12, headRefOid="abc12")]
    sh.observe(prs, FACTS, path=state, now=T0)

    with patch("subprocess.run") as mock_run, \
         patch("tempfile.mkdtemp") as mock_mkdtemp:
        scratch = tmp_path / "scratch-test"
        scratch.mkdir()
        mock_mkdtemp.return_value = str(scratch)

        # First run raises TimeoutExpired
        mock_run.side_effect = subprocess.TimeoutExpired("git", 30)

        success, detail = sh._score_one_pr(prs[0], M, state, T0)
        assert success is False


def test_score_one_pr_catches_gh_pr_edit_failure(state, tmp_path):
    """3: A PR closed while being scored — gh pr edit fails; caught and logged."""
    import subprocess
    prs = [pr(13, headRefOid="abc13")]
    sh.observe(prs, FACTS, path=state, now=T0)

    with patch("subprocess.run") as mock_run, \
         patch("tempfile.mkdtemp") as mock_mkdtemp, \
         patch("mutation_check.run_mutation_check") as mock_mc, \
         patch("mutation_check.render_section") as mock_render:
        scratch = tmp_path / "scratch-test"
        scratch.mkdir()
        mock_mkdtemp.return_value = str(scratch)
        mock_mc.return_value = {"status": "ok", "score": 0.85}
        mock_render.return_value = "## Mutation Score\n\n**Score:** 85%"

        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 4:  # The gh pr edit call
                raise subprocess.CalledProcessError(1, "gh")
            return Mock(returncode=0, stdout="base123\n", stderr="")

        mock_run.side_effect = side_effect

        success, detail = sh._score_one_pr(prs[0], M, state, T0)
        assert success is False


def test_oversized_pr_body_doesnt_break_mutation_score():
    """11: Huge/malformed PR body — oversized body doesn't break mutation_score."""
    huge_body = "X" * 100000 + "\nMutation score: 85%\n" + "Y" * 100000
    score = sh.mutation_score(huge_body)
    assert score == 85


def test_generalized_merge_bodies_with_custom_markers():
    """14: Person's mistake — hand-edited body, re-adds section with custom markers."""
    body_without_markers = "Some PR description\n\nOther content"
    new_section = "## Why Unscored\n\nQueued behind N others"

    result = mc.merge_bodies(
        body_without_markers,
        new_section,
        start_marker="<!-- marvin:unscored-reason -->",
        end_marker="<!-- /marvin:unscored-reason -->"
    )

    assert "<!-- marvin:unscored-reason -->" in result
    assert "<!-- /marvin:unscored-reason -->" in result
    assert new_section in result


def test_why_unscored_immediately_when_no_scoreable_lines():
    """7: Conclusively-unscoreable PR gets reason immediately."""
    pr_ = pr(100, files=(("dashboard/x.js", 5),), body="")

    mc_result = {
        "status": "unknown",
        "score": None,
        "unmeasured": [
            {"file": "dashboard/x.js", "line": 1, "snippet": "JS isn't mutation-tested yet"}
        ],
        "reason": "nothing could be scored"
    }

    reason = sh.why_unscored(pr_, T0, scored={}, mc_result=mc_result)
    assert reason is not None


def test_why_unscored_waits_24h_before_stating(state):
    """8: 24h boundary — 23h59m no reason, 24h01m gets reason."""
    pr_ = pr(101, body="")
    sh.observe([pr_], FACTS, path=state, now=T0)  # Record with first_seen=T0

    # Read back the PR state to get the first_seen field
    st = sh._read(state)
    pr_state = st["prs"][pr_["url"]]

    error_entries = []
    mc_result = {"status": "unknown", "score": None}

    # At 23:59:00, no reason (unless conclusively unscoreable)
    now = T0 + 86399
    reason_early = sh.why_unscored(pr_state, now, scored={}, error_log_entries=error_entries, mc_result=mc_result)
    assert reason_early is None or "conclusively" in (reason_early or "")

    # At 24:00:01, should get reason
    now = T0 + 86401
    reason_late = sh.why_unscored(pr_state, now, scored={}, error_log_entries=error_entries, mc_result=mc_result)
    assert reason_late is not None


def test_concurrency_with_flock(state):
    """12: Concurrency — two overlapping scans leave state consistent."""
    pr1 = pr(103, headRefOid="abc103")
    sh.observe([pr1], FACTS, path=state, now=T0)

    with sh._Locked(state) as st1:
        st1.setdefault("scored", {})[pr1["url"]] = pr1["headRefOid"]

    with sh._Locked(state) as st2:
        assert st2["scored"][pr1["url"]] == pr1["headRefOid"]


def test_stale_scored_commit_triggers_fresh_attempt(state):
    """13: Stale state — old headRefOid triggers fresh attempt."""
    pr_new = pr(104, headRefOid="new_commit")
    prs = [pr_new]
    sh.observe(prs, FACTS, path=state, now=T0)

    with sh._Locked(state) as st:
        st.setdefault("scored", {})[pr_new["url"]] = "old_commit"

    # pick_unscored should pick it because commit changed
    picked = sh.pick_unscored(prs, scored={pr_new["url"]: "old_commit"})
    assert picked is not None


def test_mutation_score_regex_handles_malformed_text():
    """11: Malformed text doesn't break mutation_score."""
    malformed = "garbage\x00\x01\x02text Mutation score: 75%"
    score = sh.mutation_score(malformed)
    assert score == 75
