"""Tests for build_type_measure.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_build_type_measure.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import build_type_measure as btm  # noqa: E402


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo_with_worktree(tmp_path):
    main_repo = tmp_path / "main-repo"
    main_repo.mkdir()
    _run(["git", "init", "-q"], cwd=main_repo)
    _run(["git", "config", "user.email", "test@test.com"], cwd=main_repo)
    _run(["git", "config", "user.name", "Test"], cwd=main_repo)
    (main_repo / "README.md").write_text("hello\n")
    _run(["git", "add", "."], cwd=main_repo)
    _run(["git", "commit", "-q", "-m", "init"], cwd=main_repo)
    _run(["git", "branch", "-M", "main"], cwd=main_repo)

    worktree = tmp_path / "worktree"
    _run(["git", "worktree", "add", "-b", "pipeline/ticket-1", str(worktree)], cwd=main_repo)
    return worktree


def _commit_change(worktree, relative_path, content):
    target = worktree / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _run(["git", "add", "."], cwd=worktree)
    _run(["git", "commit", "-q", "-m", "change"], cwd=worktree)


# ── test_command_for (real git diff, no test runner invoked) ───────────────

def test_command_for_picks_vitest_for_a_dashboard_change(repo_with_worktree):
    _commit_change(repo_with_worktree, "dashboard/src/App.jsx", "// change\n")
    command = btm.test_command_for(repo_with_worktree, parallel=[])
    assert "vitest" in " ".join(command)


def test_command_for_scopes_pytest_to_the_touched_top_level_directory(repo_with_worktree):
    _commit_change(repo_with_worktree, "lib/some_module.py", "# change\n")
    command = btm.test_command_for(repo_with_worktree, parallel=[])
    assert command == [btm.VENV_PYTHON, "-m", "pytest", "-q", "lib"]


def test_command_for_scopes_skills_to_two_path_components_not_all_of_skills(repo_with_worktree):
    # G-Eskayo/marvin#21 found this the hard way: scoping only to "skills"
    # would still pull in every other skill's tests, not only this one's.
    _commit_change(repo_with_worktree, "skills/paper-dive/scripts/paper_graph.py", "# change\n")
    command = btm.test_command_for(repo_with_worktree, parallel=[])
    assert command == [btm.VENV_PYTHON, "-m", "pytest", "-q", "skills/paper-dive"]


def test_command_for_scopes_to_multiple_roots_when_several_areas_touched(repo_with_worktree):
    _commit_change(repo_with_worktree, "lib/some_module.py", "# change\n")
    _commit_change(repo_with_worktree, "bench/some_bench_file.py", "# change\n")
    command = btm.test_command_for(repo_with_worktree, parallel=[])
    assert command == [btm.VENV_PYTHON, "-m", "pytest", "-q", "bench", "lib"]


def test_command_for_falls_back_to_whole_repo_when_nothing_changed(repo_with_worktree):
    command = btm.test_command_for(repo_with_worktree, parallel=[])
    assert command == [btm.VENV_PYTHON, "-m", "pytest", "-q"]


def test_command_for_falls_back_to_whole_repo_when_touched_paths_have_no_real_directory(repo_with_worktree):
    # e.g. a docs-only change under a path that doesn't exist as a real
    # code directory in the worktree -- no scoped target to run.
    _commit_change(repo_with_worktree, "CONTEXT.md", "docs change\n")
    command = btm.test_command_for(repo_with_worktree, parallel=[])
    assert command == [btm.VENV_PYTHON, "-m", "pytest", "-q"]


def test_command_for_picks_vitest_when_both_dashboard_and_backend_changed(repo_with_worktree):
    _commit_change(repo_with_worktree, "lib/some_module.py", "# change\n")
    _commit_change(repo_with_worktree, "dashboard/src/App.jsx", "// change\n")
    command = btm.test_command_for(repo_with_worktree, parallel=[])
    assert "vitest" in " ".join(command)


def test_command_for_runs_python_tests_in_parallel_by_default(repo_with_worktree, monkeypatch):
    """#995: run serially, `pytest -q lib` outgrew the 1200 s limit and every marvin build timed out (#995)."""
    monkeypatch.setattr(btm, "parallel_args", lambda: ["-n", "5"])
    _commit_change(repo_with_worktree, "lib/some_module.py", "# change\n")
    assert btm.test_command_for(repo_with_worktree) == [btm.VENV_PYTHON, "-m", "pytest", "-q", "-n", "5", "lib"]
    assert btm.test_command_for(repo_with_worktree, base_branch="main")[4:6] == ["-n", "5"]


