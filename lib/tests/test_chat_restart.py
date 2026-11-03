"""marvin#1086: a chat tab still on an old Claude Code is resumed on the new one, only while idle on Gil's turn."""
import json
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import chat_restart as cr  # noqa: E402
import wezterm_cli  # noqa: E402


def chat(**over):
    c = {"id": "c1", "mac": "macbook-pro", "socket": "/s/gui-sock-1", "pane": 16, "window_id": 1, "tab_id": 4,
         "state": "your-turn", "title": "✳ PR 941", "unknown": False, "claude_pid": 59044, "session": "abc-123",
         "cwd": "/wt/ticket-941", "claude_version": "2.1.300"}
    c.update(over)
    return c


# ── which version ───────────────────────────────────────────────────────────────────────────

def test_the_installed_version_is_read_from_the_package_next_to_the_binary(tmp_path):
    pkg = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code"
    (pkg / "bin").mkdir(parents=True)
    (pkg / "bin" / "claude.exe").touch()
    (pkg / "package.json").write_text(json.dumps({"name": "@anthropic-ai/claude-code", "version": "2.1.317"}))
    link = tmp_path / "claude"
    link.symlink_to(pkg / "bin" / "claude.exe")
    assert cr.installed_version(which=lambda n: str(link)) == "2.1.317"


def test_a_native_install_reads_the_version_from_its_folder(tmp_path):
    exe = tmp_path / "share" / "claude" / "versions" / "2.1.320"
    exe.parent.mkdir(parents=True)
    exe.touch()
    link = tmp_path / "claude"
    link.symlink_to(exe)
    assert cr.installed_version(which=lambda n: str(link)) == "2.1.320"


@pytest.mark.parametrize("which", [lambda n: None, lambda n: "/nonexistent/claude"])
def test_no_claude_means_no_version(which):
    assert cr.installed_version(which=which) is None


@pytest.mark.parametrize("a,b,newer", [("2.1.317", "2.1.300", True), ("2.1.300", "2.1.300", False),
                                       ("2.1.300", "2.1.317", False), ("2.10.0", "2.9.9", True), ("x", "2.1.0", False)])
def test_versions_compare_numerically(a, b, newer):
    assert cr.newer(a, b) is newer


# ── when it is safe ─────────────────────────────────────────────────────────────────────────

def why(c=None, installed="2.1.317", focused=(), shells=()):
    return cr.why_not(c or chat(), installed, set(focused), list(shells))


def test_an_idle_outdated_chat_on_gils_turn_is_restarted():
    assert why() is None


def test_a_current_chat_is_left_alone():
    assert "current" in why(chat(claude_version="2.1.317"))


def test_a_chat_with_no_recorded_version_is_left_alone():
    assert why(chat(claude_version=None))


@pytest.mark.parametrize("over", [{"state": "working"}, {"state": "waiting"}, {"state": "done"},
                                  {"title": "◐ PR 941"}, {"unknown": True}])
def test_a_busy_waiting_or_unknown_chat_is_never_restarted(over):
    assert why(chat(**over))


def test_the_chat_gil_is_looking_at_is_never_restarted():
    assert "looking" in why(focused=[16])


def test_a_background_job_the_chat_started_blocks_it():
    assert "background" in why(shells=["/bin/bash -c npm run build"])


def test_no_installed_version_blocks_it():
    assert why(installed=None)


def test_background_shells_are_told_apart_from_mcp_servers_and_caffeinate():
    rows = {59044: [(1, "node /x/mcp-server.js"), (2, "caffeinate -i -t 300"), (3, "/bin/bash -c sleep 600"),
                    (4, "/opt/homebrew/bin/python3 server.py"), (5, "zsh -c make")]}
    def run(cmd, **k):
        ppid = int(cmd[cmd.index("-P") + 1]) if "-P" in cmd else None
        out = "\n".join(f"{pid} {c}" for pid, c in rows.get(ppid, []))
        return subprocess.CompletedProcess(cmd, 0, out, "")
    assert cr.shell_children(59044, run=run) == ["/bin/bash -c sleep 600", "zsh -c make"]


# ── the restart ─────────────────────────────────────────────────────────────────────────────

class FakeWez:
    def __init__(self, spawn_fails=False):
        self.calls, self.spawn_fails = [], spawn_fails

    def spawn(self, cwd, program, window_id=None, new_window=False):
        self.calls.append(("spawn", str(cwd), window_id, program))
        if self.spawn_fails:
            raise wezterm_cli.WeztermError("spawn failed")
        return 99

    def kill_pane(self, pane):
        self.calls.append(("kill", pane))


def restart(c=None, wez=None, recheck=None, log=None, notify=None):
    wez = wez or FakeWez()
    out = cr.restart(c or chat(), "2.1.317", wez=wez, recheck=recheck or (lambda: None),
                     log=(log.append if log is not None else lambda e: None),
                     notify=(notify.append if notify is not None else lambda t: None))
    return out, wez


