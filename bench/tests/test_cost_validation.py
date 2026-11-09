"""Tests for the cost-validation pieces of the bench (marvin#645):
hidden task checks in bench.py, the model recorded by score.parse_stream, and the
cost-per-successful-task report in cost_report.py.
    ~/.agents/venv/bin/python -m pytest bench/tests/test_cost_validation.py -v
"""
from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "lib"))

import bench  # noqa: E402
import cost_report as cr  # noqa: E402
from score import parse_stream  # noqa: E402


# ── hidden checks ─────────────────────────────────────────────────────────

def _task_with_check(tmp_path: Path) -> dict:
    tdir = tmp_path / "task-x"
    (tdir / "check").mkdir(parents=True)
    (tdir / "check" / "test_hidden_x.py").write_text(
        "from mod import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )
    return {"id": "task-x", "dir": tdir, "check": {"files": "check"}}


def test_hidden_check_passes_on_correct_code(tmp_path):
    task = _task_with_check(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    (work / "mod.py").write_text("def add(a, b):\n    return a + b\n")
    res = bench.run_hidden_check(task, work)
    assert res["pass"] is True


def test_hidden_check_fails_on_wrong_code_and_keeps_the_output(tmp_path):
    task = _task_with_check(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    (work / "mod.py").write_text("def add(a, b):\n    return a - b\n")
    res = bench.run_hidden_check(task, work)
    assert res["pass"] is False
    assert "assert" in res["output"]


def test_hidden_check_fails_when_the_code_does_not_import(tmp_path):
    task = _task_with_check(tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    (work / "mod.py").write_text("def add(a, b)\n")  # syntax error
    assert bench.run_hidden_check(task, work)["pass"] is False


def test_task_without_check_is_not_checked(tmp_path):
    assert bench.run_hidden_check({"id": "t", "dir": tmp_path}, tmp_path) is None


def test_the_real_hidden_checks_fail_on_the_seeded_buggy_files(tmp_path):
    """Every shipped hidden check must fail on the task's own starting files, or it can't tell a fix from no fix."""
    import shutil
    checked = [d for d in sorted((BENCH / "tasks").iterdir())
               if (d / "task.json").exists() and json.loads((d / "task.json").read_text()).get("check")]
    assert checked, "expected at least one task with a hidden check"
    for d in checked:
        task = bench.load_task(d)
        work = tmp_path / d.name
        shutil.copytree(d / "files", work)
        res = bench.run_hidden_check(task, work)
        assert res["pass"] is False, f"{d.name}: hidden check passes on the unfixed code"


# ── qa tasks can run outside home ─────────────────────────────────────────

def test_qa_task_with_tmp_cwd_runs_in_a_fresh_folder_outside_home(tmp_path, monkeypatch):
    """cwd = 'tmp' makes Claude Code run outside home (deterministic workdir, emptied at start not deleted at end)."""
    seen = {}

    def fake_run(cmd, cwd=None, **kw):
        seen["cwd"], seen["prompt"] = Path(cwd), cmd[2]
        seen["empty"] = not any(Path(cwd).iterdir())
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)
    task = {"id": "t", "type": "qa", "cwd": "tmp", "prompt": "Q", "dir": tmp_path}
    run = bench.run_once(task, "clean", prompt_prefix="Caveman mode. ")
    assert seen["empty"] and Path.home() not in seen["cwd"].resolve().parents
    assert seen["cwd"].exists()          # deterministic workdir persists
    assert seen["prompt"] == "Caveman mode. Q"
    assert "check" not in run


def test_deterministic_workdir_same_params_same_path():
    """Same task_id, profile, model, prompt_prefix yields same workdir path."""
    p1 = bench._deterministic_workdir("task-1", "marvin", "claude-opus-5-5", "prefix")
    p2 = bench._deterministic_workdir("task-1", "marvin", "claude-opus-5-5", "prefix")
    assert p1 == p2
    p3 = bench._deterministic_workdir("task-1", "clean", "claude-opus-5-5", "prefix")
    assert p1 != p3


def test_deterministic_workdir_path_under_system_temp():
    """Deterministic workdir paths are under the system temp root."""
    from tempfile import gettempdir
    p = bench._deterministic_workdir("task-1", "marvin", None, "x")
    assert str(p).startswith(gettempdir())


def test_workdir_emptied_at_start_not_deleted_at_end(tmp_path, monkeypatch):
    """is_fs task: workdir is emptied at start, persists after run."""
    seen = {}
    run_count = [0]

    def fake_run(cmd, cwd=None, **kw):
        run_count[0] += 1
        cwd_path = Path(cwd)

        # On run 2, check what's in the workdir BEFORE the task creates files
        if run_count[0] == 2:
            # The old output.txt from run1 should be gone
            seen["has_old_output"] = (cwd_path / "output.txt").exists()
            # The input files should still be there (restored by bench.py)
            seen["has_input"] = (cwd_path / "input.txt").exists()

        # Task creates an output file
        (cwd_path / "output.txt").write_text(f"result_from_run_{run_count[0]}")
        seen[f"cwd_run{run_count[0]}"] = cwd_path
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)

    # Create a task that will use fs mode
    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.json").write_text(json.dumps({"id": "fs-task", "type": "fs", "prompt_file": "p.md"}))
    (task_dir / "p.md").write_text("prompt")
    (task_dir / "files").mkdir()
    (task_dir / "files" / "input.txt").write_text("data")

    task = bench.load_task(task_dir)
    run1 = bench.run_once(task, "marvin")
    workdir = seen["cwd_run1"]

    # Verify file created during run1 exists
    assert (workdir / "output.txt").exists()
    assert (workdir / "input.txt").exists()

    # Second run with same params should empty the workdir but keep the directory
    run2 = bench.run_once(task, "marvin")
    assert seen["cwd_run2"] == workdir  # same workdir path
    assert workdir.exists()
    # Old output.txt should be gone, input files should be restored
    assert not seen["has_old_output"], "old output.txt was not removed before run2"
    assert seen["has_input"], "input files were not restored before run2"


def test_workdir_handles_file_path():
    """If workdir path exists as a plain file, it's removed before mkdir."""
    import tempfile
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmpdir:
        # Create a file where we want the workdir to be
        fake_path = Path(tmpdir) / "mb-fake"
        fake_path.write_text("I am a file")

        # Simulate the workdir setup code from bench.py
        workdir = fake_path
        if workdir.exists() and workdir.is_dir():
            for item in workdir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
        elif workdir.exists() or workdir.is_symlink():
            workdir.unlink(missing_ok=True)
            workdir.mkdir(parents=True, exist_ok=True)
        else:
            workdir.mkdir(parents=True, exist_ok=True)

        # Should now be a clean directory, not a file
        assert workdir.is_dir()
        assert not any(workdir.iterdir())


def test_workdir_handles_broken_symlink():
    """If workdir path is a broken symlink, it's removed before mkdir."""
    import tempfile
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmpdir:
        # Create a broken symlink
        fake_path = Path(tmpdir) / "mb-broken"
        fake_path.symlink_to("/nonexistent/path")
        assert not fake_path.exists()  # broken symlink
        assert fake_path.is_symlink()

        # Simulate the workdir setup code
        workdir = fake_path
        if workdir.exists() and workdir.is_dir():
            for item in workdir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item, ignore_errors=True)
                else:
                    item.unlink(missing_ok=True)
        elif workdir.exists() or workdir.is_symlink():
            workdir.unlink(missing_ok=True)
            workdir.mkdir(parents=True, exist_ok=True)
        else:
            workdir.mkdir(parents=True, exist_ok=True)

        # Should now be a clean directory
        assert workdir.is_dir()
        assert not any(workdir.iterdir())


# ── budget stop ───────────────────────────────────────────────────────────

def test_budget_stop_fires_on_either_usage_window():
    q = {"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.4},
                                                  "seven_day": {"utilization": 0.81}}}
    assert "seven_day" in bench._usage_over(q, 0.8)
    assert bench._usage_over(q, 0.9) is None