def test_the_dashboard_command_is_unchanged_by_the_python_workers(repo_with_worktree, monkeypatch):
    monkeypatch.setattr(btm, "parallel_args", lambda: ["-n", "5"])
    _commit_change(repo_with_worktree, "dashboard/src/App.jsx", "// change\n")
    assert "-n" not in btm.test_command_for(repo_with_worktree)


def test_parallel_args_follow_the_gates_count_then_free_memory_and_never_go_serial_by_accident():
    assert btm.parallel_args({"MARVIN_TEST_WORKERS": "3"}, True) == ["-n", "3"]
    assert btm.parallel_args({}, True, workers=lambda: 4) == ["-n", "4"]
    for junk in ("0", "-1", "x", " 2"):
        assert btm.parallel_args({"MARVIN_TEST_WORKERS": junk}, True, workers=lambda: 2) == ["-n", "2"]

    def broken():
        raise OSError("no vm_stat")
    assert btm.parallel_args({}, True, workers=broken) == ["-n", "auto"]
    assert btm.parallel_args({"MARVIN_TEST_WORKERS": "3"}, False) == []


# ── measure() (injected capture_test_results via monkeypatch) ──────────────

def test_measure_returns_raw_passed_and_failed_counts(monkeypatch, tmp_path):
    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 8, "failed": 3, "total": 11,
    })
    result = btm.measure(tmp_path)
    assert result["tests_passed"] == {"value": 8, "higher_is_better": True}
    assert result["tests_failed"] == {"value": 3, "higher_is_better": False}


def test_measure_returns_zero_counts_when_the_runner_explicitly_says_no_tests_ran(monkeypatch, tmp_path):
    # A subsystem with genuinely no tests yet is a legitimate 0 -- distinct
    # from a crashed run (see the MeasureError tests below).
    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": None, "failed": None, "total": None,
        "output_tail": "no tests ran in 0.01s",
    })
    result = btm.measure(tmp_path)
    assert result["tests_passed"]["value"] == 0
    assert result["tests_failed"]["value"] == 0


def test_measure_a_baseline_and_a_current_run_produce_a_real_improvement(monkeypatch, tmp_path):
    # Exercises the actual acceptance criterion: baseline (failing/absent)
    # vs. current (passing) must differ, and metrics_registry.compare()
    # must call that "improved" using this module's shape unmodified.
    sys.path.insert(0, str(LIB))
    import metrics_registry as mr

    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": None, "failed": None, "total": None,
        "output_tail": "no tests ran in 0.01s",
    })
    baseline = btm.measure(tmp_path)

    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 5, "failed": 0, "total": 5,
    })
    current = btm.measure(tmp_path)

    comparison = mr.compare("test-subsystem", baseline, current)
    assert comparison["passing"] is True
    assert comparison["verdict"] == "improved"


def test_measure_detects_new_passing_tests_added_to_an_already_fully_passing_suite(monkeypatch, tmp_path):
    # The actual bug found live-firing G-Eskayo/marvin#21: a ticket that
    # adds new passing tests to a suite already at 100% (34/34 -> 37/37)
    # is invisible to a passing-fraction metric (1.0 -> 1.0, "unchanged")
    # even though real, correct work landed. Raw counts must catch this.
    sys.path.insert(0, str(LIB))
    import metrics_registry as mr

    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 34, "failed": 0, "total": 34,
    })
    baseline = btm.measure(tmp_path)

    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 37, "failed": 0, "total": 37,
    })
    current = btm.measure(tmp_path)

    comparison = mr.compare("test-subsystem", baseline, current)
    assert comparison["passing"] is True
    assert comparison["verdict"] == "improved"


def test_measure_a_new_failure_does_not_register_as_improved_even_if_more_pass_too(monkeypatch, tmp_path):
    sys.path.insert(0, str(LIB))
    import metrics_registry as mr

    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 34, "failed": 0, "total": 34,
    })
    baseline = btm.measure(tmp_path)

    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "pytest", "passed": 36, "failed": 1, "total": 37,
    })
    current = btm.measure(tmp_path)

    comparison = mr.compare("test-subsystem", baseline, current)
    assert comparison["passing"] is False
    assert comparison["verdict"] == "mixed"


# ── measure() scope consistency (found 2026-10-01 re-releasing parked tickets) ─
# measure() used test_command_for()'s diff-scoped command. The baseline has an
# empty diff -> whole suite (540 passed); after the executor commits a change
# under skills/research the same measure() ran `pytest -q skills/research` ->
# 0 tests, "regressed" in 1s. A dashboard ticket compared pytest (baseline) to
# vitest (current). Baseline and current must run the SAME commands.

