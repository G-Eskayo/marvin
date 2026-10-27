"""WezTerm session spawning fix for missing GUI identity (tests 23-24).

When gui_identity() returns None (no running WezTerm process found),
open_in_wezterm should skip the mux spawn attempts entirely and go
directly to wezterm start, rather than trying spawns that will fail."""

import json
import subprocess
import marvin_session as ms


class FakeWezTerm:
    """Fake WezTerm for testing spawn behavior."""

    def __init__(self, windows=None, fail_spawn=False):
        self.windows = {w: list(p) for w, p in (windows or {}).items()}
        self.next_pane = 100
        self.fail_spawn = fail_spawn
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)

        if cmd[1:3] == ["cli", "list"]:
            rows = [{"window_id": w, "pane_id": p} for w, panes in self.windows.items() for p in panes]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(rows), "")

        if cmd[1:3] == ["cli", "spawn"]:
            if self.fail_spawn:
                return subprocess.CompletedProcess(cmd, 1, "", "mux not available")
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

        return subprocess.CompletedProcess(cmd, 1, "", "")


def test_23_skip_spawn_when_gui_identity_is_none(tmp_path):
    """When gui_identity returns None, should skip cli spawn entirely."""
    wez = FakeWezTerm()
    started = []

    # gui_identity returns None (no running WezTerm)
    identity = lambda run: None

    ms.open_in_wezterm(
        tmp_path,
        wezterm="/x/wezterm",
        run=wez,
        state_file=tmp_path / "window.json",
        identity=identity,
        start=lambda cmd: started.append(cmd)
    )

    # Should NOT have attempted any cli spawn commands
    spawn_calls = [c for c in wez.calls if len(c) > 2 and c[1:3] == ["cli", "spawn"]]
    assert len(spawn_calls) == 0, "Should not attempt spawn when gui_identity is None"

    # Should have called wezterm start directly
    assert started, "Should have called wezterm start"
    assert started[0][:2] == ["/x/wezterm", "start"]


def test_24_prefers_spawn_when_gui_identity_present(tmp_path):
    """When gui_identity returns a value, should attempt spawn first."""
    # Start with an existing window
    wez = FakeWezTerm({1: [1, 2]})
    started = []

    # gui_identity returns a valid identity (GUI is running)
    identity = lambda run: "1234 Wed Sep 30 15:46:12 2026"

    ms.open_in_wezterm(
        tmp_path,
        wezterm="/x/wezterm",
        run=wez,
        state_file=tmp_path / "window.json",
        identity=identity,
        start=lambda cmd: started.append(cmd)
    )

    # Should have attempted cli spawn commands (list and spawn)
    list_calls = [c for c in wez.calls if len(c) > 2 and c[1:3] == ["cli", "list"]]
    spawn_calls = [c for c in wez.calls if len(c) > 2 and c[1:3] == ["cli", "spawn"]]

    assert len(list_calls) >= 1, "Should call cli list when gui_identity is present"
    assert len(spawn_calls) >= 1, "Should attempt spawn when gui_identity is present"

    # Should NOT have fallen back to wezterm start (spawn succeeded)
    assert not started, "Should not call wezterm start when spawn succeeds"
