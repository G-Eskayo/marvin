"""The box's live display stops while dispatched jobs run and comes back when the last one ends (marvin #931).

Real processes play the display (a sleeper whose command line carries a pattern unique to the test, so the real
display on mac-mini-2012 is never matched when this suite runs there) and the jobs (sleepers with task records)."""
import json
import os
import subprocess
import sys
import time
import uuid

import pytest

import job_hooks as jh
import task_dispatch as td


@pytest.fixture
def box(monkeypatch, tmp_path):
    pattern = f"fake-display-{uuid.uuid4().hex}/main.js"
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    started = tmp_path / "started.log"
    launcher = tmp_path / "marvin-desktoplive.sh"
    launcher.write_text(f'#!/bin/bash\necho "$DISPLAY" >> {started}\n'
                        f'exec {sys.executable} -c "import time; time.sleep(60)" {pattern}\n')
    launcher.chmod(0o755)
    monkeypatch.setattr(jh, "DISPLAY_PATTERN", pattern)
    monkeypatch.setattr(jh, "TASKS_DIR", tasks)
    monkeypatch.setattr(jh, "PAUSE_FILE", tmp_path / "paused.json")
    monkeypatch.setattr(jh, "LOCK_FILE", tmp_path / "lock")
    monkeypatch.setattr(jh, "LOG", tmp_path / "box-display.jsonl")
    monkeypatch.setattr(jh, "launcher", lambda: launcher)
    monkeypatch.setattr(jh, "process_env", lambda pid: {"DISPLAY": ":0", "XAUTHORITY": "/home/marvin/.Xauthority"})
    procs = []

    class Box:
        def show(self):
            p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", pattern])
            procs.append(p)
            wait_for(lambda: jh.display_pids())
            return p

        def job(self, name):
            p = subprocess.Popen(["sleep", "60"])
            procs.append(p)
            (tasks / f"{name}.json").write_text(json.dumps({"task_id": name, "pid": p.pid}))
            return p

        def end(self, name, proc):
            (tasks / f"{name}.json").unlink()     # the wrapper's EXIT trap removes the record first ...
            proc.kill()
            proc.wait()

        def starts(self):
            return started.read_text().split() if started.exists() else []

    yield Box()
    for p in procs:
        p.kill()
        p.wait()
    for pid in jh.display_pids():   # anything the launcher started
        os.kill(pid, 9)


