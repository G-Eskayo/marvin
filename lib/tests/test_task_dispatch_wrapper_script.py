"""Tests for task_dispatch.py's _build_wrapper_script -- the token-export
behavior specifically, since nothing else in this repo covered it before
the GH_TOKEN gap (2026-10-01) was found live. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_task_dispatch_wrapper_script.py -v
"""
from __future__ import annotations
import sys
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


def test_wrapper_script_marks_busy_then_idle_on_exit():
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1")
    assert '"busy": true' in script
    assert '"busy": false' in script
    assert "trap " in script and "EXIT" in script


def test_wrapper_script_puts_homebrew_on_path():
    """Found live 2026-10-05: a ticket dispatched to the macbook over ssh died instantly with FileNotFoundError: 'gh'
    (an ssh command runs in a non-interactive shell whose PATH has no /opt/homebrew/bin), so no ticket had really run on the
    laptop and the claim label was left behind."""
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1")
    export = [l for l in script.splitlines() if l.startswith("export PATH=")]
    assert export and "/opt/homebrew/bin" in export[0] and "$PATH" in export[0]
    assert script.index(export[0]) < script.index("echo hi")   # before the real command runs


def test_wrapper_script_writes_task_record_with_device_id():
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1")
    assert '.claude/dispatch/tasks/task123.json' in script
    assert '"machine": "mac-mini-1"' in script
    assert '"pid":' in script  # PID injected at runtime


def test_wrapper_script_includes_ticket_and_repo_metadata():
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1",
                                     ticket="42", repo="G-Eskayo/marvin")
    assert '"ticket": "42"' in script
    assert '"repo": "G-Eskayo/marvin"' in script


def test_wrapper_script_calls_refresh_summary_on_start_and_exit():
    script = td._build_wrapper_script("echo hi", "task123", "my task", "mac-mini-1")
    lines = script.splitlines()
    refresh_calls = [l for l in lines if 'refresh-summary' in l]
    assert len(refresh_calls) >= 2  # one on start, one in trap
