"""Tests for session_start_report._check_digest's quarantine placeholder detection.

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_session_start_digest.py -v
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import session_start_report as ssr

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS.parent / "skills" / "safety-monitor" / "scripts"))


def test_check_digest_reports_ready_for_normal_content(tmp_path):
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir()
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    digest_file = digest_dir / f"{today}.md"
    digest_file.write_text(f"# Daily Digest — {today}\n\n*Good digest content here*\n")

    result = ssr._check_digest("test digest", digest_dir)
    assert result is not None
    assert "ready" in result.lower()
    assert "Good digest content here" in result


def test_check_digest_reports_held_back_for_quarantine_placeholder(tmp_path):
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir()
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    digest_file = digest_dir / f"{today}.md"

    from verify import quarantine_placeholder_text
    placeholder = quarantine_placeholder_text("daily_digest")
    digest_file.write_text(f"# Daily Digest — {today}\n\n{placeholder}\n")

    result = ssr._check_digest("test digest", digest_dir)
    assert result is not None
    assert "held back" in result.lower() or "quarantine" in result.lower()


def test_check_digest_returns_none_when_file_missing(tmp_path):
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir()

    result = ssr._check_digest("test digest", digest_dir)
    assert result is None


def test_check_digest_with_daily_digest_quarantine_placeholder(tmp_path):
    digest_dir = tmp_path / "daily-digest"
    digest_dir.mkdir()
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    digest_file = digest_dir / f"{today}.md"

    from verify import quarantine_placeholder_text
    placeholder = quarantine_placeholder_text("daily_digest")
    digest_file.write_text(f"# Daily Digest — {today}\n\n{placeholder}")

    result = ssr._check_digest("today's daily digest", digest_dir)
    assert "quarantine" in result.lower() or "held back" in result.lower()


def test_check_digest_with_research_digest_quarantine_placeholder(tmp_path):
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    digest_file = digest_dir / f"{today}.md"

    from verify import quarantine_placeholder_text
    placeholder = quarantine_placeholder_text("research_colony")
    digest_file.write_text(f"# Research Digest — {today}\n\n{placeholder}")

    result = ssr._check_digest("today's research digest", digest_dir)
    assert "quarantine" in result.lower() or "held back" in result.lower()


def test_13_load_quarantine_detector_catches_import_error():
    """Existing behavior: ImportError is caught and returns False."""
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "verify":
            raise ImportError("verify not found")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = mock_import
    try:
        result = ssr._load_quarantine_detector()
        assert result is False
    finally:
        builtins.__import__ = original_import


def test_14_load_quarantine_detector_catches_any_exception():
    """New behavior: any exception (e.g., RuntimeError) is caught and returns False."""
    import builtins
    original_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "verify":
            raise RuntimeError("verify has a runtime error")
        return original_import(name, *args, **kwargs)

    builtins.__import__ = mock_import
    try:
        result = ssr._load_quarantine_detector()
        assert result is False
    finally:
        builtins.__import__ = original_import


def test_15_quarantine_detector_is_loaded_in_test_environment():
    """Verify that the detector actually loaded and is available."""
    assert ssr._QUARANTINE_DETECT_AVAILABLE is True
    assert ssr._is_quarantine_placeholder is not None
