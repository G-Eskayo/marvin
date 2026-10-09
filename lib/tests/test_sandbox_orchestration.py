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
        class R:
            stdout = _json.dumps(next(responses))
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    plan = so._default_executor(tmp_path, "G-Eskayo/marvin#42", None)

    assert plan == "a real plan"
    events = ts.read_stages(42)
    costs = [e["cost_usd"] for e in events]
    assert costs == [0.0098, 0.0211]


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


def test_default_executor_planning_and_execution_use_dontask_mode(monkeypatch, tmp_path):
    # ADR 0030: non-interactive `-p` calls have no TTY, so an unlisted tool
    # hard-denies instead of prompting -- `dontAsk` makes that explicit
    # rather than relying on --allowedTools scoping alone.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "a plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)

    for cmd in calls:
        assert "--permission-mode" in cmd
        assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"


def test_default_executor_execution_step_scoped_to_build_and_test_tools(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "a plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)

    exec_cmd = calls[1]
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


def test_default_executor_tells_the_planner_its_headless_and_autonomous(monkeypatch, tmp_path):
    # G-Eskayo/marvin#21 hit this for real: without this, the planner
    # paused to ask for human confirmation nobody headless could answer.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "a plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    plan_prompt = calls[0][calls[0].index("-p") + 1]
    assert "autonomously" in plan_prompt.lower()
    assert "no human present" in plan_prompt.lower() or "no one" in plan_prompt.lower()


def test_default_executor_tells_the_executor_not_to_commit_push_or_open_a_pr(monkeypatch, tmp_path):
    # G-Eskayo/marvin#21 hit this for real too: the executor got stuck
    # asking for Bash permission to commit/push/open a PR itself, not
    # knowing raise_mr does that automatically after it returns.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "a plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    exec_prompt = calls[1][calls[1].index("-p") + 1]
    assert "do not" in exec_prompt.lower() or "do not commit" in exec_prompt.lower()
    assert "commit" in exec_prompt.lower()
    assert "pull request" in exec_prompt.lower() or " pr" in exec_prompt.lower()


# ── executor must not be able to write outside its worktree ─────────────────
# Found 2026-10-01 on #41: Edit/Write were allowlisted with no path scope, so
# the headless executor wrote a copy of lib/s2_client.py into the real
# ~/.agents checkout (to satisfy a Path.home()/.agents/lib import) as well as
# its worktree. Reproduced with a live probe (absolute-path write succeeded),
# then confirmed a deny rule blocks it while a cwd-relative write still works.

def _capture_executor_calls(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "a plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    return calls


def test_default_executor_execution_step_denies_writes_to_the_real_checkout(monkeypatch, tmp_path):
    exec_cmd = _capture_executor_calls(monkeypatch, tmp_path)[1]

    assert "--disallowedTools" in exec_cmd
    denied = exec_cmd[exec_cmd.index("--disallowedTools") + 1]
    assert "Write(~/.agents/**)" in denied
    assert "Edit(~/.agents/**)" in denied


def test_default_executor_deny_rule_does_not_match_the_worktree_directory():
    # Worktrees live in ~/.agents-pipeline-worktrees, a sibling of ~/.agents,
    # not under it -- the deny glob must not catch them (the glob needs a path
    # separator after ".agents"), or the executor couldn't write at all.
    assert so.WORKTREES_DIR_NAME == ".agents-pipeline-worktrees"
    assert not so.WORKTREES_DIR_NAME.startswith(".agents/")


def test_default_executor_planning_step_has_no_write_tools_to_begin_with(monkeypatch, tmp_path):
    plan_cmd = _capture_executor_calls(monkeypatch, tmp_path)[0]
    allowed = plan_cmd[plan_cmd.index("--allowedTools") + 1]
    assert "Write" not in allowed and "Edit" not in allowed


def test_default_executor_prompt_tells_it_to_stay_in_its_worktree_and_import_relatively(monkeypatch, tmp_path):
    exec_prompt = _capture_executor_calls(monkeypatch, tmp_path)[1][2]

    assert "current working directory" in exec_prompt
    assert "Path.home()" in exec_prompt and "__file__" in exec_prompt


# ── a re-dispatch must never destroy a previous attempt's unique work ───────
# _create_worktree force-removed any existing worktree AND branch, its docstring
# calling that "safe to discard" because a re-dispatch only happens once the
# ticket "never got far enough to push anything". False: found 2026-10-01 with
# five worktrees holding real unmerged work (uncommitted skills/, a partial Files
# tab, committed bench tests...) and #41's own first attempt lost the same way.
# Anything the old attempt produced must survive under refs/rescue/*.

def _rescue_refs(repo):
    out = subprocess.run(["git", "for-each-ref", "--format=%(refname)", "refs/rescue/"],
                         cwd=repo, capture_output=True, text=True, check=True).stdout
    return [r for r in out.splitlines() if r]


def _show(repo, ref, path):
    return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True).stdout


def test_redispatch_preserves_uncommitted_work_under_a_rescue_ref(git_repo):
    wt = so._create_worktree(git_repo, "G-Eskayo/marvin#7")
    (wt / "new_feature.py").write_text("print('half done')\n")       # untracked
    (wt / "README.md").write_text("edited by the executor\n")          # tracked, modified

    wt2 = so._create_worktree(git_repo, "G-Eskayo/marvin#7")            # re-dispatch

    refs = _rescue_refs(git_repo)
    assert len(refs) == 1 and "pipeline/g-eskayo/marvin#7" in refs[0]
    assert _show(git_repo, refs[0], "new_feature.py") == "print('half done')\n"
    assert _show(git_repo, refs[0], "README.md") == "edited by the executor\n"
    # ...and the fresh attempt still starts clean from origin/main
    assert not (wt2 / "new_feature.py").exists()
    assert (wt2 / "README.md").read_text() == "hello\n"


def test_redispatch_preserves_committed_but_unpushed_work(git_repo):
    wt = so._create_worktree(git_repo, "G-Eskayo/marvin#8")
    (wt / "impl.py").write_text("x = 1\n")
    subprocess.run(["git", "add", "."], cwd=wt, check=True)
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "Implement #8"],
                   cwd=wt, check=True)

    so._create_worktree(git_repo, "G-Eskayo/marvin#8")

    [ref] = _rescue_refs(git_repo)
    assert _show(git_repo, ref, "impl.py") == "x = 1\n"