def test_budget_stop_fires_when_the_plan_already_refuses_and_never_on_unknown_usage():
    assert bench._usage_over({"status": "rejected", "rateLimitType": "five_hour"}, 0.9)
    assert bench._usage_over(None, 0.1) is None


# ── model recorded from the stream ────────────────────────────────────────

def test_parse_stream_records_the_model_the_session_used():
    lines = [
        {"type": "system", "subtype": "init", "model": "claude-haiku-4-5-20251001"},
        {"type": "result", "result": "ok", "total_cost_usd": 0.01, "usage": {"output_tokens": 3}},
    ]
    out = parse_stream("\n".join(json.dumps(x) for x in lines))
    assert out["model_used"] == "claude-haiku-4-5-20251001"


# ── success rule ──────────────────────────────────────────────────────────

def test_success_needs_both_the_hidden_check_and_the_judge():
    assert cr.is_success({"check": {"pass": True}, "judge_correctness": {"score": 1.0}}) is True
    assert cr.is_success({"check": {"pass": False}, "judge_correctness": {"score": 1.0}}) is False
    assert cr.is_success({"check": {"pass": True}, "judge_correctness": {"score": 0.0}}) is False


def test_success_without_a_check_uses_the_judge_then_the_substring_score():
    assert cr.is_success({"judge_correctness": {"score": 1.0}, "correctness": {"score": 0.0}}) is True
    assert cr.is_success({"correctness": {"score": 1.0}}) is True
    assert cr.is_success({"correctness": {"score": 0.5}}) is False


