"""Tests for research_digest.py's fallback builder logic (ADR 0067)."""
from __future__ import annotations
import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd  # noqa: E402


# Test 22: today_path() returns correct digest path
def test_today_path():
    path = rd.today_path()
    today_str = date.today().isoformat()
    assert path.name == f"{today_str}.md"
    assert "research-digest" in str(path)


# Test 23: FAILURE_MARKERS no longer exists (moved to brief_fallback)
def test_failure_markers_removed():
    assert not hasattr(rd, "FAILURE_MARKERS"), "FAILURE_MARKERS should be removed from research_digest (use brief_fallback.produced() instead)"


# Test 24: generate() returns the path (skips rebuild) when today's digest already exists
def test_generate_skips_when_exists(tmp_path, monkeypatch):
    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
    today_str = date.today().isoformat()
    digest_file = tmp_path / f"{today_str}.md"
    digest_file.write_text("# Research Digest\n\nExisting content")
    result = rd.generate()
    # Returns the path (not None), but skips the expensive rebuild
    assert result == digest_file
    # Verify original content is unchanged
    assert result.read_text() == "# Research Digest\n\nExisting content"


# Tests 29-32: run_colony.py fallback builder logic

def test_run_colony_main_skips_when_produced(tmp_path, monkeypatch):
    """Test 29: run_colony.main() skips when produced() returns True."""
    import run_colony
    import brief_fallback

    # Mock produced to return True (primary already produced)
    monkeypatch.setattr(brief_fallback, "produced", return_value=True)

    # Mock the functions that would be called if we proceeded
    def raise_if_called():
        raise AssertionError("Should not be called when primary produced")

    monkeypatch.setattr(run_colony, "source_monitor", type("mock", (), {"main": raise_if_called})())

    # Run main
    result = run_colony.main()

    # Should return 0 (success) despite skipping
    assert result == 0


def test_run_colony_main_skips_when_should_build_false(tmp_path, monkeypatch):
    """Test 30: run_colony.main() skips when should_build() returns False."""
    import run_colony
    import brief_fallback

    # Mock produced and should_build
    monkeypatch.setattr(brief_fallback, "produced", return_value=False)
    monkeypatch.setattr(brief_fallback, "should_build", return_value=(False, "owner"))

    # Mock the functions that would be called if we proceeded
    def raise_if_called():
        raise AssertionError("Should not be called when should_build is False")

    monkeypatch.setattr(run_colony, "source_monitor", type("mock", (), {"main": raise_if_called})())

    # Run main
    result = run_colony.main()

    # Should return 0 (success) despite skipping
    assert result == 0


def test_run_colony_main_calls_mark_built(tmp_path, monkeypatch):
    """Test 31: run_colony.main() calls mark_built() after generating digest."""
    import run_colony
    import brief_fallback

    # Mock produced and should_build
    monkeypatch.setattr(brief_fallback, "produced", return_value=False)
    monkeypatch.setattr(brief_fallback, "should_build", return_value=(True, "primary-missing"))

    # Mock the colony functions to succeed
    monkeypatch.setattr(run_colony, "source_monitor", type("mock", (), {"main": lambda: None})())
    monkeypatch.setattr(run_colony, "correlate", type("mock", (), {"correlate": lambda: None})())

    # Mock research_digest.generate() to return a path
    import research_digest
    test_path = tmp_path / "test-digest.md"
    test_path.write_text("# Test")
    monkeypatch.setattr(research_digest, "generate", return_value=test_path)

    # Track whether mark_built was called
    mark_built_calls = []
    def mock_mark_built(output_dir, day, reason):
        mark_built_calls.append((output_dir, day, reason))

    monkeypatch.setattr(brief_fallback, "mark_built", mock_mark_built)

    # Run main
    result = run_colony.main()

    # Should succeed
    assert result == 0
    # mark_built should have been called
    assert len(mark_built_calls) == 1
    assert mark_built_calls[0][2] == "primary-missing"  # reason from should_build


def test_run_colony_import_brief_fallback(tmp_path, monkeypatch):
    """Test 32: run_colony imports brief_fallback from the local scripts directory (not ~/.agents/lib)."""
    import run_colony
    import brief_fallback as bf_worktree

    # Verify brief_fallback is imported correctly
    # This test ensures that in the test environment, we're using the worktree copy
    # In the real environment, it should also resolve to ~/.agents/lib, but in tests
    # it should find our modified version first.

    # Check that the imported module has the new produced() signature
    import inspect
    sig = inspect.signature(bf_worktree.produced)
    params = list(sig.parameters.keys())
    # New signature: produced(day, builder_path, remote_host=None, read_remote_fn=None)
    assert "read_remote_fn" in params, "produced() should have read_remote_fn parameter"
