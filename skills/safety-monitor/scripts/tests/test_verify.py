"""Tests for verify.py's quarantine() dedup. Run via:
    ~/.agents/venv/bin/python -m pytest skills/safety-monitor/scripts/tests/test_verify.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import verify as v  # noqa: E402


def test_last_quarantined_artifact_text_returns_none_when_file_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "QUARANTINE_FILE", tmp_path / "quarantine.md")
    assert v._last_quarantined_artifact_text("improvement_sweep") is None


def test_last_quarantined_artifact_text_returns_none_when_loop_never_appeared(tmp_path, monkeypatch):
    quarantine_file = tmp_path / "quarantine.md"
    monkeypatch.setattr(v, "QUARANTINE_FILE", quarantine_file)

    v.quarantine("some artifact", 0.5, "research_colony", 0.3)

    assert v._last_quarantined_artifact_text("improvement_sweep") is None


def test_last_quarantined_artifact_text_extracts_the_most_recent_matching_block(tmp_path, monkeypatch):
    quarantine_file = tmp_path / "quarantine.md"
    monkeypatch.setattr(v, "QUARANTINE_FILE", quarantine_file)

    v.quarantine("old artifact text", 0.5, "improvement_sweep", 0.3)
    v.quarantine("unrelated loop's artifact", 0.6, "research_colony", 0.3)
    v.quarantine("new artifact text\nwith a second line", 0.7, "improvement_sweep", 0.3)

    assert v._last_quarantined_artifact_text("improvement_sweep") == "new artifact text\nwith a second line"


def test_last_quarantined_artifact_text_survives_a_reason_and_checkbox_footer(tmp_path, monkeypatch):
    quarantine_file = tmp_path / "quarantine.md"
    monkeypatch.setattr(v, "QUARANTINE_FILE", quarantine_file)

    v.quarantine("flagged artifact text", 0.9, "improvement_sweep", 0.3, reason="looked garbled")

    assert v._last_quarantined_artifact_text("improvement_sweep") == "flagged artifact text"


def test_quarantine_skips_a_block_identical_to_the_last_one_for_the_same_loop(tmp_path, monkeypatch):
    # The actual bug found live: quarantine.md had grown to 999 lines with
    # at least four byte-for-byte identical improvement_sweep blocks,
    # because DEFAULT_TAU never adapts and nothing dedupes the re-flagged
    # content -- the exact same failure shape improvement_sweep.py's own
    # queue writer had, but in the shared safety-monitor choke point instead.
    quarantine_file = tmp_path / "quarantine.md"
    monkeypatch.setattr(v, "QUARANTINE_FILE", quarantine_file)

    v.quarantine("repeat offender", 0.5, "improvement_sweep", 0.3)
    before = quarantine_file.read_text()

    v.quarantine("repeat offender", 0.6, "improvement_sweep", 0.3)

    assert quarantine_file.read_text() == before


def test_quarantine_still_appends_when_the_artifact_differs_from_the_last_block(tmp_path, monkeypatch):
    quarantine_file = tmp_path / "quarantine.md"
    monkeypatch.setattr(v, "QUARANTINE_FILE", quarantine_file)

    v.quarantine("first artifact", 0.5, "improvement_sweep", 0.3)
    before = quarantine_file.read_text()

    v.quarantine("second, different artifact", 0.6, "improvement_sweep", 0.3)

    assert quarantine_file.read_text() != before
    assert "second, different artifact" in quarantine_file.read_text()


def test_quarantine_dedup_is_scoped_per_loop_not_global(tmp_path, monkeypatch):
    quarantine_file = tmp_path / "quarantine.md"
    monkeypatch.setattr(v, "QUARANTINE_FILE", quarantine_file)

    v.quarantine("same-shaped content", 0.5, "improvement_sweep", 0.3)
    before = quarantine_file.read_text()

    v.quarantine("same-shaped content", 0.6, "research_colony", 0.3)

    assert quarantine_file.read_text() != before
