"""Tests for mr_notification.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_mr_notification.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import mr_notification as mn  # noqa: E402


def test_sends_desktop_notification_when_raised(monkeypatch):
    desktop_calls = []
    monkeypatch.setattr(mn, "desktop_notify", lambda title, msg, **kw: desktop_calls.append((title, msg)))
    monkeypatch.setattr(mn, "push_notify", lambda msg: None)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: None)

    mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    assert len(desktop_calls) == 1


def test_desktop_notification_click_opens_the_pr(monkeypatch):
    captured = {}
    monkeypatch.setattr(mn, "desktop_notify", lambda title, msg, **kw: captured.update(kw))
    monkeypatch.setattr(mn, "push_notify", lambda msg: None)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: None)

    mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    assert captured.get("open_target") == "https://github.com/G-Eskayo/marvin/pull/99"


def test_message_identifies_ticket_and_is_concise(monkeypatch):
    captured = {}
    monkeypatch.setattr(mn, "desktop_notify", lambda title, msg, **kw: captured.update(title=title, msg=msg))
    monkeypatch.setattr(mn, "push_notify", lambda msg: None)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: None)

    mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    assert "G-Eskayo/marvin#1" in captured["msg"] or "G-Eskayo/marvin#1" in captured["title"]
    assert len(captured["msg"]) < 200


def test_attempts_push_notification_too(monkeypatch):
    push_calls = []
    monkeypatch.setattr(mn, "desktop_notify", lambda title, msg, **kw: None)
    monkeypatch.setattr(mn, "push_notify", lambda msg: push_calls.append(msg))
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: None)

    mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    assert len(push_calls) == 1


def test_push_notification_failure_does_not_raise_or_block_desktop(monkeypatch):
    desktop_calls = []
    monkeypatch.setattr(mn, "desktop_notify", lambda title, msg, **kw: desktop_calls.append((title, msg)))

    def failing_push(msg):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(mn, "push_notify", failing_push)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: None)

    # should not raise
    result = mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    assert len(desktop_calls) == 1
    assert result["push_attempted"] is True
    assert result["push_succeeded"] is False


def test_returns_status_dict(monkeypatch):
    monkeypatch.setattr(mn, "desktop_notify", lambda title, msg, **kw: None)
    monkeypatch.setattr(mn, "push_notify", lambda msg: None)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: None)

    result = mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    assert result["desktop_sent"] is True
    assert result["push_attempted"] is True
    assert result["push_succeeded"] is True
    assert result["dashboard_ping_attempted"] is True
    assert result["dashboard_ping_succeeded"] is True


def test_attempts_a_dashboard_refresh_ping_too(monkeypatch):
    ping_calls = []
    monkeypatch.setattr(mn, "desktop_notify", lambda title, msg, **kw: None)
    monkeypatch.setattr(mn, "push_notify", lambda msg: None)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: ping_calls.append(True))

    mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    assert len(ping_calls) == 1


def test_dashboard_refresh_ping_failure_does_not_raise_or_block_the_other_channels(monkeypatch):
    # Expected, not exceptional: nothing may be listening on this machine
    # (Electron app not running here, or dispatch happened on the other
    # machine's webhook-server instead).
    desktop_calls = []
    push_calls = []
    monkeypatch.setattr(mn, "desktop_notify", lambda title, msg, **kw: desktop_calls.append(True))
    monkeypatch.setattr(mn, "push_notify", lambda msg: push_calls.append(True))

    def failing_ping():
        raise OSError("Connection refused")

    monkeypatch.setattr(mn, "dashboard_refresh_ping", failing_ping)

    result = mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    assert len(desktop_calls) == 1
    assert len(push_calls) == 1
    assert result["dashboard_ping_attempted"] is True
    assert result["dashboard_ping_succeeded"] is False


def test_default_dashboard_refresh_ping_posts_to_the_webhook_servers_mr_ready_endpoint(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return None

    monkeypatch.setattr(mn.urllib.request, "urlopen", fake_urlopen)
    mn._default_dashboard_refresh_ping()

    assert captured["url"] == "http://localhost:7878/mr-ready"
    assert captured["method"] == "POST"
    assert captured["timeout"] == mn.DASHBOARD_REFRESH_TIMEOUT_S


def test_default_push_notify_invokes_headless_claude(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stdout = ""
            stderr = ""
        return R()

    monkeypatch.setattr(mn.subprocess, "run", fake_run)
    mn._default_push_notify("a test message")

    cmd = calls[0]
    assert "claude" in cmd
    assert "-p" in cmd
    prompt = cmd[cmd.index("-p") + 1]
    assert "a test message" in prompt
    assert "PushNotification" in " ".join(cmd) or "PushNotification" in prompt
