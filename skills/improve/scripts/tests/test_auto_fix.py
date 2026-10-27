"""auto_fix.py, gated (Gil, 2026-10-26): fixes land in a worktree on auto-fix/<date>, the tests run there before and
after, and ONE PR a day goes to the normal merge gate. The shared checkout is never edited. Run via:
    ~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_auto_fix.py -n 2

Real temp git repos (a bare origin plus a "shared" clone standing in for ~/.agents) and real pytest runs inside the
worktree. Only the model (the fixer) and GitHub (gh) are faked: the fixer is a function that edits files the way a
model would, and gh records what it was asked. Temp HOME (repo conftest) and temp paths; never the real ~/.claude.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import auto_fix as af  # noqa: E402
import sandbox_orchestration as so  # noqa: E402

TODAY = "2026-10-26"
BRANCH = f"auto-fix/{TODAY}"

WIDGET = '''def total(data):
    # just add them up
    result = 0
    for x in data:
        result = result + x
    return result
'''

WIDGET_TEST = '''import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import widget


def test_total():
    assert widget.total([1, 2, 3]) == 6
'''

QUEUE = """# Improvement Queue

---
## 2026-07-01 — marvin

- **[NAMING]** Generic parameter name `data` in `total()` at line 1. (`lib/widget.py`)
- **[VERBOSITY]** Filler word `just` in comment at line 2: `just add them up` (`lib/widget.py`)
- **[KISS]** Function 'total' at line 1 is 6 lines long. (`lib/widget.py`)

*3 item(s). Run `qa_scan.py <project> --dry-run` for the full list.*
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def git_ok(cwd: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True).returncode == 0


class FakeGh:
    """Stands in for ~/.agents/bin/gh. `prs` maps branch or number -> state; `create` opens PR 901."""
    def __init__(self):
        self.calls: list[list[str]] = []
        self.prs: dict[str, dict] = {}
        self.fail = False
        self.bodies: list[str] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        if self.fail:
            return subprocess.CompletedProcess(args, 1, "", "API rate limit exceeded")
        if args[:2] == ["pr", "list"]:
            head = args[args.index("--head") + 1]
            pr = self.prs.get(head)
            return subprocess.CompletedProcess(args, 0, json.dumps([pr] if pr else []), "")
        if args[:2] == ["pr", "view"]:
            pr = self.prs.get(args[2])
            if not pr:
                return subprocess.CompletedProcess(args, 1, "", "no pull requests found")
            return subprocess.CompletedProcess(args, 0, json.dumps(pr), "")
        if args[:2] == ["pr", "create"]:
            assert "--body" not in args, "PR body must go through --body-file"
            self.bodies.append(Path(args[args.index("--body-file") + 1]).read_text())
            head = args[args.index("--head") + 1]
            self.prs[head] = {"number": 901, "state": "OPEN"}
            self.prs["901"] = {"number": 901, "state": "OPEN"}
            return subprocess.CompletedProcess(args, 0, "https://github.com/G-Eskayo/marvin/pull/901\n", "")
        return subprocess.CompletedProcess(args, 1, "", f"unexpected gh call {args}")

    def created(self) -> int:
        return sum(1 for c in self.calls if c[:2] == ["pr", "create"])


def good_fixer(prompt: str, cwd: Path) -> None:
    w = cwd / "lib" / "widget.py"
    w.write_text(w.read_text().replace("data", "numbers").replace("# just add", "# add"))