def test_redispatch_of_an_untouched_worktree_leaves_no_rescue_noise(git_repo):
    so._create_worktree(git_repo, "G-Eskayo/marvin#9")
    so._create_worktree(git_repo, "G-Eskayo/marvin#9")
    assert _rescue_refs(git_repo) == []


def test_rescue_ref_is_pushed_to_origin_so_it_survives_the_machine(git_repo):
    wt = so._create_worktree(git_repo, "G-Eskayo/marvin#10")
    (wt / "work.py").write_text("y = 2\n")

    so._create_worktree(git_repo, "G-Eskayo/marvin#10")

    remote = subprocess.run(["git", "ls-remote", "origin", "refs/rescue/*"], cwd=git_repo,
                            capture_output=True, text=True).stdout
    assert "refs/rescue/" in remote


# ── worktree directory names must not contain '#' ───────────────────────────
# Worktrees were named pipeline-g-eskayo-marvin#NN. Vite/vitest treat '#' in a
# filesystem path as a URL fragment (it surfaced as ".../pipeline-g-eskayo-marvin%2332/
# dashboard/node_modules/..."), so vitest crashed in every pipeline worktree and
# silently contributed 0 to every ticket's measure -- found 2026-10-01 when
# measure() started failing loudly (and it explained #41's 544-vs-684 baseline).

