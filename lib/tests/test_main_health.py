"""main_health: is the base branch green? Checked on a clean checkout, recorded, and shown in Health."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_health as mh  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


def test_a_green_run_is_recorded_with_the_commit_it_checked(tmp_path):
    state = tmp_path / "m.json"
    res = mh.refresh(state_path=state, head=lambda: "abc1234", run_suite=lambda: (True, [], "1137 passed"), now=NOW)
    assert res == {"sha": "abc1234", "ok": True, "failed": [], "summary": "1137 passed", "checked_at": NOW.isoformat(), "ran": True}
    assert json.loads(state.read_text())["ok"] is True


def test_an_unchanged_commit_is_not_rechecked(tmp_path):
    state = tmp_path / "m.json"
    calls = []
    run = lambda: calls.append(1) or (True, [], "ok")
    mh.refresh(state_path=state, head=lambda: "abc", run_suite=run, now=NOW)
    again = mh.refresh(state_path=state, head=lambda: "abc", run_suite=run, now=NOW + timedelta(hours=1))
    assert len(calls) == 1 and again["ran"] is False


def test_a_new_commit_is_checked_and_a_failure_names_the_tests(tmp_path):
    state = tmp_path / "m.json"
    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW)
    res = mh.refresh(state_path=state, head=lambda: "bbb", run_suite=lambda: (False, ["tests/test_a.py::test_x"], "1 failed"), now=NOW)
    assert res["ok"] is False and res["failed"] == ["tests/test_a.py::test_x"] and res["sha"] == "bbb"


def test_a_run_that_could_not_happen_keeps_the_last_good_answer(tmp_path):
    state = tmp_path / "m.json"
    mh.refresh(state_path=state, head=lambda: "aaa", run_suite=lambda: (True, [], "ok"), now=NOW)
    res = mh.refresh(state_path=state, head=lambda: None, run_suite=lambda: (False, [], "x"), now=NOW)   # offline: no head
    assert res["sha"] == "aaa" and res["ok"] is True


def test_pytest_failures_are_read_from_the_output():
    out = "FAILED tests/test_a.py::test_x - AssertionError\nFAILED tests/test_b.py::test_y\n2 failed, 10 passed in 3s\n"
    assert mh.failed_ids(out) == ["tests/test_a.py::test_x", "tests/test_b.py::test_y"]


# ---- marvin#457: single flight, and only when code moved ----

def _seed(state, sha="aaa", ok=True, failed=None):
    mh.refresh(state_path=state, head=lambda: sha, run_suite=lambda: (ok, failed or [], "seed"), now=NOW,
               changed=lambda a, b: None)


def test_a_refresh_while_one_is_running_returns_at_once_and_runs_nothing(tmp_path):
    import fcntl
    state = tmp_path / "m.json"
    with open(state.with_suffix(".lock"), "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)  # another refresh, mid-suite
        calls = []
        res = mh.refresh(state_path=state, head=lambda: calls.append("head") or "abc",
                         run_suite=lambda: calls.append("suite") or (True, [], "ok"), now=NOW)
    assert res == {"ran": False, "busy": True}
    assert calls == [], "a busy refresh must not even fetch"
    assert not state.exists()


def test_the_lock_is_released_after_a_run_and_after_a_crash(tmp_path):
    state = tmp_path / "m.json"
    def boom():
        raise RuntimeError("worktree add failed")
    import pytest
    with pytest.raises(RuntimeError):
        mh.refresh(state_path=state, head=lambda: "abc", run_suite=boom, now=NOW)
    res = mh.refresh(state_path=state, head=lambda: "abc", run_suite=lambda: (True, [], "ok"), now=NOW)
    assert res["ran"] is True


def test_two_processes_at_once_run_one_suite(tmp_path):
    """Real processes racing for the lock: exactly one suite runs (three ran at once on the mini, 2026-10-21)."""
    import subprocess, textwrap
    state = tmp_path / "m.json"
    runs = tmp_path / "runs"
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(Path(mh.__file__).parent)!r})
        import main_health as mh
        from pathlib import Path
        def suite():
            with open({str(runs)!r}, "a") as f: f.write("x")
            time.sleep(1.5)
            return True, [], "ok"
        print(mh.refresh(state_path=Path({str(state)!r}), head=lambda: "abc", run_suite=suite, changed=lambda a, b: None))
    """)
    procs = [subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, text=True) for _ in range(3)]
    outs = [p.communicate(timeout=60)[0] for p in procs]
    assert runs.read_text() == "x"
    assert sum("'busy': True" in o for o in outs) == 2


