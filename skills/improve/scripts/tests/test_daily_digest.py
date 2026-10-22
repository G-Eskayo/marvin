#!/usr/bin/env python3
"""Tests for daily_digest.py — gate and TOCTOU handling."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sys
import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

import brief_fallback


class TestDailyDigestGate:
    """Test that the fallback gate skips the digest build when appropriate."""

    def test_gate_off_skips_without_writing(self, tmp_path, monkeypatch):
        """If should_run() returns False, main() should not call claude or write."""
        # Import after monkeypatching to get the mocked module
        import daily_digest

        # Mock the output file path
        digest_dir = tmp_path / "daily-digest"
        out_file = digest_dir / "2026-10-22.md"
        monkeypatch.setattr("daily_digest.DIGEST_DIR", digest_dir)
        monkeypatch.setattr("daily_digest.OUT_FILE", out_file)

        # Mock should_run to return False
        def mock_should_run(*args, **kwargs):
            return brief_fallback.Decision(False, "fallback: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Mock call_claude so it fails if called
        def mock_call_claude(*args, **kwargs):
            raise AssertionError("call_claude should not be invoked")
        monkeypatch.setattr("daily_digest.call_claude", mock_call_claude)

        # Run main
        daily_digest.main()

        # Assert OUT_FILE was not created
        assert not out_file.exists()

    def test_toctou_recheck_uses_produced_not_exists(self, tmp_path, monkeypatch):
        """If OUT_FILE has valid content (even after gate check), don't rebuild."""
        import daily_digest

        digest_dir = tmp_path / "daily-digest"
        out_file = digest_dir / "2026-10-22.md"
        monkeypatch.setattr("daily_digest.DIGEST_DIR", digest_dir)
        monkeypatch.setattr("daily_digest.OUT_FILE", out_file)

        # Mock should_run to return True
        def mock_should_run(*args, **kwargs):
            return brief_fallback.Decision(True, "primary")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Pre-create the file with valid content to simulate a race condition
        digest_dir.mkdir(parents=True)
        existing_content = "# Existing digest from another process\n\nRace condition test."
        out_file.write_text(existing_content)

        # Mock call_claude to return some content
        def mock_call_claude(*args, **kwargs):
            return "# New digest\n\nThis should not overwrite existing content."
        monkeypatch.setattr("daily_digest.call_claude", mock_call_claude)

        # Run main
        daily_digest.main()

        # Assert the original content was NOT overwritten
        assert out_file.read_text() == existing_content

    def test_should_run_called_with_explicit_parameters(self, tmp_path, monkeypatch):
        """should_run() is called with usual_hour=8, usual_minute=30."""
        import daily_digest

        digest_dir = tmp_path / "daily-digest"
        out_file = digest_dir / "2026-10-22.md"
        monkeypatch.setattr("daily_digest.DIGEST_DIR", digest_dir)
        monkeypatch.setattr("daily_digest.OUT_FILE", out_file)

        # Track calls to should_run
        calls = []

        def mock_should_run(*args, **kwargs):
            calls.append(kwargs)
            return brief_fallback.Decision(False, "test: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Run main
        daily_digest.main()

        # Verify should_run was called with the right parameters
        assert len(calls) == 1
        assert calls[0].get("usual_hour") == 8
        assert calls[0].get("usual_minute") == 30