def wait_for(cond, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_the_first_job_stops_the_display_and_the_last_one_brings_it_back_with_its_session(box):
    shown = box.show()
    a = box.job("a")
    assert jh.on_start() == "stopped"
    assert shown.wait(timeout=5) is not None
    assert json.loads(jh.PAUSE_FILE.read_text())["env"]["DISPLAY"] == ":0"
    box.end("a", a)
    assert jh.on_stop() == "started"
    assert wait_for(lambda: jh.display_pids()) and wait_for(lambda: box.starts() == [":0"])
    assert not jh.PAUSE_FILE.exists()


def test_overlapping_jobs_keep_it_off_until_both_end_and_it_comes_back_exactly_once(box):
    box.show()
    a, b = box.job("a"), box.job("b")
    assert jh.on_start() == "stopped"
    assert jh.on_start() == "not-running"              # b's start: already off
    box.end("a", a)
    assert jh.on_stop() == "jobs-still-running"
    assert jh.display_pids() == []
    box.end("b", b)
    assert jh.on_stop() == "started"
    assert jh.on_stop() == "not-paused"                # a second stop (a late trap) starts nothing more
    wait_for(lambda: box.starts())
    time.sleep(0.3)
    assert box.starts() == [":0"]


def test_a_display_someone_closed_is_not_started_by_a_job(box):
    a = box.job("a")
    assert jh.on_start() == "not-running"
    box.end("a", a)
    assert jh.on_stop() == "not-paused"
    assert box.starts() == [] and jh.display_pids() == []


def test_a_job_killed_without_its_trap_leaves_a_stale_record_that_does_not_keep_the_display_off(box):
    box.show()
    killed = box.job("killed")
    assert jh.on_start() == "stopped"
    killed.kill()                                      # SIGKILL: no EXIT trap, its record stays behind
    killed.wait()
    later = box.job("later")
    box.end("later", later)
    assert jh.on_stop() == "started"


def test_a_display_restarted_by_hand_during_a_job_is_stopped_again_by_the_next_job(box):
    box.show()
    a = box.job("a")
    jh.on_start()
    again = box.show()                                 # Gil starts it from the menu mid-job
    b = box.job("b")
    assert jh.on_start() == "stopped"
    assert again.wait(timeout=5) is not None
    for name, p in (("a", a), ("b", b)):
        box.end(name, p)
    assert jh.on_stop() == "started"


def test_a_running_display_at_the_end_is_left_alone_and_not_doubled(box):
    box.show()
    a = box.job("a")
    jh.on_start()
    box.show()
    box.end("a", a)
    assert jh.on_stop() == "already-running"
    assert len(jh.display_pids()) == 1 and box.starts() == []


def test_without_a_launcher_it_says_so_and_does_not_fail(box, monkeypatch, tmp_path):
    box.show()
    a = box.job("a")
    jh.on_start()
    monkeypatch.setattr(jh, "launcher", lambda: tmp_path / "missing.sh")
    box.end("a", a)
    assert jh.on_stop() == "no-launcher"


def test_a_hook_that_blows_up_still_exits_zero(monkeypatch, tmp_path):
    monkeypatch.setattr(jh, "LOG", tmp_path / "log.jsonl")

    def boom():
        raise RuntimeError("pgrep vanished")
    monkeypatch.setattr(jh, "on_start", boom)
    assert jh.main(["job_hooks.py", "start"]) == 0
    assert "pgrep vanished" in (tmp_path / "log.jsonl").read_text()


def test_on_a_mac_with_no_display_both_hooks_are_no_ops(box):
    a = box.job("a")
    assert jh.on_start() == "not-running"
    box.end("a", a)
    assert jh.on_stop() == "not-paused"
    assert not jh.PAUSE_FILE.exists()


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="/proc is Linux's")
def test_the_session_environment_is_read_from_proc():
    p = subprocess.Popen(["sleep", "30"], env={"DISPLAY": ":7", "XAUTHORITY": "/x", "SECRET": "no", "PATH": "/usr/bin:/bin"})
    try:
        env = jh.process_env(p.pid)
        assert env["DISPLAY"] == ":7" and env["XAUTHORITY"] == "/x" and "SECRET" not in env
    finally:
        p.kill()
        p.wait()


def test_the_launcher_is_this_hosts_config_script():
    assert jh.launcher().parts[-3:] == ("config", __import__("socket").gethostname(), "marvin-desktoplive.sh")


# ── the wrapper calls the hooks, at the right moments, and they never change its exit code ─────────────────────

def test_the_wrapper_runs_start_after_its_task_record_and_stop_after_removing_it():
    script = td._build_wrapper_script("true", "abc", "label", "mac-mini-2012")
    record_at = script.index("dispatch/tasks\"/abc.json")
    start_at = script.index("job_hooks.py\" start")
    trap = script[script.index("trap '"):]
    assert record_at < start_at < script.index("trap '")
    assert trap.index("rm -f") < trap.index("job_hooks.py\" stop") < trap.index("' EXIT")


@pytest.mark.parametrize("command,code", [("true", 0), ("exit 3", 3)])
def test_a_missing_or_broken_hook_never_changes_the_jobs_exit_code(tmp_path, command, code):
    hooks = tmp_path / ".agents" / "lib"
    hooks.mkdir(parents=True)
    (hooks / "job_hooks.py").write_text("raise SystemExit(9)\n")
    venv = tmp_path / ".agents" / "venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").symlink_to(sys.executable)
    f = tmp_path / "w.sh"
    f.write_text(td._build_wrapper_script(command, "abc", "label", "box"))
    r = subprocess.run(["/bin/bash", str(f)], env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}, capture_output=True)
    assert r.returncode == code
