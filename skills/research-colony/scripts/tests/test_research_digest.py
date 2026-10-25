"""Tests for research_digest.py's generate() function. Run via:
    ~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/test_research_digest.py -v
"""
from __future__ import annotations
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import research_digest as rd  # noqa: E402


# ── generate() with should_run() gate ──────────────────────────────────────

def test_generate_skips_before_deadline_gate(tmp_path, monkeypatch):
    """generate() respects the should_run() fallback gate — skips if before deadline."""
    today = datetime.now(timezone.utc)
    out_path = tmp_path / f"{today.date().isoformat()}.md"

    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
    monkeypatch.setattr(rd, "CHROMA_PATH", tmp_path / "chroma")

    # Monkeypatch brief_fallback.should_run to return False (before deadline)
    mock_decision = MagicMock()
    mock_decision.should_build = False
    mock_decision.reason = "standby: before deadline"

    with patch("research_digest.brief_fallback") as mock_bf:
        mock_bf.produced.return_value = False
        mock_bf.should_run.return_value = mock_decision

        result = rd.generate()

    assert result is None
    assert not out_path.exists()


def test_generate_has_prelaunch_recheck(tmp_path, monkeypatch):
    """generate() has a pre-launch recheck: ensures primary hasn't produced since we started."""
    today = datetime.now(timezone.utc)
    out_path = tmp_path / f"{today.date().isoformat()}.md"

    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)
    monkeypatch.setattr(rd, "CHROMA_PATH", tmp_path / "chroma")
    monkeypatch.setattr(rd, "CACHE_DIR", tmp_path / "cache")

    # Create a fake cache with items
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    import json
    cache_file = cache_dir / f"{today.date().isoformat()}.json"
    cache_file.write_text(json.dumps([{"title": "Item 1", "url": "http://example.com", "source": "arXiv"}]))

    # Mock brief_fallback: first call passes (not produced yet), second call fails (primary produced)
    call_count = [0]
    def should_run_side_effect(*args, **kwargs):
        call_count[0] += 1
        mock_decision = MagicMock()
        if call_count[0] == 1:
            # Initial gate check
            mock_decision.should_build = True
        else:
            # Pre-launch recheck
            mock_decision.should_build = False
            mock_decision.reason = "standby: primary already produced"
        return mock_decision

    with patch("research_digest.brief_fallback") as mock_bf:
        mock_bf.produced.return_value = False
        mock_bf.should_run.side_effect = should_run_side_effect

        with patch("research_digest.load_correlated_from_chroma", return_value=[]):
            result = rd.generate()

    assert result is None
    assert not out_path.exists()
    # should_run should have been called twice (initial + recheck)
    assert call_count[0] == 2


def test_generate_already_produced_returns_early(tmp_path, monkeypatch):
    """generate() returns early if digest already produced (via produced() check)."""
    today = datetime.now(timezone.utc)
    out_path = tmp_path / f"{today.date().isoformat()}.md"
    out_path.write_text("# Research Digest\n\nAlready produced.")

    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)

    with patch("research_digest.brief_fallback") as mock_bf:
        mock_bf.produced.return_value = True

        result = rd.generate()

    assert result == out_path
    # marvin_launcher should not have been called
    with patch("research_digest.marvin_launcher") as mock_ml:
        assert not mock_ml.launch.called


def test_generate_detects_failure_placeholder_as_not_produced(tmp_path, monkeypatch):
    """generate() treats a failed digest (failure marker) as not produced, triggers rebuild."""
    today = datetime.now(timezone.utc)
    out_path = tmp_path / f"{today.date().isoformat()}.md"
    out_path.write_text("(claude call failed: timeout)")

    monkeypatch.setattr(rd, "DIGEST_DIR", tmp_path)

    with patch("research_digest.brief_fallback") as mock_bf:
        # produced() should return False for failure marker
        mock_bf.produced.return_value = False

        # should_run gate checks pass
        decision = MagicMock()
        decision.should_build = True
        mock_bf.should_run.return_value = decision

        with patch("research_digest.load_today_cache", return_value=[]):
            result = rd.generate()

    # Should return None because load_today_cache is empty
    assert result is None
