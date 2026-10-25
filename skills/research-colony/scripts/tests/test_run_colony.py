#!/usr/bin/env python3
"""Tests for run_colony.py's should_run() gate for fallback builder."""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony as rc  # noqa: E402


class TestRunColonyGate:
    """Test the should_run() gate in main() — fallback only runs if primary didn't."""

    def test_gate_allows_run_when_not_produced(self, tmp_path, monkeypatch):
        """should_run gate returns (True, reason) when research digest not produced -> main() proceeds."""
        digest_dir = tmp_path / "research-digest"
        digest_dir.mkdir()

        with patch("run_colony.brief_fallback") as mock_bf:
            mock_bf.should_run.return_value = (True, "fallback: primary missed")
            with patch("run_colony.source_monitor") as mock_sm:
                with patch("run_colony.correlate") as mock_corr:
                    with patch("run_colony.research_digest") as mock_rd:
                        rc.main()

        # brief_fallback.should_run() should have been called
        assert mock_bf.should_run.called

    def test_gate_blocks_run_when_produced(self, tmp_path, monkeypatch):
        """should_run gate returns (False, reason) when already produced -> main() short-circuits."""
        digest_dir = tmp_path / "research-digest"
        digest_dir.mkdir()
        digest_file = digest_dir / f"{date.today().isoformat()}.md"
        digest_file.write_text("existing digest")

        with patch("run_colony.brief_fallback") as mock_bf:
            mock_bf.should_run.return_value = (False, "already produced")
            with patch("run_colony.source_monitor.main") as mock_sm_main:
                rc.main()

        # source_monitor.main() should NOT have been called when should_run returns False
        assert not mock_sm_main.called


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
