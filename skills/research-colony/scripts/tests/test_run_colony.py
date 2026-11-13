#!/usr/bin/env python3
"""Tests for run_colony.py — gate and TOCTOU handling."""
from __future__ import annotations
from datetime import date
from pathlib import Path
import sys
import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

import brief_fallback


class TestRunColonyGate:
    """Test that the fallback gate skips the entire colony run when appropriate."""

    def test_gate_off_skips_the_whole_colony_run(self, tmp_path, monkeypatch):
        """If should_run() returns False, main() should not run any steps."""
        import run_colony
        import source_monitor
        import correlate

        # Mock should_run to return False
        def mock_should_run(*args, **kwargs):
            return brief_fallback.Decision(False, "fallback: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Mock the steps to track if they're called
        called = {"source_monitor": False, "correlate": False}

        def mock_source_monitor_main():
            called["source_monitor"] = True

        def mock_correlate():
            called["correlate"] = True
            return []

        monkeypatch.setattr("source_monitor.main", mock_source_monitor_main)
        monkeypatch.setattr("correlate.correlate", mock_correlate)

        # Run main
        result = run_colony.main()

        # Assert steps were not called
        assert called["source_monitor"] is False
        assert called["correlate"] is False
        assert result == 0

    def test_should_run_called_with_explicit_parameters(self, monkeypatch):
        """should_run() is called with usual_hour=9, usual_minute=0."""
        import run_colony
        import source_monitor
        import correlate

        # Track calls to should_run
        calls = []

        def mock_should_run(*args, **kwargs):
            calls.append(kwargs)
            return brief_fallback.Decision(False, "test: skipping")
        monkeypatch.setattr("brief_fallback.should_run", mock_should_run)

        # Mock the steps to prevent them from running
        monkeypatch.setattr("source_monitor.main", lambda: None)
        monkeypatch.setattr("correlate.correlate", lambda: [])

        # Run main
        run_colony.main()

        # Verify should_run was called with the right parameters
        assert len(calls) == 1
        assert calls[0].get("usual_hour") == 9
        assert calls[0].get("usual_minute") == 0

    def test_research_digest_toctou_uses_produced(self, tmp_path, monkeypatch):
        """If digest file has valid content, don't rebuild it."""
        import research_digest
        from datetime import date

        today = date.today().isoformat()
        digest_dir = tmp_path / "research-digest"
        digest_dir.mkdir(parents=True)
        out_path = digest_dir / f"{today}.md"

        monkeypatch.setattr("research_digest.DIGEST_DIR", digest_dir)

        # Pre-create the file with valid content to simulate a race condition
        existing_content = "# Existing research digest from another process\n\nRace condition test."
        out_path.write_text(existing_content)

        # Mock the data loading functions
        def mock_load_today_cache():
            return [{"title": "item1", "url": "http://example.com", "source": "arXiv"}]

        def mock_load_correlated_from_chroma():
            return []

        # Mock the marvin_launcher.launch to return content
        def mock_launch(*args, **kwargs):
            class Result:
                exit_code = 0
                text = "# New research digest\n\nThis should not overwrite existing content."
                stderr = ""
            return Result()

        monkeypatch.setattr("research_digest.load_today_cache", mock_load_today_cache)
        monkeypatch.setattr("research_digest.load_correlated_from_chroma", mock_load_correlated_from_chroma)
        monkeypatch.setattr("research_digest.marvin_launcher.launch", mock_launch)

        # Run generate
        result = research_digest.generate()

        # Assert the original content was NOT overwritten
        assert out_path.read_text() == existing_content
        # But the function returns the path
        assert result == out_path


class TestSourceMonitorErrorHandling:
    """Test source_monitor error handling for empty results."""

    def test_empty_sources_skip_cache_save(self, tmp_path, monkeypatch, capsys):
        """If all sources return empty, don't call save_raw_cache."""
        import source_monitor

        cache_dir = tmp_path / "research-feed"
        monkeypatch.setattr("source_monitor.CACHE_DIR", cache_dir)

        # Mock all fetch functions to return empty
        monkeypatch.setattr("source_monitor.fetch_arxiv", lambda: [])
        monkeypatch.setattr("source_monitor.fetch_github", lambda: [])
        monkeypatch.setattr("source_monitor.fetch_hackernews", lambda: [])

        # Mock store_items to track if called
        store_called = []
        def mock_store_items(items):
            store_called.append(len(items))
            return 0
        monkeypatch.setattr("source_monitor.store_items", mock_store_items)

        result = source_monitor.main()

        # Verify error message printed
        captured = capsys.readouterr()
        assert "[colony] ERROR: all sources returned 0 items" in captured.err

        # Verify cache file was not created
        assert not cache_dir.exists()

        # Verify store_items was still called (with empty list)
        assert store_called == [0]
        assert result == 0


class TestResearchDigestErrorHandling:
    """Test research_digest error handling and notifications."""

    def test_no_items_notifies_and_returns_none(self, tmp_path, monkeypatch):
        """When no items in cache, notify and return None."""
        import research_digest

        cache_dir = tmp_path / "research-feed"
        digest_dir = tmp_path / "research-digest"
        monkeypatch.setattr("research_digest.CACHE_DIR", cache_dir)
        monkeypatch.setattr("research_digest.DIGEST_DIR", digest_dir)

        # Mock load functions
        monkeypatch.setattr("research_digest.load_today_cache", lambda: [])
        monkeypatch.setattr("research_digest.load_correlated_from_chroma", lambda: [])

        # Track notify calls
        notify_calls = []
        def mock_notify(title, msg, **kwargs):
            notify_calls.append((title, msg))
        monkeypatch.setattr("research_digest.notify", mock_notify)

        result = research_digest.generate()

        assert result is None
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "MARVIN research-colony failed"
        assert "no items fetched" in notify_calls[0][1]

    def test_claude_exception_notifies_and_returns_none(self, tmp_path, monkeypatch):
        """When claude call raises exception, notify and return None."""
        import research_digest

        cache_dir = tmp_path / "research-feed"
        digest_dir = tmp_path / "research-digest"
        monkeypatch.setattr("research_digest.CACHE_DIR", cache_dir)
        monkeypatch.setattr("research_digest.DIGEST_DIR", digest_dir)

        # Mock load functions with valid data
        monkeypatch.setattr("research_digest.load_today_cache",
                           lambda: [{"title": "item1", "url": "http://example.com", "source": "test"}])
        monkeypatch.setattr("research_digest.load_correlated_from_chroma", lambda: [])

        # Mock marvin_launcher to raise exception
        def mock_launch(*args, **kwargs):
            raise RuntimeError("Connection timeout")
        monkeypatch.setattr("research_digest.marvin_launcher.launch", mock_launch)

        # Track notify calls
        notify_calls = []
        def mock_notify(title, msg, **kwargs):
            notify_calls.append((title, msg))
        monkeypatch.setattr("research_digest.notify", mock_notify)

        result = research_digest.generate()

        assert result is None
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "MARVIN research-colony failed"
        assert "claude call failed" in notify_calls[0][1]
        assert "Connection timeout" in notify_calls[0][1]

    def test_claude_bad_exit_code_notifies_and_returns_none(self, tmp_path, monkeypatch):
        """When claude call returns bad exit code, notify and return None."""
        import research_digest

        cache_dir = tmp_path / "research-feed"
        digest_dir = tmp_path / "research-digest"
        monkeypatch.setattr("research_digest.CACHE_DIR", cache_dir)
        monkeypatch.setattr("research_digest.DIGEST_DIR", digest_dir)

        # Mock load functions with valid data
        monkeypatch.setattr("research_digest.load_today_cache",
                           lambda: [{"title": "item1", "url": "http://example.com", "source": "test"}])
        monkeypatch.setattr("research_digest.load_correlated_from_chroma", lambda: [])

        # Mock marvin_launcher to return bad exit code
        def mock_launch(*args, **kwargs):
            class Result:
                exit_code = 1
                text = ""
                stderr = "Model error occurred"
            return Result()
        monkeypatch.setattr("research_digest.marvin_launcher.launch", mock_launch)

        # Track notify calls
        notify_calls = []
        def mock_notify(title, msg, **kwargs):
            notify_calls.append((title, msg))
        monkeypatch.setattr("research_digest.notify", mock_notify)

        result = research_digest.generate()

        assert result is None
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "MARVIN research-colony failed"
        assert "claude call failed" in notify_calls[0][1]

    def test_claude_empty_text_notifies_and_returns_none(self, tmp_path, monkeypatch):
        """When claude call returns empty text, notify and return None."""
        import research_digest

        cache_dir = tmp_path / "research-feed"
        digest_dir = tmp_path / "research-digest"
        monkeypatch.setattr("research_digest.CACHE_DIR", cache_dir)
        monkeypatch.setattr("research_digest.DIGEST_DIR", digest_dir)

        # Mock load functions with valid data
        monkeypatch.setattr("research_digest.load_today_cache",
                           lambda: [{"title": "item1", "url": "http://example.com", "source": "test"}])
        monkeypatch.setattr("research_digest.load_correlated_from_chroma", lambda: [])

        # Mock marvin_launcher to return empty text
        def mock_launch(*args, **kwargs):
            class Result:
                exit_code = 0
                text = "   "  # whitespace only
                stderr = ""
            return Result()
        monkeypatch.setattr("research_digest.marvin_launcher.launch", mock_launch)

        # Track notify calls
        notify_calls = []
        def mock_notify(title, msg, **kwargs):
            notify_calls.append((title, msg))
        monkeypatch.setattr("research_digest.notify", mock_notify)

        result = research_digest.generate()

        assert result is None
        assert len(notify_calls) == 1
        assert notify_calls[0][0] == "MARVIN research-colony failed"


class TestRunColonyReturnCode:
    """Test run_colony return code behavior."""

    def test_returns_1_when_digest_not_written(self, tmp_path, monkeypatch, capsys):
        """run_colony should return 1 when digest generation fails."""
        import run_colony
        import source_monitor
        import correlate
        import research_digest

        # Mock should_run to allow the run
        def mock_should_run(*args, **kwargs):
            return brief_fallback.Decision(True, "proceed")
        monkeypatch.setattr("run_colony.brief_fallback.should_run", mock_should_run)

        # Mock steps: source_monitor and correlate succeed
        monkeypatch.setattr("source_monitor.main", lambda: 0)
        monkeypatch.setattr("correlate.correlate", lambda: [])

        # Mock research_digest to fail (return None)
        monkeypatch.setattr("research_digest.generate", lambda: None)

        result = run_colony.main()

        # Should return 1 on failure
        assert result == 1

        # Verify error message printed
        captured = capsys.readouterr()
        assert "no digest written — see errors above" in captured.err

    def test_returns_0_when_digest_written(self, tmp_path, monkeypatch, capsys):
        """run_colony should return 0 when digest is successfully written."""
        import run_colony
        import source_monitor
        import correlate
        import research_digest

        # Mock should_run to allow the run
        def mock_should_run(*args, **kwargs):
            return brief_fallback.Decision(True, "proceed")
        monkeypatch.setattr("run_colony.brief_fallback.should_run", mock_should_run)

        # Mock steps
        monkeypatch.setattr("source_monitor.main", lambda: 0)
        monkeypatch.setattr("correlate.correlate", lambda: [])

        # Mock research_digest to succeed
        fake_path = tmp_path / "digest.md"
        monkeypatch.setattr("research_digest.generate", lambda: fake_path)

        result = run_colony.main()

        # Should return 0 on success
        assert result == 0

        # Verify success message printed
        captured = capsys.readouterr()
        assert "done — digest at" in captured.err
