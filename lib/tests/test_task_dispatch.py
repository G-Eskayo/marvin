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
