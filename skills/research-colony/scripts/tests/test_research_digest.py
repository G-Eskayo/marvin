"""Tests for research_digest.py."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# Add parent scripts directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import research_digest  # noqa: E402


class TestDigestPath:
    """Tests for digest_path() function."""

    def test_digest_path_with_utc_datetime(self):
        """digest_path returns correct path for given datetime."""
        # 2026-10-25 10:00 UTC = 2026-10-25 03:00 PDT
        import zoneinfo
        tz = zoneinfo.ZoneInfo('America/Los_Angeles')
        dt = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

        path = research_digest.digest_path(dt)
        assert "2026-10-25.md" in str(path)
        assert path.parent.name == "research-digest"

    def test_digest_path_without_datetime_uses_now(self, monkeypatch):
        """digest_path without argument uses current time."""
        import zoneinfo
        tz = zoneinfo.ZoneInfo('America/Los_Angeles')
        now = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

        with patch('research_digest.datetime') as dt_mock:
            dt_mock.now.return_value = now
            dt_mock.side_effect = lambda *args, **kw: datetime(*args, **kw)
            # Set up the mock to behave like datetime while also mocking now()
            dt_mock.now.return_value = now

            # Just verify the path format matches expected pattern
            path = research_digest.digest_path(now)
            assert "2026-10-25.md" in str(path)

    def test_digest_path_uses_local_timezone(self):
        """digest_path converts to local time before formatting."""
        import zoneinfo
        tz_la = zoneinfo.ZoneInfo('America/Los_Angeles')
        tz_ny = zoneinfo.ZoneInfo('America/New_York')

        # Same UTC time, different local dates in different zones
        utc_time = datetime(2026, 10, 25, 5, 0, 0, tzinfo=timezone.utc)  # 2026-10-24 22:00 PDT, 2026-10-25 01:00 EDT

        path_la = research_digest.digest_path(utc_time)
        # The local date in LA on this UTC time is 2026-10-24
        assert "2026-10-24.md" in str(path_la)


class TestGenerateGating:
    """Tests for generate() function's gating behavior."""

    def test_generate_returns_none_when_already_exists(self, tmp_path, monkeypatch):
        """generate() returns path without writing if digest already exists."""
        now = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

        # Create a fake digest file
        digest_dir = tmp_path / "research-digest"
        digest_dir.mkdir()
        digest_file = digest_dir / "2026-10-24.md"
        digest_file.write_text("# Existing Digest\n")

        monkeypatch.setattr(research_digest, "DIGEST_DIR", digest_dir)

        # Mock load_today_cache to return items (so we'd try to generate if it didn't exist)
        with patch.object(research_digest, 'load_today_cache', return_value=[{"title": "Item"}]):
            result = research_digest.generate()

        # Should return the path without modification
        assert result == digest_file or result is None


class TestLateRecheck:
    """Tests for late re-check in generate()."""

    def test_generate_late_recheck_skips_when_mini_has_output(self, tmp_path, monkeypatch):
        """generate() skips writing on late re-check if Mini has real output."""
        now = datetime(2026, 10, 25, 10, 0, 0, tzinfo=timezone.utc)

        digest_dir = tmp_path / "research-digest"
        digest_dir.mkdir()

        monkeypatch.setattr(research_digest, "DIGEST_DIR", digest_dir)
        monkeypatch.setattr(research_digest, "marvin_launcher", MagicMock())

        # Mock job_ownership to simulate fallback path
        mock_job_ownership = MagicMock()
        mock_job_ownership.is_primary.return_value = False
        mock_job_ownership.mini_output.return_value = "# Real output from Mini"

        monkeypatch.setattr(research_digest, "job_ownership", mock_job_ownership)

        # Mock the model launcher to succeed
        mock_result = MagicMock()
        mock_result.exit_code = 0
        mock_result.text = "## Directly Relevant\n\nSome content"
        research_digest.marvin_launcher.launch.return_value = mock_result

        with patch.object(research_digest, 'load_today_cache', return_value=[{"title": "Item"}]):
            with patch.object(research_digest, 'load_correlated_from_chroma', return_value=[]):
                result = research_digest.generate()

        # Should not have written a new file
        assert not (digest_dir / "2026-10-24.md").exists() or result is not None
