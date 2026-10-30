"""Tests for research_digest.py: digest generation with fallback logic.

    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_research_digest.py -v
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd  # noqa: E402


class TestGenerateIdempotency:
    @patch("research_digest.brief_fallback.produced")
    def test_generate_returns_early_when_produced_locally(self, mock_produced):
        """generate() returns early when brief_fallback.produced() says True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "2026-10-24.md"
            out_path.write_text("existing digest")

            mock_produced.return_value = True

            result = rd.generate()

            assert result == out_path
            mock_produced.assert_called_once()

    @patch("research_digest.brief_fallback.produced")
    def test_generate_checks_other_machines(self, mock_produced):
        """generate() uses brief_fallback.produced() which checks remote machines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "2026-10-24.md"

            # Simulate another machine having the file
            mock_produced.return_value = True

            result = rd.generate()

            # Should return the path even though it doesn't exist locally
            assert result == out_path
            # brief_fallback.produced should be called to check remote machines
            mock_produced.assert_called_once()

    @patch("research_digest.load_today_cache")
    @patch("research_digest.brief_fallback.produced")
    def test_generate_proceeds_when_not_produced(self, mock_produced, mock_cache):
        """generate() proceeds to build when brief_fallback.produced() returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch DIGEST_DIR for this test
            out_path = Path(tmpdir) / "2026-10-24.md"
            mock_produced.return_value = False
            mock_cache.return_value = [{"title": "Test", "url": "http://test", "source": "test"}]

            with patch("research_digest.DIGEST_DIR", Path(tmpdir)):
                with patch("research_digest.load_correlated_from_chroma", return_value=[]):
                    with patch("research_digest.marvin_launcher.launch") as mock_launch:
                        mock_launch.return_value = MagicMock(exit_code=0, text="## Test\nContent")

                        result = rd.generate()

                        # Should have called marvin_launcher to generate content
                        mock_launch.assert_called_once()
