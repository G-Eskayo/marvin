"""Tests for run_colony.py: research colony orchestration with fallback logic.

    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_run_colony.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony  # noqa: E402


class TestRunColonyGate:
    @patch("run_colony.brief_fallback.should_run")
    @patch("run_colony.source_monitor")
    def test_gate_prevents_fallback_run_early(self, mock_source_monitor, mock_should_run):
        """main() returns early when should_run() says no (fallback window not open yet)."""
        mock_should_run.return_value = False
        result = run_colony.main()
        assert result == 0
        # source_monitor should not be called
        mock_source_monitor.main.assert_not_called()

    @patch("run_colony.brief_fallback.should_run")
    @patch("run_colony.source_monitor")
    @patch("run_colony.correlate")
    @patch("run_colony.research_digest")
    def test_main_runs_pipeline_when_should_run_true(self, mock_digest, mock_correlate, mock_source_monitor, mock_should_run):
        """main() runs the full pipeline when should_run() returns True."""
        mock_should_run.return_value = True
        mock_digest.generate.return_value = Path("/tmp/digest.md")

        result = run_colony.main()

        assert result == 0
        mock_source_monitor.main.assert_called_once()
        mock_correlate.correlate.assert_called_once()
        mock_digest.generate.assert_called_once()

    @patch("run_colony.brief_fallback.should_run")
    @patch("run_colony.source_monitor")
    @patch("run_colony.correlate")
    @patch("run_colony.research_digest")
    def test_main_returns_zero_on_no_digest(self, mock_digest, mock_correlate, mock_source_monitor, mock_should_run):
        """main() returns 0 even when generate() returns None (already exists)."""
        mock_should_run.return_value = True
        mock_digest.generate.return_value = None

        result = run_colony.main()

        assert result == 0
