"""Tests for skills/research-colony/scripts/run_colony.py's fallback gate. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_run_colony.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import run_colony as rc  # noqa: E402


def test_main_short_circuits_when_produced(tmp_path, monkeypatch):
    """When brief_fallback.produced() returns True, main() returns early without building."""
    from datetime import date
    monkeypatch.setenv("HOME", str(tmp_path))

    # Create the digest directory and a pre-existing digest file
    digest_dir = tmp_path / ".claude" / "research-digest"
    digest_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    digest_path = digest_dir / f"{today}.md"
    digest_path.write_text("# Already built\n\nPre-existing content.")

    import brief_fallback
    with patch.object(brief_fallback, "produced", return_value=True):
        def raise_if_called():
            raise AssertionError("source_monitor.main should not be called when digest already produced")

        with patch.object(rc, "source_monitor") as mock_source:
            mock_source.main = raise_if_called
            exit_code = rc.main()

        # Verify it returned early and did not modify the file
        assert exit_code == 0
        assert digest_path.read_text() == "# Already built\n\nPre-existing content."


def test_main_gates_on_should_run_false(tmp_path, monkeypatch):
    """When brief_fallback.should_run() returns False, main() returns early."""
    monkeypatch.setenv("HOME", str(tmp_path))

    # Mock brief_fallback.should_run to return False
    import brief_fallback
    with patch.object(brief_fallback, "produced", return_value=False):
        with patch.object(brief_fallback, "should_run", return_value=(False, "test: should not run")):
            # main() should return early without calling source_monitor
            exit_code = rc.main()
            assert exit_code == 0


def test_main_runs_when_should_run_true(tmp_path, monkeypatch):
    """When brief_fallback.should_run() returns True, main() proceeds."""
    monkeypatch.setenv("HOME", str(tmp_path))

    import brief_fallback
    with patch.object(brief_fallback, "produced", return_value=False):
        with patch.object(brief_fallback, "should_run", return_value=(True, "test: should run")):
            # Mock the actual implementations
            with patch.object(rc, "source_monitor") as mock_source:
                mock_source.main = lambda: None
                with patch.object(rc, "correlate") as mock_corr:
                    mock_corr.correlate = lambda: {}
                    with patch.object(rc, "research_digest") as mock_digest:
                        mock_digest.generate = lambda: None
                        exit_code = rc.main()

            # Verify it ran successfully
            assert exit_code == 0
