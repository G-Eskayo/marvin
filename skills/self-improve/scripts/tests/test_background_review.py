"""Tests for background_review.py -- particularly autonomous run accounting via launch() tagging. Run via:
    ~/.agents/venv/bin/python -m pytest skills/self-improve/scripts/tests/test_background_review.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import background_review as br  # noqa: E402


def test_background_review_calls_launch_with_ticket_tag(monkeypatch):
    """Verify that background_review.run_review() calls launch() with ticket='self-improve' for autonomous accounting."""
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append({"kind": kind, "ticket": kwargs.get("ticket")})
        class R:
            text = "# Self-improve review"
            exit_code = 0
            stderr = ""
        return R()

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(br, "marvin_launcher", marvin_launcher)

    br.run_review("test handoff content")

    assert len(launches) == 1
    assert launches[0]["ticket"] == "self-improve", "background_review.run_review() must tag launch() with ticket='self-improve'"


def test_background_review_on_launch_failure_surfaces_exception(monkeypatch):
    """If launch() raises an exception, it should propagate rather than being silently caught."""
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append(kwargs.get("ticket"))
        raise TimeoutError("test timeout")

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(br, "marvin_launcher", marvin_launcher)

    try:
        br.run_review("test handoff content")
        assert False, "Expected TimeoutError to propagate"
    except TimeoutError:
        pass

    assert len(launches) == 1
    assert launches[0] == "self-improve"