def _record_commands(monkeypatch):
    seen = []

    def fake(wt, cmd):
        seen.append(list(cmd))
        return {"suite": "x", "passed": 1, "failed": 0, "total": 1}

    monkeypatch.setattr(btm, "capture_test_results", fake)
    monkeypatch.setattr(btm, "_ensure_dashboard_deps", lambda wt: None)
    return seen


def test_measure_runs_identical_commands_before_and_after_a_committed_change(monkeypatch, repo_with_worktree):
    seen = _record_commands(monkeypatch)
    btm.measure(repo_with_worktree)
    baseline_cmds = list(seen)
    seen.clear()

    _commit_change(repo_with_worktree, "skills/research/SKILL.md", "edited\n")
    btm.measure(repo_with_worktree)

    assert seen == baseline_cmds


def test_measure_never_scopes_pytest_to_the_touched_directory(monkeypatch, repo_with_worktree):
    seen = _record_commands(monkeypatch)
    _commit_change(repo_with_worktree, "skills/research/SKILL.md", "edited\n")
    (repo_with_worktree / "skills/research").mkdir(exist_ok=True)

    btm.measure(repo_with_worktree)

    pytest_cmds = [c for c in seen if "pytest" in c]
    assert len(pytest_cmds) == 1
    assert pytest_cmds[0][-2:] == ["pytest", "-q"]


def test_measure_includes_vitest_and_sums_counts_when_a_dashboard_exists(monkeypatch, tmp_path):
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "package.json").write_text("{}")
    monkeypatch.setattr(btm, "_ensure_dashboard_deps", lambda wt: None)

    def fake(wt, cmd):
        if any("vitest" in part for part in cmd):
            return {"suite": "vitest", "passed": 100, "failed": 2, "total": 102}
        return {"suite": "pytest", "passed": 540, "failed": 1, "total": 541}

    monkeypatch.setattr(btm, "capture_test_results", fake)
    result = btm.measure(tmp_path)

    assert result["tests_passed"]["value"] == 640
    assert result["tests_failed"]["value"] == 3


def test_measure_skips_vitest_and_dependency_install_when_there_is_no_dashboard(monkeypatch, tmp_path):
    installs = []
    monkeypatch.setattr(btm, "_ensure_dashboard_deps", lambda wt: installs.append(wt))
    cmds = []
    monkeypatch.setattr(btm, "capture_test_results",
                        lambda wt, cmd: cmds.append(cmd) or {"suite": "p", "passed": 3, "failed": 0, "total": 3})

    btm.measure(tmp_path)

    assert len(cmds) == 1 and installs == []


# ── per-suite visibility + loud failure (found 2026-10-01) ─────────────────
# #41's recorded baseline was 544 (pytest only) while a clean worktree measures
# 684 (544 + 140 vitest): a suite had silently contributed 0 and nothing in the
# data showed it. Each suite's counts are now recorded separately, and a suite
# that produced no summary because it crashed is an error, not a zero.

def _fake_suites(monkeypatch, pytest_result, vitest_result):
    def fake(wt, cmd):
        return vitest_result if any("vitest" in part for part in cmd) else pytest_result
    monkeypatch.setattr(btm, "capture_test_results", fake)
    monkeypatch.setattr(btm, "_ensure_dashboard_deps", lambda wt: None)


def _dashboard_repo(tmp_path):
    (tmp_path / "dashboard").mkdir()
    (tmp_path / "dashboard" / "package.json").write_text("{}")
    return tmp_path


def test_measure_records_each_suites_counts_separately(monkeypatch, tmp_path):
    _fake_suites(monkeypatch,
                 {"suite": "p", "passed": 540, "failed": 1, "total": 541},
                 {"suite": "v", "passed": 140, "failed": 2, "total": 142})
    result = btm.measure(_dashboard_repo(tmp_path))

    assert result["pytest_passed"]["value"] == 540
    assert result["pytest_failed"]["value"] == 1
    assert result["vitest_passed"]["value"] == 140
    assert result["vitest_failed"]["value"] == 2
    assert result["tests_passed"]["value"] == 680
    assert result["pytest_failed"]["higher_is_better"] is False