@pytest.fixture
def env(tmp_path, monkeypatch):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    shared = tmp_path / "agents"
    shared.mkdir()
    git(shared, "init", "-q", "-b", "main")
    git(shared, "config", "user.email", "t@t")
    git(shared, "config", "user.name", "T")
    (shared / "lib" / "tests").mkdir(parents=True)
    (shared / "lib" / "widget.py").write_text(WIDGET)
    (shared / "lib" / "tests" / "test_widget.py").write_text(WIDGET_TEST)
    (shared / "tools").mkdir()
    (shared / "tools" / "orphan.py").write_text("def f(data):\n    return data\n")
    git(shared, "add", "-A")
    git(shared, "commit", "-qm", "seed")
    git(shared, "remote", "add", "origin", str(origin))
    git(shared, "push", "-q", "origin", "main")

    queue = tmp_path / "improvement-queue.md"
    queue.write_text(QUEUE)
    log = tmp_path / "auto-fix-log.md"
    gh = FakeGh()
    launches: list[dict] = []
    fixer = {"fn": good_fixer}

    def launch(prompt, cwd):
        launches.append({"prompt": prompt, "cwd": Path(cwd)})
        fixer["fn"](prompt, Path(cwd))

    monkeypatch.setattr(af, "AGENTS_DIR", shared)
    monkeypatch.setattr(af, "QUEUE_PATH", queue)
    monkeypatch.setattr(af, "LOG_PATH", log)
    monkeypatch.setattr(af, "VENV_PYTHON", Path(sys.executable))
    monkeypatch.setattr(af, "_core_files", lambda: set())
    monkeypatch.setattr(af, "_gh", gh)
    monkeypatch.setattr(af, "_launch_fixer", launch)
    monkeypatch.setattr(af, "_load_5min", lambda: 1.0)
    monkeypatch.setattr(so, "WORKTREES_ROOT", tmp_path / "worktrees")

    class Env:
        pass
    e = Env()
    e.tmp, e.shared, e.origin, e.queue, e.log, e.gh, e.launches, e.fixer = (
        tmp_path, shared, origin, queue, log, gh, launches, fixer)
    e.status = lambda: git(shared, "status", "--porcelain", "--untracked-files=all")
    e.head = lambda: git(shared, "rev-parse", "HEAD")
    e.on_origin = lambda b: bool(git(origin, "branch", "--list", b))
    return e


def run(env, today=TODAY):
    before_status, before_head = env.status(), env.head()
    af.run(today=today)
    assert env.status() == before_status == "", "the shared checkout was touched"
    assert env.head() == before_head, "the shared checkout's HEAD moved"
    assert git(env.shared, "branch", "--show-current") == "main"


# ── the happy path ────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_good_batch_opens_one_pr_from_its_own_branch_and_leaves_the_shared_checkout_untouched(env):
    run(env)
    assert env.gh.created() == 1
    assert env.on_origin(BRANCH)
    fixed = git(env.origin, "show", f"{BRANCH}:lib/widget.py")
    assert "numbers" in fixed and "just" not in fixed
    assert (env.shared / "lib" / "widget.py").read_text() == WIDGET
    # the fixer worked inside the run's own worktree, never the shared clone
    [launch] = env.launches
    assert launch["cwd"] != env.shared and so.WORKTREES_ROOT in launch["cwd"].parents
    create = next(c for c in env.gh.calls if c[:2] == ["pr", "create"])
    assert create[create.index("--head") + 1] == BRANCH and create[create.index("--base") + 1] == "main"
    assert "--repo" in create


def test_the_pr_body_lists_every_item_with_its_queue_entry_and_the_test_results(env):
    run(env)
    [body] = env.gh.bodies
    for line in QUEUE.splitlines():
        if line.startswith("- **["):
            assert line[2:] in body, f"missing queue entry: {line}"
    assert "Before" in body and "After" in body and "Passed" in body
    assert "not auto-merged" in body.lower() or "merge gate" in body.lower()


def test_items_are_marked_in_pr_when_it_opens_and_done_once_it_merges(env):
    run(env)
    text = env.queue.read_text()
    assert text.count("auto-fix: in PR #901") == 3
    env.gh.prs["901"] = {"number": 901, "state": "MERGED"}
    af.refresh_pr_marks()
    text = env.queue.read_text()
    assert text.count("auto-fix: done, PR #901 merged") == 3 and "in PR #901" not in text


