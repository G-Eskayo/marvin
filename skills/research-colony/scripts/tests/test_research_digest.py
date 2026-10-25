"""Tests for research_digest.py's fallback gate. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_research_digest.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd  # noqa: E402


class TestResearchDigestGate:
    """Test research_digest.generate() gate: checks should_run() before building."""

    def test_generate_toctou_recheck_regression(self, tmp_path, monkeypatch):
        """TOCTOU regression: should_run() passes (returns True), but produced() then finds file exists."""
        out_file = tmp_path / "2026-10-24.md"
        out_file.write_text("# Research digest\n\nBuilt by primary.")
        monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)

        import brief_fallback
        check_sequence = {"produced_call_count": 0}

        def mock_should_run(path, usual_hour=9, usual_minute=0, grace_minutes=60, now=None):
            # should_run() returns True (fallback should run)
            return (True, "test: should run")

        def mock_produced(path):
            check_sequence["produced_call_count"] += 1
            # But produced() later sees the file does exist
            return path.exists()

        with patch.object(brief_fallback, "should_run", side_effect=mock_should_run):
            with patch.object(brief_fallback, "produced", side_effect=mock_produced):
                def raise_if_called(*args, **kwargs):
                    raise AssertionError("generate() should not rebuild (file already produced)")
                monkeypatch.setattr(rd, "call_claude", raise_if_called)

                # generate() should check should_run() then produced() and skip building
                rd.generate(out_file)

                # Verify produced() was called to double-check
                assert check_sequence["produced_call_count"] >= 1
                # And the file unchanged
                assert out_file.read_text() == "# Research digest\n\nBuilt by primary."
