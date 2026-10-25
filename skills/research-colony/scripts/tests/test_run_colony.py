"""Tests for run_colony.py's brief_fallback gating. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_run_colony.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony as rc  # noqa: E402


class TestRunColonyGate:
    """Tests for gating run_colony.main() via brief_fallback.should_run()."""

    def test_should_run_gate_skips_pipeline_if_not_primary_and_before_deadline(self, tmp_path, monkeypatch):
        """main() should skip the fetch/correlate/digest pipeline if brief_fallback.should_run() returns False."""
        # Mock the research digest output path
        digest_path = tmp_path / "research-digest.md"

        with patch("run_colony.brief_fallback") as mock_bf, \
             patch("run_colony.source_monitor") as mock_sm, \
             patch("run_colony.correlate") as mock_corr, \
             patch("run_colony.research_digest") as mock_rd:

            # Gate returns False (standby before deadline)
            mock_bf.should_run.return_value = mock_bf.Decision(False, "standby: before deadline")

            # Run main
            rc.main()

            # Verify should_run was called with correct parameters
            mock_bf.should_run.assert_called_once()
            call_kwargs = mock_bf.should_run.call_args.kwargs
            assert call_kwargs["usual_hour"] == 9
            assert call_kwargs["usual_minute"] == 0

            # Verify the pipeline was NOT run
            mock_sm.run_sources.assert_not_called()
            mock_corr.correlate.assert_not_called()
            mock_rd.generate.assert_not_called()

    def test_should_run_gate_runs_pipeline_if_primary(self, tmp_path, monkeypatch):
        """main() should run the full pipeline if brief_fallback.should_run() returns True (primary)."""
        digest_path = tmp_path / "research-digest.md"

        with patch("run_colony.brief_fallback") as mock_bf, \
             patch("run_colony.source_monitor") as mock_sm, \
             patch("run_colony.correlate") as mock_corr, \
             patch("run_colony.research_digest") as mock_rd:

            # Gate returns True (primary)
            mock_bf.should_run.return_value = mock_bf.Decision(True, "primary")
            mock_bf.produced.return_value = False

            # Set up mock returns for the pipeline steps
            mock_sm.run_sources.return_value = {"source1": []}
            mock_corr.correlate.return_value = {}

            # Run main
            rc.main()

            # Verify the pipeline WAS run
            mock_sm.run_sources.assert_called_once()
            mock_corr.correlate.assert_called_once()
            mock_rd.generate.assert_called_once()

    def test_should_run_gate_respects_produced_check(self, tmp_path, monkeypatch):
        """main() should skip pipeline if brief_fallback.produced() indicates already built."""
        with patch("run_colony.brief_fallback") as mock_bf, \
             patch("run_colony.source_monitor") as mock_sm, \
             patch("run_colony.correlate") as mock_corr, \
             patch("run_colony.research_digest") as mock_rd:

            # Gate returns True (would normally build), but produced is True
            mock_bf.should_run.return_value = mock_bf.Decision(True, "primary")
            mock_bf.produced.return_value = True

            # Run main
            rc.main()

            # Verify the pipeline was NOT run (produced prevents it)
            mock_sm.run_sources.assert_not_called()
            mock_corr.correlate.assert_not_called()
            mock_rd.generate.assert_not_called()

    def test_should_run_gate_passes_correct_schedule_times(self, tmp_path, monkeypatch):
        """main() should pass the correct schedule times (09:00) to should_run()."""
        with patch("run_colony.brief_fallback") as mock_bf:
            mock_bf.should_run.return_value = mock_bf.Decision(False, "standby")
            mock_bf.produced.return_value = False

            rc.main()

            # Verify should_run was called with 09:00 schedule
            call_args = mock_bf.should_run.call_args
            assert call_args.kwargs.get("usual_hour") == 9
            assert call_args.kwargs.get("usual_minute") == 0

    def test_should_run_gate_passes_digest_path(self, tmp_path, monkeypatch):
        """main() should pass the research-digest path to should_run() for staleness check."""
        with patch("run_colony.brief_fallback") as mock_bf, \
             patch("run_colony.RESEARCH_DIGEST_PATH") as mock_path:

            digest_path = tmp_path / "research-digest.txt"
            mock_path.__truediv__ = lambda self, other: digest_path

            mock_bf.should_run.return_value = mock_bf.Decision(False, "standby")
            mock_bf.produced.return_value = False

            rc.main()

            # Verify should_run was called (it would have local_path passed)
            mock_bf.should_run.assert_called_once()

    def test_should_run_gate_fallback_coverage(self, tmp_path, monkeypatch):
        """main() should run the pipeline if gate returns True (fallback covering for primary)."""
        with patch("run_colony.brief_fallback") as mock_bf, \
             patch("run_colony.source_monitor") as mock_sm, \
             patch("run_colony.correlate") as mock_corr, \
             patch("run_colony.research_digest") as mock_rd:

            # Gate returns True (fallback)
            mock_bf.should_run.return_value = mock_bf.Decision(True, "fallback: covering for the primary")
            mock_bf.produced.return_value = False

            # Set up mocks
            mock_sm.run_sources.return_value = {}
            mock_corr.correlate.return_value = {}

            # Run main
            rc.main()

            # Verify pipeline ran
            mock_sm.run_sources.assert_called_once()
            mock_corr.correlate.assert_called_once()
            mock_rd.generate.assert_called_once()
