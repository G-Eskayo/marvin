#!/usr/bin/env python3
"""Tests for run_colony.py fallback gate logic. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_run_colony.py -v
"""
from __future__ import annotations
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony  # noqa: E402
import research_digest  # noqa: E402


def test_gate_off_skips_the_whole_colony_run(tmp_path, monkeypatch):
    """main() skips the entire colony run when brief_fallback.should_run() returns False."""
    import brief_fallback

    monkeypatch.setattr(research_digest, "DIGEST_DIR", tmp_path)

    def mock_should_run(**kwargs):
        return brief_fallback.Decision(False, "test: standby")
    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)

    # Mock the submodule calls to ensure they're not called
    source_monitor_called = []
    def mock_source_monitor_main():
        source_monitor_called.append(1)

    monkeypatch.setattr(run_colony.source_monitor, "main", mock_source_monitor_main)

    result = run_colony.main()

    assert result == 0
    assert len(source_monitor_called) == 0


def test_should_run_called_with_explicit_parameters(tmp_path, monkeypatch):
    """main() calls brief_fallback.should_run with the correct time parameters."""
    import brief_fallback

    monkeypatch.setattr(research_digest, "DIGEST_DIR", tmp_path)

    captured = []
    def mock_should_run(**kwargs):
        captured.append(kwargs)
        return brief_fallback.Decision(False, "test: standby")
    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)

    run_colony.main()

    assert len(captured) == 1
    assert captured[0]["usual_hour"] == 9
    assert captured[0]["usual_minute"] == 0


def test_research_digest_toctou_uses_produced(tmp_path, monkeypatch):
    """research_digest.generate() uses brief_fallback.produced() for TOCTOU checks."""
    import brief_fallback

    monkeypatch.setattr(research_digest, "DIGEST_DIR", tmp_path)
    monkeypatch.setattr(research_digest, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(research_digest, "CHROMA_PATH", tmp_path / "chroma")

    # Create a fake cache with real data (list of items)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / f"{date.today().isoformat()}.json").write_text('[{"id": "test-1", "text": "Test item"}]')

    # Mock brief_fallback.should_run to return True (we're allowed to build)
    def mock_should_run(**kwargs):
        return brief_fallback.Decision(True, "test: primary")
    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)

    # Track calls to produced
    produced_calls = []
    def mock_produced(local_path, **kwargs):
        produced_calls.append(local_path)
        return len(produced_calls) > 1  # First call: False, second call: True (TOCTOU)
    monkeypatch.setattr(brief_fallback, "produced", mock_produced)

    # Mock the LLM calls
    def mock_launch(*args, **kwargs):
        result = MagicMock()
        result.exit_code = 0
        result.text = "# Research Digest\n\n## Directly Relevant\n\nTest."
        return result
    monkeypatch.setattr(research_digest, "marvin_launcher", MagicMock(launch=mock_launch))

    # Mock safety monitor
    monkeypatch.setattr(research_digest, "_SAFETY_MONITOR_AVAILABLE", False)

    result = research_digest.generate()

    # Should have called produced twice (initial check + TOCTOU recheck)
    assert len(produced_calls) == 2
    # Digest file should not have been written due to TOCTOU
    assert not (tmp_path / f"{date.today().isoformat()}.md").exists()
