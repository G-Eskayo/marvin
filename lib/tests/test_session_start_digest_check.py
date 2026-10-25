"""Tests for session_start_report._check_digest improvements (quarantine detection, empty content).

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_session_start_digest_check.py -v
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import session_start_report as ssr  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_home_writes(monkeypatch):
    """Never write to the real ~/.claude during tests."""
    monkeypatch.setattr(ssr, "log_hook_error", lambda *a, **kw: None)


NOW = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def test_check_digest_returns_ready_with_summary(tmp_path, monkeypatch):
    """A normal digest with summary text is marked ready."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    f = digest_dir / "2026-10-15.md"
    f.write_text("## Summary\n\n*Some interesting finding*\n\n- Idea 1\n")

    result = ssr._check_digest("today's research digest", digest_dir)
    assert result and "ready" in result
    assert "Some interesting finding" in result


def test_check_digest_detects_quarantine_marker(tmp_path, monkeypatch):
    """A digest with the quarantine marker is reported as held back."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    f = digest_dir / "2026-10-15.md"
    f.write_text("Quarantined by safety-monitor — review before publishing\n")

    result = ssr._check_digest("today's research digest", digest_dir)
    assert result and "held back" in result
    assert "quarantined" in result


def test_check_digest_returns_none_for_missing_file(tmp_path, monkeypatch):
    """A missing digest is silent."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()

    result = ssr._check_digest("today's research digest", digest_dir)
    assert result is None


def test_check_digest_returns_none_for_empty_file(tmp_path, monkeypatch):
    """An empty digest is silent."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    f = digest_dir / "2026-10-15.md"
    f.write_text("")

    result = ssr._check_digest("today's research digest", digest_dir)
    assert result is None


def test_check_digest_handles_read_errors(tmp_path, monkeypatch):
    """A file that fails to read is treated as empty."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    f = digest_dir / "2026-10-15.md"
    f.write_text("Normal content")

    # Simulate a read failure by mocking read_text to raise OSError
    original_read = Path.read_text
    def mock_read(self, *args, **kwargs):
        if self == f:
            raise OSError("Permission denied")
        return original_read(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", mock_read)
    result = ssr._check_digest("today's research digest", digest_dir)
    assert result is None


def test_check_digest_handles_corrupted_utf8(tmp_path, monkeypatch):
    """A digest with invalid UTF-8 is read with errors='ignore'."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    f = digest_dir / "2026-10-15.md"
    # Write bytes that include invalid UTF-8 but also valid content
    f.write_bytes(b"\x80\x81\x82- Valid idea\n*Summary*\n")

    result = ssr._check_digest("today's research digest", digest_dir)
    # The function should handle this gracefully and read what it can
    # Since the corrupted bytes are at the start, the valid content should be visible
    assert result and "ready" in result and "Summary" in result


def test_check_digest_quarantine_includes_pointer(tmp_path, monkeypatch):
    """Quarantined digest message includes pointer to ~/.claude/quarantine.md."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    f = digest_dir / "2026-10-15.md"
    f.write_text("Content\n\nQuarantined by safety-monitor — needs review\n")

    result = ssr._check_digest("today's research digest", digest_dir)
    assert result is not None
    assert "held back" in result
    assert "~/.claude/quarantine.md" in result


def test_session_report_detects_quarantined_research_digest(tmp_path, monkeypatch):
    """The session-start report shows quarantined digests as held back."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    monkeypatch.setattr(ssr, "CLAUDE_DIR", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    f = digest_dir / "2026-10-15.md"
    f.write_text("Quarantined by safety-monitor\n")

    result = ssr.check_research_digest()
    assert result is not None
    assert "held back" in result


def test_check_digest_yesterdays_file_is_not_used_as_today(tmp_path, monkeypatch):
    """Yesterday's file is not used for today."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    yesterday = Path(f"2026-10-14.md")
    f = digest_dir / yesterday
    f.write_text("Yesterday's content")

    result = ssr._check_digest("today's research digest", digest_dir)
    assert result is None


def test_check_research_digest_preserves_summary_text(tmp_path, monkeypatch):
    """check_research_digest includes summary text in the ready message."""
    monkeypatch.setattr(ssr, "_now", lambda: NOW)
    monkeypatch.setattr(ssr, "CLAUDE_DIR", tmp_path)
    digest_dir = tmp_path / "research-digest"
    digest_dir.mkdir()
    f = digest_dir / "2026-10-15.md"
    f.write_text("## Summary\n\n*Important finding*\n\n- Idea 1\n")

    result = ssr.check_research_digest()
    assert result is not None
    assert "ready" in result
    assert "Important finding" in result