def test_an_infra_error_is_neither_success_nor_failure():
    assert cr.is_success({"infra_error": True, "correctness": {"score": None}}) is None


# ── cell summary ──────────────────────────────────────────────────────────

def _run(cost, ok=True, out=100, inp=10, cc=1000, cr_=5000, wall=10.0):
    return {"cost_usd": cost, "output_tokens": out, "input_tokens": inp,
            "cache_creation_input_tokens": cc, "cache_read_input_tokens": cr_,
            "wall_s": wall, "judge_correctness": {"score": 1.0 if ok else 0.0}}


def test_cost_per_success_charges_failed_runs_to_the_successes():
    s = cr.summarize_cell([_run(1.0), _run(1.0, ok=False), _run(1.0)])
    assert s["n"] == 3 and s["n_success"] == 2
    assert s["cost_mean"] == pytest.approx(1.0)
    assert s["cost_per_success"] == pytest.approx(1.5)


def test_cell_with_no_success_has_infinite_cost_per_success():
    s = cr.summarize_cell([_run(0.5, ok=False), _run(0.5, ok=False)])
    assert s["n_success"] == 0 and math.isinf(s["cost_per_success"])


def test_cell_summary_splits_input_and_output_tokens_and_skips_infra_errors():
    runs = [_run(1.0, out=200, inp=1, cc=10, cr_=100), _run(3.0, out=400, inp=1, cc=10, cr_=100),
            {"infra_error": True, "cost_usd": 0.0}]
    s = cr.summarize_cell(runs)
    assert s["n"] == 2 and s["n_infra_error"] == 1
    assert s["output_mean"] == pytest.approx(300)
    assert s["input_mean"] == pytest.approx(111)   # fresh + cache writes + cache reads
    assert s["cost_sd"] == pytest.approx(math.sqrt(2))


# ── ratios and the headline ───────────────────────────────────────────────

def test_ratio_is_treatment_over_baseline_cost_per_success_with_an_interval_around_it():
    base = [_run(1.0), _run(1.2), _run(0.8)]
    treat = [_run(0.5), _run(0.6), _run(0.4)]
    point, lo, hi = cr.ratio_ci(base, treat, iters=500, seed=1)
    assert point == pytest.approx(0.5)
    assert lo <= point <= hi
    assert hi < 1.0  # every resample is cheaper


def test_ratio_is_undefined_when_the_baseline_never_succeeds():
    base = [_run(1.0, ok=False)] * 3
    treat = [_run(0.5)] * 3
    point, lo, hi = cr.ratio_ci(base, treat, iters=50, seed=1)
    assert point is None


def test_headline_is_the_geometric_mean_of_per_task_ratios():
    pairs = {
        "t1": ([_run(1.0)] * 3, [_run(0.5)] * 3),   # 0.5
        "t2": ([_run(1.0)] * 3, [_run(2.0)] * 3),   # 2.0
    }
    h = cr.headline(pairs, iters=200, seed=1)
    assert h["ratio"] == pytest.approx(1.0)        # sqrt(0.5 * 2.0)
    assert h["tasks"] == ["t1", "t2"]
    assert h["excluded"] == []


def test_headline_lists_tasks_it_could_not_compare():
    pairs = {
        "t1": ([_run(1.0)] * 3, [_run(0.5)] * 3),
        "recall": ([_run(1.0, ok=False)] * 3, [_run(0.2)] * 3),
    }
    h = cr.headline(pairs, iters=50, seed=1)
    assert h["tasks"] == ["t1"] and h["excluded"] == ["recall"]


# ── loading result files ──────────────────────────────────────────────────

