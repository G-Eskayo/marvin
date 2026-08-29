"""Tests for improvement_sweep.py's queue-writer dedup. Run via:
    ~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_improvement_sweep.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import improvement_sweep as isw  # noqa: E402


def _issue(kind: str, msg: str, filepath: str) -> dict:
    return {
        "metadata": {"category": "anti-pattern"},
        "document": f"[{kind}] {msg} (file: {filepath})",
    }


def test_last_block_issue_lines_returns_none_when_queue_file_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(isw, "QUEUE_FILE", tmp_path / "improvement-queue.md")
    assert isw._last_block_issue_lines("marvin") is None


def test_last_block_issue_lines_returns_none_when_project_never_appeared(tmp_path, monkeypatch):
    queue_file = tmp_path / "improvement-queue.md"
    monkeypatch.setattr(isw, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(isw, "_SAFETY_MONITOR_AVAILABLE", False)

    isw.append_to_queue("hermes-agent", [_issue("VERBOSITY", "filler word", "a.py")])

    assert isw._last_block_issue_lines("marvin") is None


def test_last_block_issue_lines_extracts_the_most_recent_matching_block(tmp_path, monkeypatch):
    queue_file = tmp_path / "improvement-queue.md"
    monkeypatch.setattr(isw, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(isw, "_SAFETY_MONITOR_AVAILABLE", False)

    isw.append_to_queue("marvin", [_issue("VERBOSITY", "old filler", "old.py")])
    isw.append_to_queue("hermes-agent", [_issue("KISS", "long function", "b.py")])
    isw.append_to_queue("marvin", [_issue("VERBOSITY", "new filler", "new.py")])

    lines = isw._last_block_issue_lines("marvin")

    assert lines == [isw.format_issue(_issue("VERBOSITY", "new filler", "new.py"))]


def test_append_to_queue_skips_a_block_identical_to_the_last_one_for_the_same_project(tmp_path, monkeypatch):
    # The actual bug found live: improvement-queue.md's tail had 8 byte-for-
    # -byte identical blocks in a row (2026-07-14) because nothing compared
    # against what was already queued -- pure repeat content, forever.
    queue_file = tmp_path / "improvement-queue.md"
    monkeypatch.setattr(isw, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(isw, "_SAFETY_MONITOR_AVAILABLE", False)

    issues = [_issue("VERBOSITY", "filler word", "a.py")]
    isw.append_to_queue("marvin", issues)
    before = queue_file.read_text()

    result = isw.append_to_queue("marvin", issues)

    assert result is True
    assert queue_file.read_text() == before


def test_append_to_queue_still_appends_when_the_issues_differ_from_the_last_block(tmp_path, monkeypatch):
    queue_file = tmp_path / "improvement-queue.md"
    monkeypatch.setattr(isw, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(isw, "_SAFETY_MONITOR_AVAILABLE", False)

    isw.append_to_queue("marvin", [_issue("VERBOSITY", "filler word", "a.py")])
    before = queue_file.read_text()

    result = isw.append_to_queue("marvin", [_issue("KISS", "long function", "b.py")])

    assert result is True
    assert queue_file.read_text() != before
    assert "long function" in queue_file.read_text()


def test_append_to_queue_dedup_is_scoped_per_project_not_global(tmp_path, monkeypatch):
    # Two different projects legitimately queuing the same-shaped issue on
    # the same day must not suppress each other.
    queue_file = tmp_path / "improvement-queue.md"
    monkeypatch.setattr(isw, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(isw, "_SAFETY_MONITOR_AVAILABLE", False)

    issues = [_issue("VERBOSITY", "filler word", "a.py")]
    isw.append_to_queue("marvin", issues)
    before = queue_file.read_text()

    result = isw.append_to_queue("hermes-agent", issues)

    assert result is True
    assert queue_file.read_text() != before


def test_report_outcome_says_quarantined_when_append_returned_false():
    msg = isw._report_outcome(appended=False, before="a", after="a", project_name="marvin", count=3)
    assert "quarantined" in msg


def test_report_outcome_says_skipped_when_content_did_not_change():
    msg = isw._report_outcome(appended=True, before="same", after="same", project_name="marvin", count=3)
    assert "skipped" in msg
    assert "quarantined" not in msg


def test_report_outcome_says_queued_when_content_actually_changed():
    msg = isw._report_outcome(appended=True, before="old", after="old\nnew", project_name="marvin", count=3)
    assert "queued" in msg
    assert "skipped" not in msg
    assert "quarantined" not in msg
