"""Test quarantine detection in session-start digest checks."""
from datetime import datetime, timezone
from pathlib import Path
import os
import time
import session_start_report as ssr


def test_check_digest_returns_ready_when_no_quarantine(tmp_path, monkeypatch):
    """Digest with normal content shows ready status."""
    digest_dir = tmp_path / "test-digest"
    digest_dir.mkdir()
    monkeypatch.setattr(ssr, "_now", lambda: datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
    (digest_dir / "2026-10-09.md").write_text("**Today's idea**: Some good finding.")
    result = ssr._check_digest("test digest", digest_dir)
    assert result is not None
    assert "ready" in result
    assert "quarantine" not in result.lower()


def test_check_digest_returns_quarantine_message_when_quarantined(tmp_path, monkeypatch):
    """Digest with Quarantined marker shows quarantine message instead of ready."""
    digest_dir = tmp_path / "test-digest"
    digest_dir.mkdir()
    monkeypatch.setattr(ssr, "_now", lambda: datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
    (digest_dir / "2026-10-09.md").write_text("**Quarantined idea**: Research\n\nQuarantined by safety-monitor")
    result = ssr._check_digest("test digest", digest_dir)
    assert result is not None
    assert "held back by the safety monitor" in result
    assert "~/.claude/quarantine.md" in result


def test_check_digest_handles_missing_file(tmp_path, monkeypatch):
    """Missing digest file returns None."""
    digest_dir = tmp_path / "test-digest"
    digest_dir.mkdir()
    monkeypatch.setattr(ssr, "_now", lambda: datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
    result = ssr._check_digest("test digest", digest_dir)
    assert result is None


def test_check_digest_returns_none_on_decode_error(tmp_path, monkeypatch):
    """Digest with invalid UTF-8 returns None (error caught and handled)."""
    digest_dir = tmp_path / "test-digest"
    digest_dir.mkdir()
    monkeypatch.setattr(ssr, "_now", lambda: datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
    f = digest_dir / "2026-10-09.md"
    f.write_bytes(b'\xff\xfe')
    result = ssr._check_digest("test digest", digest_dir)
    assert result is None


def test_check_digest_extracts_asterisk_note(tmp_path, monkeypatch):
    """Digest with asterisk note shows the note in output."""
    digest_dir = tmp_path / "test-digest"
    digest_dir.mkdir()
    monkeypatch.setattr(ssr, "_now", lambda: datetime(2026, 10, 9, 9, tzinfo=timezone.utc))
    (digest_dir / "2026-10-09.md").write_text("**Today's idea**: Some good finding.\n\n*Slow to generate*")
    result = ssr._check_digest("test digest", digest_dir)
    assert result is not None
    assert "Slow to generate" in result


def test_check_digest_uses_local_time_not_utc(tmp_path, monkeypatch):
    """_check_digest uses local time to determine today's date (not UTC)."""
    digest_dir = tmp_path / "test-digest"
    digest_dir.mkdir()

    # Create a mock datetime that returns a different date when astimezone() is called
    class MockDatetime:
        def astimezone(self):
            # Return a datetime object representing the local date (one day ahead in this mock)
            return datetime(2026, 10, 10, 11, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(ssr, "_now", lambda: MockDatetime())

    (digest_dir / "2026-10-10.md").write_text("**Local time**: found")
    (digest_dir / "2026-10-09.md").write_text("**UTC date**: not used")
    result = ssr._check_digest("test digest", digest_dir)
    # Should find the 2026-10-10.md file (local date), not 2026-10-09.md (UTC date)
    assert result is not None
    assert "2026-10-10.md" in result  # verifies local date was used, not UTC
    assert "2026-10-09.md" not in result  # verifies UTC date was not used


def test_check_digest_uses_shared_is_quarantined_helper(tmp_path, monkeypatch):
    """_check_digest uses morning_brief._is_quarantined, catching both exact and paraphrased forms."""
    import morning_brief as mb
    digest_dir = tmp_path / "test-digest"
    digest_dir.mkdir()
    monkeypatch.setattr(ssr, "_now", lambda: datetime(2026, 10, 9, 9, tzinfo=timezone.utc))

    # Test paraphrased quarantine message (the main reason for the shared helper)
    (digest_dir / "2026-10-09.md").write_text(
        "**Research idea**: Some finding\n\nThe safety-monitor quarantined this for safety"
    )
    result = ssr._check_digest("test digest", digest_dir)
    assert "held back by the safety monitor" in result
    # Also verify that morning_brief sees the same thing
    assert mb._is_quarantined((digest_dir / "2026-10-09.md").read_text()) is True