def test_load_groups_runs_by_task_and_cell(tmp_path):
    f1 = tmp_path / "a.json"
    f1.write_text(json.dumps({"task": "t1", "tag": "", "model": "default",
                              "runs": [{"profile": "clean", **_run(1.0)}, {"profile": "marvin", **_run(2.0)}]}))
    f2 = tmp_path / "b.json"
    f2.write_text(json.dumps({"task": "t1", "tag": "caveman", "model": "default",
                              "runs": [{"profile": "marvin", **_run(0.5)}]}))
    cells = cr.load_cells([f1, f2])
    assert set(cells["t1"]) == {"clean", "marvin", "marvin+caveman"}
    assert len(cells["t1"]["marvin"]) == 1


def test_load_names_a_model_override_in_the_cell(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"task": "t1", "tag": "", "model": "claude-haiku-4-5-20251001",
                             "runs": [{"profile": "marvin", **_run(0.1)}]}))
    assert set(cr.load_cells([f])["t1"]) == {"marvin@haiku"}


# ── deterministic temp directories ────────────────────────────────────────

def test_fs_task_uses_deterministic_workdir_path(tmp_path, monkeypatch):
    """FS tasks get deterministic paths keyed on (task_id, profile, model, slug(prompt_prefix))."""
    monkeypatch.setattr(bench, "PROFILES", {"clean": tmp_path / "clean"})
    (tmp_path / "clean").mkdir()

    task = {
        "id": "task-001-fix",
        "type": "fs",
        "prompt": "fix the bug",
        "dir": tmp_path,
        "timeout": 30,
    }

    # Run 1: creates the deterministic path
    run1_cwd = None

    def capture_cwd_1(cmd, cwd=None, **kw):
        nonlocal run1_cwd
        run1_cwd = cwd
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", capture_cwd_1)
    bench.run_once(task, "clean", model=None, prompt_prefix="")

    # Run 2: same task, same profile → same path (deterministic)
    run2_cwd = None

    def capture_cwd_2(cmd, cwd=None, **kw):
        nonlocal run2_cwd
        run2_cwd = cwd
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", capture_cwd_2)
    bench.run_once(task, "clean", model=None, prompt_prefix="")

    assert run1_cwd == run2_cwd, "workdir path should be deterministic"
    assert "mb-" in str(run1_cwd), "workdir path should be under system temp"


def test_deterministic_workdir_is_emptied_not_deleted(tmp_path, monkeypatch):
    """Deterministic workdir is emptied at the start if it exists, not deleted."""
    monkeypatch.setattr(bench, "PROFILES", {"clean": tmp_path / "clean"})
    (tmp_path / "clean").mkdir()

    task = {
        "id": "task-x",
        "type": "fs",
        "prompt": "test",
        "dir": tmp_path,
        "timeout": 30,
    }

    captured_cwd = None
    call_count = [0]

    def fake_run(cmd, cwd=None, **kw):
        nonlocal captured_cwd
        captured_cwd = cwd
        call_count[0] += 1
        # Only create a file on the first run
        if call_count[0] == 1:
            Path(cwd).mkdir(parents=True, exist_ok=True)
            (Path(cwd) / "leftover.txt").write_text("should be removed")
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)

    # Run 1: creates the workdir with a file
    bench.run_once(task, "clean", model=None, prompt_prefix="")
    workdir = Path(captured_cwd)
    assert workdir.exists(), "workdir should exist after run"
    assert (workdir / "leftover.txt").exists(), "file should exist"

    # Run 2: same task → workdir is emptied before subprocess.run, file is gone
    bench.run_once(task, "clean", model=None, prompt_prefix="")
    assert workdir.exists(), "workdir should still exist (not deleted)"
    assert not (workdir / "leftover.txt").exists(), "old files should be removed by the cleanup code"


def test_workdir_path_differs_by_task_id(tmp_path, monkeypatch):
    """Different task IDs get different workdir paths."""
    monkeypatch.setattr(bench, "PROFILES", {"clean": tmp_path / "clean"})
    (tmp_path / "clean").mkdir()

    paths = []

    def capture_cwd(cmd, cwd=None, **kw):
        paths.append(cwd)
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", capture_cwd)

    task1 = {"id": "task-a", "type": "fs", "prompt": "test", "dir": tmp_path, "timeout": 30}
    task2 = {"id": "task-b", "type": "fs", "prompt": "test", "dir": tmp_path, "timeout": 30}

    bench.run_once(task1, "clean", model=None, prompt_prefix="")
    bench.run_once(task2, "clean", model=None, prompt_prefix="")

    assert paths[0] != paths[1], "different task IDs should have different workdir paths"


