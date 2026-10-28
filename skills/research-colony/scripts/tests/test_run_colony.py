"""Tests for run_colony.py's brief_fallback integration and orchestration.
Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_run_colony.py -v
"""
from __future__ import annotations
import sys
import io
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, call

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony as rc  # noqa: E402


def test_run_colony_main_returns_zero(monkeypatch):
    """main() returns 0 on success."""
    # Mock all the actual work modules to avoid side effects
    monkeypatch.setattr(rc, "source_monitor", MagicMock())
    monkeypatch.setattr(rc, "correlate", MagicMock())
    monkeypatch.setattr(rc, "research_digest", MagicMock())

    # Capture stderr
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main()
    finally:
        sys.stderr = old_stderr

    assert result == 0


def test_run_colony_skips_fetch_when_not_should_run(tmp_path, monkeypatch):
    """main() returns early if brief_fallback.should_run is False."""
    # Pretend we're standby (not primary)
    monkeypatch.setattr("run_colony.brief_fallback.machine_profile.scanner_role.is_primary", lambda x: False)

    # Use raise-on-call sentinels: if these are called, the gate didn't work
    def raise_source_monitor():
        raise AssertionError("source_monitor.main should not be called when gate returns False")

    monkeypatch.setattr(rc, "source_monitor", MagicMock(main=raise_source_monitor))

    # Capture stderr to verify gate message
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main()
        output = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    # Verify gate message was printed
    assert "standby:" in output or "primary hasn't reached deadline" in output
    assert result == 0


def test_run_colony_calls_source_monitor_when_primary(monkeypatch):
    """main() calls source_monitor.main() when brief_fallback.should_run is True."""
    # Pretend we're primary
    monkeypatch.setattr("run_colony.brief_fallback.machine_profile.scanner_role.is_primary", lambda x: True)

    # Mock the modules
    mock_source_monitor = MagicMock()
    monkeypatch.setattr(rc, "source_monitor", mock_source_monitor)
    monkeypatch.setattr(rc, "correlate", MagicMock())
    monkeypatch.setattr(rc, "research_digest", MagicMock())

    # Capture stderr
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main()
    finally:
        sys.stderr = old_stderr

    # Verify source_monitor.main was called
    mock_source_monitor.main.assert_called_once()
    assert result == 0


def test_run_colony_calls_correlate_when_primary(monkeypatch):
    """main() calls correlate.correlate() when brief_fallback.should_run is True."""
    # Pretend we're primary
    monkeypatch.setattr("run_colony.brief_fallback.machine_profile.scanner_role.is_primary", lambda x: True)

    # Mock the modules
    monkeypatch.setattr(rc, "source_monitor", MagicMock())
    mock_correlate = MagicMock()
    monkeypatch.setattr(rc, "correlate", mock_correlate)
    monkeypatch.setattr(rc, "research_digest", MagicMock())

    # Capture stderr
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main()
    finally:
        sys.stderr = old_stderr

    # Verify correlate.correlate was called
    mock_correlate.correlate.assert_called_once()
    assert result == 0


def test_run_colony_calls_research_digest_generate_when_primary(monkeypatch):
    """main() calls research_digest.generate() when brief_fallback.should_run is True."""
    # Pretend we're primary
    monkeypatch.setattr("run_colony.brief_fallback.machine_profile.scanner_role.is_primary", lambda x: True)

    # Mock the modules
    monkeypatch.setattr(rc, "source_monitor", MagicMock())
    monkeypatch.setattr(rc, "correlate", MagicMock())
    mock_research_digest = MagicMock()
    mock_research_digest.generate = MagicMock(return_value=Path("/tmp/test.md"))
    monkeypatch.setattr(rc, "research_digest", mock_research_digest)

    # Capture stderr
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main()
    finally:
        sys.stderr = old_stderr

    # Verify research_digest.generate was called with now=None (default)
    mock_research_digest.generate.assert_called_once_with(now=None)
    assert result == 0


def test_run_colony_passes_now_parameter_through(monkeypatch):
    """main(now=...) threads now parameter to research_digest.generate()."""
    # Pretend we're primary
    monkeypatch.setattr("run_colony.brief_fallback.machine_profile.scanner_role.is_primary", lambda x: True)

    # Mock the modules
    monkeypatch.setattr(rc, "source_monitor", MagicMock())
    monkeypatch.setattr(rc, "correlate", MagicMock())
    mock_research_digest = MagicMock()
    mock_research_digest.generate = MagicMock(return_value=Path("/tmp/test.md"))
    monkeypatch.setattr(rc, "research_digest", mock_research_digest)

    test_now = datetime(2026, 10, 25, 15, 30, tzinfo=timezone.utc)

    # Capture stderr
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main(now=test_now)
    finally:
        sys.stderr = old_stderr

    # Verify research_digest.generate was called with the provided now
    mock_research_digest.generate.assert_called_once_with(now=test_now)
    assert result == 0
