"""notify.py (#1123): `desktop()` is the alert path's desktop channel and reports its real result; `notify()` goes
through the one alert path. Run: ~/.agents/venv/bin/python -m pytest lib/tests/test_notify.py -v"""
from __future__ import annotations
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import notify as nf  # noqa: E402
import mr_notification as mn  # noqa: E402


def _ran(calls, rc=0, stderr=b""):
    return lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=rc, stderr=stderr)


def test_to_open_url_passes_through_urls():
    assert nf._to_open_url("https://github.com/x/y/pull/1") == "https://github.com/x/y/pull/1"
    assert nf._to_open_url("file:///tmp/foo.md") == "file:///tmp/foo.md"


def test_to_open_url_converts_local_path(tmp_path):
    target = tmp_path / "quarantine.md"
    target.write_text("x")
    assert nf._to_open_url(str(target)) == target.resolve().as_uri()


def test_uses_terminal_notifier_with_open_flag_when_available(monkeypatch):
    calls = []
    monkeypatch.setattr(nf, "_notifier", lambda: "/opt/homebrew/bin/terminal-notifier")
    monkeypatch.setattr(nf.subprocess, "run", _ran(calls))
    assert nf.desktop("title", "message", open_target="https://example.com/pr/1") == "sent"
    cmd = calls[0]
    assert cmd[0] == "/opt/homebrew/bin/terminal-notifier"
    assert cmd[cmd.index("-open") + 1] == "https://example.com/pr/1"


def test_finds_terminal_notifier_in_homebrew_when_launchds_path_lacks_it(monkeypatch, tmp_path):
    """launchd's default PATH has no /opt/homebrew/bin: the banner silently lost its click action (#1123)."""
    fake = tmp_path / "terminal-notifier"
    fake.write_text("#!/bin/sh\n")
    fake.chmod(0o755)
    monkeypatch.setattr(nf.shutil, "which", lambda name: None)
    monkeypatch.setattr(nf, "NOTIFIER_PLACES", ("/nonexistent/terminal-notifier", str(fake)))
    assert nf._notifier() == str(fake)


def test_a_non_executable_notifier_is_not_used(monkeypatch, tmp_path):
    fake = tmp_path / "terminal-notifier"
    fake.write_text("x")
    fake.chmod(0o644)
    monkeypatch.setattr(nf.shutil, "which", lambda name: None)
    monkeypatch.setattr(nf, "NOTIFIER_PLACES", (str(fake),))
    assert nf._notifier() is None


def test_falls_back_to_osascript_and_says_the_click_action_is_missing(monkeypatch):
    calls = []
    monkeypatch.setattr(nf, "_notifier", lambda: None)
    monkeypatch.setattr(nf.subprocess, "run", _ran(calls))
    result = nf.desktop("title", "message", open_target="https://example.com/pr/1")
    assert calls[0][0] == "osascript" and "-open" not in calls[0]
    assert result.startswith("sent") and "no click action" in result


def test_a_notifier_that_exits_non_zero_is_a_failure_not_sent(monkeypatch):
    monkeypatch.setattr(nf, "_notifier", lambda: "/opt/homebrew/bin/terminal-notifier")
    monkeypatch.setattr(nf.subprocess, "run", _ran([], rc=1, stderr=b"line\nNotification Center unavailable\n"))
    with pytest.raises(RuntimeError, match="exited 1: Notification Center unavailable"):
        nf.desktop("t", "m")


def test_quotes_and_backslashes_cannot_break_out_of_the_applescript_string(monkeypatch):
    calls = []
    monkeypatch.setattr(nf, "_notifier", lambda: None)
    monkeypatch.setattr(nf.subprocess, "run", _ran(calls))
    nf.desktop('a" & do shell script "rm -rf ~', 'b\\" & beep')
    script = calls[0][2]
    assert 'display notification "b\\\\\\" & beep" with title "a\\" & do shell script \\"rm -rf ~"' == script


def test_notify_goes_through_the_one_alert_path(monkeypatch):
    seen = []
    monkeypatch.setattr(mn, "_fire", lambda t, m, o=None: seen.append((t, m, o)) or {"delivered": ["desktop"]})
    assert nf.notify("t", "m", open_target="x") == {"delivered": ["desktop"]}
    assert seen == [("t", "m", "x")]


def test_notify_never_raises_even_when_the_alert_path_does(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("simulated")
    monkeypatch.setattr(mn, "_fire", boom)
    out = nf.notify("title", "message")
    assert out["delivered"] == [] and "simulated" in out["error"]
