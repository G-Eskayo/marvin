"""Tests for notify.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_notify.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import notify as nf  # noqa: E402


def test_to_open_url_passes_through_urls():
    assert nf._to_open_url("https://github.com/x/y/pull/1") == "https://github.com/x/y/pull/1"
    assert nf._to_open_url("file:///tmp/foo.md") == "file:///tmp/foo.md"


def test_to_open_url_converts_local_path(tmp_path):
    target = tmp_path / "quarantine.md"
    target.write_text("x")
    assert nf._to_open_url(str(target)) == target.resolve().as_uri()


def test_uses_terminal_notifier_with_open_flag_when_available(monkeypatch):
    calls = []
    monkeypatch.setattr(nf.shutil, "which", lambda name: "/opt/homebrew/bin/terminal-notifier")
    monkeypatch.setattr(nf.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    nf.notify("title", "message", open_target="https://example.com/pr/1")

    cmd = calls[0]
    assert cmd[0] == "/opt/homebrew/bin/terminal-notifier"
    assert "-open" in cmd
    assert cmd[cmd.index("-open") + 1] == "https://example.com/pr/1"


def test_falls_back_to_osascript_without_terminal_notifier(monkeypatch):
    calls = []
    monkeypatch.setattr(nf.shutil, "which", lambda name: None)
    monkeypatch.setattr(nf.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    nf.notify("title", "message", open_target="https://example.com/pr/1")

    cmd = calls[0]
    assert cmd[0] == "osascript"
    # plain display notification has no click-action mechanism to pass open_target through
    assert "-open" not in cmd


def test_notify_never_raises_on_failure(monkeypatch):
    monkeypatch.setattr(nf.shutil, "which", lambda name: "/opt/homebrew/bin/terminal-notifier")

    def failing_run(cmd, **kw):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(nf.subprocess, "run", failing_run)

    nf.notify("title", "message")  # should not raise