def test_a_pr_closed_unmerged_marks_its_items_tried_so_they_are_not_retried_forever(env):
    run(env)
    env.gh.prs["901"] = {"number": 901, "state": "CLOSED"}
    af.refresh_pr_marks()
    assert env.queue.read_text().count("auto-fix: tried") == 3


def test_the_log_keeps_the_line_output_contracts_reads(env):
    run(env)
    import re
    text = env.log.read_text()
    assert re.search(r"^## " + TODAY + r"T[^\n]*\n3 candidate\(s\) found, 3 fixed", text, re.M), text
    assert "PR #901" in text


def test_tests_run_with_two_workers_before_and_after(env, monkeypatch):
    seen = []
    real = af._run_suite
    monkeypatch.setattr(af, "_run_suite", lambda wt, cmd: (seen.append(cmd), real(wt, cmd))[1])
    run(env)
    assert len(seen) == 2 and all(c[c.index("-n") + 1] == "2" for c in seen)
    assert all(c[-1] == "lib" for c in seen)


# ── a fix that breaks something ───────────────────────────────────────────────────────────────────────────────────

def test_a_fix_that_breaks_a_test_opens_no_pr_logs_why_and_marks_items_tried(env):
    def breaking(prompt, cwd):
        w = cwd / "lib" / "widget.py"
        w.write_text(w.read_text().replace("result + x", "result - x"))
    env.fixer["fn"] = breaking
    run(env)
    assert env.gh.created() == 0
    assert not env.on_origin(BRANCH)
    assert "tests failed" in env.log.read_text().lower()
    assert env.queue.read_text().count(f"auto-fix: tried {TODAY}, tests failed") == 3
    assert not list(so.WORKTREES_ROOT.glob("auto-fix-*")), "the failed worktree was left behind"


def test_a_fix_that_no_longer_compiles_is_reverted_and_never_committed(env):
    env.fixer["fn"] = lambda p, cwd: (cwd / "lib" / "widget.py").write_text("def total(:\n")
    run(env)
    assert env.gh.created() == 0
    assert f"auto-fix: tried {TODAY}" in env.queue.read_text()


def test_a_red_baseline_means_nothing_is_attempted_and_nothing_marked(env):
    (env.shared / "lib" / "tests" / "test_widget.py").write_text(WIDGET_TEST.replace("== 6", "== 7"))
    git(env.shared, "commit", "-qam", "red")
    git(env.shared, "push", "-q", "origin", "main")
    run(env)
    assert env.launches == [] and env.gh.created() == 0
    assert "auto-fix:" not in env.queue.read_text()
    assert "baseline" in env.log.read_text().lower()


def test_a_fixer_that_changes_nothing_opens_no_pr(env):
    env.fixer["fn"] = lambda p, cwd: None
    run(env)
    assert env.gh.created() == 0
    assert env.queue.read_text().count(f"auto-fix: tried {TODAY}, no change made") == 3


def test_a_fixer_that_crashes_opens_no_pr_and_marks_nothing(env):
    def boom(p, cwd):
        raise subprocess.TimeoutExpired("claude", 300)
    env.fixer["fn"] = boom
    run(env)
    assert env.gh.created() == 0 and "auto-fix:" not in env.queue.read_text()
    assert "fixer" in env.log.read_text().lower()


# ── the queue: empty, malformed, huge ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("content", [None, "", "# Improvement Queue\n", "\x00\x01 garbage\n- **[\n- **[NAMING]** no path\n"])
def test_an_empty_missing_or_garbage_queue_launches_nothing(env, content):
    if content is None:
        env.queue.unlink()
    else:
        env.queue.write_text(content)
    run(env)
    assert env.launches == [] and env.gh.created() == 0
    assert "no queued items" in env.log.read_text()


