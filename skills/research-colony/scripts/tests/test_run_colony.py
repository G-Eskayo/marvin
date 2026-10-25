#!/usr/bin/env python3
"""Tests for run_colony.py (test 17 per plan item 12)."""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path.home() / ".agents" / "lib"))

import run_colony
import brief_fallback


class TestRunColonyFallbackGate:
    """Test 17: run_colony's fallback gate behavior."""

    def test_main_skips_when_fallback_should_not_run(self, monkeypatch, capsys):
        """Test 17: main() skips if fallback gate says not to run."""
        def mock_should_run(path, usual_hour, usual_minute, now=None):
            return brief_fallback.Decision(False, "primary produced output (local)")

        monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)

        result = run_colony.main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Skipping" in captured.err
        assert "primary produced output" in captured.err

    def test_main_runs_when_fallback_should_run(self, monkeypatch, capsys):
        """Test 17b: main() proceeds if fallback gate says to run."""
        def mock_should_run(path, usual_hour, usual_minute, now=None):
            return brief_fallback.Decision(True, "primary did not produce output")

        def mock_source_monitor():
            pass

        def mock_correlate():
            return None

        def mock_generate():
            return Path.home() / ".claude" / "research-digest" / "2026-10-24.md"

        monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)
        monkeypatch.setattr(run_colony, "source_monitor", MagicMock(main=mock_source_monitor))
        monkeypatch.setattr(run_colony, "correlate", MagicMock(correlate=mock_correlate))
        monkeypatch.setattr(run_colony, "research_digest", MagicMock(generate=mock_generate))

        result = run_colony.main()

        assert result == 0
        captured = capsys.readouterr()
        # Should print the source monitor, correlation, and digest sections
        assert "source monitor" in captured.err
        assert "correlation engine" in captured.err
        assert "digest generator" in captured.err
