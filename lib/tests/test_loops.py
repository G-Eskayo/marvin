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
    jd.mkdir(exist_ok=True)
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
    assert problems == [] and len(loops) >= 33  # the audit's 34, less open-loops (folded into tickets, marvin#1222)
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
    assert out == {"ok": True, "how": "open", "repo": "G-Eskayo/marvin", "number": 2001,
                   "url": "https://github.com/G-Eskayo/marvin/issues/2001", "says": "Filed #2001"}
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


def test_validate_rejects_an_auto_level_rerun_fix_whose_job_is_not_in_the_safe_allowlist(tmp_path):
    """An auto-level rerun fix must name a job in AUTO_SAFE_JOBS."""
    out = _world(tmp_path, [_loop(fix={"level": "auto", "kind": "rerun", "arg": "ticket-pipeline"})])
    assert out["loops"] == [] and "auto rerun must specify arg in" in out["problems"][0]["error"]


def test_validate_rejects_auto_level_for_kinds_that_are_never_safe(tmp_path):
    """Only AUTO_SAFE_KINDS are allowed at auto level."""
    for bad_kind in ("relogin", "rollback", "ticket", "decision"):
        out = _world(tmp_path, [_loop(fix={"level": "auto", "kind": bad_kind})])
        assert out["loops"] == [] and f"auto-level fixes must have kind in" in out["problems"][0]["error"]


def test_rebuild_graph_and_refresh_catalog_kinds_take_no_arg(tmp_path):
    """The new kinds are fixed-target, not parameterized."""
    out1 = _world(tmp_path, [_loop(fix={"level": "auto", "kind": "rebuild_graph", "arg": "x"})])
    assert out1["loops"] == [] and "takes no arg" in out1["problems"][0]["error"]
    out2 = _world(tmp_path, [_loop(fix={"level": "auto", "kind": "refresh_catalog", "arg": None})])
    assert len(out2["loops"]) == 1  # none is ok


def test_two_consecutive_auto_failures_demote_to_one_tap_with_both_reasons(tmp_path):
    """After 2+ failures, the loop reports its effective fix as one_tap with reasons."""
    loop = _loop(id="x", fix={"level": "auto", "kind": "rerun", "arg": "health-check"})
    rows = _world(tmp_path, [loop], jobs={"loopfix-x": [
        _r("failed", 10, "first error"),
        _r("failed", 5, "second error"),
    ]})["loops"]
    assert len(rows) == 1 and rows[0]["fix"]["level"] == "one_tap" and rows[0]["fix"]["reasons"] == ["first error", "second error"]


def test_a_third_failure_does_not_add_a_third_reason(tmp_path):
    """Failure-reason list is capped at 2."""
    loop = _loop(id="x", fix={"level": "auto", "kind": "rerun", "arg": "health-check"})
    rows = _world(tmp_path, [loop], jobs={"loopfix-x": [
        _r("failed", 15, "e1"),
        _r("failed", 10, "e2"),
        _r("failed", 5, "e3"),
    ]})["loops"]
    assert rows[0]["fix"]["reasons"] == ["e1", "e2"]


def test_a_fix_that_clears_resets_the_failure_count(tmp_path):
    """After a passing fix, a fresh episode starts the counter from zero."""
    loop = _loop(id="x", fix={"level": "auto", "kind": "rerun", "arg": "health-check"})
    # Three runs: failed, failed, passed
    rows = _world(tmp_path, [loop], jobs={"loopfix-x": [
        _r("failed", 30, "e1"),
        _r("failed", 20, "e2"),
        _r("passed", 10),
    ]})["loops"]
    # After the pass, no demotion (< 2 consecutive failures)
    assert rows[0]["fix"]["level"] == "auto"


def test_run_auto_fixes_skips_a_loop_whose_fix_attempt_is_running(tmp_path):
    """A running loopfix-<id> job blocks that loop from auto-attempting again."""
    loop = _loop(id="x", fix={"level": "auto", "kind": "rerun", "arg": "health-check"})
    checks = [{"id": "jobs:placement", "severity": "red"}]
    _world(tmp_path, [loop], checks=checks,
            jobs={"loopfix-x": [
              _r("failed", 2, "error"),
              {"status": "running", "started_at": NOW.isoformat()},
            ], "health-check": [_r("failed", 1)]})
    # The loop is broken, but since loopfix-x is running, we don't fire another attempt
    def fail_runner(argv):
        pytest.fail(f"runner should not be called when fix is running, but got: {argv}")
    result = lp.run_auto_fixes(checks, tmp_path / "loops.json", tmp_path / "jobs", runner=fail_runner)
    assert result == []  # no fixes attempted


def test_run_auto_fixes_only_fires_on_broken_auto_level_loops(tmp_path):
    """Only broken loops with auto level are candidates."""
    # closed: auto level, not broken (cleanup-sweep passed)
    closed = _loop(id="ok", fix={"level": "auto", "kind": "rerun", "arg": "cleanup-sweep"})
    # broken_manual: one_tap level, broken (health-check failed 3 times)
    broken_manual = _loop(id="manual", watches="job:health-check", fix={"level": "one_tap", "kind": "rerun", "arg": "health-check"})
    # broken_auto: auto level, broken (health-check failed 3 times)
    broken_auto = _loop(id="auto", watches="job:health-check", fix={"level": "auto", "kind": "rerun", "arg": "health-check"})

    checks = []
    _world(tmp_path, [closed, broken_manual, broken_auto],
           checks=checks,
           jobs={"health-check": [_r("failed", 3)], "cleanup-sweep": [_r("passed")]})

    seen = []
    def capture(argv):
        seen.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    lp.run_auto_fixes(checks, tmp_path / "loops.json", tmp_path / "jobs", runner=capture)
    # Only the auto one should fire (broken_auto is broken, broken_manual is not auto, closed is not broken)
    assert len(seen) == 1


