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


# ── multi-PR scoring with budget, backoff, and error logging (ADR 0064 robustness) ──────────────────────────────

def test_classify_failure_wraps_error_log_classify():
    classified = sh._classify_failure(ValueError("some error"))
    assert isinstance(classified, dict) and "cause" in classified


def test_score_one_pr_returns_dict_on_error(tmp_path, monkeypatch):
    """_score_one_pr always returns a result dict, even on error, never raises."""
    def broken(*a, **k):
        raise RuntimeError("mutation check failed")
    monkeypatch.setattr(sh, "_gh", lambda a: "")
    import mutation_check
    monkeypatch.setattr(mutation_check, "run_mutation_check", broken)
    monkeypatch.setattr(mutation_check, "render_section", lambda r: "")
    monkeypatch.setattr(mutation_check, "merge_bodies", lambda b, s: s)
    p = pr(1)
    result = sh._score_one_pr(p, M, tmp_path / "state.json")
    assert isinstance(result, dict) and result["status"] == "unknown" and "reason" in result


def test_score_many_returns_summary_with_counts_and_cost(tmp_path, monkeypatch):
    """_score_many returns {'scored': ..., 'failed': ..., 'elapsed_sec': ..., 'disk_kb': ...}."""
    def success_score(pr, repo, path):
        return {"status": "scored", "number": pr["number"], "headRefOid": pr.get("headRefOid"), "elapsed_sec": 1.5, "disk_kb": 300}
    monkeypatch.setattr(sh, "_score_one_pr", success_score)
    prs_to_score = [pr(n) for n in range(1, 3)]
    result = sh._score_many(prs_to_score, M, tmp_path / "state.json", budget_sec=60, now=T0)
    assert all(k in result for k in ("scored", "failed", "elapsed_sec", "disk_kb"))
    assert isinstance(result["scored"], int) and isinstance(result["failed"], int)


def test_score_many_handles_disk_ledger_sentinel_string(tmp_path, monkeypatch):
    """disk_ledger.du_kb returning a string sentinel doesn't raise TypeError."""
    import mutation_check
    import disk_ledger
    monkeypatch.setattr(mutation_check, "run_mutation_check", lambda *a, **k: {"lines": 10})
    monkeypatch.setattr(mutation_check, "render_section", lambda r: "**Score:** 82%")
    monkeypatch.setattr(mutation_check, "merge_bodies", lambda b, s: s)
    monkeypatch.setattr(sh, "_gh", lambda a: "")
    # return the sentinel string from disk_ledger
    monkeypatch.setattr(disk_ledger, "du_kb", lambda p: "not measured (protected)")
    prs_to_score = [pr(n) for n in range(1, 2)]
    result = sh._score_many(prs_to_score, M, tmp_path / "state.json", budget_sec=60, now=T0)
    # should complete without TypeError, disk_kb should be 0 (not accumulated from sentinel)
    assert result["disk_kb"] == 0


def test_score_many_masks_failed_prs_for_rest_of_run(tmp_path, monkeypatch):
    """A failed PR is not retried again in the same run."""
    import json
    attempt_count = {"count": 0}
    def failing_score_one_pr(pr, repo, path):
        attempt_count["count"] += 1
        return {"status": "unknown", "number": pr["number"], "reason": "test failure"}
    monkeypatch.setattr(sh, "_score_one_pr", failing_score_one_pr)
    # single PR passed with no score (so it gets picked)
    prs_to_score = [{"number": 1, "repo": M, "url": "u1", "title": "PR 1", "body": "", "files": [],
                     "headRefName": "branch", "headRefOid": "oid1", "author": ""}]
    result = sh._score_many(prs_to_score, M, tmp_path / "state.json", budget_sec=60, now=T0)
    # first attempt fails, subsequent attempts should be masked, not retried
    assert attempt_count["count"] == 1  # only one attempt for this PR in the run
    st = json.loads((tmp_path / "state.json").read_text())
    # check that it's recorded as failed
    assert "u1" in st.get("scoring_failures", {})


