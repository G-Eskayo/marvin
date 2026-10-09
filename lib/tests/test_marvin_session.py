"""The MARVIN button's session launcher (marvin#228): a ready Interactive MARVIN session in WezTerm."""
import json
import subprocess
from pathlib import Path

import pytest

import cleanup_sweep
import marvin_launcher as ml
import marvin_session as ms

AGENTS = Path(__file__).resolve().parents[2]


def test_slug_is_short_lowercase_and_shell_safe():
    assert ms.slug("Header button: open a MARVIN session in WezTerm!") == "header-button-open-a-marvin-session-in"
    assert ms.branch_for(228, "Header button") == "ticket/228-header-button"


def test_the_cleanup_sweep_reads_the_ticket_from_a_session_branch():
    assert cleanup_sweep._extract_issue_number("ticket/228-header-button") == 228
    assert cleanup_sweep._extract_issue_number("pipeline/g-eskayo/marvin#188") == 188


def _repo(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True, capture_output=True)
    git = lambda *a: subprocess.run(["git", "-C", str(clone), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                                    check=True, capture_output=True, text=True)
    (clone / "f").write_text("x")
    git("add", "f"); git("commit", "-qm", "init"); git("push", "-q", "origin", "main")
    return clone


def test_a_ticket_gets_its_own_worktree_on_its_ticket_branch_and_reuses_it(tmp_path, monkeypatch):
    clone = _repo(tmp_path)
    monkeypatch.setattr(ms, "WORKTREES_ROOT", tmp_path / "wt")
    first = ms.session_dir(clone, 228, "Header button")
    assert first == tmp_path / "wt" / "ticket-228-header-button"
    head = subprocess.run(["git", "-C", str(first), "branch", "--show-current"], capture_output=True, text=True)
    assert head.stdout.strip() == "ticket/228-header-button"
    (first / "work.txt").write_text("in progress")
    assert ms.session_dir(clone, 228, "Header button") == first
    assert (first / "work.txt").read_text() == "in progress"  # reused, never recreated


def test_no_ticket_starts_at_home_never_in_the_shared_checkout():
    assert ms.session_dir(AGENTS, None, None) == Path.home()


def test_the_shell_script_sets_its_own_environment_and_keeps_the_token_off_the_command_line(tmp_path):
    script = ms.shell_script(tmp_path)
    assert f"cd {tmp_path}" in script
    assert "export PATH=" in script and "/.agents/venv/bin" in script and "/.local/bin" in script
    assert f"export {ml.KIND_ENV}=interactive" in script
    assert 'GH_TOKEN="$(cat' in script  # read inside the shell, so `ps` never shows it
    assert script.rstrip().endswith("exec claude")


def test_spawns_into_the_running_wezterm_and_falls_back_to_starting_it(tmp_path):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1 if cmd[1:3] == ["cli", "spawn"] else 0, "", "no mux")

    started = []
    ms.open_in_wezterm(tmp_path, wezterm="/x/wezterm", run=run, start=lambda cmd: started.append(cmd),
                       state_file=tmp_path / "window.json", identity=lambda run: None)
    spawn = next(c for c in calls if c[1:3] == ["cli", "spawn"])
    assert spawn[:4] == ["/x/wezterm", "cli", "spawn", "--new-window"]
    assert started and started[0][:2] == ["/x/wezterm", "start"]


class FakeWezTerm:
    """A WezTerm mux: windows hold panes; `cli spawn` adds a pane to a window or a new one, `cli list` reports them."""

    def __init__(self, windows=None, fail_spawn=False):
        self.windows = {w: list(p) for w, p in (windows or {}).items()}
        self.next_pane = 100
        self.fail_spawn = fail_spawn
        self.spawns = []

    def __call__(self, cmd, **kw):
        if cmd[1:3] == ["cli", "list"]:
            rows = [{"window_id": w, "pane_id": p} for w, panes in self.windows.items() for p in panes]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(rows), "")
        if cmd[1:3] == ["cli", "spawn"]:
            self.spawns.append(cmd)
            if self.fail_spawn:
                return subprocess.CompletedProcess(cmd, 1, "", "no mux")
            if "--window-id" in cmd:
                window = int(cmd[cmd.index("--window-id") + 1])
                if window not in self.windows:
                    return subprocess.CompletedProcess(cmd, 1, "", "window not found")
            else:
                window = max(self.windows, default=-1) + 1
                self.windows[window] = []
            self.next_pane += 1
            self.windows[window].append(self.next_pane)
            return subprocess.CompletedProcess(cmd, 0, f"{self.next_pane}\n", "")
        raise AssertionError(f"unexpected command {cmd}")


def _open(tmp_path, wez, gui="2279 Wed Sep 30 15:46:12 2026", started=None):
    ms.open_in_wezterm(tmp_path, wezterm="/x/wezterm", run=wez, state_file=tmp_path / "window.json",
                       identity=lambda run: gui, start=(started.append if started is not None else lambda c: None))