def test_the_real_registry_validates_with_the_new_allowlist_rules():
    """Load the actual config/loops.json and confirm all entries validate."""
    loops, problems = lp.load()
    # The real registry should have no problems
    assert problems == []
    # Specific entries should be present and valid
    ids = {x["id"] for x in loops}
    assert "code-graph" in ids and "disk" in ids
    # code-graph should be auto-level with rebuild_graph
    cg = next(x for x in loops if x["id"] == "code-graph")
    assert cg["fix"]["level"] == "auto" and cg["fix"]["kind"] == "rebuild_graph"
    # disk should be auto-level with rerun
    disk = next(x for x in loops if x["id"] == "disk")
    assert disk["fix"]["level"] == "auto" and disk["fix"]["kind"] == "rerun" and disk["fix"]["arg"] == "cleanup-sweep"


def test_run_fix_writes_to_the_provided_jobs_dir(tmp_path):
    """run_fix should use the provided jobs_dir, not the real JOBS_DIR."""
    loop = _loop(id="test", fix={"level": "auto", "kind": "rerun", "arg": "cleanup-sweep"})
    _world(tmp_path, [loop])

    # Mock the job_events module to track where it writes
    import job_events as real_job_events
    written_dirs = []

    class MockRun:
        def __init__(self, job, directory, label):
            written_dirs.append(directory)
            self._failed = None
        def step(self, name, detail=""):
            pass
        def summary(self, detail=""):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    class MockJobEvents:
        JOBS_DIR = real_job_events.JOBS_DIR
        CRASHED_AFTER_S = real_job_events.CRASHED_AFTER_S
        @staticmethod
        def job_run(job, label=None, directory=None):
            return MockRun(job, directory, label)

    result = lp.run_fix("test", tmp_path / "loops.json", jobs_dir=tmp_path / "jobs", job_events_module=MockJobEvents)
    assert len(written_dirs) == 1 and written_dirs[0] == tmp_path / "jobs"


def test_a_stale_running_record_does_not_block_auto_fix(tmp_path):
    """A 'running' record older than CRASHED_AFTER_S should be ignored."""
    import job_events
    loop = _loop(id="x", watches="job:health-check", action="job:health-check", verify="none",
                 fix={"level": "auto", "kind": "rerun", "arg": "health-check"})
    # Create a "running" record that's older than CRASHED_AFTER_S
    stale_time = (NOW - timedelta(seconds=job_events.CRASHED_AFTER_S + 100)).isoformat()
    checks = []
    _world(tmp_path, [loop], checks=checks,
            jobs={"loopfix-x": [
              _r("failed", 2, "error"),
              {"status": "running", "started_at": stale_time, "finished_at": stale_time},
            ], "health-check": [_r("failed", 1), _r("failed", 2), _r("failed", 3)]})

    # Should attempt the fix because the "running" record is stale
    seen = []
    def capture(argv):
        seen.append(argv)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    result = lp.run_auto_fixes(checks, tmp_path / "loops.json", tmp_path / "jobs", now=NOW, runner=capture)
    assert len(result) == 1 and result[0][0] == "x" and len(seen) == 1


def test_a_fix_timeout_is_recorded_as_failure(tmp_path):
    """When run_fix gets a TimeoutExpired, it should be recorded as a failure in the job run."""
    import subprocess
    loop = _loop(id="test", fix={"level": "one_tap", "kind": "rerun", "arg": "cleanup-sweep"})
    _world(tmp_path, [loop])

    def timeout_runner(argv):
        raise subprocess.TimeoutExpired(argv, 120)

    result = lp.run_fix("test", tmp_path / "loops.json", jobs_dir=tmp_path / "jobs", runner=timeout_runner)
    # Should return failure
    assert result["ok"] is False
    # Check that the loopfix-test job was recorded as failed
    runs = lp.read_runs("loopfix-test", tmp_path / "jobs")
    assert runs and runs[-1]["status"] == "failed"


def test_a_fix_nonzero_exit_is_recorded_as_failure(tmp_path):
    """When a fix command exits nonzero, it should be recorded as a failure in the job run."""
    loop = _loop(id="test", fix={"level": "one_tap", "kind": "rerun", "arg": "cleanup-sweep"})
    _world(tmp_path, [loop])

    def fail_runner(argv):
        return SimpleNamespace(returncode=1, stdout="", stderr="something failed")

    result = lp.run_fix("test", tmp_path / "loops.json", jobs_dir=tmp_path / "jobs", runner=fail_runner)
    # Should return failure
    assert result["ok"] is False
    # Check that the loopfix-test job was recorded as failed
    runs = lp.read_runs("loopfix-test", tmp_path / "jobs")
    assert runs and runs[-1]["status"] == "failed"


def test_the_cli_refuses_anything_but_status_and_fix_one_id():
    assert lp.main([]) == 2 and lp.main(["fix"]) == 2 and lp.main(["rm", "-rf", "/"]) == 2
