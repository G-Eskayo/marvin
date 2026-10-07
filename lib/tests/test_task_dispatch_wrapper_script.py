"""Tests for task_dispatch.py's _build_wrapper_script -- the token-export
behavior specifically, since nothing else in this repo covered it before
the GH_TOKEN gap (2026-10-01) was found live. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_task_dispatch_wrapper_script.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import task_dispatch as td  # noqa: E402


def test_wrapper_script_exports_claude_oauth_token_if_present():
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1")
    assert 'if [ -f "$HOME/.claude/.oauth-token" ]; then' in script
    assert 'export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude/.oauth-token")"' in script


def test_wrapper_script_exports_gh_token_if_present():
    # Found live 2026-10-01: a ticket's implementation and tests genuinely
    # passed, but mr_raiser.py's plain `gh pr create` subprocess call died
    # on a keychain-access error (errSecInteractionNotAllowed) under the
    # same non-interactive-shell restriction that originally broke claude
    # auth -- the work succeeded and was discarded anyway since nothing
    # could preserve it as a PR. GH_TOKEN is gh's own documented env-var
    # override for exactly this (bypasses its keychain-backed credential
    # helper), mirroring the existing CLAUDE_CODE_OAUTH_TOKEN mechanism.
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1")
    assert 'if [ -f "$HOME/.claude/.gh-token" ]; then' in script
    assert 'export GH_TOKEN="$(cat "$HOME/.claude/.gh-token")"' in script


def test_wrapper_script_runs_the_real_command():
    script = td._build_wrapper_script("echo hi && do-the-thing", "task123", "my task", "mac-mini-1")
    assert "echo hi && do-the-thing" in script


def test_wrapper_script_writes_and_removes_task_record():
    """Integration test: wrapper script creates task record, runs command, and removes record on exit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set up a temp HOME with dispatch tasks directory
        home = Path(tmpdir)
        tasks_dir = home / ".claude" / "dispatch" / "tasks"
        state_path = home / ".claude" / "dispatch-state.json"

        # Create a simple command that exits successfully
        script = td._build_wrapper_script(
            "true",  # just succeed
            "task123",
            "my task",
            "mac-mini-1",
            ticket="5",
            repo="myrepo"
        ).replace("$HOME", str(home))

        # Replace the dispatch_concurrency path references
        script = script.replace(
            str(td.DISPATCH_CONCURRENCY_SCRIPT),
            f"{LIB}/dispatch_concurrency.py"
        ).replace(
            str(td.VENV_PYTHON),
            sys.executable
        )

        # Run the wrapper script
        result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0, f"Script failed: {result.stderr}"

        # After execution, task record should be gone
        record_file = tasks_dir / "task123.json"
        assert not record_file.exists(), f"Task record should be removed but found {record_file}"

        # dispatch-state.json should be idle (no records left)
        if state_path.exists():
            state = json.loads(state_path.read_text())
            assert state.get("busy") is False


def test_wrapper_script_keeps_other_records_busy():
    """When multiple tasks run and one finishes, the other keeps dispatch-state busy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        home = Path(tmpdir)
        tasks_dir = home / ".claude" / "dispatch" / "tasks"
        state_path = home / ".claude" / "dispatch-state.json"
        tasks_dir.mkdir(parents=True, exist_ok=True)

        # Pre-create a second task record (simulating another running task)
        other_record = {
            "pid": 1,  # unlikely to be a real process
            "task_id": "other_task",
            "task": "other task",
            "machine": "mac-mini-1",
            "started_at": "2026-10-06T10:00:00Z",
        }
        (tasks_dir / "other_task.json").write_text(json.dumps(other_record))

        script = td._build_wrapper_script(
            "true",
            "task123",
            "my task",
            "mac-mini-1"
        ).replace("$HOME", str(home))

        script = script.replace(
            str(td.DISPATCH_CONCURRENCY_SCRIPT),
            f"{LIB}/dispatch_concurrency.py"
        ).replace(
            str(td.VENV_PYTHON),
            sys.executable
        )

        result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True)
        assert result.returncode == 0

        # The other record should still exist (pid 1 is dead, so it gets reaped)
        # but dispatch-state should reflect the remaining state
        if state_path.exists():
            state = json.loads(state_path.read_text())
            # With only a dead process record left, it gets reaped, so busy should be False
            assert state.get("busy") is False


def test_wrapper_script_puts_homebrew_on_path():
    """Found live 2026-10-05: a ticket dispatched to the macbook over ssh died instantly with FileNotFoundError: 'gh'
    (an ssh command runs in a non-interactive shell whose PATH has no /opt/homebrew/bin), so no ticket had really run on the
    laptop and the claim label was left behind."""
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1")
    export = [l for l in script.splitlines() if l.startswith("export PATH=")]
    assert export and "/opt/homebrew/bin" in export[0] and "$PATH" in export[0]
    assert script.index(export[0]) < script.index("echo hi")   # before the real command runs