def test_measure_raises_when_a_suite_crashes_without_a_summary(monkeypatch, tmp_path):
    _fake_suites(monkeypatch,
                 {"suite": "p", "passed": 540, "failed": 0, "total": 540},
                 {"suite": "v", "passed": None, "failed": None, "total": None,
                  "output_tail": "sh: npx: command not found"})
    with pytest.raises(btm.MeasureError) as exc:
        btm.measure(_dashboard_repo(tmp_path))

    assert "vitest" in str(exc.value)
    assert "command not found" in str(exc.value)


def test_measure_raises_when_pytest_dies_with_an_environment_error(monkeypatch, tmp_path):
    monkeypatch.setattr(btm, "capture_test_results", lambda wt, cmd: {
        "suite": "p", "passed": None, "failed": None, "total": None,
        "output_tail": "OSError: [Errno 24] Too many open files",
    })
    with pytest.raises(btm.MeasureError) as exc:
        btm.measure(tmp_path)
    assert "Too many open files" in str(exc.value)


# ── PairedMeasure: affected tests, the same set before and after (marvin#1152) ─
# The pipeline's verify ran the whole Python suite (~5,700 tests, serially) for the baseline and again on every
# reading, and timed out at 1200 s on almost every marvin ticket (103 times on the Mini). The merge gate runs only the
# affected tests (MARVIN_BASE). The selection depends on the change, which doesn't exist when the baseline is taken,
# so PairedMeasure pins the base commit then, and on each reading runs ONE selection, computed from the change, on
# both the change and the base commit. Real git repos; only the pytest run itself is faked.

import metrics_registry as mr  # noqa: E402

RULES = ["lib/tests/test_instance.py", "lib/tests/test_instance_move.py"]


@pytest.fixture
def marvin_like(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["git", "init", "-q", "-b", "main"], cwd=repo)
    _run(["git", "config", "user.email", "t@example.invalid"], cwd=repo)
    _run(["git", "config", "user.name", "t"], cwd=repo)
    files = {
        "conftest.py": "",
        "README.md": "hi\n",
        "lib/foo.py": "X = 1\n",
        "lib/bar.py": "Y = 2\n",
        "lib/tests/test_instance.py": "def test_rule(): pass\n",
        "lib/tests/test_instance_move.py": "def test_rule(): pass\n",
        "lib/tests/test_foo.py": "import foo\n",
        "lib/tests/test_bar.py": "import bar\n",
        ".github/workflows/ci.yml": "on: push\n",
    }
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-q", "-m", "init"], cwd=repo)
    monkeypatch.setattr(btm, "parallel_args", lambda *a, **k: ["-n", "2"])
    monkeypatch.delenv("MARVIN_BASE", raising=False)
    monkeypatch.delenv("MARVIN_SELECTED_TESTS", raising=False)
    return repo


def _fake_pytest(monkeypatch):
    """Each run: which tree, which command, which selection (None = everything), and which selected files the tree
    really has. A test counts as one pass per test file the run would collect there."""
    runs = []

    def fake(wt, cmd, env=None, **kw):
        env = env if env is not None else {}
        listing = env.get("MARVIN_SELECTED_TESTS")
        selection = Path(listing).read_text().split() if listing else None
        wt = Path(wt)
        present = sorted(str(p.relative_to(wt)) for p in wt.rglob("test_*.py"))
        collected = present if selection is None else [p for p in selection if (wt / p).is_file()]
        runs.append({"wt": wt, "cmd": list(cmd), "selection": selection, "collected": collected, "env": dict(env),
                     "head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True,
                                            text=True).stdout.strip()})
        if not collected:
            return {"suite": "pytest", "passed": None, "failed": None, "total": None, "output_tail": "no tests ran in 0.1s"}
        return {"suite": "pytest", "passed": len(collected), "failed": 0, "total": len(collected)}

    monkeypatch.setattr(btm, "capture_test_results", fake)
    monkeypatch.setattr(btm, "_ensure_dashboard_deps", lambda wt: None)
    return runs


def _base_and_after(runs, after_wt):
    after = [r for r in runs if r["wt"] == Path(after_wt)]
    base = [r for r in runs if r["wt"] != Path(after_wt)]
    return base, after


def test_paired_no_python_change_still_runs_the_rules_on_both_sides(marvin_like, monkeypatch):
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)                       # the untouched worktree: pins the base, runs no Python tests
    assert runs == []
    base_sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=marvin_like, capture_output=True, text=True).stdout.strip()
    (marvin_like / "docs").mkdir()
    (marvin_like / "docs" / "note.md").write_text("words\n")   # uncommitted, untracked: the executor never commits

    current = pm(marvin_like)
    base, after = _base_and_after(runs, marvin_like)

    assert len(base) == 1 and len(after) == 1
    assert after[0]["selection"] == RULES and base[0]["selection"] == RULES
    assert base[0]["head"] == base_sha and not (base[0]["wt"] / "docs" / "note.md").exists()
    assert current["pytest_passed"]["value"] == 2
    assert pm.paired_baseline()["pytest_passed"]["value"] == 2