def test_worktree_directory_name_has_no_hash_character(git_repo):
    wt = so._create_worktree(git_repo, "G-Eskayo/marvin#32")
    assert "#" not in str(wt)
    assert wt.name == "pipeline-g-eskayo-marvin-32"


def test_branch_name_keeps_the_issue_number_so_cleanup_sweep_still_finds_it(git_repo):
    wt = so._create_worktree(git_repo, "G-Eskayo/marvin#32")
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=wt,
                            capture_output=True, text=True).stdout.strip()
    assert branch == "pipeline/g-eskayo/marvin#32"


def test_a_legacy_hash_named_worktree_is_preserved_then_replaced(git_repo):
    # Worktrees created before the rename sit at the old '#' path on the same branch.
    legacy = so.WORKTREES_ROOT / "pipeline-g-eskayo-marvin#33"
    so.WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "worktree", "add", "-b", "pipeline/g-eskayo/marvin#33", str(legacy), "origin/main"],
                   cwd=git_repo, check=True, capture_output=True)
    (legacy / "unfinished.py").write_text("keep me\n")

    new = so._create_worktree(git_repo, "G-Eskayo/marvin#33")

    assert "#" not in str(new) and new.exists()
    assert not legacy.exists()
    [ref] = _rescue_refs(git_repo)
    assert _show(git_repo, ref, "unfinished.py") == "keep me\n"


def test_default_executor_tells_the_planner_to_read_the_ticket_comments(monkeypatch, tmp_path):
    # Denial feedback and earlier failure notes live in the ticket's comments, which a plain
    # `gh issue view` does not show. Without this a re-queued ticket repeats the same mistake.
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "G-Eskayo/marvin#9", None)
    plan_prompt = calls[0][calls[0].index("-p") + 1]
    assert "--comments" in plan_prompt
    assert "feedback" in plan_prompt.lower()


# ── per-project profiles ────────────────────────────────────────────────────