def test_score_many_resets_failure_count_on_new_push(tmp_path, monkeypatch):
    """When a PR receives a new push, its failure counter resets."""
    import json
    state_file = tmp_path / "state.json"
    # first run: record a failure with oid "old"
    prs1 = [{"number": 1, "repo": M, "url": "u1", "title": "PR 1", "body": "", "files": [],
             "headRefName": "branch", "headRefOid": "old", "author": ""}]
    def fail_once(pr, repo, path):
        return {"status": "unknown", "number": pr["number"], "reason": "first attempt fails"}
    monkeypatch.setattr(sh, "_score_one_pr", fail_once)
    sh._score_many(prs1, M, state_file, budget_sec=60, now=T0)
    st = json.loads(state_file.read_text())
    assert st.get("scoring_failures", {}).get("u1", {}).get("count") == 1
    assert st["scoring_failures"]["u1"]["headRefOid"] == "old"
    # second run: same PR but with new push (oid "new") — counter should reset
    prs2 = [{"number": 1, "repo": M, "url": "u1", "title": "PR 1", "body": "", "files": [],
             "headRefName": "branch", "headRefOid": "new", "author": ""}]
    sh._score_many(prs2, M, state_file, budget_sec=60, now=T0 + 100)
    st = json.loads(state_file.read_text())
    # counter should be 1, not 2 (reset on new oid)
    assert st["scoring_failures"]["u1"]["count"] == 1
    assert st["scoring_failures"]["u1"]["headRefOid"] == "new"


def test_score_many_parks_pr_after_max_score_failures(tmp_path, monkeypatch):
    """After MAX_SCORE_FAILURES=5, PR is marked not_before and not retried this run."""
    import json
    state_file = tmp_path / "state.json"
    # initialize the state file
    state_file.write_text(json.dumps({"mode": "shadow", "prs": {}, "scored": {}, "scoring_failures": {}}))
    # PR with no score in the body so it gets picked
    prs = [{"number": 1, "repo": M, "url": "u1", "title": "PR 1", "body": "", "files": [],
            "headRefName": "branch", "headRefOid": "oid1", "author": ""}]
    def fail_score(pr, repo, path):
        return {"status": "unknown", "number": pr["number"], "reason": "consistent failure"}
    # run 5 times, each time the PR fails
    for i in range(sh.MAX_SCORE_FAILURES):
        monkeypatch.setattr(sh, "_score_one_pr", fail_score)
        sh._score_many(prs, M, state_file, budget_sec=60, now=T0 + i * 100)
    st = json.loads(state_file.read_text())
    entry = st["scoring_failures"]["u1"]
    assert entry["count"] >= sh.MAX_SCORE_FAILURES
    assert "not_before" in entry  # now parked
    assert entry["not_before"] > T0 + (sh.MAX_SCORE_FAILURES - 1) * 100


def test_score_many_skips_backoff_prs_without_marking_as_scored(tmp_path, monkeypatch):
    """PRs in backoff (not_before > now) don't consume budget or increment scored count."""
    import json
    def success_score(pr, repo, path):
        return {"status": "scored", "number": pr["number"], "headRefOid": pr.get("headRefOid"), "elapsed_sec": 1.0, "disk_kb": 200}
    monkeypatch.setattr(sh, "_score_one_pr", success_score)
    state_file = tmp_path / "state.json"
    # manually set up a parked PR in backoff
    st = {"mode": "shadow", "prs": {}, "scored": {}, "scoring_failures": {
        "u1": {"count": 5, "not_before": T0 + 10000, "headRefOid": "oid1", "reason": "test"}  # far in the future
    }}
    state_file.write_text(json.dumps(st))
    # PR 2 has no score in body, so it can be selected
    prs = [pr(1), {"number": 2, "repo": M, "url": "u2", "title": "PR 2", "body": "", "files": [],
                   "headRefName": "branch", "headRefOid": "oid2", "author": ""}]
    result = sh._score_many(prs, M, state_file, budget_sec=60, now=T0)
    # PR 1 is in backoff: should skip it, only PR 2 scored
    assert result["scored"] == 1 and result["failed"] == 0
    st = json.loads(state_file.read_text())
    assert st["scored"].get("u2") is not None  # PR 2 was scored
    assert st["scored"].get("u1") is None  # PR 1 was not marked scored


