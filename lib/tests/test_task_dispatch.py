import pytest

import task_dispatch as td


def test_tailscale_status_gets_a_term_and_ignores_error_text(monkeypatch):
    import subprocess
    seen = {}

    def fake_run(cmd, **kw):
        seen["env"] = kw.get("env")
        out = "The Tailscale GUI failed to start: error 3.\n100.1.1.1  box  me@  macOS  active\n100.1.1.2  gone  me@  macOS  offline, last seen 1h ago\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")

    monkeypatch.setattr(td.subprocess, "run", fake_run)
    assert td._tailscale_online_hosts() == {"box"}
    assert seen["env"]["TERM"] == "dumb"


def test_the_dispatch_wrapper_puts_the_claude_install_dir_on_path():
    # Same incident: the wrapper added Homebrew dirs but not ~/.local/bin, where the claude CLI lives.
    import task_dispatch as td
    script = td._build_wrapper_script("echo hi", "abc", "label", "test-device")
    path_line = next(l for l in script.splitlines() if l.startswith("export PATH="))
    assert "$HOME/.local/bin" in path_line


def test_the_wrapper_refreshes_the_busy_summary_from_marvins_folder_with_marvins_python(tmp_path):
    # `python3 -m lib.dispatch_concurrency` ran relative to whatever folder the job started in, so on every machine it
    # failed with "No module named 'lib'" and the summary never refreshed (found registering mac-mini-2012).
    import subprocess
    import task_dispatch as td
    script = td._build_wrapper_script("true", "abc", "label", "test-device")
    lines = [l for l in script.splitlines() if "dispatch_concurrency" in l]
    assert lines and all('cd "$HOME/.agents"' in l and "$HOME/.agents/venv/bin/python" in l for l in lines)


def test_the_wrapper_names_no_path_from_the_machine_that_built_it():
    # Built on a Mac, run on mac-mini-2012 (home /home/marvin): the busy flag and task record must land in the
    # RUNNING machine's ~/.claude, or the box never looks busy and gets a second job (ADR 0069).
    from pathlib import Path
    import task_dispatch as td
    script = td._build_wrapper_script("true", "abc", "label", "mac-mini-2012")
    assert str(Path.home()) not in script
    assert "$HOME/.claude/dispatch/tasks" in script and "$HOME/.claude/dispatch-state.json" in script


def test_the_wrapper_really_marks_busy_and_idle_under_the_running_home(tmp_path):
    import subprocess
    import task_dispatch as td
    script = td._build_wrapper_script('cat "$HOME/.claude/dispatch-state.json"', "abc", "label", "box")
    f = tmp_path / "w.sh"
    f.write_text(script)
    out = subprocess.run(["/bin/bash", str(f)], env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True).stdout
    assert '"busy": true' in out
    assert '"busy": false' in (tmp_path / ".claude" / "dispatch-state.json").read_text()


# ── memory guard (marvin#845) ────────────────────────────────────────────────────────────────────────────────

def _local(monkeypatch):
    monkeypatch.setattr(td, "select_machine", lambda target=None, need=None: ("mac-mini-1", {"is_self": True}))
    monkeypatch.setattr(td, "_run_local", lambda *a, **k: pytest.fail("nothing may start under memory pressure"))


def test_local_work_under_memory_pressure_is_refused_with_the_plain_message(monkeypatch):
    import memory_guard
    _local(monkeypatch)
    seen = []
    monkeypatch.setattr(memory_guard, "guard", lambda what, argv, cwd, **k: seen.append(argv) or
                        {"ok": False, "queued": bool(argv), "message": f"The Mac mini's memory is under pressure, so {what} waits."})
    r = td.dispatch("make build", task_label="ticket #845: guard")
    assert r.ok is False and r.waiting is False and "so ticket #845: guard waits" in r.error
    assert seen == [None], "a caller that didn't hand over a command to re-run gets a refusal, nothing queued"


def test_async_work_hands_over_its_rerun_and_is_reported_waiting(monkeypatch):
    import memory_guard
    _local(monkeypatch)
    seen = []
    monkeypatch.setattr(memory_guard, "guard", lambda what, argv, cwd, **k: seen.append(argv) or
                        {"ok": False, "queued": True, "message": "waits"})
    r = td.dispatch("make build", mode="async", queue_argv=["python", "task_dispatch.py", "make build", "--async"])
    assert r.ok is False and r.waiting is True and seen == [["python", "task_dispatch.py", "make build", "--async"]]


def test_work_sent_to_another_mac_is_not_checked_against_this_macs_memory(monkeypatch):
    import memory_guard
    monkeypatch.setattr(td, "select_machine", lambda target=None, need=None: ("macbook-pro-1", {"is_self": False, "tailscale_hostname": "mbp"}))
    monkeypatch.setattr(memory_guard, "guard", lambda *a, **k: pytest.fail("not this Mac's memory"))
    monkeypatch.setattr(td, "_run_remote", lambda *a, **k: td.DispatchResult(ok=True, device_id="macbook-pro-1"))
    assert td.dispatch("true").ok is True


def test_a_finished_task_starts_the_next_one_queued_for_memory():
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1")
    trap = script[script.index("trap "):script.index("' EXIT")]
    assert '"$HOME/.agents/lib/memory_guard.py" kick' in trap


def test_online_hosts_says_none_when_tailscale_cannot_run_and_dispatch_still_gets_a_set(monkeypatch):
    # marvin#889: "the CLI can't run" must be distinguishable from "every peer is offline".
    import task_dispatch as td

    def missing(*a, **k):
        raise FileNotFoundError("no tailscale")
    monkeypatch.setattr(td.subprocess, "run", missing)
    assert td.tailscale_online_hosts_or_none() is None
    assert td._tailscale_online_hosts() == set()


def test_online_hosts_says_none_when_tailscale_exits_non_zero(monkeypatch):
    import subprocess as sp
    import task_dispatch as td
    monkeypatch.setattr(td.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 1, "", "failed to connect to local tailscaled"))
    assert td.tailscale_online_hosts_or_none() is None


def test_online_hosts_reads_peers_when_tailscale_answers(monkeypatch):
    import subprocess as sp
    import task_dispatch as td
    out = ("100.82.55.107    gils-mac-mini   geskayo@  macOS  -\n"
           "100.80.189.85    mbp             geskayo@  macOS  active; direct 192.168.0.40:41641\n"
           "100.102.243.126  box             geskayo@  linux  offline, last seen 1d ago\n")
    monkeypatch.setattr(td.subprocess, "run", lambda *a, **k: sp.CompletedProcess(a, 0, out, ""))
    assert td.tailscale_online_hosts_or_none() == {"gils-mac-mini", "mbp"}
