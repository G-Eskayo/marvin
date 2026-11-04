"""The loop registry (lib/loops.py, #1123, ADR 0083). Tests try to break it: a hostile or malformed registry, signals
that are missing, mangled or contradictory, a job that never reported, failures in a row interrupted by a running one,
a fix arg that tries to inject a command, a ticket gh refuses, and the real registry against the real job catalog."""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import loops as lp  # noqa: E402

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)


def _loop(**kw):
    base = {"id": "disk", "name": "Disk stays free", "watches": "check:disk:headroom", "broken_when": "failed_runs:3",
            "action": "job:cleanup-sweep", "verify": "check:disk:space", "cycle_days": 1, "owner": "marvin",
            "fix": {"level": "one_tap", "kind": "rerun", "arg": "cleanup-sweep"}, "wired": True, "ticket": 1123}
    return {**base, **kw}


def _world(tmp_path, loops, checks=(), jobs=None):
    reg = tmp_path / "loops.json"
    reg.write_text(json.dumps({"loops": loops}))
    health = tmp_path / "health.json"
    health.write_text(json.dumps({"generated_at": "t", "checks": list(checks)}))
    jd = tmp_path / "jobs"
    jd.mkdir()
    for name, runs in (jobs or {}).items():
        (jd / f"{name}.json").write_text(json.dumps({"job": name, "runs": runs}))
    return lp.status(reg, health, jd, NOW)


def _r(status, hours_ago=1, error=""):
    t = (NOW - timedelta(hours=hours_ago)).isoformat()
    return {"status": status, "started_at": t, "finished_at": t, "error": error}


def _one(tmp_path, loop=None, **kw):
    return _world(tmp_path, [loop or _loop()], **kw)["loops"][0]


# ── status ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_cycle_that_passed_today_with_green_signals_is_closed(tmp_path):
    row = _one(tmp_path, checks=[{"id": "disk:headroom@mini", "severity": "green"}, {"id": "disk:space@mini", "severity": "green"}],
               jobs={"cleanup-sweep": [_r("passed", 3)]})
    assert row["status"] == "closed" and row["last_cycle"] == (NOW - timedelta(hours=3)).isoformat()


def test_unwired_comes_first_whatever_the_signals_say(tmp_path):
    row = _one(tmp_path, _loop(wired=False, why="Tier 1"), checks=[{"id": "disk:headroom", "severity": "red"}])
    assert row["status"] == "not_wired" and row["reason"] == "Tier 1"


def test_a_job_that_never_reported_is_not_wired_not_closed(tmp_path):
    assert _one(tmp_path)["status"] == "not_wired"


def test_the_worst_matching_check_wins_across_machines(tmp_path):
    row = _one(tmp_path, checks=[{"id": "disk:headroom@laptop", "severity": "green"}, {"id": "disk:headroom@mini", "severity": "red", "detail": "2 days left"}],
               jobs={"cleanup-sweep": [_r("passed")]})
    assert row["status"] == "broken" and "2 days left" in row["reason"]


def test_a_red_verify_breaks_it_and_a_pass_under_a_red_verify_is_not_a_full_cycle(tmp_path):
    row = _one(tmp_path, checks=[{"id": "disk:space@mini", "severity": "red"}], jobs={"cleanup-sweep": [_r("passed")]})
    assert row["status"] == "broken" and row["last_cycle"] is None


def test_three_failures_in_a_row_break_it_even_with_a_run_in_progress(tmp_path):
    runs = [_r("passed", 9), _r("failed", 3, "e1"), _r("failed", 2, "e2"), _r("crashed", 1), {"status": "running", "started_at": NOW.isoformat()}]
    row = _one(tmp_path, jobs={"cleanup-sweep": runs})
    assert row["status"] == "broken" and row["reason"] == "cleanup-sweep failed 3 runs in a row"


def test_two_failures_are_not_three(tmp_path):
    row = _one(tmp_path, _loop(watches="none", verify="none"), jobs={"cleanup-sweep": [_r("passed", 5), _r("failed", 2), _r("failed", 1)]})
    assert row["status"] == "closed"


def test_no_pass_within_its_cycle_is_stalled(tmp_path):
    row = _one(tmp_path, jobs={"cleanup-sweep": [_r("passed", 50)]})
    assert row["status"] == "stalled" and "2 days ago" in row["reason"]