def test_a_metrics_only_move_carries_the_verdict_forward_without_running(tmp_path):
    state = tmp_path / "m.json"
    _seed(state, "aaa")
    calls = []
    res = mh.refresh(state_path=state, head=lambda: "bbb", run_suite=lambda: calls.append(1) or (False, ["x"], "1 failed"),
                     now=NOW + timedelta(hours=30),
                     changed=lambda a, b: ["bench/metrics/health-monitor.mac-mini.json", "bench/metrics/health-monitor.mac-mini.md"],
                     named_by_a_test=lambda p, s: True)
    assert calls == []
    assert res["sha"] == "bbb" and res["ok"] is True and res["tested_sha"] == "aaa" and res["ran"] is False
    assert "carried" in res
    saved = json.loads(state.read_text())
    assert saved["sha"] == "bbb" and saved["checked_at"] == (NOW + timedelta(hours=30)).isoformat()  # not "a day old"


def test_a_red_main_stays_red_across_a_docs_only_move(tmp_path):
    state = tmp_path / "m.json"
    _seed(state, "aaa", ok=False, failed=["lib/tests/test_a.py::test_x"])
    res = mh.refresh(state_path=state, head=lambda: "bbb", run_suite=lambda: (True, [], "ok"), now=NOW,
                     changed=lambda a, b: ["docs/plans/x.md"], named_by_a_test=lambda p, s: False)
    assert res["ok"] is False and res["failed"] == ["lib/tests/test_a.py::test_x"] and res["sha"] == "bbb"


def test_carried_forward_twice_still_names_the_commit_actually_tested(tmp_path):
    state = tmp_path / "m.json"
    _seed(state, "aaa")
    for sha in ("bbb", "ccc"):
        res = mh.refresh(state_path=state, head=lambda s=sha: s, run_suite=lambda: (True, [], "ok"), now=NOW,
                         changed=lambda a, b: ["x.log"], named_by_a_test=lambda p, s: False)
    assert res["sha"] == "ccc" and res["tested_sha"] == "aaa"


def test_any_code_change_runs_the_suite(tmp_path):
    state = tmp_path / "m.json"
    _seed(state, "aaa")
    for changed in (["lib/main_health.py"], ["bench/metrics/x.json", "lib/a.py"], ["dashboard/src/App.jsx"], ["pytest.ini"],
                    ["VERSION"], ["config/projects/marvin.json"]):
        res = mh.refresh(state_path=state, head=lambda c=changed: "s" + str(len(c)) + c[-1], run_suite=lambda: (True, [], "ran"),
                         now=NOW, changed=lambda a, b, c=changed: c, named_by_a_test=lambda p, s: False)
        assert res["ran"] is True, changed


def test_a_doc_a_test_reads_runs_the_suite(tmp_path):
    state = tmp_path / "m.json"
    _seed(state, "aaa")
    res = mh.refresh(state_path=state, head=lambda: "bbb", run_suite=lambda: (True, [], "ran"), now=NOW,
                     changed=lambda a, b: ["docs/north-stars.md"], named_by_a_test=lambda p, s: p == "docs/north-stars.md")
    assert res["ran"] is True


def test_unknown_changes_run_the_suite(tmp_path):
    state = tmp_path / "m.json"
    _seed(state, "aaa")
    res = mh.refresh(state_path=state, head=lambda: "bbb", run_suite=lambda: (True, [], "ran"), now=NOW,
                     changed=lambda a, b: None)
    assert res["ran"] is True


def test_no_prior_record_runs_the_suite(tmp_path):
    res = mh.refresh(state_path=tmp_path / "m.json", head=lambda: "aaa", run_suite=lambda: (True, [], "ran"), now=NOW,
                     changed=lambda a, b: [], named_by_a_test=lambda p, s: False)
    assert res["ran"] is True


def test_needs_suite_classifies_paths():
    never = lambda p: False
    assert mh.needs_suite([], never) is False
    assert mh.needs_suite(["bench/metrics/a.json", "logs/x.jsonl", "a.log", "docs/adr/0099-x.md", "README.md"], never) is False
    assert mh.needs_suite(["bench/bench.py"], never) is True          # bench code is code
    assert mh.needs_suite(["docs/build.sh"], never) is False           # under docs/: a doc unless a test names it
    assert mh.needs_suite(["lib/x.mdx"], never) is True
    assert mh.needs_suite(["CONTEXT.md"], lambda p: p == "CONTEXT.md") is True
    assert mh.needs_suite(None, never) is True


def test_named_by_a_test_uses_git_grep_on_the_new_commit(tmp_path, monkeypatch):
    import subprocess
    repo = tmp_path / "r"
    (repo / "lib" / "tests").mkdir(parents=True)
    (repo / "lib" / "tests" / "test_x.py").write_text('assert "north-stars.md" in open("docs/north-stars.md").read()\n')
    (repo / "docs").mkdir()
    (repo / "docs" / "north-stars.md").write_text("x")
    (repo / "docs" / "plan.md").write_text("x")
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True)
    monkeypatch.setattr(mh, "REPO_DIR", repo)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert mh._named_by_a_test("docs/north-stars.md", sha) is True
    assert mh._named_by_a_test("docs/plan.md", sha) is False
    assert mh._named_by_a_test("docs/plan.md", "no-such-sha") is True  # unknown: run the suite
    (repo / "docs" / "plan.md").write_text("y")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "d"], cwd=repo, check=True)
    new = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert mh._changed_paths(sha, new) == ["docs/plan.md"]
    assert mh._changed_paths("nope", new) is None


