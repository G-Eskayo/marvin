"""Tests for run_colony.py (ADR 0067): fallback gate checking."""
from pathlib import Path
import sys
from datetime import date
from unittest.mock import MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony as rc  # noqa: E402


def test_gate_off_skips_the_whole_colony_run(tmp_path, monkeypatch):
    """When should_run returns False, main() skips the entire colony without running steps (test 15)."""
    import brief_fallback

    # Mock should_run to return False
    monkeypatch.setattr(brief_fallback, "should_run",
                       lambda *a, **k: brief_fallback.Decision(should_build=False, reason="standby: waiting"))

    # Mock all the steps with sentinels that raise if called
    def raise_source():
        raise AssertionError("source_monitor should not be called when gate is off")
    def raise_correlate():
        raise AssertionError("correlate should not be called when gate is off")
    def raise_digest():
        raise AssertionError("research_digest should not be called when gate is off")

    monkeypatch.setattr(rc, "source_monitor", type("SM", (), {"main": raise_source})())
    monkeypatch.setattr(rc, "correlate", type("C", (), {"correlate": raise_correlate})())
    monkeypatch.setattr(rc, "research_digest", type("RD", (), {"generate": raise_digest})())

    # Capture stderr to check the skip message
    import io
    old_stderr = sys.stderr
    sys.stderr = io.StringIO()

    try:
        result = rc.main()
        stderr_output = sys.stderr.getvalue()
    finally:
        sys.stderr = old_stderr

    # Should return 0 (success) but skip everything
    assert result == 0
    assert "Skipped" in stderr_output


def test_gate_on_runs_full_colony(tmp_path, monkeypatch):
    """When should_run returns True, main() runs the full colony (test 15)."""
    import brief_fallback

    # Mock should_run to return True
    monkeypatch.setattr(brief_fallback, "should_run",
                       lambda *a, **k: brief_fallback.Decision(should_build=True, reason="primary"))

    # Track which steps were called
    called = []

    def mock_source():
        called.append("source_monitor")

    def mock_correlate():
        called.append("correlate")
        return []

    def mock_digest():
        called.append("research_digest")
        return None

    monkeypatch.setattr(rc, "source_monitor", type("SM", (), {"main": mock_source})())
    monkeypatch.setattr(rc, "correlate", type("C", (), {"correlate": mock_correlate})())
    monkeypatch.setattr(rc, "research_digest", type("RD", (), {"generate": mock_digest})())

    result = rc.main()

    # Should have called all steps
    assert "source_monitor" in called
    assert "correlate" in called
    assert "research_digest" in called
    assert result == 0
