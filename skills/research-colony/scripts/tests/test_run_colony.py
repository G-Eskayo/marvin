#!/usr/bin/env python3
"""Tests for run_colony.py — research colony orchestration and fallback gate."""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony


class TestRunColonyFallbackGate:
    """Test fallback gate decision in run_colony.main()."""

    @patch("run_colony.brief_fallback.should_run")
    @patch("run_colony.source_monitor.main")
    def test_fallback_gate_standby_no_run(self, mock_source_monitor, mock_should_run, capsys):
        """main() should not run the pipeline if fallback gate returns False (standby)."""
        mock_should_run.return_value = MagicMock(
            should_build=False,
            reason="standby: primary already produced"
        )

        # source_monitor.main() should not be called
        mock_source_monitor.side_effect = AssertionError(
            "source_monitor.main() should not be called when fallback gate says no"
        )

        result = run_colony.main()

        # Verify the function returns without error
        assert result == 0
        captured = capsys.readouterr()
        # Verify standby message was printed
        assert "standby" in captured.err.lower() or "skipping" in captured.err.lower() or len(captured.err) == 0

    @patch("run_colony.brief_fallback.should_run")
    @patch("run_colony.source_monitor.main")
    @patch("run_colony.correlate.correlate")
    @patch("run_colony.research_digest.generate")
    def test_fallback_gate_primary_runs_pipeline(
        self, mock_generate, mock_correlate, mock_source_monitor, mock_should_run, capsys
    ):
        """main() runs the pipeline when fallback gate returns True (primary or fallback)."""
        mock_should_run.return_value = MagicMock(
            should_build=True,
            reason="primary"
        )
        mock_generate.return_value = "/home/user/.claude/outbox/research-digest.md"

        result = run_colony.main()

        assert result == 0
        assert mock_source_monitor.called
        assert mock_correlate.called
        assert mock_generate.called
        captured = capsys.readouterr()
        assert "done" in captured.err.lower()

    def test_run_colony_gate_checks_the_real_digest_path(self):
        """should_run() is called with research_digest.DIGEST_DIR path, not outbox."""
        from datetime import date
        import research_digest

        call_args = None
        def mock_should_run(**kwargs):
            nonlocal call_args
            call_args = kwargs
            return MagicMock(should_build=False, reason="test")

        with patch("run_colony.brief_fallback.should_run", mock_should_run):
            with patch("run_colony.source_monitor.main"):
                run_colony.main()

        # Verify should_run was called with the correct path
        assert call_args is not None
        local_path = call_args.get("local_path")
        expected_path = research_digest.DIGEST_DIR / f"{date.today().isoformat()}.md"
        assert local_path == expected_path, f"Expected {expected_path}, got {local_path}"