def test_paired_before_and_after_run_the_identical_command(marvin_like, monkeypatch):
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)
    (marvin_like / "lib" / "foo.py").write_text("X = 2\n")
    pm(marvin_like)
    base, after = _base_and_after(runs, marvin_like)
    strip = lambda c: [p for p in c if not p.startswith("--basetemp")]  # noqa: E731
    assert strip(base[0]["cmd"]) == strip(after[0]["cmd"])
    assert base[0]["selection"] == after[0]["selection"] == sorted(RULES + ["lib/tests/test_foo.py"])


@pytest.mark.parametrize("path, text", [("conftest.py", "# changed\n"), (".github/workflows/ci.yml", "on: pull_request\n")])
def test_paired_a_change_to_how_tests_run_runs_everything_on_both_sides(marvin_like, monkeypatch, path, text):
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)
    (marvin_like / path).write_text(text)
    pm(marvin_like)
    base, after = _base_and_after(runs, marvin_like)
    assert base[0]["selection"] is None and after[0]["selection"] is None
    assert "MARVIN_SELECTED_TESTS" not in base[0]["env"] and "MARVIN_SELECTED_TESTS" not in after[0]["env"]
    assert len(after[0]["collected"]) == 4


def test_paired_a_base_that_cannot_be_resolved_runs_everything_never_skips(tmp_path, monkeypatch):
    runs = _fake_pytest(monkeypatch)
    monkeypatch.setattr(btm, "parallel_args", lambda *a, **k: [])
    not_git = tmp_path / "plain"
    (not_git / "lib" / "tests").mkdir(parents=True)
    (not_git / "lib" / "tests" / "test_a.py").write_text("")
    pm = btm.PairedMeasure()
    baseline = pm(not_git)
    current = pm(not_git)
    assert [r["selection"] for r in runs] == [None, None]
    assert baseline["pytest_passed"]["value"] == 1 and current["pytest_passed"]["value"] == 1
    assert pm.paired_baseline() == baseline


def test_paired_when_the_change_cannot_be_read_both_sides_run_everything(marvin_like, monkeypatch):
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)

    def broken(*a, **k):
        raise subprocess.CalledProcessError(128, "git diff")
    monkeypatch.setattr(btm, "_changed_since", broken)
    pm(marvin_like)
    base, after = _base_and_after(runs, marvin_like)
    assert base[0]["selection"] is None and after[0]["selection"] is None


def test_paired_a_test_the_change_adds_runs_after_and_reads_as_an_improvement(marvin_like, monkeypatch):
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)
    (marvin_like / "lib" / "baz.py").write_text("Z = 3\n")
    (marvin_like / "lib" / "tests" / "test_baz.py").write_text("import baz\n")   # untracked, as the executor leaves it

    current = pm(marvin_like)
    base, after = _base_and_after(runs, marvin_like)
    assert "lib/tests/test_baz.py" in after[0]["selection"]
    assert base[0]["selection"] == after[0]["selection"]
    assert "lib/tests/test_baz.py" in after[0]["collected"] and "lib/tests/test_baz.py" not in base[0]["collected"]
    assert mr.compare("t", pm.paired_baseline(), current)["verdict"] == "improved"


def test_paired_a_test_the_change_deletes_runs_on_neither_side(marvin_like, monkeypatch):
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)
    (marvin_like / "lib" / "tests" / "test_bar.py").unlink()     # deleted, not staged
    (marvin_like / "lib" / "bar.py").write_text("Y = 3\n")

    current = pm(marvin_like)
    base, after = _base_and_after(runs, marvin_like)
    assert "lib/tests/test_bar.py" not in after[0]["selection"]
    assert base[0]["selection"] == after[0]["selection"]
    assert "lib/tests/test_bar.py" not in base[0]["collected"]
    assert mr.compare("t", pm.paired_baseline(), current)["verdict"] == "unchanged"


