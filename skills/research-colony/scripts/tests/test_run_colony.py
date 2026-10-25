#!/usr/bin/env python3
"""Tests for run_colony.py — gate and TOCTOU handling."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import sys
import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "lib"))

import brief_fallback


class TestRunColonyGate:
    """Test that the fallback gate skips the entire colony run when appropriate."""

    def test_gate_off_skips_the_whole_colony_run(self, tmp_path, monkeypatch):
        """If should_run() returns False, main() should not run any steps."""
        import run_colony
        import source_monitor
        import correlate

        # Mock should_run to return False
        def mock_should_run(*args, **kwargs):
            return brief_fallback.Decision(False, "fallback: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Mock the steps to track if they're called
        called = {"source_monitor": False, "correlate": False}

        def mock_source_monitor_main():
            called["source_monitor"] = True

        def mock_correlate():
            called["correlate"] = True
            return []

        monkeypatch.setattr("source_monitor.main", mock_source_monitor_main)
        monkeypatch.setattr("correlate.correlate", mock_correlate)

        # Run main
        result = run_colony.main()

        # Assert steps were not called
        assert called["source_monitor"] is False
        assert called["correlate"] is False
        assert result == 0

    def test_should_run_called_with_explicit_parameters(self, monkeypatch):
        """should_run() is called with usual_hour=9, usual_minute=0."""
        import run_colony
        import source_monitor
        import correlate

        # Track calls to should_run
        calls = []

        def mock_should_run(*args, **kwargs):
            calls.append(kwargs)
            return brief_fallback.Decision(False, "test: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Mock the steps to prevent them from running
        monkeypatch.setattr("source_monitor.main", lambda: None)
        monkeypatch.setattr("correlate.correlate", lambda: [])

        # Run main
        run_colony.main()

        # Verify should_run was called with the right parameters
        assert len(calls) == 1
        assert calls[0].get("usual_hour") == 9
        assert calls[0].get("usual_minute") == 0

    def test_research_digest_toctou_uses_produced(self, tmp_path, monkeypatch):
        """If digest file has valid content, don't rebuild it."""
        import research_digest
        from datetime import date

        today = date.today().isoformat()
        digest_dir = tmp_path / "research-digest"
        digest_dir.mkdir(parents=True)
        out_path = digest_dir / f"{today}.md"

        monkeypatch.setattr("research_digest.DIGEST_DIR", digest_dir)

        # The race condition: mock_launch creates the file before generate() tries to
        existing_content = "# Existing research digest from another process\n\nRace condition test."

        # Mock the data loading functions
        def mock_load_today_cache():
            return [{"title": "item1", "url": "http://example.com", "source": "arXiv"}]

        def mock_load_correlated_from_chroma():
            return []

        # Mock the marvin_launcher.launch to create the file (simulating another process)
        def mock_launch(*args, **kwargs):
            out_path.write_text(existing_content)
            class Result:
                exit_code = 0
                text = "# New research digest\n\nThis should not overwrite existing content."
                stderr = ""
            return Result()

        monkeypatch.setattr("research_digest.load_today_cache", mock_load_today_cache)
        monkeypatch.setattr("research_digest.load_correlated_from_chroma", mock_load_correlated_from_chroma)
        monkeypatch.setattr("research_digest.marvin_launcher.launch", mock_launch)

        # Run generate
        result = research_digest.generate()

        # Assert the content created by mock_launch is still there
        assert out_path.read_text() == existing_content
        # But the function returns the path
        assert result == out_path

    def test_run_colony_passes_digest_dir_derived_path_to_should_run(self, tmp_path, monkeypatch):
        """run_colony.py passes research_digest.DIGEST_DIR-derived path to should_run()."""
        import run_colony
        import research_digest

        digest_dir = tmp_path / "research-digest"
        monkeypatch.setattr("research_digest.DIGEST_DIR", digest_dir)

        # Track calls to should_run
        calls = []

        def mock_should_run(*args, **kwargs):
            calls.append({"local_path": kwargs.get("local_path")})
            return brief_fallback.Decision(False, "test: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Mock the steps to prevent them from running
        monkeypatch.setattr("source_monitor.main", lambda: None)
        monkeypatch.setattr("correlate.correlate", lambda: [])

        # Run main
        run_colony.main()

        # Verify should_run was called with a path derived from research_digest.DIGEST_DIR
        assert len(calls) == 1
        local_path = calls[0]["local_path"]
        assert local_path.parent == digest_dir