def test_a_half_written_state_file_is_never_left(tmp_path):
    state = tmp_path / "m.json"
    _seed(state, "aaa")
    assert not state.with_suffix(".tmp").exists()
    assert json.loads(state.read_text())["sha"] == "aaa"


def test_the_suite_runs_niced_so_it_never_starves_the_merge_gate(monkeypatch):
    seen = []

    class R:
        returncode, stdout, stderr = 0, "5 passed in 1s\n", ""
    monkeypatch.setattr(mh.subprocess, "run", lambda cmd, **k: seen.append(cmd) or R())
    ok, failed, summary = mh._run_suite()
    suite = [c for c in seen if "pytest" in c][0]
    assert suite[:3] == ["nice", "-n", "10"] and ok is True and summary == "5 passed in 1s"


# ---- parallel suite (pytest-xdist) ----

def test_parallel_args_with_the_real_venv_sizes_workers_to_free_memory():
    """marvin#940: as many workers as fit in free memory (test_slot.workers), never one per core regardless."""
    import pytest
    if mh.subprocess.run([str(mh.VENV_PY), "-c", "import xdist"], capture_output=True).returncode != 0:
        pytest.skip("this machine's venv has no pytest-xdist")
    assert mh.parallel_args(workers=lambda: 3) == ["-n", "3"]
    n, count = mh.parallel_args()
    assert n == "-n" and int(count) >= 1


def test_a_python_without_xdist_runs_serially_and_says_why(tmp_path, capsys):
    fake = tmp_path / "python"
    fake.write_text("#!/bin/sh\necho 'ModuleNotFoundError: No module named xdist' >&2\nexit 1\n")
    fake.chmod(0o755)
    assert mh.parallel_args(fake) == []
    err = capsys.readouterr().err
    assert "pytest-xdist is not installed" in err and "serially" in err and "pip install pytest-xdist" in err


def test_a_missing_or_broken_python_runs_serially_never_crashes(tmp_path):
    assert mh.parallel_args(tmp_path / "no-such-python") == []
    d = tmp_path / "a-dir"
    d.mkdir()
    assert mh.parallel_args(d) == []


def test_the_suite_gets_n_workers_when_the_plugin_is_there_and_not_when_it_is_missing(monkeypatch):
    for probe_rc, expect in ((0, True), (1, False)):
        seen = []

        class R:
            def __init__(self, cmd):
                self.returncode = probe_rc if cmd[1:] == ["-c", "import xdist"] else 0
                self.stdout, self.stderr = "5 passed in 1s\n", ""
        monkeypatch.setattr(mh.subprocess, "run", lambda cmd, **k: seen.append(cmd) or R(cmd))
        mh._run_suite()
        suite = [c for c in seen if "pytest" in c][0]
        assert (suite[-2] == "-n" and suite[-1].isdigit()) is expect, (probe_rc, suite)


# ---- marvin#940: after a burst of merges, one more run on the latest main (not one per merge) ----

def test_a_burst_of_merges_during_a_run_coalesces_into_one_more_run_on_the_latest_main(tmp_path):
    state = tmp_path / "m.json"
    heads = iter(["a", "c"])
    current = {"sha": None}
    ran = []

    def head():
        current["sha"] = next(heads)
        return current["sha"]

    def suite():
        ran.append(current["sha"])
        if len(ran) == 1:   # two more merges land while the first run is going: both find it busy
            for _ in range(2):
                assert mh.refresh(state_path=state, head=lambda: "never read", run_suite=suite, now=NOW)["busy"]
        return True, [], "ok"

    res = mh.refresh(state_path=state, head=head, run_suite=suite, now=NOW, changed=lambda a, b: None)
    assert ran == ["a", "c"]
    assert res["sha"] == "c" and json.loads(state.read_text())["sha"] == "c"


def test_no_merge_during_a_run_means_no_second_run(tmp_path):
    state = tmp_path / "m.json"
    ran = []
    mh.refresh(state_path=state, head=lambda: "a", run_suite=lambda: ran.append(1) or (True, [], "ok"), now=NOW)
    assert ran == [1]


def test_the_suite_runs_in_the_machines_test_slot(monkeypatch):
    import test_slot
    entered = []

    class R:
        returncode, stdout, stderr = 0, "5 passed in 1s\n", ""

    class Slot:
        def __init__(self, what, **k):
            entered.append(what)
        def __enter__(self):
            return True
        def __exit__(self, *a):
            entered.append("left")
    monkeypatch.setattr(test_slot, "slot", Slot)
    monkeypatch.setattr(mh.subprocess, "run", lambda cmd, **k: R())
    mh._run_suite()
    assert entered == ["main-health (after-merge full suite)", "left"]
