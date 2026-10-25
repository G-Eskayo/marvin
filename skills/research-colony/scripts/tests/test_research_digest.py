"""Tests for research_digest.py (ADR 0067): TOCTOU recheck before writing."""
import sys
from pathlib import Path
from datetime import date
from unittest.mock import MagicMock, patch
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd


class TestResearchDigestToctouCheck:
    """Test 24: research_digest.generate() TOCTOU recheck."""

    def test_24_generate_discards_if_another_process_produced_during_build(self, tmp_path, monkeypatch):
        """Test 24: generate() returns without overwriting if digest was produced during build."""
        today = date.today().isoformat()
        out_path = tmp_path / f"{today}.md"

        monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
        monkeypatch.setattr(rd, "CACHE_DIR", tmp_path)
        monkeypatch.setattr(rd, "CHROMA_PATH", tmp_path)
        monkeypatch.setattr(rd, "_SAFETY_MONITOR_AVAILABLE", False)

        # Create cache file with items
        cache_file = tmp_path / f"{today}.json"
        cache_file.write_text('[]')  # Empty list of items

        with patch("research_digest.load_today_cache", return_value=[{"title": "Test", "url": "http://test"}]):
            with patch("research_digest.load_correlated_from_chroma", return_value=[]):
                with patch("research_digest.marvin_launcher") as mock_ml:
                    with patch("research_digest.brief_fallback") as mock_bf:
                        # First call to produced() during check at top: returns False
                        # Second call to produced() in TOCTOU check: returns True (someone else wrote it)
                        mock_bf.produced.side_effect = [False, True]

                        # Mock the claude call
                        mock_ml.launch.return_value.exit_code = 0
                        mock_ml.launch.return_value.text = "# Research Digest\n\nDirectly Relevant\n\nTest content."

                        result = rd.generate()

                        # Should return the path but not write new content
                        assert result == out_path
                        # File should not have been written (or had content overwritten)
                        # Actually, the function returns the path from load_today_cache check,
                        # so the file won't be there
                        assert not out_path.exists() or out_path.read_text() == ""