def test_an_amber_signal_is_stalled(tmp_path):
    row = _one(tmp_path, checks=[{"id": "disk:headroom", "severity": "yellow", "detail": "9 days"}], jobs={"cleanup-sweep": [_r("passed")]})
    assert row["status"] == "stalled"


def test_a_contract_signal_reads_its_finding(tmp_path):
    loop = _loop(watches="contract:safety-monitor", verify="none", action="Gil's review", wired=True)
    row = _one(tmp_path, loop, checks=[{"id": "contract:safety-monitor", "severity": "red", "detail": "70 waiting"}])
    assert row["status"] == "broken" and "70 waiting" in row["reason"]


@pytest.mark.parametrize("health", ["{", "[]", '{"checks": 5}', '{"checks": [null, 3, {"id": 7}]}'])
def test_a_mangled_health_file_means_unknown_signals_not_a_crash(tmp_path, health):
    reg = tmp_path / "loops.json"
    reg.write_text(json.dumps({"loops": [_loop()]}))
    (tmp_path / "h.json").write_text(health)
    (tmp_path / "jobs").mkdir()
    (tmp_path / "jobs" / "cleanup-sweep.json").write_text('{"runs": [5, null, {"status": "passed", "finished_at": "garbage"}]}')
    row = lp.status(reg, tmp_path / "h.json", tmp_path / "jobs", NOW)["loops"][0]
    assert row["status"] == "stalled" and row["watched"]["state"] == "unknown"


def test_loops_are_listed_worst_first_with_counts(tmp_path):
    out = _world(tmp_path, [_loop(id="a", name="A", wired=False), _loop(id="b", name="B")],
                 checks=[{"id": "disk:headroom", "severity": "red"}], jobs={"cleanup-sweep": [_r("passed")]})
    assert [r["status"] for r in out["loops"]] == ["broken", "not_wired"]
    assert out["counts"] == {"broken": 1, "stalled": 0, "not_wired": 1, "closed": 0}


# ── the registry itself ───────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [
    {"id": "../x"}, {"id": "A"}, {"surprise": 1},
    {"watches": "shell:rm -rf"}, {"watches": "job:a b"}, {"verify": None},
    {"broken_when": "failed_runs:0"}, {"broken_when": "sometimes"},
    {"cycle_days": 0}, {"cycle_days": True}, {"cycle_days": 91},
    {"owner": "someone"}, {"wired": "yes"}, {"ticket": -1}, {"ticket": True},
    {"name": ""}, {"name": "x" * 400}, {"action": None},
    {"fix": {"level": "auto", "kind": "rerun", "arg": "x; rm -rf ~"}},
    {"fix": {"level": "auto", "kind": "rerun", "arg": "../../evil"}},
    {"fix": {"level": "auto", "kind": "shell", "arg": "x"}},
    {"fix": {"level": "sometimes", "kind": "ticket"}},
    {"fix": {"level": "one_tap", "kind": "ticket", "arg": "x"}},
    {"fix": {"level": "one_tap", "kind": "decision", "arg": "12abc"}},
    {"fix": {"level": "one_tap", "kind": "relogin", "arg": "GitHub token"}},
])
def test_a_bad_entry_is_a_problem_and_never_shown(tmp_path, bad):
    out = _world(tmp_path, [_loop(**bad), _loop(id="ok")])
    assert [r["id"] for r in out["loops"]] == ["ok"] and len(out["problems"]) == 1


@pytest.mark.parametrize("registry", ["", "{", "[]", '{"loops": 5}', "\x00"])
def test_an_unreadable_registry_is_one_problem_not_a_crash(tmp_path, registry):
    (tmp_path / "loops.json").write_text(registry)
    out = lp.status(tmp_path / "loops.json", tmp_path / "missing.json", tmp_path, NOW)
    assert out["loops"] == [] and out["problems"][0]["error"].startswith("registry unreadable")


def test_a_duplicate_id_keeps_the_first(tmp_path):
    out = _world(tmp_path, [_loop(name="First"), _loop(name="Second")])
    assert [r["name"] for r in out["loops"]] == ["First"] and "duplicate" in out["problems"][0]["error"]