def test_workdir_path_differs_by_profile(tmp_path, monkeypatch):
    """Different profiles get different workdir paths."""
    monkeypatch.setattr(bench, "PROFILES", {
        "clean": tmp_path / "clean",
        "marvin": tmp_path / "marvin"
    })
    (tmp_path / "clean").mkdir()
    (tmp_path / "marvin").mkdir()

    paths = []

    def capture_cwd(cmd, cwd=None, **kw):
        paths.append(cwd)
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", capture_cwd)

    task = {"id": "task-x", "type": "fs", "prompt": "test", "dir": tmp_path, "timeout": 30}

    bench.run_once(task, "clean", model=None, prompt_prefix="")
    bench.run_once(task, "marvin", model=None, prompt_prefix="")

    assert paths[0] != paths[1], "different profiles should have different workdir paths"


def test_workdir_path_differs_by_model(tmp_path, monkeypatch):
    """Different models get different workdir paths."""
    monkeypatch.setattr(bench, "PROFILES", {"clean": tmp_path / "clean"})
    (tmp_path / "clean").mkdir()

    paths = []

    def capture_cwd(cmd, cwd=None, **kw):
        paths.append(cwd)
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", capture_cwd)

    task = {"id": "task-x", "type": "fs", "prompt": "test", "dir": tmp_path, "timeout": 30}

    bench.run_once(task, "clean", model=None, prompt_prefix="")
    bench.run_once(task, "clean", model="claude-haiku-4-5-20251001", prompt_prefix="")

    assert paths[0] != paths[1], "different models should have different workdir paths"


def test_workdir_path_differs_by_prompt_prefix(tmp_path, monkeypatch):
    """Different prompt prefixes get different workdir paths."""
    monkeypatch.setattr(bench, "PROFILES", {"clean": tmp_path / "clean"})
    (tmp_path / "clean").mkdir()

    paths = []

    def capture_cwd(cmd, cwd=None, **kw):
        paths.append(cwd)
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", capture_cwd)

    task = {"id": "task-x", "type": "fs", "prompt": "test", "dir": tmp_path, "timeout": 30}

    bench.run_once(task, "clean", model=None, prompt_prefix="")
    bench.run_once(task, "clean", model=None, prompt_prefix="Caveman mode. ")

    assert paths[0] != paths[1], "different prompt prefixes should have different workdir paths"


def test_workdir_persists_after_run_and_is_not_deleted(tmp_path, monkeypatch):
    """Deterministic workdir is not deleted at teardown; it persists for reuse."""
    monkeypatch.setattr(bench, "PROFILES", {"clean": tmp_path / "clean"})
    (tmp_path / "clean").mkdir()

    task = {"id": "task-x", "type": "fs", "prompt": "test", "dir": tmp_path, "timeout": 30}

    captured_cwd = None

    def fake_run(cmd, cwd=None, **kw):
        nonlocal captured_cwd
        captured_cwd = cwd
        Path(cwd).mkdir(parents=True, exist_ok=True)
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)

    bench.run_once(task, "clean", model=None, prompt_prefix="")
    workdir = Path(captured_cwd)

    assert workdir.exists(), "workdir should exist after run (not deleted)"


# ── secure workdir preparation (tests 8-16) ────────────────────────────────

def test_prepare_workdir_creates_new_dir_with_secure_perms(tmp_path):
    """_prepare_workdir creates new directories with mode 0700."""
    workdir = tmp_path / "new-workdir"
    assert not workdir.exists()

    bench._prepare_workdir(workdir)

    assert workdir.exists()
    assert workdir.is_dir()
    # Verify ownership (most important security property)
    import os
    st = workdir.stat()
    assert st.st_uid == os.getuid(), "workdir should be owned by current user"


def test_prepare_workdir_empties_existing_dir(tmp_path):
    """_prepare_workdir empties an existing directory without deleting it."""
    workdir = tmp_path / "existing-workdir"
    workdir.mkdir()
    (workdir / "file1.txt").write_text("content")
    (workdir / "subdir").mkdir()
    (workdir / "subdir" / "file2.txt").write_text("content")

    bench._prepare_workdir(workdir)

    assert workdir.exists(), "workdir should still exist"
    assert not list(workdir.iterdir()), "workdir should be empty"


