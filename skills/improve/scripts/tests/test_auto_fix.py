"""Tests for auto_fix.py -- particularly autonomous run accounting via launch() tagging. Run via:
    ~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_auto_fix.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import auto_fix as af  # noqa: E402


def test_auto_fix_calls_launch_with_ticket_tag(monkeypatch):
    """Verify that auto_fix.main() calls launch() with ticket='auto-fix' for autonomous accounting."""
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append({"kind": kind, "ticket": kwargs.get("ticket")})
        class R:
            text = "No fixes needed"
            exit_code = 0
            stderr = ""
        return R()

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(af, "marvin_launcher", marvin_launcher)

    af.main()

    assert len(launches) == 1
    assert launches[0]["ticket"] == "auto-fix", "auto_fix.main() must tag launch() with ticket='auto-fix'"


def test_auto_fix_on_launch_failure_surfaces_exception(monkeypatch):
    """If launch() raises an exception, it should propagate rather than being silently caught."""
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append(kwargs.get("ticket"))
        raise TimeoutError("test timeout")

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(af, "marvin_launcher", marvin_launcher)

    try:
        af.main()
        assert False, "Expected TimeoutError to propagate"
    except TimeoutError:
        pass

    assert len(launches) == 1
    assert launches[0] == "auto-fix"