def test_malformed_lines_are_ignored_and_the_good_ones_still_run(env):
    env.queue.write_text(QUEUE + "- **[NAMING]** broken (`\n- **[WAT]** odd kind (`lib/widget.py`)\n"
                         "- **[NAMING]** escapes the repo (`../../etc/passwd.py`)\n"
                         "- **[NAMING]** absolute (`/etc/hosts.py`)\n")
    run(env)
    assert env.gh.created() == 1
    assert "passwd" not in env.launches[0]["prompt"] and "/etc/hosts" not in env.launches[0]["prompt"]


def test_a_huge_queue_is_parsed_quickly_and_only_a_capped_batch_is_taken(env):
    lines = ["# Improvement Queue", ""]
    for day in range(200):
        lines += ["---", f"## 2026-07-{(day % 28) + 1:02d} — marvin", ""]
        for i in range(100):
            lines.append(f"- **[VERBOSITY]** Filler word `just` in comment at line {i}: `x` (`lib/widget.py`)")
            lines.append(f"- **[NAMING]** Generic parameter name `data` in `f()` at line {i}. (`tools/f{i}.py`)")
    env.queue.write_text("\n".join(lines) + "\n")
    t = time.monotonic()
    items = af.parse_queue(env.queue.read_text())
    assert time.monotonic() - t < 2
    assert len(items) == 200  # 40,000 lines, 200 distinct items
    run(env)
    [launch] = env.launches
    assert launch["prompt"].count("- [") <= af.MAX_ITEMS


def test_items_already_marked_are_not_picked_again(env):
    run(env)
    env.launches.clear()
    af.run(today="2026-10-27")
    assert env.launches == []


# ── two runs, leftover state ──────────────────────────────────────────────────────────────────────────────────────

def test_a_second_run_the_same_day_opens_no_second_pr(env):
    run(env)
    env.queue.write_text(QUEUE)  # even with fresh items queued
    run(env)
    assert env.gh.created() == 1 and len(env.launches) == 1
    assert "already" in env.log.read_text().split("\n## ")[-1]


def test_an_unreadable_github_fails_closed(env):
    env.gh.fail = True
    run(env)
    assert env.launches == [] and env.gh.created() == 0
    assert "auto-fix:" not in env.queue.read_text()


def test_a_dirty_leftover_worktree_from_earlier_today_is_preserved_then_replaced(env):
    wt = so._create_worktree(env.shared, "unused", branch=BRANCH)
    (wt / "lib" / "widget.py").write_text("half-finished\n")
    (wt / "stray.py").write_text("x = 1\n")
    run(env)
    assert env.gh.created() == 1
    assert git(env.origin, "show", f"{BRANCH}:lib/widget.py") != "half-finished"
    assert git_ok(env.origin, "cat-file", "-e", f"{BRANCH}:lib/widget.py")
    assert not git_ok(env.origin, "cat-file", "-e", f"{BRANCH}:stray.py")
    rescue = git(env.shared, "for-each-ref", "--format=%(refname)", "refs/rescue/")
    assert BRANCH in rescue


def test_a_worktree_that_cannot_be_created_logs_it_and_marks_nothing(env):
    git(env.shared, "remote", "remove", "origin")
    run(env)
    assert env.launches == [] and env.gh.created() == 0
    assert "auto-fix:" not in env.queue.read_text()
    assert "worktree" in env.log.read_text().lower()