def test_prepare_workdir_rejects_symlink_to_directory(tmp_path):
    """_prepare_workdir rejects a path that is a symlink, even to a directory."""
    workdir = tmp_path / "symlink-workdir"
    target = tmp_path / "target"
    target.mkdir()
    workdir.symlink_to(target)

    with pytest.raises(ValueError, match="symlink"):
        bench._prepare_workdir(workdir)


def test_prepare_workdir_rejects_broken_symlink(tmp_path):
    """_prepare_workdir rejects a broken symlink."""
    workdir = tmp_path / "broken-symlink"
    workdir.symlink_to("/nonexistent/path")

    with pytest.raises(ValueError, match="symlink"):
        bench._prepare_workdir(workdir)


def test_prepare_workdir_rejects_plain_file(tmp_path):
    """_prepare_workdir rejects a path that is a plain file."""
    workdir = tmp_path / "file-not-dir"
    workdir.write_text("I am a file")

    with pytest.raises(ValueError, match="plain file"):
        bench._prepare_workdir(workdir)


def test_prepare_workdir_removes_symlinks_inside_dir(tmp_path):
    """_prepare_workdir removes symlinks (both working and broken) inside the directory."""
    workdir = tmp_path / "workdir-with-symlinks"
    workdir.mkdir()

    # Create a file to link to
    target = tmp_path / "target.txt"
    target.write_text("target")

    # Create working and broken symlinks inside
    (workdir / "good-link").symlink_to(target)
    (workdir / "broken-link").symlink_to("/nonexistent")
    (workdir / "regular-file.txt").write_text("file")

    bench._prepare_workdir(workdir)

    assert workdir.exists()
    assert not list(workdir.iterdir()), "all items should be removed"


def test_prepare_workdir_fails_on_removal_error(tmp_path, monkeypatch):
    """_prepare_workdir fails loudly if it cannot remove something."""
    workdir = tmp_path / "protected-workdir"
    workdir.mkdir()
    (workdir / "file.txt").write_text("content")

    # Mock shutil.rmtree to fail on any call
    original_unlink = Path.unlink

    def failing_unlink(self, missing_ok=False):
        raise OSError("permission denied")

    # Patch the unlink method to fail
    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises(RuntimeError, match="failed to unlink"):
        bench._prepare_workdir(workdir)


def test_prepare_workdir_fails_on_leftover_items(tmp_path, monkeypatch):
    """_prepare_workdir fails loudly if items remain after cleanup."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    (workdir / "file.txt").write_text("content")

    # Mock iterdir to return items the second time, simulating a failure to empty
    original_iterdir = Path.iterdir
    call_count = [0]

    def mock_iterdir(self):
        call_count[0] += 1
        if call_count[0] == 2:  # After cleanup, return items
            return iter([(workdir / "phantom.txt")])
        return original_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", mock_iterdir)

    with pytest.raises(RuntimeError, match="not fully emptied"):
        bench._prepare_workdir(workdir)


def test_prepare_workdir_via_run_once_integration(tmp_path, monkeypatch):
    """Integration: run_once uses _prepare_workdir for fs tasks."""
    import os
    monkeypatch.setattr(bench, "PROFILES", {"clean": tmp_path / "clean"})
    (tmp_path / "clean").mkdir()

    task_dir = tmp_path / "task"
    task_dir.mkdir()
    (task_dir / "task.json").write_text(json.dumps(
        {"id": "task-x", "type": "fs", "prompt_file": "p.md"}
    ))
    (task_dir / "p.md").write_text("prompt")
    (task_dir / "files").mkdir()
    (task_dir / "files" / "input.txt").write_text("data")

    task = bench.load_task(task_dir)

    workdir_path = None

    def fake_run(cmd, cwd=None, **kw):
        nonlocal workdir_path
        workdir_path = cwd
        # Verify the workdir exists and is owned by current user
        st = Path(cwd).stat()
        assert st.st_uid == os.getuid(), "workdir should be owned by current user"
        assert Path(cwd).is_dir(), "workdir should be a directory"
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)

    bench.run_once(task, "clean", model=None, prompt_prefix="")

    # Verify the workdir is deterministic and was set up correctly
    assert workdir_path is not None
    workdir = Path(workdir_path)
    assert workdir.exists()
    assert (workdir / "input.txt").exists(), "task files should be copied"