def test_it_resumes_the_same_session_in_a_new_tab_of_the_same_window_then_closes_the_old_one():
    out, wez = restart()
    assert out["ok"] and out["pane"] == 99
    kind, cwd, window, program = wez.calls[0]
    assert (kind, cwd, window) == ("spawn", "/wt/ticket-941", 1)
    script = program[-1]
    assert "exec claude --resume abc-123" in script and "MARVIN_LAUNCH_KIND=interactive" in script
    assert wez.calls[1] == ("kill", 16)


def test_a_session_id_is_quoted_so_it_can_never_become_shell_code():
    out, wez = restart(chat(session="x; rm -rf ~"))
    assert "--resume 'x; rm -rf ~'" in wez.calls[0][3][-1]


def test_a_failed_spawn_keeps_the_old_chat_and_reports_it():
    log, notes = [], []
    out, wez = restart(wez=FakeWez(spawn_fails=True), log=log, notify=notes)
    assert not out["ok"] and all(c[0] != "kill" for c in wez.calls)
    assert log[-1]["ok"] is False and notes and "couldn't" in notes[-1]


def test_if_gil_starts_typing_during_the_swap_the_new_tab_is_closed_and_the_old_kept():
    out, wez = restart(recheck=lambda: "you started typing in it")
    assert not out["ok"] and wez.calls[-1] == ("kill", 99)


def test_a_session_without_an_id_is_never_restarted():
    out, wez = restart(chat(session=""))
    assert not out["ok"] and wez.calls == []


def test_each_restart_is_logged_and_announced():
    log, notes = [], []
    restart(log=log, notify=notes)
    assert log[-1]["ok"] and log[-1]["from"] == "2.1.300" and log[-1]["to"] == "2.1.317"
    assert notes and "2.1.317" in notes[-1]


# ── sweep: every idle outdated chat, one by one ─────────────────────────────────────────────

def test_sweep_restarts_only_the_safe_ones(monkeypatch):
    chats = [chat(id="a", pane=1), chat(id="b", pane=2, state="working"), chat(id="c", pane=3, claude_version="2.1.317"),
             chat(id="d", pane=4, mac="mac-mini-1")]
    done = []
    out = cr.sweep(chats=lambda: chats, installed=lambda: "2.1.317", focused=lambda c: set(), shells=lambda c: [],
                   do_restart=lambda c, v: done.append(c["id"]) or {"ok": True}, here="macbook-pro")
    assert done == ["a"] and {r["id"]: r["why"] is None for r in out}["b"] is False


def test_sweep_with_nothing_installed_does_nothing():
    out = cr.sweep(chats=lambda: [chat()], installed=lambda: None, focused=lambda c: set(), shells=lambda c: [],
                   do_restart=lambda c, v: pytest.fail("no version"), here="macbook-pro")
    assert out == []


def test_a_sweep_that_fails_on_one_chat_still_does_the_rest():
    calls = []
    def flaky(c, v):
        calls.append(c["id"])
        if c["id"] == "a":
            raise RuntimeError("boom")
        return {"ok": True}
    cr.sweep(chats=lambda: [chat(id="a", pane=1), chat(id="b", pane=2)], installed=lambda: "2.1.317",
             focused=lambda c: set(), shells=lambda c: [], do_restart=flaky, here="macbook-pro")
    assert calls == ["a", "b"]


# ── the trigger: the update itself, watched (no polling) ────────────────────────────────────

def test_the_watch_job_watches_the_installed_package_and_runs_a_sweep(tmp_path):
    pkg = tmp_path / "package.json"
    pkg.write_text("{}")
    plist = plistlib.loads(cr.watch_plist(pkg, python="/py", home=tmp_path).encode())
    assert plist["WatchPaths"] == [str(pkg)]
    assert plist["ProgramArguments"][-1] == "sweep" and plist["ThrottleInterval"] >= 30
    assert "RunAtLoad" not in plist and "StartInterval" not in plist


def test_the_watch_job_is_catalogued():
    import job_catalog
    assert "claude-update-watch" in job_catalog.JOBS


def test_the_per_mac_install_loads_the_watch():
    assert "chat_restart.install_watch()" in (Path(__file__).resolve().parents[1] / "marvin_hooks.py").read_text()


def test_a_stop_on_an_old_version_starts_a_sweep_and_a_current_one_does_not(tmp_path, monkeypatch):
    import session_work as sw
    monkeypatch.setattr(sw, "STATE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(sw, "_mac", lambda: "m")
    monkeypatch.setenv("WEZTERM_PANE", "16")
    monkeypatch.setenv("WEZTERM_UNIX_SOCKET", "/s")
    started = []
    monkeypatch.setattr(sw, "_start_detached", lambda *a: started.append(a))
    (tmp_path / "s.json").write_text(json.dumps({"chats": {"m|/s|16": {**chat(), "state": "working"}}}))
    monkeypatch.setattr(sw, "_installed_claude", lambda: "2.1.300")
    sw.handle("stop", {"session_id": "abc-123"})
    assert started == []
    monkeypatch.setattr(sw, "_installed_claude", lambda: "2.1.317")
    sw.handle("stop", {"session_id": "abc-123"})
    assert started == [("sweep",)]
