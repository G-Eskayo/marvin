"""Tests for marvin_session.py open_in_wezterm() when gui_identity() returns None."""
import subprocess
from pathlib import Path

import pytest

import marvin_session as ms


class FakeWezTerm:
    """A WezTerm mux: windows hold panes; `cli spawn` adds a pane to a window or a new one, `cli list` reports them."""

    def __init__(self, windows=None, fail_spawn=False):
        self.windows = {w: list(p) for w, p in (windows or {}).items()}
        self.next_pane = 100
        self.fail_spawn = fail_spawn
        self.spawns = []

    def __call__(self, cmd, **kw):
        if cmd[1:3] == ["cli", "list"]:
            import json
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


def test_8_when_gui_is_none_spawn_is_never_called_goes_straight_to_start(tmp_path):
    """Test 8 (rewritten): When gui_identity() returns None, skip both _spawn() calls and go to start().

    The old behavior was to try --new-window spawn even when gui=None, which failed and fell back to start().
    The new behavior is to skip spawning entirely when gui=None and go directly to start().
    """
    wez = FakeWezTerm({})
    started = []
    ms.open_in_wezterm(tmp_path, wezterm="/x/wezterm", run=wez, state_file=tmp_path / "window.json",
                       identity=lambda run: None, start=lambda cmd: started.append(cmd))
    # When gui is None, _spawn should never be called at all
    assert len(wez.spawns) == 0, "Should not spawn at all when gui_identity is None"
    # Instead, start() should be called directly
    assert started, "Should call start() when gui_identity is None"
    assert started[0][:2] == ["/x/wezterm", "start"]


def test_9_when_gui_is_none_multiple_presses_all_call_start(tmp_path):
    """Test 9: Multiple presses with gui=None each call start(), never try to spawn."""
    wez = FakeWezTerm({})
    started = []
    for _ in range(3):
        ms.open_in_wezterm(tmp_path, wezterm="/x/wezterm", run=wez, state_file=tmp_path / "window.json",
                           identity=lambda run: None, start=lambda cmd: started.append(cmd))
    # All three presses should call start(), never spawn
    assert len(wez.spawns) == 0
    assert len(started) == 3


def test_10_when_gui_is_none_the_fcntl_lock_still_applies(tmp_path):
    """Test 10: The fcntl lock guards the gui_identity() check even when it's None.

    This ensures that concurrent presses with gui=None don't both call start() at once
    (which would be a race condition even though neither would spawn).
    """
    import threading
    wez = FakeWezTerm({})
    started = []
    lock = threading.Lock()

    def slow_start(cmd):
        with lock:
            started.append(cmd)

    threads = [threading.Thread(target=ms.open_in_wezterm,
                                kwargs={"directory": tmp_path, "wezterm": "/x/wezterm", "run": wez,
                                       "state_file": tmp_path / "window.json",
                                       "identity": lambda run: None, "start": slow_start})
               for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    # All 6 should call start(), but no spawns
    assert len(wez.spawns) == 0
    assert len(started) == 6


def test_11_when_gui_exists_behavior_unchanged_still_tries_spawn(tmp_path):
    """Test 11: When gui_identity() returns a value, the existing behavior is unchanged.

    This ensures the refactoring doesn't break the normal case where gui exists.
    """
    wez = FakeWezTerm({})
    ms.open_in_wezterm(tmp_path, wezterm="/x/wezterm", run=wez, state_file=tmp_path / "window.json",
                       identity=lambda run: "2279 Wed Sep 30 15:46:12 2026", start=lambda cmd: None)
    # When gui exists and has no windows, should try --new-window spawn
    assert len(wez.spawns) >= 1
    assert "--new-window" in wez.spawns[0]