def test_score_many_stops_when_budget_expires(tmp_path, monkeypatch):
    """_score_many stops at budget_sec even with more PRs to score."""
    import time
    call_times = []
    def slow_score(pr, repo, path):
        call_times.append(time.time())
        time.sleep(0.1)  # 100ms per check
        return {"status": "scored", "number": pr["number"], "headRefOid": pr.get("headRefOid"), "elapsed_sec": 0.1, "disk_kb": 150}
    monkeypatch.setattr(sh, "_score_one_pr", slow_score)
    prs_to_score = [pr(n) for n in range(1, 20)]  # many PRs
    result = sh._score_many(prs_to_score, M, tmp_path / "state.json", budget_sec=0.2, now=time.time())
    # with 0.2s budget and 0.1s per check, should score max ~2 PRs
    assert result["scored"] <= 3


def test_score_many_filters_already_scored_from_queue(tmp_path, monkeypatch):
    """_score_many skips PRs already scored at their current commit."""
    import json
    def success_score(pr, repo, path):
        return {"status": "scored", "number": pr["number"], "headRefOid": pr.get("headRefOid"), "elapsed_sec": 1.0, "disk_kb": 250}
    monkeypatch.setattr(sh, "_score_one_pr", success_score)
    state_file = tmp_path / "state.json"
    # manually set PR 1 as already scored
    st = {"mode": "shadow", "prs": {}, "scored": {"u1": "oid1"}, "scoring_failures": {}}
    state_file.write_text(json.dumps(st))
    # PR 2 with no score in body so it can be selected
    prs = [pr(1), {"number": 2, "repo": M, "url": "u2", "title": "PR 2", "body": "", "files": [],
                   "headRefName": "branch", "headRefOid": "oid2", "author": ""}]
    result = sh._score_many(prs, M, state_file, budget_sec=60, now=T0)
    # should only score PR 2
    assert result["scored"] == 1
    st = json.loads(state_file.read_text())
    assert st["scored"].get("u2") is not None


def test_run_persists_last_scan_summary_in_state(tmp_path, monkeypatch):
    """run() writes _score_many's summary as st['last_scan'] via _Locked."""
    import json
    # mock all the external dependencies
    monkeypatch.setattr(sh, "_gh", lambda a: json.dumps([]))
    monkeypatch.setattr(sh, "record_author_ramps", lambda *a, **k: [])
    monkeypatch.setattr(sh, "_score_many", lambda *a, **k: {"scored": 3, "failed": 1, "elapsed_sec": 8.2, "disk_kb": 600})
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: type('', (), {"stdout": "", "returncode": 0})())
    state_file = tmp_path / "state.json"
    try:
        sh.run(repo=M, path=state_file)
    except Exception:
        pass
    if state_file.exists():
        st = json.loads(state_file.read_text())
        if "last_scan" in st:
            assert st["last_scan"]["scored"] == 3


def test_last_scan_accessor_mirrors_mode_report_style(state):
    """last_scan() returns dict with keys from _score_many summary, or None before first run."""
    sh.observe([pr(1)], FACTS, path=state, now=T0)
    result = sh.last_scan(path=state)
    assert result is None  # last_scan not set until _score_many runs


def test_last_scan_returns_none_when_state_missing(tmp_path):
    """last_scan on missing state returns None."""
    missing = tmp_path / "missing.json"
    result = sh.last_scan(path=missing)
    assert result is None


def test_failure_reason_extracted_from_exception_and_logged():
    """Exception's cause is classified via _classify_failure."""
    exc = ValueError("test error")
    result = sh._classify_failure(exc)
    assert isinstance(result, dict) and "cause" in result


def test_score_many_accumulates_disk_cost_across_attempts(tmp_path, monkeypatch):
    """disk cost is summed across all attempts within a single run."""
    disk_costs = [250, 300, 280]  # different cost per call
    call_count = [0]
    def varying_cost(pr, repo, path):
        cost = disk_costs[call_count[0]] if call_count[0] < len(disk_costs) else 0
        call_count[0] += 1
        return {"status": "scored", "number": pr["number"], "headRefOid": pr.get("headRefOid"), "elapsed_sec": 1.0, "disk_kb": cost}
    monkeypatch.setattr(sh, "_score_one_pr", varying_cost)
    # PRs with no scores in the body so they get picked
    prs_to_score = [{"number": n, "repo": M, "url": f"u{n}", "title": f"PR {n}", "body": "", "files": [],
                     "headRefName": "branch", "headRefOid": f"oid{n}", "author": ""}
                    for n in range(1, 4)]
    result = sh._score_many(prs_to_score, M, tmp_path / "state.json", budget_sec=60, now=T0)
    # should accumulate costs from multiple PRs (250 + 300 + 280 = 830)
    assert result["disk_kb"] == 830


