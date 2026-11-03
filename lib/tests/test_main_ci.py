"""main_ci.py: GitHub CI's verdict on main's head commit, the only judge of whether main is green (marvin#1094).

Real check-run shapes (GitHub REST `commits/{sha}/check-runs`), fake gh at the boundary.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_ci  # noqa: E402

HEAD = "83fd1b46aaaabbbbccccddddeeeeffff00001111"
OLD = "4af4de63aaaabbbbccccddddeeeeffff00002222"
LANDED = datetime(2026, 11, 3, 19, 46, tzinfo=timezone.utc)
REQUIRED = ["Rules", "Python tests", "Dashboard unit tests", "Secret and transcript scan"]


def run(name, status="completed", conclusion="success", sha=HEAD, started="2026-11-03T19:46:30Z"):
    return {"name": name, "status": status, "conclusion": conclusion if status == "completed" else None,
            "head_sha": sha, "started_at": started}


def all_green(sha=HEAD):
    return [run(n, sha=sha) for n in REQUIRED] + [run("Main health ticket", sha=sha)]


def judge(runs, minutes=10, sha=HEAD):
    return main_ci.verdict(sha, LANDED, runs, now=LANDED + timedelta(minutes=minutes), required=REQUIRED)


def test_every_required_check_passed_on_the_head_is_green():
    v = judge(all_green())
    assert v["state"] == "green" and v["sha"] == HEAD and v["failing"] == []


def test_one_failed_required_check_on_the_head_is_red_and_named():
    runs = all_green()
    runs[1] = run("Python tests", conclusion="failure")
    v = judge(runs)
    assert v["state"] == "red" and v["failing"] == ["Python tests"]


def test_a_timed_out_check_is_red_too():
    runs = all_green()
    runs[0] = run("Rules", conclusion="timed_out")
    assert judge(runs)["state"] == "red"


def test_a_check_still_running_on_the_head_is_pending_with_its_name():
    runs = all_green()
    runs[1] = run("Python tests", status="in_progress")
    v = judge(runs)
    assert v["state"] == "pending" and v["pending"] == ["Python tests"]
    assert "CI is still checking main" in v["reason"]


def test_a_red_check_wins_over_one_still_running():
    runs = all_green()
    runs[0] = run("Rules", conclusion="failure")
    runs[1] = run("Python tests", status="queued")
    assert judge(runs)["state"] == "red"


def test_nothing_reported_yet_is_pending_not_green():
    v = judge([])
    assert v["state"] == "pending" and set(v["pending"]) == set(REQUIRED)


def test_a_required_check_missing_from_the_runs_is_pending_not_green():
    assert judge([r for r in all_green() if r["name"] != "Python tests"])["state"] == "pending"


def test_a_stale_result_for_an_older_commit_does_not_count():
    # GitHub only answers for the sha asked, but a cached or mis-routed answer must still never judge the head.
    assert judge(all_green(sha=OLD))["state"] == "pending"
    runs = all_green(sha=OLD)
    runs[1] = run("Python tests", conclusion="failure", sha=OLD)
    assert judge(runs)["state"] == "pending"


def test_silent_past_the_deadline_is_late_and_says_the_fallback():
    v = judge([], minutes=main_ci.DEADLINE_MIN + 1)
    assert v["state"] == "late" and "on this Mac once" in v["reason"]
    runs = all_green()
    runs[1] = run("Python tests", status="in_progress")
    assert judge(runs, minutes=main_ci.DEADLINE_MIN + 1)["state"] == "late"


def test_a_cancelled_run_says_nothing_about_main():
    runs = all_green()
    runs[1] = run("Python tests", conclusion="cancelled")
    assert judge(runs)["state"] == "pending"
    assert judge(runs, minutes=main_ci.DEADLINE_MIN + 1)["state"] == "late"


def test_a_rerun_beside_the_old_run_the_newer_wins():
    runs = all_green()
    runs.append(run("Python tests", conclusion="failure", started="2026-11-03T19:40:00Z"))  # the older attempt
    assert judge(runs)["state"] == "green"
    runs.append(run("Python tests", status="in_progress", started="2026-11-03T20:10:00Z"))  # a re-run started
    assert judge(runs)["state"] == "pending"


def test_skipped_and_neutral_count_as_passed():
    runs = all_green()
    runs[2] = run("Dashboard unit tests", conclusion="skipped")
    runs[3] = run("Secret and transcript scan", conclusion="neutral")
    assert judge(runs)["state"] == "green"


def test_the_deadline_is_counted_from_when_the_commit_landed():
    v = judge([], minutes=5)
    assert v["deadline_at"] == (LANDED + timedelta(minutes=main_ci.DEADLINE_MIN)).isoformat()


def test_the_required_names_come_from_the_repos_own_list():
    names = main_ci.required_names()
    assert {"Rules", "Python tests", "Dashboard unit tests", "Secret and transcript scan"} <= set(names)


class FakeGh:
    """gh at the boundary: answers the two REST reads main_ci makes, and records them."""

    def __init__(self, head=HEAD, runs=None, fail=False):
        self.head, self.runs, self.fail, self.calls = head, all_green() if runs is None else runs, fail, []

    def __call__(self, args):
        self.calls.append(args)
        if self.fail:
            raise RuntimeError("HTTP 502")
        path = args[1]
        if path.endswith("/check-runs?per_page=100"):
            return json.dumps({"total_count": len(self.runs), "check_runs": self.runs})
        ref = path.rsplit("/", 1)[-1]
        return json.dumps({"sha": self.head if ref == "main" else ref, "commit": {"committer": {"date": "2026-11-03T19:46:00Z"}}})


def test_read_asks_github_for_mains_head_then_that_commits_checks():
    gh = FakeGh()
    v = main_ci.read("G-Eskayo/marvin", gh=gh, now=LANDED + timedelta(minutes=30), required=REQUIRED)
    assert v["state"] == "green" and v["sha"] == HEAD
    assert gh.calls[0][:2] == ["api", "repos/G-Eskayo/marvin/commits/main"]
    assert gh.calls[1][:2] == ["api", f"repos/G-Eskayo/marvin/commits/{HEAD}/check-runs?per_page=100"]


def test_read_for_a_given_sha_judges_that_commit():
    gh = FakeGh(runs=all_green(sha=OLD))
    v = main_ci.read("G-Eskayo/marvin", sha=OLD, gh=gh, now=LANDED, required=REQUIRED)
    assert v["sha"] == OLD and v["state"] == "green"


def test_github_unreadable_is_unknown_never_green():
    v = main_ci.read("G-Eskayo/marvin", gh=FakeGh(fail=True), now=LANDED, required=REQUIRED)
    assert v["state"] == "unknown" and "HTTP 502" in v["reason"]


def test_the_cli_prints_the_verdict_as_json(monkeypatch, capsys):
    monkeypatch.setattr(main_ci, "_gh", FakeGh())
    assert main_ci.main(["verdict", "--repo", "G-Eskayo/marvin"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["sha"] == HEAD and out["state"] in ("green", "late")