def _capture_claude(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        class R:
            stdout = "plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    return calls


PROFILE = {"repo": "G-Eskayo/proj", "env": {}, "executor": {"allowed_tools": ["Bash(swift test*)"], "notes": "Logic lives in the SwiftPM package."}}


def test_profile_executor_uses_the_profiles_tools_not_marvins_and_walls_off_the_real_clone(monkeypatch, tmp_path):
    calls = _capture_claude(monkeypatch)
    so._default_executor(tmp_path, "G-Eskayo/proj#9", None, profile=PROFILE, clone=Path("/Users/me/Developer/proj"))
    exec_cmd = calls[1][0]
    allowed = exec_cmd[exec_cmd.index("--allowedTools") + 1]
    denied = exec_cmd[exec_cmd.index("--disallowedTools") + 1]
    assert "Bash(swift test*)" in allowed and "pytest" not in allowed and "npm" not in allowed
    assert "Edit(/Users/me/Developer/proj/**)" in denied
    assert "~/.agents/**" not in denied  # marvin's rule, not this project's


def test_profile_executor_gives_both_calls_the_project_notes_and_drops_marvins_import_advice(monkeypatch, tmp_path):
    calls = _capture_claude(monkeypatch)
    so._default_executor(tmp_path, "G-Eskayo/proj#9", None, profile=PROFILE, clone=Path("/x"))
    plan_prompt = calls[0][0][calls[0][0].index("-p") + 1]
    exec_prompt = calls[1][0][calls[1][0].index("-p") + 1]
    assert "Logic lives in the SwiftPM package." in plan_prompt
    assert "Logic lives in the SwiftPM package." in exec_prompt
    assert "Path.home()" not in exec_prompt and "__file__" not in exec_prompt


def test_profile_executor_runs_the_model_in_the_projects_environment(monkeypatch, tmp_path):
    calls = _capture_claude(monkeypatch)
    so._default_executor(tmp_path, "G-Eskayo/proj#9", None, profile=PROFILE, clone=Path("/x"), env={"DEVELOPER_DIR": "/Applications/Xcode.app/Contents/Developer"})
    for cmd, kw in calls:
        assert kw["env"]["DEVELOPER_DIR"] == "/Applications/Xcode.app/Contents/Developer"


def test_worktree_branches_from_the_projects_base_branch_not_always_main(monkeypatch, tmp_path):
    cmds = []

    def fake_run(cmd, **kwargs):
        cmds.append(cmd)
        class R:
            stdout = "0"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    monkeypatch.setattr(so, "WORKTREES_ROOT", tmp_path / "wt")
    so._create_worktree(Path("/repo"), "G-Eskayo/proj#9", base_branch="trunk")
    flat = [" ".join(c) for c in cmds]
    assert any(c.startswith("git fetch origin trunk") for c in flat)
    assert any("worktree add" in c and c.endswith("origin/trunk") for c in flat)
    assert not any("origin/main" in c for c in flat)


def test_the_planner_is_given_an_issue_view_command_that_actually_works(monkeypatch, tmp_path):
    # `gh issue view owner/repo#17` is rejected by gh ("invalid issue format"); the working form is
    # `gh issue view 17 --repo owner/repo`. Do not make the model discover that from an error.
    calls = _capture_claude(monkeypatch)
    so._default_executor(tmp_path, "G-Eskayo/clarity-captions#17", None)
    prompt = calls[0][0][calls[0][0].index("-p") + 1]
    assert "gh issue view 17 --repo G-Eskayo/clarity-captions" in prompt
    assert "gh issue view 17 --repo G-Eskayo/clarity-captions --comments" in prompt
    assert "gh issue view G-Eskayo/clarity-captions#17" not in prompt


def test_a_ticket_ref_that_is_not_owner_repo_hash_number_is_passed_through_unchanged(monkeypatch, tmp_path):
    calls = _capture_claude(monkeypatch)
    so._default_executor(tmp_path, "TICKET-1", None)
    prompt = calls[0][0][calls[0][0].index("-p") + 1]
    assert "gh issue view TICKET-1" in prompt


def test_fetching_the_base_branch_retries_a_transient_failure(monkeypatch, tmp_path):
    import sandbox_orchestration as so
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        rc = 255 if len(calls) == 1 else 0
        return type("R", (), {"returncode": rc, "stdout": "", "stderr": "fatal: unable to access remote"})()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    monkeypatch.setattr(so.time, "sleep", lambda s: None)
    so._fetch_base(tmp_path, "main")
    assert len(calls) == 2


def test_a_persistent_fetch_failure_says_what_git_said(monkeypatch, tmp_path):
    import sandbox_orchestration as so
    monkeypatch.setattr(so.subprocess, "run", lambda cmd, **kw: type("R", (), {"returncode": 255, "stdout": "", "stderr": "fatal: index.lock exists"})())
    monkeypatch.setattr(so.time, "sleep", lambda s: None)
    import pytest
    with pytest.raises(RuntimeError, match="index.lock exists"):
        so._fetch_base(tmp_path, "main")


def test_the_planning_call_gets_longer_than_the_slowest_runs_that_were_seen_to_succeed():
    """Measured 2026-10-05 over 41 real planning calls: finished ones took 85-298s (many at 255-298s) and 8 hit the
    old 300s wall -- about 1 in 5 died for being slow, not for being wrong. The limit must clear the observed tail."""
    import sandbox_orchestration as so
    assert so.PLAN_TIMEOUT_S >= 600


def test_claude_is_resolved_even_when_the_inherited_path_lacks_it(monkeypatch, tmp_path):
    # 2026-10-06: a ticket run started from a shell whose PATH lacked ~/.local/bin (SSH from the laptop)
    # failed with "No such file or directory: 'claude'", and every re-dispatch inherited the same PATH until
    # the circuit breaker tripped. The call must resolve the binary itself, not trust the inherited PATH.
    import sandbox_orchestration as so
    import claude_bin
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(claude_bin.shutil, "which", lambda name, *a, **k: None)
    monkeypatch.setattr(claude_bin, "_candidates", lambda: (fake,))
    seen = {}
    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "ok", "total_cost_usd": 0}', stderr="")
    monkeypatch.setattr(so.subprocess, "run", fake_run)
    text, _cost = so._launch("utility-call", "hi", ticket_ref="T-1", cwd=tmp_path, model="haiku", allowed_tools="",
                             timeout=5, env={"PATH": "/usr/bin:/bin"})
    assert text == "ok"
    assert seen["cmd"][0] == str(fake)


