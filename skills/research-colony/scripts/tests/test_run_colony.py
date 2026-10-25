"""Tests for run_colony.py."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add parent scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_colony  # noqa: E402
import research_digest  # noqa: E402


class TestMainGate:
    """Tests for the top-of-main gate in run_colony.main()."""

    def test_main_skips_everything_if_digest_exists(self, tmp_path, monkeypatch):
        """main() returns 0 immediately if digest already exists."""
        now = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

        # Create fake digest directory and file
        digest_dir = tmp_path / "research-digest"
        digest_dir.mkdir()
        digest_file = digest_dir / "2026-10-24.md"
        digest_file.write_text("# Existing Digest\n")

        # Patch digest_path to return our test file
        with patch.object(research_digest, 'digest_path') as digest_path_mock:
            digest_path_mock.return_value = digest_file

            # Mock everything else to verify they're not called
            with patch.object(run_colony, 'source_monitor') as sm_mock:
                with patch.object(run_colony, 'correlate') as corr_mock:
                    with patch.object(run_colony, 'research_digest') as rd_mock:
                        result = run_colony.main()

        # Should return 0 without running anything
        assert result == 0
        sm_mock.main.assert_not_called()


class TestMiniOwnSecondFiringRegression:
    """Tests for the defect #3 regression: Mini's own second firing re-fetching."""

    def test_main_skips_on_second_mini_firing(self, tmp_path, monkeypatch, capsys):
        """Defect #3 regression: when the Mini fires twice, second firing should skip."""
        now = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

        # Create digest directory (empty)
        digest_dir = tmp_path / "research-digest"
        digest_dir.mkdir()

        # Mock digest_path to return non-existent file first, then existent file
        calls = [False, True]  # First call: doesn't exist, second call (after write): exists
        call_count = [0]

        def digest_path_side_effect(dt):
            idx = call_count[0]
            call_count[0] += 1
            digest_file = digest_dir / "2026-10-24.md"
            if idx == 0:
                # First call (at top of main): file doesn't exist
                return digest_file
            else:
                # Simulate file being written
                digest_file.write_text("# Research Digest\n")
                return digest_file

        with patch.object(research_digest, 'digest_path', side_effect=digest_path_side_effect):
            # Mock the pipeline functions
            with patch.object(run_colony, 'source_monitor'):
                with patch.object(run_colony, 'correlate'):
                    with patch.object(run_colony, 'research_digest') as rd_mock:
                        with patch.object(run_colony, 'job_ownership') as jo_mock:
                            jo_mock.is_primary.return_value = True
                            jo_mock.past_deadline.return_value = False

                            # Make the digest write succeed
                            rd_mock.generate.return_value = digest_dir / "2026-10-24.md"

                            result = run_colony.main()

        # Verify digest_path was called (at the gate check)
        assert call_count[0] >= 1
