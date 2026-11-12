"""Tests for the cost-validation pieces of the bench (marvin#645):
hidden task checks in bench.py, the model recorded by score.parse_stream, and the
cost-per-successful-task report in cost_report.py.
    ~/.agents/venv/bin/python -m pytest bench/tests/test_cost_validation.py -v
"""
from __future__ import annotations

import json
import math
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

def test_qa_task_with_tmp_cwd_runs_in_a_reused_folder_outside_home(tmp_path, monkeypatch):
    """cwd = home makes Claude Code load ~/.claude/CLAUDE.md as project instructions, even for clean."""
    seen = {}

    def fake_run(cmd, cwd=None, **kw):
        seen["cwd"], seen["prompt"] = Path(cwd), cmd[2]
        seen["empty"] = not any(Path(cwd).iterdir())
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)
    task = {"id": "t", "type": "qa", "cwd": "tmp", "prompt": "Q", "dir": tmp_path}
    run = bench.run_once(task, "clean", prompt_prefix="Caveman mode. ")
    assert seen["empty"] and Path.home() not in seen["cwd"].resolve().parents
    assert seen["cwd"].exists()          # reused folder, not deleted
    assert seen["prompt"] == "Caveman mode. Q"
    assert "check" not in run


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


# ── workdir reuse ────────────────────────────────────────────────────────────

def test_get_workdir_returns_deterministic_path():
    """_get_workdir returns the same path for the same (task_id, profile, model)."""
    w1 = bench._get_workdir("task-x", "clean", None)
    w2 = bench._get_workdir("task-x", "clean", None)
    assert w1 == w2


def test_get_workdir_creates_directory_if_missing(tmp_path, monkeypatch):
    """_get_workdir creates the directory if it doesn't exist."""
    monkeypatch.setattr(bench, "ROOT", tmp_path)
    workdir = bench._get_workdir("t1", "marvin", "claude-haiku-4-5-20251001")
    assert workdir.exists()
    assert workdir.is_dir()


def test_get_workdir_keys_by_task_profile_and_model():
    """_get_workdir produces different paths for different (task, profile, model) tuples."""
    w1 = bench._get_workdir("t1", "clean", None)
    w2 = bench._get_workdir("t1", "marvin", None)
    w3 = bench._get_workdir("t1", "clean", "claude-haiku-4-5-20251001")
    assert w1 != w2
    assert w1 != w3
    assert w2 != w3


def test_workdir_is_emptied_at_start_not_deleted_after(tmp_path, monkeypatch):
    """Workdir is emptied before each run, kept after (not deleted)."""
    monkeypatch.setattr(bench, "ROOT", tmp_path)

    call_count = [0]

    def fake_run(cmd, cwd=None, **kw):
        call_count[0] += 1
        workdir = Path(cwd)
        # On the second call, check that the directory was emptied before we run
        if call_count[0] == 2:
            # The directory should exist but be empty (previous files cleaned)
            assert workdir.exists()
            assert list(workdir.iterdir()) == []
        # Create a file during the "run"
        workdir.joinpath("output.txt").write_text("result")
        return bench.subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bench.subprocess, "run", fake_run)

    task = {"id": "t1", "type": "fs", "prompt": "Q", "dir": tmp_path, "timeout": 600}
    # First run
    bench.run_once(task, "clean", prompt_prefix="")

    # Second run should empty the directory at the start
    # (fake_run will verify this by checking for empty directory on call_count == 2)
    bench.run_once(task, "clean", prompt_prefix="")
