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
    # A bare "origin" the repo actually pushes to and fetches from, not
    # only a local-only checkout -- _create_worktree branches from
    # origin/main specifically (G-Eskayo/marvin#95), so the fixture needs
    # a real remote for that ref to resolve, matching how ~/.agents
    # actually works rather than a simplified local-only stand-in.
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=repo, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=repo, check=True)

    worktrees_root = tmp_path / "worktrees-root"
    monkeypatch.setattr(so, "WORKTREES_ROOT", worktrees_root)
    return repo


def _metric(value, higher_is_better=True):
    return {"value": value, "higher_is_better": higher_is_better}


def _noop_executor(worktree_path, ticket_ref, feedback):
    return "did nothing"


def _make_fake_run_with_design_doc(tmp_path, ticket_ref="TICKET-1", plan_text="a plan"):
    """Returns a fake_run function that also writes a stub design doc at the expected path."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # Write stub design doc on planning call (first call with "--model")
        if "--model" in cmd and so.FLAGSHIP_MODEL in cmd:
            design_doc = so._design_doc_path(tmp_path, ticket_ref)
            design_doc.parent.mkdir(parents=True, exist_ok=True)
            design_doc.write_text(plan_text)
        class R:
            stdout = plan_text
            returncode = 0
        return R()

    fake_run.calls = calls
    return fake_run


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


def test_worktree_branches_from_origin_main_not_repo_paths_current_checkout(git_repo, metrics_dir):
    # G-Eskayo/marvin#95: repo_path is the same shared checkout an
    # interactive session might be using -- if it's sitting on some other
    # branch (mid-edit, stale) when a ticket dispatches, the new worktree
    # must still branch from origin/main, not whatever repo_path happens
    # to be checked out to right now.
    subprocess.run(["git", "checkout", "-q", "-b", "someone-elses-work-in-progress"], cwd=git_repo, check=True)
    (git_repo / "README.md").write_text("an interactive session's uncommitted edit\n")

    result = so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )

    assert (result["worktree_path"] / "README.md").read_text() == "hello\n"
    # repo_path's own working tree (and its in-progress branch) are untouched
    assert (git_repo / "README.md").read_text() == "an interactive session's uncommitted edit\n"
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=git_repo, check=True, capture_output=True, text=True,
    ).stdout.strip()
    assert branch == "someone-elses-work-in-progress"


def test_redispatch_succeeds_when_the_ticket_branch_already_exists_locally(git_repo, metrics_dir):
    # A real re-dispatch of ticket #21 hit this: `git worktree remove`
    # (used to clean up a finished attempt) frees the directory but
    # leaves the branch behind, and `git worktree add -b` refuses to
    # recreate a branch that already exists -- the second attempt must
    # still succeed, starting fresh from origin/main.
    first = so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )
    subprocess.run(["git", "worktree", "remove", "--force", str(first["worktree_path"])], cwd=git_repo, check=True)

    second = so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )
    assert second["worktree_path"].exists()
    assert (second["worktree_path"] / "README.md").read_text() == "hello\n"


def test_redispatch_succeeds_when_a_stale_worktree_is_still_registered(git_repo, metrics_dir):
    # G-Eskayo/marvin#20 hit this live: a worktree from an earlier attempt
    # was never removed at all (not even via `git worktree remove`), so
    # `git branch -D` alone can't free the branch -- git refuses to delete
    # a branch checked out in an existing worktree -- and the subsequent
    # `git worktree add -b` then fails too, because the branch still
    # exists. Redispatch must still succeed by clearing the stale worktree
    # itself, not only the branch.
    first = so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )
    assert first["worktree_path"].exists()  # left in place, untouched

    second = so.execute_ticket(
        "TICKET-1", "test-subsystem",
        measure=lambda wt: {"accuracy": _metric(0.9)},
        executor=_noop_executor, repo_path=git_repo,
    )
    assert second["worktree_path"].exists()
    assert (second["worktree_path"] / "README.md").read_text() == "hello\n"


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

def test_default_executor_records_per_call_cost_against_the_ticket(monkeypatch, tmp_path):
    # Gil's 2026-10-01 ask: usage visibility alongside Health/Metrics.
    # claude -p's own --output-format json reports total_cost_usd; this
    # captures it per call rather than only ever having had the raw plan
    # text to work with.
    import json as _json
    import ticket_stages as ts

    stages_dir = tmp_path / "stages"
    monkeypatch.setattr(ts, "STAGES_DIR", stages_dir)
    monkeypatch.setattr(ts.machine_profile, "registry_id", lambda: "mac-mini-1")

    responses = iter([
        {"result": "a real plan", "total_cost_usd": 0.0098},
        {"result": "", "total_cost_usd": 0.0211},
    ])

    def fake_run(cmd, **kwargs):
        resp = next(responses)
        # Write stub design doc on planning call
        if "--model" in cmd and so.FLAGSHIP_MODEL in cmd:
            design_doc = so._design_doc_path(tmp_path, "G-Eskayo/marvin#42")
            design_doc.parent.mkdir(parents=True, exist_ok=True)
            design_doc.write_text(resp["result"])
        class R:
            stdout = _json.dumps(resp)
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    plan = so._default_executor(tmp_path, "G-Eskayo/marvin#42", None)

    assert plan == "a real plan"
    events = ts.read_stages(42)
    costs = [e["cost_usd"] for e in events]
    assert costs == [0.0098, 0.0211]


def test_default_executor_invokes_flagship_then_haiku(monkeypatch, tmp_path):
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "a plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    plan = so._default_executor(tmp_path, "TICKET-1", None)

    assert len(fake_run.calls) == 2
    assert so.FLAGSHIP_MODEL in fake_run.calls[0]
    assert so.HAIKU_MODEL in fake_run.calls[1]
    assert plan == "a plan"


def test_default_executor_planning_step_allows_file_writes_for_design_doc(monkeypatch, tmp_path):
    # Planning now writes a design doc to disk; allowlist must include
    # Write/Edit to enable that, while still excluding git commit/push.
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "stub plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)

    plan_cmd = fake_run.calls[0]
    assert "--allowedTools" in plan_cmd
    allowed = plan_cmd[plan_cmd.index("--allowedTools") + 1]
    assert "gh issue view" in allowed
    assert "Write" in allowed
    assert "Edit" in allowed
    # Broad Bash is still excluded -- only the specific allowlisted invocations work
    assert "git commit" not in allowed


def test_default_executor_planning_and_execution_use_dontask_mode(monkeypatch, tmp_path):
    # ADR 0030: non-interactive `-p` calls have no TTY, so an unlisted tool
    # hard-denies instead of prompting -- `dontAsk` makes that explicit
    # rather than relying on --allowedTools scoping alone.
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "a plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)

    for cmd in fake_run.calls:
        assert "--permission-mode" in cmd
        assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"


def test_default_executor_execution_step_scoped_to_build_and_test_tools(monkeypatch, tmp_path):
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "a plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)

    exec_cmd = fake_run.calls[1]
    assert "--allowedTools" in exec_cmd
    allowed = exec_cmd[exec_cmd.index("--allowedTools") + 1]
    assert "Edit" in allowed and "Write" in allowed
    assert "pytest" in allowed
    assert "npm test" in allowed
    # git commit/push and `gh pr create` deliberately absent -- those run as
    # plain subprocess calls from mr_raiser.py, not from inside this session.
    assert "git commit" not in allowed
    assert "gh pr create" not in allowed


def test_default_executor_includes_feedback_in_planning_prompt(monkeypatch, tmp_path):
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "revised plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    feedback = {"verdict": "regressed", "metrics": {}}
    so._default_executor(tmp_path, "TICKET-1", feedback)
    plan_prompt = fake_run.calls[0][fake_run.calls[0].index("-p") + 1]
    assert "regressed" in plan_prompt


def test_default_executor_tells_the_planner_its_headless_and_autonomous(monkeypatch, tmp_path):
    # G-Eskayo/marvin#21 hit this for real: without this, the planner
    # paused to ask for human confirmation nobody headless could answer.
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "a plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    plan_prompt = fake_run.calls[0][fake_run.calls[0].index("-p") + 1]
    assert "autonomously" in plan_prompt.lower()
    assert "no human present" in plan_prompt.lower() or "no one" in plan_prompt.lower()


def test_default_executor_tells_the_executor_not_to_commit_push_or_open_a_pr(monkeypatch, tmp_path):
    # G-Eskayo/marvin#21 hit this for real too: the executor got stuck
    # asking for Bash permission to commit/push/open a PR itself, not
    # knowing raise_mr does that automatically after it returns.
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "a plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    exec_prompt = fake_run.calls[1][fake_run.calls[1].index("-p") + 1]
    assert "do not" in exec_prompt.lower() or "do not commit" in exec_prompt.lower()
    assert "commit" in exec_prompt.lower()
    assert "pull request" in exec_prompt.lower() or " pr" in exec_prompt.lower()


def test_default_executor_planning_prompt_instructs_reading_current_file_state(monkeypatch, tmp_path):
    # AC1: planner must read current state of files before planning, not just
    # have the tools available but never be told to use them.
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    plan_prompt = fake_run.calls[0][fake_run.calls[0].index("-p") + 1]
    assert "read" in plan_prompt.lower() and "current state" in plan_prompt.lower()
    assert "Read" in plan_prompt or "Grep" in plan_prompt or "Glob" in plan_prompt


def test_default_executor_planning_prompt_specifies_design_doc_path(monkeypatch, tmp_path):
    # AC2: planning prompt must tell model the exact path to write the design doc to.
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    plan_prompt = fake_run.calls[0][fake_run.calls[0].index("-p") + 1]
    expected_path = str(so._design_doc_path(tmp_path, "TICKET-1"))
    assert expected_path in plan_prompt


def test_default_executor_planning_prompt_lists_acceptance_criteria(monkeypatch, tmp_path):
    # Planning prompt must explicitly address every acceptance criterion.
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    plan_prompt = fake_run.calls[0][fake_run.calls[0].index("-p") + 1]
    assert "acceptance criterion" in plan_prompt.lower()


def test_default_executor_returns_design_doc_file_contents_not_stdout(monkeypatch, tmp_path):
    # AC2: returned plan must be the file contents, not the raw stdout from
    # the planning call. This matters because the exec call needs the actual
    # design doc text, not an empty string or side-effect marker.
    doc_content = "# Design Doc\nPlan line 1\nPlan line 2\n"
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", doc_content)
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    plan = so._default_executor(tmp_path, "TICKET-1", None)
    assert plan == doc_content


def test_default_executor_raises_when_design_doc_not_written(monkeypatch, tmp_path):
    # If the planning call doesn't write the doc to disk, it's a failure at
    # the planning boundary, not a logic error -- should raise clearly.
    def fake_run_no_write(cmd, **kwargs):
        # Never write the design doc
        class R:
            stdout = "some response"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run_no_write)
    with pytest.raises(RuntimeError) as exc_info:
        so._default_executor(tmp_path, "TICKET-1", None)
    assert "design doc" in str(exc_info.value).lower()
    assert "not write" in str(exc_info.value).lower()


def test_default_executor_retry_prompt_references_existing_doc(monkeypatch, tmp_path):
    # AC4: on retry, prompt must tell model the doc already exists and to
    # read it first before revising, to address why the comparison came back
    # as unfavorable -- not just cosmetically rewrite it.
    fake_run = _make_fake_run_with_design_doc(tmp_path, "TICKET-1", "revised plan")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    feedback = {"verdict": "regressed", "metrics": {}}
    so._default_executor(tmp_path, "TICKET-1", feedback)
    plan_prompt = fake_run.calls[0][fake_run.calls[0].index("-p") + 1]
    # Prompt must reference the path and mention reading it
    assert str(so._design_doc_path(tmp_path, "TICKET-1")) in plan_prompt
    assert "read" in plan_prompt.lower() and ("prior attempt" in plan_prompt.lower() or "already exists" in plan_prompt.lower())
    # Must reference the specific verdict to address
    assert "regressed" in plan_prompt
