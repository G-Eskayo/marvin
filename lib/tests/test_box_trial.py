"""The box trial's five work types (marvin #932). The shell each one sends is run for real against a throwaway HOME
with its own git checkout, a fake venv python and a fake graphify, so what's tested is what the box runs."""
import argparse
import json
import os
import signal
import subprocess
import time

import pytest

import box_trial as bt
import task_dispatch as td


def ns(**kw):
    base = {"timeout": None, "workers": 8, "questions": None, "rest": []}
    return argparse.Namespace(**{**base, **kw})


# ── what each type sends ─────────────────────────────────────────────────────────────────────────────────────

def test_each_trial_type_goes_with_its_tag_and_limit(tmp_path):
    q = tmp_path / "q.json"
    q.write_text('[{"id": "a"}]')
    assert {k: (bt.plan(k, ns(rest=r, questions=q))["need"], bt.plan(k, ns(rest=r, questions=q))["timeout"]) for k, r in [
        ("suite", []), ("vitest", []), ("quarantine", ["ls"]), ("security", ["nmap", "-sn", "10.0.0.0/30"]),
        ("retrieval", [])]} == {
        "suite": ("test", 480), "vitest": ("test", 120), "quarantine": ("quarantine", 180 + 300 + 30),
        "security": ("security", 600), "retrieval": ("bench", bt.RETRIEVAL_TIMEOUT_S)}


@pytest.mark.parametrize("kind", ["build", "ticket", "general", "", "suite;rm"])
def test_anything_outside_the_five_is_refused(kind):
    with pytest.raises(ValueError):
        bt.plan(kind, ns())


def test_a_ticket_build_cannot_ride_in_as_a_security_tool():
    for argv in (["claude", "-p", "build #12"], ["bash", "-c", "x"], ["python3", "x.py"], []):
        with pytest.raises(ValueError):
            bt.security_command(argv)


def test_security_arguments_are_quoted_not_interpreted():
    assert bt.security_command(["dig", "a.example; rm -rf ~"]) == "dig 'a.example; rm -rf ~'"


def test_a_quarantine_run_needs_a_command_and_quotes_it():
    with pytest.raises(ValueError):
        bt.quarantine_command([])
    # vm_run joins its argv into the VM's shell command, so the box must hand it the words as ONE argument
    assert bt.quarantine_command(["uname -a; id"]).endswith("-- 'uname -a; id'")
    assert bt.quarantine_command(["uname", "-a"]).endswith("-- 'uname -a'")


def test_the_vm_gets_exactly_the_command_typed(tmp_path):
    # Run the box side for real up to vm_run's own joining: the words must survive the box's shell intact.
    fake = tmp_path / ".agents" / "lib"
    fake.mkdir(parents=True)
    (fake / "vm_run.py").write_text("import sys; a = sys.argv[1:]; print(' '.join(a[a.index('--') + 1:]))\n")
    venv = tmp_path / ".agents" / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(__import__("sys").executable)
    r = subprocess.run(["/bin/bash", "-c", bt.quarantine_command(["sh -c 'uname -a; id'"])],
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert r.stdout.strip() == "sh -c 'uname -a; id'"
    assert "--image quarantine" in bt.quarantine_command(["ls"])


def test_the_suite_uses_eight_workers_by_default():
    assert "-n 8 " in bt.suite_command()


# ── the question file ────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("content,why", [(None, "no retrieval question file"), ("", "not JSON"), ("[]", "no questions"),
                                         ("{", "not JSON"), ('{"a": 1}', "no questions")])
def test_a_missing_empty_or_broken_question_file_is_refused_before_anything_is_sent(tmp_path, content, why):
    q = tmp_path / "q.json"
    if content is not None:
        q.write_text(content)
    with pytest.raises(ValueError, match=why):
        bt.run("retrieval", ns(questions=q), dispatch=lambda *a, **k: pytest.fail("nothing may be dispatched"))


def test_the_questions_go_on_stdin_and_the_run_is_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(bt, "LOG", tmp_path / "box-trial.jsonl")
    q = tmp_path / "q.json"
    q.write_text('[{"id": "a", "q": "?"}]')
    seen = {}

    def dispatch(cmd, **kw):
        seen.update(kw, cmd=cmd)
        return td.DispatchResult(ok=True, device_id="macbook-pro-1", output="| rg | 30 |\n", fell_back_from="mac-mini-2012")
    rec = bt.run("retrieval", ns(questions=q), dispatch=dispatch)
    assert seen["stdin"] == q.read_text() and seen["need"] == "bench" and "/dev/stdin" in seen["cmd"]
    line = json.loads((tmp_path / "box-trial.jsonl").read_text())
    assert line["kind"] == "retrieval" and line["ran_on"] == "macbook-pro-1" and line["fell_back_from"] == "mac-mini-2012"
    assert line["summary"] == "| rg | 30 |" and "output" not in line
    assert rec["ok"]


def test_the_cli_says_where_it_ran_and_refuses_with_exit_2(tmp_path, monkeypatch, capsys):
    assert bt.main(["security", "--", "claude", "-p", "x"]) == 2
    assert "refused" in capsys.readouterr().err


