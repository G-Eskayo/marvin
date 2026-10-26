"""Tests for auto_merge_shadow.py (ADR 0064, #341): shadow mode, the 3-day report, and switch-on only on Gil's yes.
Written to break it: no PRs in the window, a PR Gil closed that shadow would have merged, a revert, the window not
over, switch-on twice or too early or with disagreements, a corrupt state file, a missing mutation score, a PR seen
many times, a PR that changes between runs.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_auto_merge_shadow.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auto_merge_shadow as sh  # noqa: E402

DAY = 86400.0
T0 = 1_800_000_000.0
M = "G-Eskayo/marvin"


def pr(n, files=(("lib/x.py", 10), ("lib/tests/test_x.py", 10)), body="Mutation score: 90%", url=None):
    return {"number": n, "repo": M, "url": url or f"https://github.com/{M}/pull/{n}", "title": f"PR {n}", "body": body,
            "files": [{"path": p, "additions": a, "deletions": 0, "status": "modified", "previous_path": None} for p, a in files]}


FACTS = {"existing_top_level": {"lib", "docs", "dashboard", "config", "bin"}, "new_top_level_this_week": 0,
         "ramp_open": True, "render_check_passed": False}


@pytest.fixture
def state(tmp_path):
    return tmp_path / "shadow.json"


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


# Scoring moved here from Approve (review of #339 / PR #351): one unscored PR per hourly run.
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
    assert sh.pick_unscored(prs, scored={"u2": "old", "u3": "c3"})["url"] == "u2"   # a new commit gets a new score
    assert sh.pick_unscored(prs[1:2], scored={}) is None


def test_a_pr_whose_score_is_stale_after_a_new_push_is_rescored():
    pr_ = {"url": "u1", "number": 1, "body": "**Score:** 90% (9/10)", "headRefOid": "new"}
    assert sh.pick_unscored([pr_], scored={"u1": "old"})["url"] == "u1"


def test_a_bot_pr_is_scored_ask_through_the_shadow_verdict():
    import auto_merge_shadow as sh
    pr = {"repo": "G-Eskayo/marvin", "author": "MARVIN-bot-gil", "body": "",
          "files": [{"path": "lib/new_helper.py", "additions": 5, "deletions": 0, "status": "added", "previous_path": None}]}
    facts = {"existing_top_level": {"lib"}, "new_top_level_this_week": 0, "ramp_open": True}
    v = sh.verdict(pr, facts)
    assert any("mac-mini-2012" in r for r in v.get("reasons", []))


def test_pick_unscored_deprioritizes_prs_with_failures_at_their_current_sha():
    """Failure bookkeeping: PRs with MAX_CONSECUTIVE_FAILURES at current sha are deprioritized."""
    prs = [{"url": "u1", "number": 1, "body": "", "headRefOid": "c1"},
           {"url": "u2", "number": 2, "body": "", "headRefOid": "c2"}]
    failures = {"u1": {"count": sh.MAX_CONSECUTIVE_FAILURES, "sha": "c1"}}
    # u1 has failures, so u2 (older) should be picked despite higher number
    picked = sh.pick_unscored(prs, scored={}, score_failures=failures)
    assert picked["url"] == "u2", "should deprioritize u1 due to failures at c1"


def test_pick_unscored_resets_failure_count_on_new_sha():
    """Failure bookkeeping: failure count resets when sha changes."""
    prs = [{"url": "u1", "number": 1, "body": "", "headRefOid": "new_sha"}]
    failures = {"u1": {"count": sh.MAX_CONSECUTIVE_FAILURES, "sha": "old_sha"}}
    # u1 has a new sha, so it should be picked despite previous failures at old_sha
    picked = sh.pick_unscored(prs, scored={}, score_failures=failures)
    assert picked["url"] == "u1", "should pick u1 since sha changed"


def test_pick_unscored_picks_one_with_failures_if_all_have_failures():
    """Failure bookkeeping: if all have failures, still pick the oldest (don't block forever)."""
    prs = [{"url": "u1", "number": 1, "body": "", "headRefOid": "c1"},
           {"url": "u2", "number": 2, "body": "", "headRefOid": "c2"}]
    failures = {"u1": {"count": sh.MAX_CONSECUTIVE_FAILURES, "sha": "c1"},
                "u2": {"count": sh.MAX_CONSECUTIVE_FAILURES, "sha": "c2"}}
    picked = sh.pick_unscored(prs, scored={}, score_failures=failures)
    assert picked["url"] == "u1", "should pick oldest even if all have failures"


def test_no_wasted_repeats_same_sha_not_rescored():
    """Item 7: PR with same sha shouldn't be rescored."""
    prs = [{"url": "u1", "number": 1, "body": "**Score:** 90%", "headRefOid": "c1"}]
    picked = sh.pick_unscored(prs, scored={"u1": "c1"})
    assert picked is None, "should not pick a PR already scored at this sha"


def test_failure_counter_increments_on_repeated_failures(state):
    """Item 4,9,10: failure counter tracks consecutive failures per (url, sha).
    This test DRIVES _score_one through its failure path, not manually manipulating state."""
    import json
    from unittest.mock import patch, MagicMock

    prs = [{"url": "u1", "number": 1, "body": "", "headRefOid": "c1", "headRefName": "feature"}]
    mock_mc = MagicMock()

    def mock_subprocess_run(cmd, **kwargs):
        """Fail on git fetch/worktree add, but allow cleanup (worktree remove)."""
        if isinstance(cmd, list) and "remove" in cmd:
            return MagicMock()
        raise RuntimeError("subprocess failed")

    def mock_gh_raises(args):
        raise RuntimeError("gh failed")

    # First attempt: _score_one should increment count to 1
    with patch.dict("sys.modules", {"mutation_check": mock_mc}):
        with patch("auto_merge_shadow._gh", side_effect=mock_gh_raises):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                sh._score_one(prs, "G-Eskayo/marvin", state)

    data = json.loads(state.read_text())
    assert data["score_failures"]["u1"]["count"] == 1, "counter should be 1 after first failure"

    # Second attempt: increment to 2
    with patch.dict("sys.modules", {"mutation_check": mock_mc}):
        with patch("auto_merge_shadow._gh", side_effect=mock_gh_raises):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                sh._score_one(prs, "G-Eskayo/marvin", state)

    data = json.loads(state.read_text())
    assert data["score_failures"]["u1"]["count"] == 2, "counter should be 2 after second failure"

    # Third attempt: increment to 3
    with patch.dict("sys.modules", {"mutation_check": mock_mc}):
        with patch("auto_merge_shadow._gh", side_effect=mock_gh_raises):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                sh._score_one(prs, "G-Eskayo/marvin", state)

    data = json.loads(state.read_text())
    assert data["score_failures"]["u1"]["count"] == 3, "counter should be 3 after third failure"


def test_failure_counter_resets_on_sha_change(state):
    """Item 5: failure counter resets when PR gets a new push (new sha).
    This test DRIVES _score_one with a new sha, not re-implementing the reset logic."""
    import json
    from unittest.mock import patch, MagicMock

    mock_mc = MagicMock()

    def mock_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "remove" in cmd:
            return MagicMock()
        raise RuntimeError("subprocess failed")

    def mock_gh_raises(args):
        raise RuntimeError("gh failed")

    # First: fail with old sha to set count=3
    prs_old = [{"url": "u1", "number": 1, "body": "", "headRefOid": "old_sha", "headRefName": "feature"}]
    for _ in range(3):
        with patch.dict("sys.modules", {"mutation_check": mock_mc}):
            with patch("auto_merge_shadow._gh", side_effect=mock_gh_raises):
                with patch("subprocess.run", side_effect=mock_subprocess_run):
                    sh._score_one(prs_old, "G-Eskayo/marvin", state)

    data = json.loads(state.read_text())
    assert data["score_failures"]["u1"]["count"] == 3
    assert data["score_failures"]["u1"]["sha"] == "old_sha"

    # Second: fail with new sha, counter should reset
    prs_new = [{"url": "u1", "number": 1, "body": "", "headRefOid": "new_sha", "headRefName": "feature"}]
    with patch.dict("sys.modules", {"mutation_check": mock_mc}):
        with patch("auto_merge_shadow._gh", side_effect=mock_gh_raises):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                sh._score_one(prs_new, "G-Eskayo/marvin", state)

    data = json.loads(state.read_text())
    assert data["score_failures"]["u1"]["count"] == 1, "counter should reset to 1 on new sha, then increment"
    assert data["score_failures"]["u1"]["sha"] == "new_sha"


def test_body_edited_flag_prevents_repeated_edits(state):
    """Item 5: once we write the stated reason, body_edited flag should prevent re-editing.
    This test DRIVES _score_one and mocks _gh to count calls, not re-evaluating the condition."""
    import json
    from unittest.mock import patch, MagicMock

    prs = [{"url": "u1", "number": 1, "body": "", "headRefOid": "c1", "headRefName": "feature"}]
    mock_mc = MagicMock()

    def mock_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "remove" in cmd:
            return MagicMock()
        raise RuntimeError("subprocess failed")

    # Fail MAX_CONSECUTIVE_FAILURES times: on the last one, body should be edited (1 call to _gh)
    gh_calls = []
    def mock_gh(args):
        gh_calls.append(args)
        if args[0:2] == ["pr", "edit"]:
            return ""
        raise RuntimeError("gh failed")

    with patch("auto_merge_shadow._gh", side_effect=mock_gh):
        for _ in range(sh.MAX_CONSECUTIVE_FAILURES):
            with patch.dict("sys.modules", {"mutation_check": mock_mc}):
                with patch("subprocess.run", side_effect=mock_subprocess_run):
                    sh._score_one(prs, "G-Eskayo/marvin", state)

    data = json.loads(state.read_text())
    assert data["score_failures"]["u1"]["body_edited"] is True
    # Should have called _gh to edit the body exactly once (on the MAX_CONSECUTIVE_FAILURES-th failure)
    pr_edit_calls = [c for c in gh_calls if c[:2] == ["pr", "edit"]]
    assert len(pr_edit_calls) == 1, f"should call _gh once to edit body, got {len(pr_edit_calls)}"

    # Now fail again: _gh should NOT be called to edit (body_edited=True already)
    gh_calls.clear()
    with patch("auto_merge_shadow._gh", side_effect=mock_gh):
        with patch.dict("sys.modules", {"mutation_check": mock_mc}):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                sh._score_one(prs, "G-Eskayo/marvin", state)

    pr_edit_calls = [c for c in gh_calls if c[:2] == ["pr", "edit"]]
    assert len(pr_edit_calls) == 0, f"should NOT call _gh to edit again (already body_edited), got {len(pr_edit_calls)}"


def test_failure_reset_clears_body_edited_on_new_sha(state):
    """Item 5: when sha changes, body_edited flag is cleared so new sha can get a reason.
    This test DRIVES _score_one with a new sha, not re-implementing the reset logic."""
    import json
    from unittest.mock import patch, MagicMock

    prs_old = [{"url": "u1", "number": 1, "body": "", "headRefOid": "old_sha", "headRefName": "feature"}]
    mock_mc = MagicMock()

    def mock_subprocess_run(cmd, **kwargs):
        if isinstance(cmd, list) and "remove" in cmd:
            return MagicMock()
        raise RuntimeError("subprocess failed")

    # Fail MAX_CONSECUTIVE_FAILURES times with old sha so body_edited=True
    def mock_gh_raises(args):
        if args[0:2] == ["pr", "edit"]:
            return ""
        raise RuntimeError("test failure")

    with patch("auto_merge_shadow._gh", side_effect=mock_gh_raises):
        for _ in range(sh.MAX_CONSECUTIVE_FAILURES):
            with patch.dict("sys.modules", {"mutation_check": mock_mc}):
                with patch("subprocess.run", side_effect=mock_subprocess_run):
                    sh._score_one(prs_old, "G-Eskayo/marvin", state)

    data = json.loads(state.read_text())
    assert data["score_failures"]["u1"]["body_edited"] is True
    assert data["score_failures"]["u1"]["sha"] == "old_sha"

    # Now fail with new sha
    prs_new = [{"url": "u1", "number": 1, "body": "", "headRefOid": "new_sha", "headRefName": "feature"}]
    with patch("auto_merge_shadow._gh", side_effect=mock_gh_raises):
        with patch.dict("sys.modules", {"mutation_check": mock_mc}):
            with patch("subprocess.run", side_effect=mock_subprocess_run):
                sh._score_one(prs_new, "G-Eskayo/marvin", state)

    data = json.loads(state.read_text())
    assert data["score_failures"]["u1"]["body_edited"] is False, "body_edited should reset on new sha"
    assert data["score_failures"]["u1"]["count"] == 1, "count should reset to 1 on new sha, then increment"
    assert data["score_failures"]["u1"]["sha"] == "new_sha"


def test_the_report_uses_current_verdict_not_frozen_verdict_regression_stale_report(state):
    """Stale-report bug (AC #1): a PR with a frozen "ask" verdict but current "auto" should show in would_merge.
    Two PRs: #1 (initially body="", verdicts to "ask") changes to body="Mutation score: 90%" (verdicts to "auto").
    #2 stays "auto". Report should show would_merge=2 and 0 disagreements."""
    sh.observe([pr(1, body=""), pr(2)], FACTS, path=state, now=T0)
    # Later run (before report is ready): #1 gets a score, so its current verdict changes to "auto"
    sh.observe([pr(1, body="Mutation score: 90%"), pr(2)], FACTS, path=state, now=T0 + 1 * DAY)
    r = sh.report(path=state, now=T0 + 4 * DAY)
    assert r["would_merge"] == 2, f"frozen verdict bug: expected 2 would merge, but got {r['would_merge']}"
    assert len(r["disagreements"]) == 0, "no disagreements since both PRs are still open"


def test_disagreements_use_current_verdict_pr_closed_after_score_is_added(state):
    """Design doc item #2: a PR that went "ask: pending" → "auto" (score added) and was then closed must be flagged as a disagreement.
    Scenario: #3 starts with no score (verdict=ask), later gets a score (verdict becomes auto), then is closed.
    The frozen verdict is "ask", but current is "auto", so it's a disagreement."""
    sh.observe([pr(3, body="")], FACTS, path=state, now=T0)
    # Later run: #3 gets a score, so current verdict is now "auto"
    sh.observe([pr(3, body="Mutation score: 90%")], FACTS, path=state, now=T0 + 1 * DAY)
    # Later still: #3 is closed (while its current verdict is "auto")
    sh.record_outcome(pr(3)["url"], "closed", path=state)
    r = sh.report(path=state, now=T0 + 4 * DAY)
    # Disagreement: current verdict is "auto" and it was closed, so it's a disagreement (would have merged it)
    assert len(r["disagreements"]) == 1, f"expected 1 disagreement (PR closed after getting a score), got {len(r['disagreements'])}"
    assert r["disagreements"][0]["number"] == 3
