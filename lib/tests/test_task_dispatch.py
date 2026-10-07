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
    script = td._build_wrapper_script("echo hi", "abc", "label", "mac-mini-1")
    path_line = next(l for l in script.splitlines() if l.startswith("export PATH="))
    assert "$HOME/.local/bin" in path_line