# ── the shell, run for real ──────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def box_home(tmp_path):
    home = tmp_path / "home"
    repo = home / ".agents"
    (repo / "dashboard" / "node_modules").mkdir(parents=True)
    (repo / "bench").mkdir()
    (repo / "README").write_text("x")
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run([*git, "-C", str(repo), "add", "README"], check=True)
    subprocess.run([*git, "-C", str(repo), "commit", "-qm", "c"], check=True)
    venv = repo / "venv" / "bin"
    venv.mkdir(parents=True)
    # The fake python: records where it ran and what it got on stdin, then behaves as FAKE_MODE says.
    (venv / "python").write_text(f"""#!/bin/bash
echo "cwd=$PWD" >> {tmp_path}/calls
case "$FAKE_MODE" in
  hang) sleep 60 ;;
  fail) echo "2 failed, 10 passed"; exit 1 ;;
  stdin) cat /dev/stdin ;;
  *) echo "12 passed" ;;
esac
""")
    (venv / "python").chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "graphify").write_text(f"#!/bin/bash\necho graphify \"$@\" >> {tmp_path}/calls\n")
    (bin_dir / "graphify").chmod(0o755)
    return home, tmp_path


def sh(home, command, mode="", stdin=None, path_extra=""):
    env = {"HOME": str(home), "PATH": f"{path_extra}:/usr/bin:/bin:/opt/homebrew/bin", "FAKE_MODE": mode}
    return subprocess.run(["/bin/bash", "-c", command], env=env, capture_output=True, text=True, input=stdin, timeout=30)


def worktrees(home):
    out = subprocess.run(["git", "-C", str(home / ".agents"), "worktree", "list"], capture_output=True, text=True).stdout
    return out.strip().splitlines()


@pytest.mark.parametrize("mode,code", [("", 0), ("fail", 1)])
def test_the_suite_runs_in_a_throwaway_worktree_keeps_its_exit_code_and_cleans_up(box_home, mode, code):
    home, tmp = box_home
    r = sh(home, bt.suite_command(), mode)
    assert r.returncode == code, r.stderr
    assert "commit " in r.stdout
    cwd = (tmp / "calls").read_text().split("cwd=")[1].strip()
    assert cwd.startswith("/tmp/box-trial-") or "/box-trial-" in cwd
    assert not os.path.exists(cwd) and len(worktrees(home)) == 1


def test_a_suite_killed_at_its_timeout_still_removes_its_worktree(box_home):
    home, tmp = box_home
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "FAKE_MODE": "hang"}
    p = subprocess.Popen(["/bin/bash", "-c", bt.suite_command()], env=env, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        if (tmp / "calls").exists():
            break
        time.sleep(0.05)
    cwd = (tmp / "calls").read_text().split("cwd=")[1].strip()
    os.killpg(p.pid, signal.SIGTERM)          # what GNU timeout does to the run's group
    p.wait(timeout=10)
    # The outer shell is gone at once; the subshell's own trap finishes the clean-up a moment later.
    end = time.monotonic() + 10
    while (os.path.exists(cwd) or len(worktrees(home)) != 1) and time.monotonic() < end:
        time.sleep(0.05)
    assert not os.path.exists(cwd) and len(worktrees(home)) == 1


def test_a_worktree_left_by_a_sigkilled_run_is_pruned_by_the_next(box_home):
    home, tmp = box_home
    orphan = tmp / "orphan"
    subprocess.run(["git", "-C", str(home / ".agents"), "worktree", "add", "-q", "--detach", str(orphan), "HEAD"], check=True)
    subprocess.run(["rm", "-rf", str(orphan)], check=True)          # SIGKILL: no trap, the directory went with /tmp
    assert sh(home, bt.suite_command()).returncode == 0
    assert len(worktrees(home)) == 1


def test_vitest_links_the_boxs_own_install_into_the_worktree(box_home):
    home, tmp = box_home
    (tmp / "bin" / "npx").write_text("#!/bin/bash\nls -la node_modules | head -1; echo \"vitest $*\"\n")
    (tmp / "bin" / "npx").chmod(0o755)
    (home / ".agents" / "dashboard" / "keep").write_text("")
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(home / ".agents")]
    subprocess.run([*git, "add", "dashboard/keep"], check=True)
    subprocess.run([*git, "commit", "-qm", "d"], check=True)
    r = sh(home, bt.vitest_command(), path_extra=str(tmp / "bin"))
    assert r.returncode == 0, r.stderr
    assert "vitest run" in r.stdout and len(worktrees(home)) == 1


def test_the_retrieval_run_reads_the_questions_from_stdin_and_leaves_nothing_on_disk(box_home):
    home, tmp = box_home
    r = sh(home, bt.retrieval_command(), "stdin", stdin='[{"id": "private-note-name"}]', path_extra=str(tmp / "bin"))
    assert r.returncode == 0 and "private-note-name" in r.stdout
    assert "graphify update ." in (tmp / "calls").read_text()
    leaked = [p for p in home.rglob("*") if p.is_file() and "private-note-name" in p.read_text(errors="ignore")]
    assert leaked == []
