"""Tests for research_digest.py -- particularly autonomous run accounting via launch() tagging. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_research_digest.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd  # noqa: E402


def test_research_digest_calls_launch_with_ticket_tag(monkeypatch, tmp_path):
    """Verify that research_digest.generate() calls launch() with ticket='research-colony' for autonomous accounting."""
    import marvin_launcher
    from pathlib import Path
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append({"kind": kind, "ticket": kwargs.get("ticket")})
        class R:
            text = "## Directly Relevant\nNo items.\n\n## Lateral Finds\nNo items.\n\n## Tools & Repos\nNo items.\n\n## Skip\nNo items."
            exit_code = 0
            stderr = ""
        return R()

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(rd, "marvin_launcher", marvin_launcher)
    # Mock the cache loading to return some items
    monkeypatch.setattr(rd, "load_today_cache", lambda: [{"title": "test", "url": "http://test", "source": "test"}])
    monkeypatch.setattr(rd, "load_correlated_from_chroma", lambda: [])
    # Mock DIGEST_DIR to avoid creating real files
    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
    # Disable safety monitor to avoid extra launch calls
    monkeypatch.setattr(rd, "_SAFETY_MONITOR_AVAILABLE", False)

    rd.generate()

    assert len(launches) == 1
    assert launches[0]["ticket"] == "research-colony", "research_digest.generate() must tag launch() with ticket='research-colony'"


def test_research_digest_on_launch_failure_surfaces_exception(monkeypatch, tmp_path):
    """If launch() raises an exception, it should be caught and logged (not propagate)."""
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append(kwargs.get("ticket"))
        raise TimeoutError("test timeout")

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(rd, "marvin_launcher", marvin_launcher)
    # Mock the cache loading to return some items
    monkeypatch.setattr(rd, "load_today_cache", lambda: [{"title": "test", "url": "http://test", "source": "test"}])
    monkeypatch.setattr(rd, "load_correlated_from_chroma", lambda: [])
    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)

    result = rd.generate()

    # The function catches the exception and returns None
    assert result is None
    assert len(launches) == 1
    assert launches[0] == "research-colony"