def test_the_real_registry_parses_and_covers_the_audit():
    loops, problems = lp.load()
    assert problems == [] and len(loops) >= 34
    ids = {x["id"] for x in loops}
    for must in ("alerts", "sync", "deploy-verify", "history-backup", "morning-brief", "disk", "safety-reviews",
                 "improvement-queue", "architecture-suggestions", "logins", "peers", "question-log", "memory"):
        assert must in ids


def test_every_job_the_real_registry_names_is_a_real_job():
    import job_catalog
    import job_units
    known = set(job_catalog.JOBS) | set(job_units.available()) | {"alerts"}
    for x in lp.load()[0]:
        for ref in (x["action"], x["watches"], x["verify"]):
            if ref.startswith("job:"):
                assert ref[4:] in known, (x["id"], ref)
        if x["fix"]["kind"] in ("rerun", "install_job"):
            assert x["fix"]["arg"] in known, (x["id"], x["fix"])


# ── fixes ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_rerun_kickstarts_only_the_registry_job(tmp_path):
    _world(tmp_path, [_loop()])
    seen = []
    out = lp.run_fix("disk", tmp_path / "loops.json", runner=lambda argv: seen.append(argv) or SimpleNamespace(returncode=0, stdout="", stderr=""))
    assert out["ok"] and seen[0][:2] == ["/bin/launchctl", "kickstart"] and seen[0][2].endswith("/com.marvin.cleanup-sweep")


def test_a_failing_fix_says_why(tmp_path):
    _world(tmp_path, [_loop()])
    out = lp.run_fix("disk", tmp_path / "loops.json", runner=lambda argv: SimpleNamespace(returncode=113, stdout="", stderr="Could not find service"))
    assert not out["ok"] and "Could not find service" in out["error"]


def test_a_hanging_fix_is_a_failure_not_a_hang(tmp_path):
    import subprocess
    _world(tmp_path, [_loop()])
    def hang(argv):
        raise subprocess.TimeoutExpired(argv, 120)
    assert lp.run_fix("disk", tmp_path / "loops.json", runner=hang)["ok"] is False


@pytest.mark.parametrize("loop_id", ["nope", "../disk", None, 5, "disk; rm"])
def test_an_unknown_loop_runs_nothing(tmp_path, loop_id):
    _world(tmp_path, [_loop()])
    out = lp.run_fix(loop_id, tmp_path / "loops.json", runner=lambda argv: pytest.fail("ran something"))
    assert out["ok"] is False


def test_file_ticket_files_one_needs_triage_ticket_and_opens_it(tmp_path):
    _world(tmp_path, [_loop(fix={"level": "one_tap", "kind": "ticket"})])
    calls = []
    out = lp.run_fix("disk", tmp_path / "loops.json", gh=lambda args, body: calls.append((args, body)) or (0, "https://github.com/G-Eskayo/marvin/issues/2001\n", ""))
    assert out == {"ok": True, "how": "open", "url": "https://github.com/G-Eskayo/marvin/issues/2001", "says": "Filed #2001"}
    assert "needs-triage" in calls[0][0] and "Part of #1123" in calls[0][1]


def test_a_ticket_gh_refuses_is_reported(tmp_path):
    _world(tmp_path, [_loop(fix={"level": "one_tap", "kind": "ticket"})])
    out = lp.run_fix("disk", tmp_path / "loops.json", gh=lambda a, b: (1, "", "HTTP 401"))
    assert out == {"ok": False, "how": "ticket", "error": "HTTP 401"}


def test_relogin_and_decision_hand_back_to_existing_flows(tmp_path):
    _world(tmp_path, [_loop(id="a", fix={"level": "one_tap", "kind": "relogin", "arg": "github"}),
                      _loop(id="b", fix={"level": "decision", "kind": "decision", "arg": 729})])
    assert lp.run_fix("a", tmp_path / "loops.json") == {"ok": True, "how": "renew", "account": "github"}
    assert lp.run_fix("b", tmp_path / "loops.json")["url"].endswith("/issues/729")


def test_the_cli_refuses_anything_but_status_and_fix_one_id():
    assert lp.main([]) == 2 and lp.main(["fix"]) == 2 and lp.main(["rm", "-rf", "/"]) == 2