def test_two_runs_at_once_the_second_one_stands_down(env):
    import fcntl
    so.WORKTREES_ROOT.mkdir(parents=True, exist_ok=True)
    with open(af._lock_path(), "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(env)
    assert env.launches == [] and "another auto-fix run" in env.log.read_text()


# ── KISS items and the size caps ──────────────────────────────────────────────────────────────────────────────────

def _big_function(n: int) -> str:
    return "def big(a):\n" + "".join(f"    a = a + {i}\n" for i in range(n - 2)) + "    return a\n"


def test_a_kiss_item_over_the_function_cap_is_skipped_with_a_note_and_never_sent(env):
    (env.shared / "lib" / "big.py").write_text(_big_function(af.KISS_MAX_FUNCTION_LINES + 5))
    git(env.shared, "add", "-A")
    git(env.shared, "commit", "-qm", "big")
    git(env.shared, "push", "-q", "origin", "main")
    env.queue.write_text(QUEUE + f"- **[KISS]** Function 'big' at line 1 is {af.KISS_MAX_FUNCTION_LINES + 5} lines long. (`lib/big.py`)\n")
    run(env)
    assert "big.py" not in env.launches[0]["prompt"]
    line = next(l for l in env.queue.read_text().splitlines() if "big.py" in l)
    assert f"auto-fix: skipped {TODAY}" in line and f"over the {af.KISS_MAX_FUNCTION_LINES}-line cap" in line


def test_a_kiss_item_at_the_function_cap_is_in_scope(env):
    (env.shared / "lib" / "big.py").write_text(_big_function(af.KISS_MAX_FUNCTION_LINES))
    git(env.shared, "add", "-A")
    git(env.shared, "commit", "-qm", "big")
    git(env.shared, "push", "-q", "origin", "main")
    env.queue.write_text(f"- **[KISS]** Function 'big' at line 1 mixes concerns: io. (`lib/big.py`)\n")
    run(env)
    assert "big.py" in env.launches[0]["prompt"]


def test_a_kiss_fix_whose_diff_is_over_the_cap_is_reverted_and_left_in_the_queue_with_a_note(env):
    def sprawl(prompt, cwd):
        good_fixer(prompt, cwd)
        w = cwd / "lib" / "widget.py"
        w.write_text(w.read_text() + "".join(f"# line {i}\n" for i in range(200)))
    env.fixer["fn"] = sprawl
    run(env)
    assert env.gh.created() == 0
    text = env.queue.read_text()
    assert text.count(f"auto-fix: skipped {TODAY}, diff") == 3 and "over the" in text


def test_a_kiss_item_whose_function_is_gone_is_skipped(env):
    env.queue.write_text("- **[KISS]** Function 'vanished' at line 1 is 9 lines long. (`lib/widget.py`)\n")
    run(env)
    assert env.launches == []
    assert "function no longer exists" in env.queue.read_text()


def test_the_fixer_may_only_change_the_queued_files(env):
    def wanders(prompt, cwd):
        good_fixer(prompt, cwd)
        (cwd / "tools" / "orphan.py").write_text("tampered\n")
        (cwd / "lib" / "tests" / "test_widget.py").write_text(WIDGET_TEST + "\n# weakened\n")
    env.fixer["fn"] = wanders
    run(env)
    assert env.gh.created() == 1
    assert git(env.origin, "show", f"{BRANCH}:tools/orphan.py") == "def f(data):\n    return data"
    assert "weakened" not in git(env.origin, "show", f"{BRANCH}:lib/tests/test_widget.py")


def test_a_fixer_that_writes_into_the_shared_checkout_is_undone(env):
    def escapes(prompt, cwd):
        good_fixer(prompt, cwd)
        (env.shared / "lib" / "widget.py").write_text("written into the shared checkout\n")
    env.fixer["fn"] = escapes
    run(env)  # asserts the shared checkout is clean afterwards
    assert "shared checkout" in env.log.read_text()


# ── files that moved on since they were queued ────────────────────────────────────────────────────────────────────

def test_a_file_deleted_since_it_was_queued_is_skipped_with_a_note(env):
    env.queue.write_text(QUEUE + "- **[NAMING]** Generic parameter name `x` in `g()` at line 1. (`lib/gone.py`)\n")
    run(env)
    assert "gone.py" not in env.launches[0]["prompt"]
    line = next(l for l in env.queue.read_text().splitlines() if "gone.py" in l)
    assert "file no longer exists" in line


def test_a_file_no_tests_cover_is_skipped(env):
    env.queue.write_text("- **[NAMING]** Generic parameter name `data` in `f()` at line 1. (`tools/orphan.py`)\n")
    run(env)
    assert env.launches == []
    assert "no tests cover tools" in env.queue.read_text()


def test_core_files_are_never_sent(env, monkeypatch):
    monkeypatch.setattr(af, "_core_files", lambda: {(env.shared / "lib" / "widget.py").resolve()})
    run(env)
    assert env.launches == []


def test_non_python_and_out_of_scope_kinds_are_ignored(env):
    env.queue.write_text("- **[LOGIC]** something (`lib/widget.py`)\n- **[NAMING]** x (`dashboard/src/a.ts`)\n")
    run(env)
    assert env.launches == []


# ── machine load ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_it_waits_while_the_5_minute_load_is_over_12(env, monkeypatch):
    loads = iter([15.0, 13.0, 4.0])
    slept = []
    monkeypatch.setattr(af, "_load_5min", lambda: next(loads))
    monkeypatch.setattr(af, "_sleep", slept.append)
    run(env)
    assert len(slept) >= 2 and env.gh.created() == 1


def test_a_machine_that_never_calms_down_skips_the_day(env, monkeypatch):
    monkeypatch.setattr(af, "_load_5min", lambda: 20.0)
    monkeypatch.setattr(af, "_sleep", lambda s: None)
    run(env)
    assert env.launches == [] and "load" in env.log.read_text().lower()
    assert "auto-fix:" not in env.queue.read_text()


# ── the fixer's leash ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_real_launch_denies_writes_to_the_shared_checkout(monkeypatch, tmp_path):
    seen = {}
    import marvin_launcher
    monkeypatch.setattr(marvin_launcher, "launch", lambda kind, prompt, **kw: seen.update(kind=kind, **kw))
    af._default_launch_fixer("fix", tmp_path)
    assert seen["kind"] == "background-analyst" and seen["cwd"] == tmp_path
    assert seen["tools"] == "Read,Edit"
    assert "Edit(~/.agents/**)" in seen["disallowed_tools"] and "Write(~/.agents/**)" in seen["disallowed_tools"]


def test_a_fixer_that_weakens_a_test_to_hide_a_broken_fix_still_opens_no_pr(env):
    """Files outside the queue are reverted BEFORE the after-run, so a test edited to pass can't vouch for a break."""
    def cheats(prompt, cwd):
        w = cwd / "lib" / "widget.py"
        w.write_text(w.read_text().replace("result + x", "result - x"))
        (cwd / "lib" / "tests" / "test_widget.py").write_text(WIDGET_TEST.replace("== 6", "== -6"))
    env.fixer["fn"] = cheats
    run(env)
    assert env.gh.created() == 0
    assert "tests failed" in env.log.read_text()


def test_a_fixer_that_writes_into_the_shared_checkout_and_then_crashes_is_still_undone(env):
    def escapes_then_dies(prompt, cwd):
        (env.shared / "lib" / "widget.py").write_text("written into the shared checkout\n")
        raise RuntimeError("fixer exited 1")
    env.fixer["fn"] = escapes_then_dies
    run(env)
    assert env.gh.created() == 0 and "shared checkout" in env.log.read_text()


def test_a_script_any_launchd_job_runs_is_core_whatever_its_label_prefix(tmp_path, monkeypatch):
    agents = tmp_path / "agents"
    (agents / "lib").mkdir(parents=True)
    script = agents / "lib" / "job.py"
    script.write_text("")
    agents_dir = tmp_path / "LaunchAgents"
    agents_dir.mkdir()
    (agents_dir / "org.someone.job.plist").write_text(f"<plist><string>{script}</string></plist>")
    (agents_dir / "com.other.plist").write_text("<plist><string>/elsewhere/x.py</string></plist>")
    (agents_dir / "broken.plist").write_bytes(b"\xff\xfe\x00")
    monkeypatch.setattr(af, "AGENTS_DIR", agents)
    monkeypatch.setattr(af, "LAUNCH_AGENTS_DIR", agents_dir)
    monkeypatch.setattr(af, "HOOK_SETTINGS_PATHS", (tmp_path / "none.json", tmp_path / "none2.json"))
    assert af._core_files() == {script.resolve()}
