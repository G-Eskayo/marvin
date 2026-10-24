"""Tests for run_colony.py's fallback gate and TOCTOU logic."""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony as rc  # noqa: E402

# Add lib to path for brief_fallback
LIB = Path(__file__).resolve().parents[3] / "lib"
sys.path.insert(0, str(LIB))
import brief_fallback  # noqa: E402


def test_main_gates_on_should_run_decision(tmp_path, monkeypatch):
    """main() returns early if brief_fallback.should_run() says not to build."""
    # Mock brief_fallback.should_run to return a negative decision
    def mock_should_run(*args, **kwargs):
        return brief_fallback.Decision(False, "standby: before deadline")
    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)

    # Mock the modules so main() doesn't try to call them
    import source_monitor
    def raise_source_monitor():
        raise AssertionError("source_monitor.main should not be called when should_run returns False")
    monkeypatch.setattr(source_monitor, "main", raise_source_monitor)

    # Capture stderr
    import io
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main()
    finally:
        output = sys.stderr.getvalue()
        sys.stderr = old_stderr

    # Verify the gate message was printed
    assert "standby: before deadline" in output
    assert "not building" in output
    assert result == 0


def test_main_runs_source_monitor_when_should_run_positive(tmp_path, monkeypatch):
    """main() runs source_monitor and other steps when should_run() returns True."""
    # Mock brief_fallback.should_run to return a positive decision
    def mock_should_run(*args, **kwargs):
        return brief_fallback.Decision(True, "primary")
    monkeypatch.setattr(brief_fallback, "should_run", mock_should_run)

    # Track what was called
    calls = []

    def mock_source_monitor():
        calls.append("source_monitor")
    def mock_correlate():
        calls.append("correlate")
        return []
    def mock_generate():
        calls.append("generate")
        return None

    import source_monitor
    import correlate
    import research_digest
    monkeypatch.setattr(source_monitor, "main", mock_source_monitor)
    monkeypatch.setattr(correlate, "correlate", mock_correlate)
    monkeypatch.setattr(research_digest, "generate", mock_generate)

    # Capture stderr
    import io
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main()
    finally:
        output = sys.stderr.getvalue()
        sys.stderr = old_stderr

    # Verify steps were called in order
    assert calls == ["source_monitor", "correlate", "generate"]
    assert result == 0
