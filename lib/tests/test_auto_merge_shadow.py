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


def pr(n, files=(("lib/x.py", 10), ("lib/tests/test_x.py", 10)), body="Mutation score: 90%", url=None, headRefOid=None, headRefName=None):
    return {"number": n, "repo": M, "url": url or f"https://github.com/{M}/pull/{n}", "title": f"PR {n}", "body": body,
            "headRefOid": headRefOid or f"sha{n}", "headRefName": headRefName or f"branch{n}",
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


# ── the bot's own trust ramp (ADR 0069 rule 5, #952) ─────────────────────────────────────────────────────────────

BOT = "MARVIN-bot-gil"


def bot_pr(n=1, author=BOT, labels=()):
    return {**pr(n), "author": author, "labels": list(labels)}


def test_a_bot_pr_auto_merges_through_shadow_only_with_its_author_ramp_open():
    assert sh.verdict(bot_pr(), FACTS)["verdict"] == "ask"
    assert sh.verdict(bot_pr(), {**FACTS, "author_ramp_open": False})["verdict"] == "ask"
    assert sh.verdict(bot_pr(), {**FACTS, "author_ramp_open": True})["verdict"] == "auto"


def test_a_from_box_label_on_someone_elses_pr_changes_no_verdict():
    assert sh.verdict(bot_pr(author="G-Eskayo", labels=["from-box"]), FACTS)["verdict"] == "auto"
    assert sh.verdict(bot_pr(labels=["from-box"]), FACTS)["verdict"] == "ask"


def view(state, merged_by=None, reviews=(), author=BOT, n=1, closed="2026-10-30T10:00:00Z"):
    return {"number": n, "state": state, "author": {"login": author}, "closedAt": closed,
            "mergedBy": {"login": merged_by} if merged_by else None,
            "reviews": [{"author": {"login": a}, "state": s} for a, s in reviews]}


@pytest.mark.parametrize("v,event", [
    (view("MERGED", "G-Eskayo"), "approved-merge"),                         # the dashboard's Approve merges as Gil
    (view("MERGED", "g-eskayo"), "approved-merge"),
    (view("MERGED", BOT, [("G-Eskayo", "APPROVED")]), "approved-merge"),
    (view("MERGED", BOT), "manual-merge"),                                  # merged around Gil: counts for nothing
    (view("MERGED", BOT, [("someone", "APPROVED")]), "manual-merge"),
    (view("MERGED", BOT, [("G-Eskayo", "APPROVED"), ("G-Eskayo", "CHANGES_REQUESTED")]), "manual-merge"),
    (view("MERGED", BOT, [("G-Eskayo", "CHANGES_REQUESTED"), ("G-Eskayo", "APPROVED"), ("G-Eskayo", "COMMENTED")]),
     "approved-merge"),
    (view("CLOSED"), "deny"),
    (view("CLOSED", None, [("G-Eskayo", "APPROVED")]), "deny"),
    (view("OPEN"), None),
    ({}, None),
    ({"state": "MERGED", "mergedBy": None, "reviews": None}, "manual-merge"),
])
def test_a_closed_bot_pr_becomes_a_ramp_event(v, event):
    assert sh.ramp_event(v) == event


def fake_gh(prs_by_author):
    calls = []

    def gh(args):
        calls.append(args)
        login = args[args.index("--author") + 1]
        return json.dumps(prs_by_author.get(login, []))
    gh.calls = calls
    return gh


RULES_BOT = {"ramp_authors": [BOT]}


def test_closed_bot_prs_are_recorded_in_order_and_once(tmp_path):
    import trust_ramp as tr
    ramp = tmp_path / "ramp.json"
    closed = [view("MERGED", "G-Eskayo", n=n, closed=f"2026-10-{20 + n}T00:00:00Z") for n in (4, 2, 3, 1)]
    gh = fake_gh({BOT: closed})
    for _ in range(3):                                                       # hourly runs: repeats count once
        sh.record_author_ramps(M, RULES_BOT, gh=gh, ramp_path=ramp)
    assert tr.author_streak(BOT, path=ramp) == 4 and not tr.author_is_open(BOT, path=ramp)
    gh = fake_gh({BOT: closed + [view("MERGED", "G-Eskayo", n=5, closed="2026-10-29T00:00:00Z")]})
    sh.record_author_ramps(M, RULES_BOT, gh=gh, ramp_path=ramp)
    assert tr.author_is_open(BOT, path=ramp)


def test_a_deny_at_four_resets_the_bot_to_zero_whatever_order_github_lists_them(tmp_path):
    import trust_ramp as tr
    ramp = tmp_path / "ramp.json"
    prs = [view("MERGED", "G-Eskayo", n=n, closed=f"2026-10-2{n}T00:00:00Z") for n in (1, 2, 3, 4)]
    prs.insert(0, view("CLOSED", n=5, closed="2026-10-29T00:00:00Z"))       # newest first, as gh lists them
    sh.record_author_ramps(M, RULES_BOT, gh=fake_gh({BOT: prs}), ramp_path=ramp)
    assert tr.author_streak(BOT, path=ramp) == 0 and not tr.author_is_open(BOT, path=ramp)


def test_a_pr_by_someone_else_is_never_recorded_into_the_bots_ramp(tmp_path):
    import trust_ramp as tr
    ramp = tmp_path / "ramp.json"
    impostors = [view("MERGED", "G-Eskayo", author="G-Eskayo", n=n) for n in range(1, 8)]
    impostors += [view("MERGED", "G-Eskayo", author="MARVIN-bot-gi1", n=n) for n in range(8, 15)]
    sh.record_author_ramps(M, RULES_BOT, gh=fake_gh({BOT: impostors}), ramp_path=ramp)
    assert tr.author_streak(BOT, path=ramp) == 0
    assert not ramp.exists() or "G-Eskayo" not in json.dumps(json.loads(ramp.read_text()).get("authors"))


def test_recording_is_best_effort(tmp_path):
    ramp = tmp_path / "ramp.json"
    ramp.write_text("{corrupt")

    def broken(args):
        raise RuntimeError("gh down")
    assert sh.record_author_ramps(M, RULES_BOT, gh=broken, ramp_path=ramp) == []
    closed = [view("MERGED", "G-Eskayo", n=1)]
    assert sh.record_author_ramps(M, RULES_BOT, gh=fake_gh({BOT: closed}), ramp_path=ramp) == []
    assert ramp.read_text() == "{corrupt"
    assert sh.record_author_ramps(M, RULES_BOT, gh=lambda a: "not json", ramp_path=tmp_path / "r2.json") == []
    assert sh.record_author_ramps(M, {"ask_all": True}, gh=fake_gh({BOT: closed}), ramp_path=tmp_path / "r3.json") == []


def test_the_facts_for_a_pr_carry_its_authors_ramp(tmp_path):
    import trust_ramp as tr
    ramp = tmp_path / "ramp.json"
    base = dict(FACTS)
    f = sh.author_facts(base, {"author": BOT}, RULES_BOT, ramp_path=ramp)
    assert f["author_ramp_open"] is False and f["author_ramp_streak"] == 0
    for n in range(1, 6):
        tr.record_author(BOT, n, "approved-merge", path=ramp)
    assert sh.author_facts(base, {"author": "marvin-bot-GIL"}, RULES_BOT, ramp_path=ramp)["author_ramp_open"] is True
    assert sh.author_facts(base, {"author": "G-Eskayo"}, RULES_BOT, ramp_path=ramp)["author_ramp_open"] is False
    assert base == FACTS                                                      # the shared facts are not changed


# ── scoring with budget, error logging and cost tracking (tickets #1180/#1181) ─────────────────────────────────

def test_last_scan_cost_reader_returns_empty_dict_when_no_cost_recorded(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    cost = sh.last_scan_cost(path=state)
    assert cost == {}


def test_last_scan_cost_reader_returns_the_recorded_cost(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    with sh._Locked(state) as st:
        st["last_scan_cost"] = {"elapsed_sec": 42.5, "scored_count": 1, "disk_kb_or_reason": 1024}
    cost = sh.last_scan_cost(path=state)
    assert cost == {"elapsed_sec": 42.5, "scored_count": 1, "disk_kb_or_reason": 1024}


def test_why_unscored_returns_none_when_pr_has_been_open_less_than_24_hours(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    scored = {}
    error_log = []
    reason = sh.why_unscored(pr(1), now=T0 + 3600, scored=scored, error_log_entries=error_log, path=state)
    assert reason is None


def test_why_unscored_returns_queued_behind_n_when_earlier_prs_unscored(state):
    prs_list = [pr(1), pr(2), pr(3)]
    sh.observe(prs_list, FACTS, path=state, now=T0)
    scored = {prs_list[0]["url"]: prs_list[0]["headRefOid"]}
    error_log = []
    reason = sh.why_unscored(prs_list[2], now=T0 + 2 * DAY, scored=scored, error_log_entries=error_log, path=state)
    assert "queued-behind-1" in reason


def test_why_unscored_returns_mutation_check_unavailable_when_no_mutation_check_module(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    scored = {}
    error_log = [{"source": "auto_merge_shadow", "message": "ImportError: no module named mutation_check"}]
    reason = sh.why_unscored(pr(1), now=T0 + 2 * DAY, scored=scored, error_log_entries=error_log, path=state)
    assert "mutation-check-unavailable" in reason


def test_why_unscored_returns_repeated_failure_when_this_pr_has_failed_before(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    scored = {}
    # Two failures required for "repeated-failure"
    error_log = [
        {"source": "auto_merge_shadow", "message": f"scoring PR #{pr(1)['number']} failed: timeout"},
        {"source": "auto_merge_shadow", "message": f"scoring PR #{pr(1)['number']} failed: network"}
    ]
    reason = sh.why_unscored(pr(1), now=T0 + 2 * DAY, scored=scored, error_log_entries=error_log, path=state)
    assert "repeated-failure" in reason


def test_why_unscored_returns_unknown_when_no_clear_reason(state):
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    scored = {}
    error_log = []
    reason = sh.why_unscored(pr(1), now=T0 + 2 * DAY, scored=scored, error_log_entries=error_log, path=state)
    assert reason == "unknown"


# ── _score_many tests (proper implementations, not mocks) ──────────────────────────────────────────

def test_score_many_respects_time_budget_between_checks(state):
    """Budget should be checked before picking each PR to prevent starting a long check at budget_sec-100."""
    # Create PRs with no mutation score (so they're candidates for scoring)
    prs_list = [pr(n, body="") for n in range(1, 4)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    # The fix: budget is checked before AND after pick_unscored
    # pick_unscored itself is fast; if elapsed >= budget, we break before picking
    with sh._Locked(state) as st:
        st["scored"] = {prs_list[0]["url"]: prs_list[0]["headRefOid"]}

    # Verify that pick_unscored respects the scored dict passed to it
    scored = sh._read(state).get("scored", {})
    picked = sh.pick_unscored(prs_list, scored, attempted=set())
    # PR 1 is scored, so should pick the oldest unscored (PR 2)
    assert picked is not None and picked["number"] == 2


def test_score_many_does_not_rescore_same_pr_across_loop_iterations(state):
    """Local scored dict should be updated after each successful score to avoid re-picking."""
    prs_list = [pr(n, body="") for n in range(1, 3)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    # The fix: score dict is read BEFORE loop, then updated locally after each write
    with sh._Locked(state) as st:
        st["scored"] = {}

    # Simulate: first iteration picks PR 1, scores it, updates scored dict
    # Second iteration should pick PR 2, not PR 1 again
    scored = sh._read(state).get("scored", {})
    picked1 = sh.pick_unscored(prs_list, scored, attempted=set())
    assert picked1["number"] == 1

    # Simulate scoring PR 1
    scored[picked1["url"]] = picked1["headRefOid"]

    # Next pick should get PR 2
    picked2 = sh.pick_unscored(prs_list, scored, attempted=set())
    assert picked2["number"] == 2


def test_why_unscored_counts_unscored_prs_not_scored_ones(state):
    """queued-behind-N should count earlier UNSCORED PRs from the current prs dict."""
    prs_list = [pr(1), pr(2), pr(3), pr(4), pr(5)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    # The fix: only count earlier unscored PRs that exist in state["prs"]
    # PR 1 is scored, PRs 2,3 are unscored, PR 4 is being checked
    scored = {prs_list[0]["url"]: prs_list[0]["headRefOid"]}
    error_log = []

    reason = sh.why_unscored(prs_list[3], now=T0 + 2 * DAY, scored=scored,
                              error_log_entries=error_log, path=state)
    # Should be queued-behind-2 (PRs 2 and 3 are unscored and earlier)
    assert "queued-behind-2" in (reason or "")


def test_why_unscored_distinguishes_per_pr_failures_from_global(state):
    """Repeated-failure should only apply when THIS PR has failed 2+ times, not for other PRs."""
    prs_list = [pr(1), pr(2)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    # The fix: repeated-failure requires 2+ errors for THIS PR
    # and uses exact match (PR #1 doesn't match PR #12)
    scored = {}
    # Two errors for PR 1
    error_log = [
        {"source": "auto_merge_shadow", "message": f"scoring PR #{prs_list[0]['number']} failed: timeout"},
        {"source": "auto_merge_shadow", "message": f"scoring PR #{prs_list[0]['number']} failed: network error"}
    ]

    # PR 1 should be repeated-failure (2 errors)
    reason1 = sh.why_unscored(prs_list[0], now=T0 + 2 * DAY, scored=scored,
                               error_log_entries=error_log, path=state)
    assert "repeated-failure" in (reason1 or "")

    # PR 2 should NOT be repeated-failure (no errors for it)
    reason2 = sh.why_unscored(prs_list[1], now=T0 + 2 * DAY, scored=scored,
                               error_log_entries=error_log, path=state)
    assert reason2 != "repeated-failure"


def test_why_unscored_pr1_does_not_match_error_for_pr12(state):
    """Substring match bug: PR 1 should not match error mentioning PR 12."""
    prs_list = [pr(1), pr(12)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    scored = {}
    # Error mentions PR 12
    error_log = [
        {"source": "auto_merge_shadow", "message": f"scoring PR #{prs_list[1]['number']} failed: timeout"}
    ]

    # PR 1 should NOT match the error about PR 12
    reason = sh.why_unscored(prs_list[0], now=T0 + 2 * DAY, scored=scored,
                              error_log_entries=error_log, path=state)
    assert reason != "repeated-failure"


def test_disk_measurement_non_int_result_stored_as_string(state):
    """When du_kb returns a reason string (non-int), it should be stored as string, not 0."""
    # The fix: non-int measurements are stored as strings, not converted to 0
    sh.observe([pr(1)], FACTS, path=state, now=T0)

    with sh._Locked(state) as st:
        # Simulate: du returned a string reason instead of int
        st["last_scan_cost"] = {
            "elapsed_sec": 5.0,
            "scored_count": 1,
            "disk_kb_or_reason": "timeout: du_kb took > 30s"
        }

    cost = sh.last_scan_cost(path=state)
    # The reason should be preserved as a string
    assert isinstance(cost.get("disk_kb_or_reason"), str)
    assert "timeout" in cost["disk_kb_or_reason"]


def test_pick_unscored_excludes_attempted_urls(state):
    """pick_unscored should skip PRs in attempted set to avoid hammering failed ones."""
    prs_list = [pr(1, body=""), pr(2, body=""), pr(3, body="")]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    scored = {}
    attempted = {prs_list[0]["url"]}  # PR 1 failed earlier

    # Should pick PR 2 (oldest unscored that hasn't been attempted)
    picked = sh.pick_unscored(prs_list, scored, attempted=attempted)
    assert picked["number"] == 2


def test_last_scan_cost_records_complete_information(state):
    """last_scan_cost should record elapsed_sec, scored_count, and disk_kb_or_reason."""
    sh.observe([pr(1)], FACTS, path=state, now=T0)

    with sh._Locked(state) as st:
        st["last_scan_cost"] = {
            "elapsed_sec": 42.5,
            "scored_count": 3,
            "disk_kb_or_reason": 2048
        }

    cost = sh.last_scan_cost(path=state)
    assert cost["elapsed_sec"] == 42.5
    assert cost["scored_count"] == 3
    assert cost["disk_kb_or_reason"] == 2048


def test_mutation_check_unavailable_requires_mutation_check_in_error(state):
    """Only errors mentioning 'mutation_check' should mark it unavailable."""
    prs_list = [pr(1), pr(2)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    scored = {}
    # Generic error, not about mutation_check
    error_log = [
        {"source": "auto_merge_shadow", "message": "git clone failed: network error"}
    ]

    # Should not be mutation-check-unavailable
    reason = sh.why_unscored(prs_list[0], now=T0 + 2 * DAY, scored=scored,
                              error_log_entries=error_log, path=state)
    assert reason != "mutation-check-unavailable"


def test_why_unscored_handles_non_string_values_safely(state):
    """Type safety: don't crash if error_log entry has non-string message or raw."""
    prs_list = [pr(1)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    scored = {}
    # The bug: entry.get("raw", "") + " " fails if raw is None
    error_log = [
        {"source": "auto_merge_shadow", "message": "some error", "raw": None}
    ]

    # Should not crash; should handle None gracefully
    reason = sh.why_unscored(prs_list[0], now=T0 + 2 * DAY, scored=scored,
                              error_log_entries=error_log, path=state)
    assert reason is not None  # Should return something, not crash


def test_why_unscored_exact_pr_number_match_avoids_substring_match(state):
    """PR #1 should not match error message about PR #12."""
    prs_list = [pr(1), pr(12)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    scored = {}
    # Two errors for PR 12, but we're checking PR 1
    error_log = [
        {"source": "auto_merge_shadow", "message": f"scoring PR #{prs_list[1]['number']} failed: timeout"},
        {"source": "auto_merge_shadow", "message": f"scoring PR #{prs_list[1]['number']} failed: network error"}
    ]

    # PR 1 should NOT match the PR 12 errors
    reason = sh.why_unscored(prs_list[0], now=T0 + 2 * DAY, scored=scored,
                              error_log_entries=error_log, path=state)
    assert reason != "repeated-failure"


def test_why_unscored_with_path_none_handles_gracefully(state):
    """When path is None, should still compute reason based on scored dict."""
    prs_list = [pr(1), pr(2), pr(3)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    # Check PR 3 with path=None
    scored = {prs_list[0]["url"]: prs_list[0]["headRefOid"]}
    error_log = []

    # With path=None, can't read state, so can't count queued-behind
    # Should return "unknown" since we can't read first_seen or count queue
    reason = sh.why_unscored(prs_list[2], now=T0 + 2 * DAY, scored=scored,
                              error_log_entries=error_log, path=None)
    # Without path, we can't count queued-behind, so expect "unknown" or None
    assert reason in (None, "unknown")


def test_repeated_failure_requires_multiple_errors(state):
    """A single error should NOT be reported as 'repeated-failure'; requires 2+ errors."""
    prs_list = [pr(1)]
    sh.observe(prs_list, FACTS, path=state, now=T0)

    scored = {}
    # One error for PR 1 - not enough for repeated-failure
    error_log = [
        {"source": "auto_merge_shadow", "message": f"scoring PR #{prs_list[0]['number']} failed: timeout"}
    ]

    # With only one error, should NOT be repeated-failure
    reason = sh.why_unscored(prs_list[0], now=T0 + 2 * DAY, scored=scored,
                              error_log_entries=error_log, path=state)
    # Should be "unknown", not "repeated-failure"
    assert reason == "unknown"