def test_a_second_press_opens_a_tab_in_the_window_the_first_press_opened(tmp_path):
    wez = FakeWezTerm({0: [1, 2]})  # Gil's own window
    _open(tmp_path, wez)
    _open(tmp_path, wez)
    _open(tmp_path, wez)
    assert "--new-window" in wez.spawns[0]
    assert wez.spawns[1][wez.spawns[1].index("--window-id") + 1] == "1"
    assert "--new-window" not in wez.spawns[2] and "--window-id" in wez.spawns[2]
    assert wez.windows == {0: [1, 2], 1: [101, 102, 103]}  # Gil's window untouched, one MARVIN window, three tabs


def test_a_closed_marvin_window_means_the_next_press_opens_a_new_window(tmp_path):
    wez = FakeWezTerm({0: [1]})
    _open(tmp_path, wez)
    del wez.windows[1]  # Gil closed it
    _open(tmp_path, wez)
    assert "--new-window" in wez.spawns[1]
    _open(tmp_path, wez)
    assert wez.spawns[2][wez.spawns[2].index("--window-id") + 1] == "1"  # remembers the replacement


def test_after_wezterm_restarts_a_reused_window_id_is_never_trusted(tmp_path):
    """Window ids restart at 0, so a saved id from the last run may now be one of Gil's own windows."""
    wez = FakeWezTerm({0: [1]})
    _open(tmp_path, wez)  # MARVIN window = 1
    restarted = FakeWezTerm({0: [1], 1: [2]})  # new run: window 1 exists but isn't ours
    _open(tmp_path, restarted, gui="4100 Fri Oct  9 21:00:00 2026")
    assert "--new-window" in restarted.spawns[0]


def test_unknown_wezterm_identity_never_reuses_a_window(tmp_path):
    wez = FakeWezTerm({})
    _open(tmp_path, wez, gui=None)
    _open(tmp_path, wez, gui=None)
    assert all("--new-window" in s for s in wez.spawns)


def test_a_window_that_vanishes_between_check_and_spawn_still_gets_a_session(tmp_path):
    wez = FakeWezTerm({})
    _open(tmp_path, wez)
    real_call = wez.__call__

    def racing(cmd, **kw):
        if cmd[1:3] == ["cli", "spawn"] and "--window-id" in cmd:
            wez.windows.pop(0, None)  # closed just now
        return real_call(cmd, **kw)

    ms.open_in_wezterm(tmp_path, wezterm="/x/wezterm", run=racing, state_file=tmp_path / "window.json",
                       identity=lambda run: "2279 x", start=lambda c: None)
    assert "--new-window" in wez.spawns[-1]


def test_a_corrupt_or_foreign_state_file_is_ignored_not_fatal(tmp_path):
    for junk in ("{not json", "[]", '{"gui": "2279 Wed Sep 30 15:46:12 2026", "window_id": "zero"}', ""):
        (tmp_path / "window.json").write_text(junk)
        wez = FakeWezTerm({0: [1]})
        _open(tmp_path, wez)
        assert "--new-window" in wez.spawns[0]


def test_starting_wezterm_from_scratch_forgets_the_old_window(tmp_path):
    wez = FakeWezTerm({})
    _open(tmp_path, wez)
    assert (tmp_path / "window.json").exists()
    dead = FakeWezTerm({}, fail_spawn=True)
    started = []
    _open(tmp_path, dead, started=started)
    assert started and not (tmp_path / "window.json").exists()


def test_concurrent_presses_open_one_window_not_two(tmp_path):
    import threading
    wez = FakeWezTerm({})
    lock = threading.Lock()

    def slow(cmd, **kw):
        with lock:
            return wez(cmd, **kw)

    threads = [threading.Thread(target=_open, args=(tmp_path, slow)) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(wez.windows) == 1 and len(wez.windows[0]) == 6


def test_gui_identity_reads_the_wezterm_gui_process_and_its_start_time():
    ps = ("  301 Mon Oct  5 09:00:00 2026     /usr/sbin/cfprefsd\n"
          " 2279 Wed Sep 30 15:46:12 2026     /Applications/WezTerm.app/Contents/MacOS/wezterm-gui\n")
    run = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, ps, "")
    assert ms.gui_identity(run) == "2279 Wed Sep 30 15:46:12 2026"
    assert ms.gui_identity(lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, ps.splitlines()[0], "")) is None
    assert ms.gui_identity(lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "denied")) is None


def test_a_missing_wezterm_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(ms, "WEZTERM_CANDIDATES", (Path("/nonexistent/wezterm"),))
    monkeypatch.setattr(ms.shutil, "which", lambda name: None)
    with pytest.raises(ms.SessionError, match="WezTerm"):
        ms.find_wezterm()


def test_the_phone_can_never_open_a_desktop_session():
    for path in (AGENTS / "dashboard/mobile-backend").rglob("*.js"):
        if "node_modules" in path.parts:
            continue
        src = path.read_text(errors="ignore")
        assert "marvin_session" not in src and "openSession" not in src, path
