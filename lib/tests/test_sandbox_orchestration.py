"""Tests for sandbox_orchestration.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_sandbox_orchestration.py -v
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import metrics_registry as mr  # noqa: E402
import sandbox_orchestration as so  # noqa: E402


@pytest.fixture
def metrics_dir(tmp_path, monkeypatch):
    d = tmp_path / "metrics"
    monkeypatch.setattr(mr, "METRICS_DIR", d)
    return d


@pytest.fixture
def git_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)

    worktrees_root = tmp_path / "worktrees-root"
    monkeypatch.setattr(so, "WORKTREES_ROOT", worktrees_root)
    return repo


def _metric(value, higher_is_better=True):
    return {"value": value, "higher_is_better": higher_is_better}


def _noop_executor(worktree_path, ticket_ref, feedback):
    return "did nothing"


# ── worktree isolation ──────────────────────────────────────────────────────

def test_creates_isolated_worktree_not_touching_live_repo(git_repo, metrics_dir):
    calls = []

    def measure(worktree_path):
        calls.append(worktree_path)
        return {"accuracy": _metric(0.9)}

    result = so.execute_ticket(
        "TICKET-1", "test-subsystem", measure=measure, executor=_noop_executor, repo_path=git_repo,
    )
    worktree_path = result["worktree_path"]
    assert worktree_path.exists()
    assert worktree_path != git_repo
    # live repo's working tree is untouched
    assert (git_repo / "README.md").read_text() == "hello\n"
    assert all(c == worktree_path for c in calls)


def test_worktree_created_outside_the_repo_tree(git_repo, metrics_dir):
    result = so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )
    assert git_repo not in result["worktree_path"].parents or result["worktree_path"].parent != git_repo


def test_worktree_left_in_place_for_downstream_mr_raiser(git_repo, metrics_dir):
    result = so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )
    assert result["worktree_path"].exists()


# ── state_setup hook ─────────────────────────────────────────────────────────

def test_state_setup_called_with_worktree_path(git_repo, metrics_dir):
    seen = []
    so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor,
        state_setup=lambda wt: seen.append(wt),
        repo_path=git_repo,
    )
    assert len(seen) == 1
    assert seen[0].exists()


def test_state_setup_optional_defaults_to_noop(git_repo, metrics_dir):
    # should not raise when state_setup is omitted -- a static measure means
    # baseline == current ("unchanged"), so check completion, not passing.
    result = so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )
    assert result["worktree_path"].exists()
    assert result["final_comparison"]["verdict"] == "unchanged"


# ── baseline measurement + recording ─────────────────────────────────────────

def test_baseline_measured_before_first_executor_call(git_repo, metrics_dir):
    order = []

    def measure(wt):
        order.append("measure")
        return {"accuracy": _metric(0.9)}

    def executor(wt, ticket_ref, feedback):
        order.append("executor")
        return "plan"

    so.execute_ticket("TICKET-1", "test-subsystem", measure=measure, executor=executor, repo_path=git_repo)
    assert order[0] == "measure"


def test_baseline_recorded_to_metrics_registry(git_repo, metrics_dir):
    so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )
    snapshots = mr._load_snapshots("test-subsystem")
    assert len(snapshots) >= 1
    assert snapshots[0]["metrics"]["accuracy"]["value"] == 0.9


# ── tune-and-compare loop ────────────────────────────────────────────────────

def test_stops_after_first_passing_comparison(git_repo, metrics_dir):
    executor_calls = []

    def measure(wt):
        # first call = baseline, second call = post-executor measurement
        return {"accuracy": _metric(0.7 if not executor_calls else 0.95)}

    def executor(wt, ticket_ref, feedback):
        executor_calls.append(feedback)
        return "plan"

    result = so.execute_ticket("TICKET-1", "test-subsystem", measure=measure, executor=executor, repo_path=git_repo)
    assert result["passing"] is True
    assert result["iterations"] == 1
    assert len(executor_calls) == 1


def test_iterates_and_passes_prior_feedback_into_next_executor_call(git_repo, metrics_dir):
    measurements = iter([
        {"accuracy": _metric(0.7)},   # baseline
        {"accuracy": _metric(0.7)},   # after iteration 1 (no improvement)
        {"accuracy": _metric(0.95)},  # after iteration 2 (improved)
    ])
    executor_calls = []

    def measure(wt):
        return next(measurements)

    def executor(wt, ticket_ref, feedback):
        executor_calls.append(feedback)
        return "plan"

    result = so.execute_ticket("TICKET-1", "test-subsystem", measure=measure, executor=executor, repo_path=git_repo, max_iterations=5)
    assert result["passing"] is True
    assert result["iterations"] == 2
    assert executor_calls[0] is None  # first attempt, no prior feedback
    assert executor_calls[1] is not None  # second attempt informed by iteration 1's comparison
    assert executor_calls[1]["verdict"] == "unchanged"


def test_stops_with_clear_report_after_max_iterations(git_repo, metrics_dir):
    def measure(wt):
        return {"accuracy": _metric(0.7)}  # never improves

    result = so.execute_ticket(
        "TICKET-1", "test-subsystem", measure=measure, executor=_noop_executor,
        repo_path=git_repo, max_iterations=3,
    )
    assert result["passing"] is False
    assert result["iterations"] == 3
    assert result["explanation"]
    assert "3" in result["explanation"] or "max" in result["explanation"].lower()


# ── default executor (mocked subprocess, no real API calls) ─────────────────

def test_default_executor_invokes_flagship_then_haiku(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "a plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    plan = so._default_executor(tmp_path, "TICKET-1", None)

    assert len(calls) == 2
    assert so.FLAGSHIP_MODEL in calls[0]
    assert so.HAIKU_MODEL in calls[1]
    assert plan == "a plan"


def test_default_executor_planning_step_scoped_to_readonly_tools(monkeypatch, tmp_path):
    # Found via two real live-fire smoke tests: (1) without any permission
    # scoping, the planning step's `gh issue view` (a Bash call) sits blocked
    # waiting on approval that can never come headlessly; (2) `--permission-
    # mode plan` unblocks reads but writes the actual plan to a separate file
    # for interactive ExitPlanMode hand-off, which headless mode can never
    # complete -- stdout ends up as meta-commentary, not the plan. Precise
    # --allowedTools scoping avoids both: real read access, clean stdout.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "a plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)

    plan_cmd = calls[0]
    assert "--allowedTools" in plan_cmd
    allowed = plan_cmd[plan_cmd.index("--allowedTools") + 1]
    assert "gh issue view" in allowed
    assert "Edit" not in allowed
    assert "Write" not in allowed


def test_default_executor_includes_feedback_in_planning_prompt(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "revised plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    feedback = {"verdict": "regressed", "metrics": {}}
    so._default_executor(tmp_path, "TICKET-1", feedback)
    plan_prompt = calls[0][calls[0].index("-p") + 1]
    assert "regressed" in plan_prompt