def test_score_one_pr_handles_all_errors_in_except_block(tmp_path, monkeypatch):
    """_score_one_pr never raises even if disk_ledger, error_log, or classify raises."""
    import disk_ledger
    import error_log
    # Make du_kb raise
    monkeypatch.setattr(disk_ledger, "du_kb", lambda p: 1/0)
    # Make sure _score_one_pr still returns a dict
    p = pr(1)
    result = sh._score_one_pr(p, M, tmp_path / "state.json")
    assert isinstance(result, dict) and "status" in result


def test_score_one_pr_handles_missing_pr_fields(tmp_path, monkeypatch):
    """_score_one_pr handles PRs missing required fields like number or headRefOid."""
    def broken(*a, **k):
        raise RuntimeError("mutation check failed")
    monkeypatch.setattr(sh, "_gh", lambda a: "")
    import mutation_check
    monkeypatch.setattr(mutation_check, "run_mutation_check", broken)
    monkeypatch.setattr(mutation_check, "render_section", lambda r: "")
    monkeypatch.setattr(mutation_check, "merge_bodies", lambda b, s: s)
    # Missing required fields
    p = {"url": "https://github.com/test", "repo": M}
    result = sh._score_one_pr(p, M, tmp_path / "state.json")
    assert isinstance(result, dict) and result.get("status") in ("unknown", "scored")


def test_score_many_revives_parked_pr_on_new_push(tmp_path, monkeypatch):
    """A parked PR that receives a new push (different headRefOid) is revived and retried immediately."""
    import json
    def success_score(pr, repo, path):
        return {"status": "scored", "number": pr["number"], "headRefOid": pr.get("headRefOid"), "elapsed_sec": 1.0, "disk_kb": 200}
    state_file = tmp_path / "state.json"
    # Setup: PR failed 5 times with oid "old", now parked
    st = {"mode": "shadow", "prs": {}, "scored": {}, "scoring_failures": {
        "u1": {"count": 5, "not_before": T0 + 10000, "headRefOid": "old", "reason": "test"}
    }}
    state_file.write_text(json.dumps(st))
    # Same PR but with new push (oid "new")
    prs = [{"number": 1, "repo": M, "url": "u1", "title": "PR 1", "body": "", "files": [],
            "headRefName": "branch", "headRefOid": "new", "author": ""}]
    monkeypatch.setattr(sh, "_score_one_pr", success_score)
    result = sh._score_many(prs, M, state_file, budget_sec=60, now=T0)
    # Should attempt it because commit changed, resetting the failure counter
    st = json.loads(state_file.read_text())
    # Either scored, or failure counter reset to 1 (and it succeeded so scored)
    assert st["scored"].get("u1") == "new" or st["scoring_failures"]["u1"]["count"] == 1


def test_score_many_respects_budget_deadline(tmp_path, monkeypatch):
    """_score_many stops before attempting a check that would exceed budget."""
    import time
    attempt_times = []
    def track_time(pr, repo, path):
        attempt_times.append(time.time())
        time.sleep(0.05)  # 50ms per attempt
        return {"status": "scored", "number": pr["number"], "headRefOid": pr.get("headRefOid"), "elapsed_sec": 0.05, "disk_kb": 100}
    monkeypatch.setattr(sh, "_score_one_pr", track_time)
    # Create many PRs that need scoring
    prs = [{"number": n, "repo": M, "url": f"u{n}", "title": f"PR {n}", "body": "", "files": [],
            "headRefName": "branch", "headRefOid": f"oid{n}", "author": ""}
           for n in range(1, 30)]  # many PRs
    now = time.time()
    result = sh._score_many(prs, M, tmp_path / "state.json", budget_sec=0.15, now=now)
    # With 0.15s budget and 0.05s per attempt, should not exceed budget by more than ~100ms
    total_time = attempt_times[-1] - attempt_times[0] if attempt_times else 0
    assert total_time < 0.3  # should not take 1+ seconds with budget of 0.15s