def test_planner_and_marvin_executor_share_the_read_only_inspection_rules():
    """#277: headless agents were refused graphify (which CLAUDE.md tells them to run) and read-only gh/git."""
    import project_profile as pp
    plan = so._PLAN_ALLOWED_TOOLS.split(",")
    exec_ = so._EXEC_ALLOWED_TOOLS.split(",")
    for rule in pp.READ_ONLY_INSPECTION_TOOLS:
        assert rule in plan and rule in exec_, rule


def test_both_prompts_steer_away_from_refused_shell_habits(monkeypatch, tmp_path):
    """#277: 17% of headless refusals were ls/find/cat instead of Read/Glob/Grep (and Read on a directory
    after ls was refused), 8% were allowed commands prefixed with `cd <dir> &&`."""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "a plan"
            returncode = 0
        return R()

    monkeypatch.setattr(so.subprocess, "run", fake_run)
    so._default_executor(tmp_path, "TICKET-1", None)
    for call in calls[:2]:
        prompt = call[call.index("-p") + 1]
        assert "Glob" in prompt and "Grep" in prompt and "ls" in prompt
        assert "already" in prompt and "cd" in prompt


# ── the agent's working directory is checked, not just claimed (Gil, 2026-10-08) ──
# The prompt tells the agent where its shell is. That claim must be TRUE by construction: a deterministic
# preflight proves the path is this ticket's own worktree before any tokens are spent, and the prompt
# names the exact path the process is launched in (same variable), so the two can never drift apart.

REAL_PREFLIGHT = so._preflight_worktree


@pytest.fixture(autouse=True)
def _skip_preflight_for_fake_paths(monkeypatch, request):
    # Older tests pass a bare tmp_path with a faked subprocess.run; they test prompt/flag wiring, not git.
    if "real_preflight" not in request.keywords:
        monkeypatch.setattr(so, "_preflight_worktree", lambda path, ticket_ref: None)


def _git(*args, cwd):
    import subprocess as sp
    sp.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _real_worktree(tmp_path, monkeypatch, ticket_ref="G-Eskayo/marvin#999"):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init", cwd=repo)
    root = tmp_path / "worktrees"
    root.mkdir()
    monkeypatch.setattr(so, "WORKTREES_ROOT", root)
    branch = so._branch_for(ticket_ref)
    path = root / branch.replace("/", "-").replace("#", "-")
    _git("worktree", "add", "-q", "-b", branch, str(path), "main", cwd=repo)
    return repo, path


@pytest.mark.real_preflight
def test_preflight_accepts_this_tickets_own_worktree(tmp_path, monkeypatch):
    _, wt = _real_worktree(tmp_path, monkeypatch)
    REAL_PREFLIGHT(wt, "G-Eskayo/marvin#999")  # no exception


@pytest.mark.real_preflight
def test_preflight_refuses_a_folder_that_is_not_a_git_worktree(tmp_path, monkeypatch):
    monkeypatch.setattr(so, "WORKTREES_ROOT", tmp_path)
    plain = tmp_path / "pipeline-g-eskayo-marvin-999"
    plain.mkdir()
    with pytest.raises(RuntimeError, match="not a git worktree"):
        REAL_PREFLIGHT(plain, "G-Eskayo/marvin#999")


