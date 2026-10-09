"""Tests for daily_digest.py -- particularly autonomous run accounting via launch() tagging. Run via:
    ~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_daily_digest.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import daily_digest as dd  # noqa: E402


def test_call_claude_passes_daily_digest_job_label(monkeypatch):
    """The daily_digest launch() call should tag itself as ticket='daily-digest' for autonomous accounting."""
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append({"kind": kind, "ticket": kwargs.get("ticket")})
        class R:
            text = "# Daily digest content"
            exit_code = 0
            stderr = ""
        return R()

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(dd, "marvin_launcher", marvin_launcher)

    result = dd.call_claude("test prompt")

    assert len(launches) == 1
    assert launches[0]["kind"] == "background-analyst"
    assert launches[0]["ticket"] == "daily-digest", "daily_digest.py must tag launch() with ticket='daily-digest'"


def test_call_claude_on_launch_failure_returns_error_message(monkeypatch):
    """If launch() times out or fails, call_claude should return a descriptive error, not crash."""
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append(kwargs.get("ticket"))
        raise TimeoutError("test timeout")

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(dd, "marvin_launcher", marvin_launcher)

    result = dd.call_claude("test prompt")

    assert "failed" in result.lower()
    assert len(launches) == 1
    assert launches[0] == "daily-digest"
