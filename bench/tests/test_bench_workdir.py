"""Stable bench folders (PR #1125, decision bench-folders).

Under Claude Code 2.1.318 plain Claude Code's system prompt embeds an auto-memory path derived from the
working folder, so a fresh temp folder per run made it rewrite its whole prompt every run and flattered MARVIN.
A run now gets one stable folder per (task, cell), emptied between runs, like a person working in one repo.
    ~/.agents/venv/bin/python -m pytest bench/tests/test_bench_workdir.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH / "lib"))

import bench  # noqa: E402


def _fs_task(tmp_path: Path, tid: str = "task-x") -> dict:
    tdir = tmp_path / "tasks" / tid
    (tdir / "files").mkdir(parents=True)
    (tdir / "files" / "mod.py").write_text("x = 1\n")
    return {"id": tid, "type": "fs", "dir": tdir, "prompt": "p"}


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / "work"
    monkeypatch.setattr(bench, "WORK_ROOT", r)
    return r


def test_the_same_cell_gets_the_same_folder_every_run(tmp_path, root):
    task = _fs_task(tmp_path)
    a = bench.prepare_workdir(task, "clean", None, "")[0]
    b = bench.prepare_workdir(task, "clean", None, "")[0]
    assert a == b and a.parent == root.resolve()


def test_each_cell_gets_its_own_folder(tmp_path, root):
    task = _fs_task(tmp_path)
    dirs = {
        bench.prepare_workdir(task, "clean", None, "")[0],
        bench.prepare_workdir(task, "marvin", None, "")[0],
        bench.prepare_workdir(task, "marvin", "claude-haiku-4-5-20251001", "")[0],
        bench.prepare_workdir(task, "marvin", None, "Caveman mode. ")[0],
        bench.prepare_workdir(_fs_task(tmp_path, "task-y"), "clean", None, "")[0],
    }
    assert len(dirs) == 5


def test_a_run_starts_from_only_the_task_files(tmp_path, root):
    """Emptied between runs: whatever the last run left (edits, new files, caches) is gone."""
    task = _fs_task(tmp_path)
    wd = bench.prepare_workdir(task, "clean", None, "")[0]
    (wd / "mod.py").write_text("x = 2  # the last run's edit\n")
    (wd / "leftover.py").write_text("junk")
    (wd / "__pycache__").mkdir()
    (wd / "__pycache__" / "mod.pyc").write_bytes(b"\0")
    wd = bench.prepare_workdir(task, "clean", None, "")[0]
    assert sorted(p.name for p in wd.iterdir()) == ["mod.py"]
    assert (wd / "mod.py").read_text() == "x = 1\n"


def test_finish_empties_the_folder_but_keeps_the_path(tmp_path, root):
    task = _fs_task(tmp_path)
    wd = bench.prepare_workdir(task, "clean", None, "")[0]
    bench.finish_workdir(wd, "stable")
    assert wd.is_dir() and list(wd.iterdir()) == []


def test_fresh_mode_keeps_the_old_one_temp_folder_per_run(tmp_path, root):
    task = _fs_task(tmp_path)
    a = bench.prepare_workdir(task, "clean", None, "", mode="fresh")[0]
    b = bench.prepare_workdir(task, "clean", None, "", mode="fresh")[0]
    assert a != b and (a / "mod.py").exists()
    bench.finish_workdir(a, "fresh")
    assert not a.exists()


def test_a_hostile_task_id_cannot_escape_the_root(tmp_path, root):
    for tid in ("../../etc", "/abs/path", "a/../../b", "..", "x\0y"):
        task = {"id": tid, "type": "fs", "dir": tmp_path / "nowhere", "prompt": "p"}
        wd = bench.prepare_workdir(task, "../clean", "m/../../x", "")[0]
        assert wd.parent == root.resolve(), tid


def test_refuses_a_root_that_is_home_or_above_it(tmp_path, monkeypatch):
    """Emptying the folder must never be able to touch the home folder."""
    task = _fs_task(tmp_path)
    for bad in (Path.home(), Path.home().parent, Path("/")):
        monkeypatch.setattr(bench, "WORK_ROOT", bad)
        with pytest.raises(ValueError):
            bench.prepare_workdir(task, "clean", None, "")


def test_qa_tasks_in_a_fixed_folder_are_untouched(tmp_path, root):
    fixed = tmp_path / "fixed"
    fixed.mkdir()
    (fixed / "keep.txt").write_text("keep")
    task = {"id": "qa", "type": "qa", "cwd": str(fixed), "dir": tmp_path, "prompt": "p"}
    wd, cleanup = bench.prepare_workdir(task, "clean", None, "")
    assert wd == fixed and cleanup is False and (fixed / "keep.txt").exists()


def test_cwd_tmp_qa_tasks_also_get_a_stable_folder(tmp_path, root):
    task = {"id": "qa-tmp", "type": "qa", "cwd": "tmp", "dir": tmp_path, "prompt": "p"}
    a, cleanup = bench.prepare_workdir(task, "clean", None, "")
    b, _ = bench.prepare_workdir(task, "clean", None, "")
    assert a == b and cleanup is True


def test_the_cells_auto_memory_is_cleared_between_runs(tmp_path, root):
    """The folder is stable, so Claude Code's per-folder auto memory would carry one run's notes into the next."""
    task = _fs_task(tmp_path)
    config = tmp_path / "profile"
    wd = bench.prepare_workdir(task, "clean", None, "", config_dir=config)[0]
    mem = config / "projects" / bench.project_slug(wd) / "memory"
    mem.mkdir(parents=True)
    (mem / "MEMORY.md").write_text("- the answer is in mod.py")
    transcript = mem.parent / "session.jsonl"
    transcript.write_text("{}")
    bench.prepare_workdir(task, "clean", None, "", config_dir=config)
    assert not mem.exists()
    assert transcript.exists(), "only the memory folder goes; transcripts are evidence"


def test_project_slug_matches_claude_codes_folder_names():
    assert bench.project_slug(Path("/Users/gil/.agents")) == "-Users-gil--agents"
    assert bench.project_slug(Path("/private/var/folders/8t/T/mb-x")) == "-private-var-folders-8t-T-mb-x"


def test_run_once_uses_the_stable_folder_and_records_the_mode(tmp_path, root, monkeypatch):
    task = _fs_task(tmp_path)
    seen = []

    def fake_run(cmd, cwd=None, **kw):
        seen.append(Path(cwd))
        (Path(cwd) / "made.py").write_text("y = 1\n")
        import subprocess
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(bench.subprocess, "run", fake_run)
    monkeypatch.setattr(bench, "parse_stream", lambda out: {"result_text": "ok"})
    monkeypatch.setattr(bench, "score_correctness", lambda *a, **k: {"score": 1})
    monkeypatch.setattr(bench, "run_hidden_check", lambda *a, **k: None)
    r1 = bench.run_once(task, "clean")
    r2 = bench.run_once(task, "clean")
    assert seen[0] == seen[1]
    assert r1["workdir_mode"] == r2["workdir_mode"] == "stable"
    assert list(seen[0].iterdir()) == []


def test_workdir_mode_flag_defaults_to_stable(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["bench.py", "--help"])
    import argparse
    ap = bench.build_arg_parser()
    assert ap.parse_args(["t"]).workdir == "stable"
    assert ap.parse_args(["t", "--workdir", "fresh"]).workdir == "fresh"
    with pytest.raises(SystemExit):
        ap.parse_args(["t", "--workdir", "home"])