def test_paired_ignores_marvin_base_and_a_selection_already_in_the_environment(marvin_like, monkeypatch, tmp_path):
    stale = tmp_path / "stale-selection.txt"
    stale.write_text("lib/tests/test_instance.py\n")
    monkeypatch.setenv("MARVIN_BASE", "origin/does-not-exist")
    monkeypatch.setenv("MARVIN_SELECTED_TESTS", str(stale))
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)
    (marvin_like / "conftest.py").write_text("# changed\n")      # everything: a stale selection must not narrow it
    pm(marvin_like)
    for r in runs:
        assert "MARVIN_BASE" not in r["env"]
        assert "MARVIN_SELECTED_TESTS" not in r["env"]
        assert len(r["collected"]) == 4


def test_paired_the_base_reading_is_reused_while_the_selection_holds_and_redone_when_it_changes(marvin_like, monkeypatch):
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)
    (marvin_like / "lib" / "foo.py").write_text("X = 2\n")
    pm(marvin_like)
    pm(marvin_like)                                              # iteration 2, same change
    base, after = _base_and_after(runs, marvin_like)
    assert len(base) == 1 and len(after) == 2
    (marvin_like / "lib" / "bar.py").write_text("Y = 3\n")     # iteration 3 widens the change
    pm(marvin_like)
    base, after = _base_and_after(runs, marvin_like)
    assert len(base) == 2 and base[-1]["selection"] == after[-1]["selection"]
    assert "lib/tests/test_bar.py" in base[-1]["selection"]


def test_paired_leaves_no_base_worktree_or_selection_file_behind(marvin_like, monkeypatch):
    runs = _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)
    (marvin_like / "lib" / "foo.py").write_text("X = 2\n")
    pm(marvin_like)
    listed = subprocess.run(["git", "worktree", "list"], cwd=marvin_like, capture_output=True, text=True).stdout
    assert len(listed.strip().splitlines()) == 1
    for r in runs:
        assert not r["wt"].exists() or r["wt"] == marvin_like
        if r["env"].get("MARVIN_SELECTED_TESTS"):
            assert not Path(r["env"]["MARVIN_SELECTED_TESTS"]).exists()


def test_paired_a_base_tree_that_cannot_be_made_is_an_error_not_a_skip(marvin_like, monkeypatch):
    _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    pm(marvin_like)
    pm.base_sha = "0" * 40                                       # a commit that doesn't exist
    (marvin_like / "lib" / "foo.py").write_text("X = 2\n")
    with pytest.raises(btm.MeasureError):
        pm(marvin_like)


def test_paired_reports_the_after_reading_as_the_prs_test_results(marvin_like, monkeypatch):
    _fake_pytest(monkeypatch)
    pm = btm.PairedMeasure()
    assert pm.test_results() is None
    pm(marvin_like)
    (marvin_like / "lib" / "foo.py").write_text("X = 2\n")
    pm(marvin_like)
    tr = pm.test_results()
    assert tr["passed"] == 3 and tr["failed"] == 0 and tr["total"] == 3
    assert "3 test files" in tr["suite"]


def test_paired_vitest_runs_on_the_untouched_tree_and_after_the_change(marvin_like, monkeypatch):
    (marvin_like / "dashboard").mkdir()
    (marvin_like / "dashboard" / "package.json").write_text("{}")
    _run(["git", "add", "-A"], cwd=marvin_like)
    _run(["git", "commit", "-q", "-m", "dash"], cwd=marvin_like)
    seen = []

    def fake(wt, cmd, env=None, **kw):
        seen.append((Path(wt), "vitest" if any("vitest" in c for c in cmd) else "pytest"))
        if seen[-1][1] == "vitest":
            return {"suite": "vitest", "passed": 10 if len([s for s in seen if s[1] == "vitest"]) == 1 else 12,
                    "failed": 0, "total": 10}
        return {"suite": "pytest", "passed": 2, "failed": 0, "total": 2}

    monkeypatch.setattr(btm, "capture_test_results", fake)
    monkeypatch.setattr(btm, "_ensure_dashboard_deps", lambda wt: None)
    pm = btm.PairedMeasure()
    first = pm(marvin_like)
    assert seen == [(marvin_like, "vitest")] and first["vitest_passed"]["value"] == 10
    (marvin_like / "dashboard" / "x.js").write_text("1\n")
    current = pm(marvin_like)
    assert [s for s in seen if s[1] == "vitest"] == [(marvin_like, "vitest")] * 2
    assert pm.paired_baseline()["vitest_passed"]["value"] == 10 and current["vitest_passed"]["value"] == 12
    assert pm.paired_baseline()["tests_passed"]["value"] == 12 and current["tests_passed"]["value"] == 14