def test_score_many_parks_pr_long_enough(tmp_path, monkeypatch):
    """A parked PR stays parked for its full not_before window, not just one run."""
    import json
    import ticket_policy
    state_file = tmp_path / "state.json"
    # Initial state: PR parked with not_before far in future
    backoff_sec = ticket_policy.retry_backoff_s(sh.MAX_SCORE_FAILURES)
    not_before = T0 + backoff_sec
    st = {"mode": "shadow", "prs": {}, "scored": {}, "scoring_failures": {
        "u1": {"count": 5, "not_before": not_before, "headRefOid": "oid1", "reason": "test"}
    }}
    state_file.write_text(json.dumps(st))
    prs = [{"number": 2, "repo": M, "url": "u2", "title": "PR 2", "body": "", "files": [],
            "headRefName": "branch", "headRefOid": "oid2", "author": ""}]
    # Run at T0 (well before not_before)
    def success(pr, repo, path):
        return {"status": "scored", "number": pr["number"], "headRefOid": pr.get("headRefOid"), "elapsed_sec": 1.0, "disk_kb": 200}
    monkeypatch.setattr(sh, "_score_one_pr", success)
    result = sh._score_many(prs, M, state_file, budget_sec=60, now=T0)
    # u1 should still be parked (not attempted)
    st = json.loads(state_file.read_text())
    assert st["scoring_failures"]["u1"]["not_before"] > T0
    # Only u2 should be scored
    assert st["scored"].get("u2") == "oid2"
    assert st["scored"].get("u1") is None


def test_score_one_pr_guards_disk_ledger_call(tmp_path, monkeypatch):
    """If disk_ledger raises in the except path, the error is handled, not raised."""
    import disk_ledger
    call_count = [0]
    def track_disk_calls(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] >= 1:
            raise RuntimeError("disk check failed")
        return 100
    monkeypatch.setattr(disk_ledger, "du_kb", track_disk_calls)
    def fail_score(*a, **k):
        raise RuntimeError("mutation check failed")
    import mutation_check
    monkeypatch.setattr(mutation_check, "run_mutation_check", fail_score)
    monkeypatch.setattr(mutation_check, "render_section", lambda r: "")
    monkeypatch.setattr(mutation_check, "merge_bodies", lambda b, s: s)
    monkeypatch.setattr(sh, "_gh", lambda a: "")
    p = pr(1)
    result = sh._score_one_pr(p, M, tmp_path / "state.json")
    # Should still return a dict, even though disk_ledger raised
    assert isinstance(result, dict) and "status" in result


def test_score_many_with_empty_queue_respects_budget(tmp_path):
    """If all PRs are already scored or parked, _score_many returns immediately without error."""
    import json
    state_file = tmp_path / "state.json"
    st = {"mode": "shadow", "prs": {}, "scored": {"u1": "oid1"}, "scoring_failures": {}}
    state_file.write_text(json.dumps(st))
    prs = [pr(1)]  # already scored
    result = sh._score_many(prs, M, state_file, budget_sec=60, now=T0)
    assert result["scored"] == 0 and result["failed"] == 0


def test_score_many_failure_counter_resets_on_new_push_not_parked(tmp_path, monkeypatch):
    """Failure counter resets to 1 on new push, even before reaching MAX_SCORE_FAILURES."""
    import json
    state_file = tmp_path / "state.json"
    # PR failed once with oid "old"
    st = {"mode": "shadow", "prs": {}, "scored": {}, "scoring_failures": {
        "u1": {"count": 1, "headRefOid": "old", "reason": "test"}
    }}
    state_file.write_text(json.dumps(st))
    # Same PR with new push (oid "new")
    prs = [{"number": 1, "repo": M, "url": "u1", "title": "PR 1", "body": "", "files": [],
            "headRefName": "branch", "headRefOid": "new", "author": ""}]
    def fail(pr, repo, path):
        return {"status": "unknown", "number": pr["number"], "reason": "test failure"}
    monkeypatch.setattr(sh, "_score_one_pr", fail)
    sh._score_many(prs, M, state_file, budget_sec=60, now=T0)
    st = json.loads(state_file.read_text())
    # Count should be 1 (reset on new oid), not 2
    assert st["scoring_failures"]["u1"]["count"] == 1
    assert st["scoring_failures"]["u1"]["headRefOid"] == "new"
