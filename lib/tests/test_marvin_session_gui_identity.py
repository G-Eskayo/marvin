"""WezTerm session launcher: restructure open_in_wezterm for None gui_identity (plan §2).

Tests 6-7: When gui_identity() returns None, skip both _spawn() attempts and fall
straight to start() within the same fcntl lock."""

from pathlib import Path
from unittest.mock import Mock, call

import pytest

import marvin_session as ms


class TestOpenInWeztermNoneGuiIdentity:
    """Tests 6-7: None gui_identity() skips both _spawn() calls."""

    def test_none_gui_identity_skips_spawn_calls_and_goes_straight_to_start(self, tmp_path, monkeypatch):
        """Test 6: When gui_identity() returns None, skip _spawn() and go straight to start()."""
        directory = tmp_path / "session"
        directory.mkdir()
        state_file = tmp_path / "window.json"
        lock_file = state_file.with_suffix(".lock")

        spawn_calls = []
        start_calls = []

        def fake_run(*args, **kwargs):
            return Mock(returncode=0, stdout="")

        def fake_spawn(wezterm, where, directory, program, run):
            spawn_calls.append((where, directory, program))
            return Mock(returncode=0, stdout="")

        def fake_start(cmd):
            start_calls.append(cmd)

        def fake_identity(run):
            return None  # No running WezTerm

        monkeypatch.setattr(ms, "_spawn", fake_spawn)
        monkeypatch.setattr(ms, "_start_detached", fake_start)

        ms.open_in_wezterm(
            directory,
            wezterm="/opt/homebrew/bin/wezterm",
            run=fake_run,
            start=fake_start,
            state_file=state_file,
            identity=fake_identity
        )

        # _spawn should not be called at all
        assert len(spawn_calls) == 0, "When gui_identity() is None, _spawn() should not be called"
        # start() should be called
        assert len(start_calls) == 1, "When gui_identity() is None, start() should be called once"
        assert start_calls[0][0] == "/opt/homebrew/bin/wezterm"

    def test_with_running_gui_identity_still_attempts_spawn(self, tmp_path, monkeypatch):
        """Test 7: When gui_identity() returns a value, _spawn() is attempted (existing behavior)."""
        directory = tmp_path / "session"
        directory.mkdir()
        state_file = tmp_path / "window.json"

        spawn_calls = []

        def fake_run(*args, **kwargs):
            return Mock(returncode=0, stdout="")

        def fake_spawn(wezterm, where, directory, program, run):
            spawn_calls.append((where, directory, program))
            return Mock(returncode=0, stdout="12345\n")  # pane_id

        def fake_windows(wezterm, run):
            return {12345: 1}  # pane_id -> window_id

        def fake_identity(run):
            return "1234 2026-10-26"  # Running WezTerm

        monkeypatch.setattr(ms, "_spawn", fake_spawn)
        monkeypatch.setattr(ms, "_windows", fake_windows)

        ms.open_in_wezterm(
            directory,
            wezterm="/opt/homebrew/bin/wezterm",
            run=fake_run,
            start=lambda *a: None,
            state_file=state_file,
            identity=fake_identity
        )

        # _spawn should be called
        assert len(spawn_calls) > 0, "When gui_identity() returns a value, _spawn() should be called"
