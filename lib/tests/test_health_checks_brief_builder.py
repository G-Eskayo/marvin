#!/usr/bin/env python3
"""Tests for health_checks.check_brief_builder."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import health_checks


def test_check_brief_builder_all_exist():
    """Test check_brief_builder returns green when all files exist."""
    with patch("health_checks.HOME", Path("/tmp")):
        with patch("health_checks.datetime") as mock_dt:
            now = datetime.now(timezone.utc).replace(hour=14, minute=0)
            mock_dt.now.return_value = now
            # Create dummy files
            test_dir = Path("/tmp/test_brief_builder")
            test_dir.mkdir(exist_ok=True)
            (test_dir / ".claude" / "daily-digest").mkdir(parents=True, exist_ok=True)
            (test_dir / ".claude" / "research-digest").mkdir(parents=True, exist_ok=True)
            (test_dir / ".claude" / "briefs").mkdir(parents=True, exist_ok=True)

            day = now.astimezone().strftime("%Y-%m-%d")
            (test_dir / ".claude" / "daily-digest" / f"{day}.md").write_text("content")
            (test_dir / ".claude" / "research-digest" / f"{day}.md").write_text("content")
            (test_dir / ".claude" / "briefs" / f"{day}.md").write_text("content")

            with patch("health_checks.HOME", test_dir):
                result = health_checks.check_brief_builder(now=now)
                assert result["severity"] == "green"
                assert "all builders current" in result["detail"]


def test_check_brief_builder_missing_digest():
    """Test check_brief_builder returns red when digest is missing past deadline."""
    test_home = Path("/tmp/test_missing_digest")
    test_home.mkdir(exist_ok=True)
    # Don't create the digest files
    # Create a time that's definitely past all deadlines in local time
    local_tz = datetime.now(timezone.utc).astimezone().tzinfo
    now_local = datetime.now(local_tz).replace(hour=23, minute=0, second=0, microsecond=0)
    with patch("health_checks.HOME", test_home):
        result = health_checks.check_brief_builder(now=now_local)
        assert result["severity"] == "red", f"Expected red but got {result['severity']}: {result['detail']}"
        assert "missed their deadline" in result["detail"]


def test_check_brief_builder_too_early():
    """Test check_brief_builder returns green when file is missing but before deadline."""
    with patch("health_checks.HOME", Path("/tmp/nonexistent")):
        now = datetime.now(timezone.utc).replace(hour=8, minute=0)  # Before all deadlines
        result = health_checks.check_brief_builder(now=now)
        assert result["severity"] == "green"


def test_check_brief_builder_cid():
    """Test check_brief_builder uses correct check id."""
    with patch("health_checks.HOME", Path("/tmp/nonexistent")):
        now = datetime.now(timezone.utc).replace(hour=8, minute=0)
        result = health_checks.check_brief_builder(now=now)
        assert result["id"] == "brief:builder"


def test_check_brief_builder_label():
    """Test check_brief_builder uses correct label."""
    with patch("health_checks.HOME", Path("/tmp/nonexistent")):
        now = datetime.now(timezone.utc).replace(hour=8, minute=0)
        result = health_checks.check_brief_builder(now=now)
        assert result["label"] == "Digest/brief builders are current"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