@pytest.mark.real_preflight
def test_preflight_refuses_the_real_clone(tmp_path, monkeypatch):
    repo, _ = _real_worktree(tmp_path, monkeypatch)
    with pytest.raises(RuntimeError, match="outside"):
        REAL_PREFLIGHT(repo, "G-Eskayo/marvin#999")


@pytest.mark.real_preflight
def test_preflight_refuses_another_tickets_worktree(tmp_path, monkeypatch):
    _, wt = _real_worktree(tmp_path, monkeypatch, ticket_ref="G-Eskayo/marvin#999")
    with pytest.raises(RuntimeError, match="branch"):
        REAL_PREFLIGHT(wt, "G-Eskayo/marvin#123")


@pytest.mark.real_preflight
def test_a_failed_preflight_spends_no_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(so, "WORKTREES_ROOT", tmp_path)
    launched = []
    monkeypatch.setattr(so, "_launch", lambda *a, **k: launched.append(a) or ("", 0.0))
    with pytest.raises(RuntimeError):
        so._default_executor(tmp_path / "missing", "G-Eskayo/marvin#999", None)
    assert launched == []


@pytest.mark.real_preflight
def test_the_prompt_names_the_exact_directory_the_agent_is_launched_in(tmp_path, monkeypatch):
    _, wt = _real_worktree(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(so, "_launch", lambda kind, prompt, **k: calls.append((prompt, k.get("cwd"))) or ("a plan", 0.0))
    so._default_executor(wt, "G-Eskayo/marvin#999", None)
    assert len(calls) == 2
    for prompt, cwd in calls:
        assert cwd == wt
        assert str(wt) in prompt


def test_the_planner_opens_its_plan_with_a_north_star_fit(monkeypatch, tmp_path):
    """marvin#276: the plan carries the fit, which is how the executor receives the north stars."""
    prompts = []
    monkeypatch.setattr(so, "_launch", lambda kind, prompt, **k: prompts.append((kind, prompt)) or ("a plan", 0.0))
    so._default_executor(tmp_path, "TICKET-1", None)
    kinds = dict(prompts)
    assert "## North-star fit" in kinds["ticket-planner"]
    assert "a plan" in kinds["ticket-executor"]



# ── ADR 0063 gate 2 (#336): verify needs a test change when code changed ──────

def _improving():
    calls = {"n": 0}

    def measure(wt):
        calls["n"] += 1
        return {"accuracy": _metric(0.8 if calls["n"] == 1 else 0.9)}   # baseline, then better
    return measure


def _writes(files):
    def executor(worktree_path, ticket_ref, feedback):
        for rel, text in files.items():
            p = worktree_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        return "wrote"
    return executor


def test_code_without_a_test_change_does_not_pass_verify_and_tells_the_agent_why(git_repo, metrics_dir):
    seen = []

    def executor(worktree_path, ticket_ref, feedback):
        seen.append(feedback)
        (worktree_path / "lib").mkdir(exist_ok=True)
        (worktree_path / "lib" / "feature.py").write_text("def f():\n    return 1\n")
        return "code only"

    result = so.execute_ticket("TICKET-1", "test-subsystem", measure=_improving(),
                               executor=executor, repo_path=git_repo, max_iterations=2)
    assert result["passing"] is False
    assert seen[1] and "How we'll try to break it" in str(seen[1])


def test_code_with_a_test_passes_verify(git_repo, metrics_dir):
    ex = _writes({"lib/feature.py": "def f():\n    return 1\n",
                  "lib/tests/test_feature.py": "def test_f():\n    assert True\n"})
    result = so.execute_ticket("TICKET-1", "test-subsystem", measure=_improving(),
                               executor=ex, repo_path=git_repo)
    assert result["passing"] is True


def test_docs_only_work_passes_verify(git_repo, metrics_dir):
    ex = _writes({"docs/notes.md": "# notes\n"})
    result = so.execute_ticket("TICKET-1", "test-subsystem", measure=_improving(),
                               executor=ex, repo_path=git_repo)
    assert result["passing"] is True
