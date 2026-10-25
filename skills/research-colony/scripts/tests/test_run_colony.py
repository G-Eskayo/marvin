"""Tests for run_colony.py (ADR 0067): research colony orchestration with fallback gate."""
import sys
from pathlib import Path
from datetime import date
from unittest.mock import MagicMock, patch
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony


class TestColonyFallbackGate:
    """Test 22-23: run_colony.main() fallback gate behavior."""

    def test_22_main_skips_when_fallback_gate_returns_false(self):
        """Test 22: main() returns 0 and skips when should_run returns False."""
        with patch("run_colony.brief_fallback") as mock_bf:
            with patch("run_colony.machine_profile") as mock_mp:
                with patch("run_colony.source_monitor") as mock_sm:
                    mock_mp.registry_id.return_value = "macbook"
                    mock_bf.should_run.return_value = False

                    result = run_colony.main()

                    assert result == 0
                    # source_monitor should not be called
                    mock_sm.main.assert_not_called()

    def test_23_main_proceeds_when_fallback_gate_returns_true(self):
        """Test 23: main() proceeds when should_run returns True and output doesn't exist."""
        with patch("run_colony.brief_fallback") as mock_bf:
            with patch("run_colony.machine_profile") as mock_mp:
                with patch("run_colony.source_monitor") as mock_sm:
                    with patch("run_colony.correlate") as mock_corr:
                        with patch("run_colony.research_digest") as mock_rd:
                            mock_mp.registry_id.return_value = "mac-mini"
                            # produced returns False (no file exists), should_run returns True
                            mock_bf.produced.return_value = False
                            mock_bf.should_run.return_value = True
                            mock_rd.generate.return_value = None

                            result = run_colony.main()

                            assert result == 0
                            # source_monitor should be called
                            mock_sm.main.assert_called_once()
                            mock_corr.correlate.assert_called_once()
                            mock_rd.generate.assert_called_once()
