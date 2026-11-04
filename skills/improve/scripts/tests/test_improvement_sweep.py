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


def test_known_project_paths_point_where_the_projects_actually_live():
    # These had drifted to paths that exist on neither Mac (~/resume-tailor, ~/marvin-bench, ~/gileskayo.me), so the
    # sweep silently skipped them. Resume Tailor lives inside MARVIN as a skill; the bench lives in ~/.agents/bench.
    import improvement_sweep as sweep
    home = Path.home()
    assert sweep.KNOWN_PROJECTS["resume-tailor"] == home / ".agents" / "skills" / "resume-tailor"
    assert sweep.KNOWN_PROJECTS["marvin-bench"] == home / ".agents" / "bench"
    assert sweep.KNOWN_PROJECTS["portfolio"] == home / "Developer" / "portfolio-website-updater"


# ── after the move to the inbox (ADR 0083) ───────────────────────────────────────────────────────────────────

import json  # noqa: E402

import pytest  # noqa: E402

LIB = Path(__file__).resolve().parents[4] / "lib"
sys.path.insert(0, str(LIB))
import inbox  # noqa: E402


@pytest.fixture
def piled(tmp_path, monkeypatch):
    """A temp ~/.claude whose improvement queue has already moved into the inbox."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    queue_file = claude / "improvement-queue.md"
    queue_file.write_text("# Improvement Queue\n\n---\n## 2026-07-01 — marvin\n\n"
                          "- **[NAMING]** old one (`a.py`) — auto-fix: done, PR #9 merged\n")
    monkeypatch.setattr(inbox, "default_root", lambda: claude / "inbox")
    monkeypatch.setattr(isw, "QUEUE_FILE", queue_file)
    monkeypatch.setattr(isw, "_SAFETY_MONITOR_AVAILABLE", False)
    inbox.import_legacy("improvement-queue")
    return queue_file


def _items():
    return {i["fields"]["entry"]: i for i in inbox.list_items("improvement-queue")["items"]}


def test_in_inbox_mode_findings_become_items_and_the_old_file_is_untouched(piled):
    before = piled.read_text()
    assert isw.append_to_queue("marvin", [_issue("LOGIC", "new bug", "b.py"), _issue("NAMING", "old one", "a.py")])
    items = _items()
    assert piled.read_text() == before
    new = items["**[LOGIC]** new bug (`b.py`)"]
    assert new["status"] == {"state": "open"} and new["fields"]["project"] == "marvin" and new["source"] == "improvement-sweep"
    assert items["**[NAMING]** old one (`a.py`)"]["status"]["state"] == "done"  # a repeat keeps its auto-fix status
    assert items["**[NAMING]** old one (`a.py`)"]["added"] == "2026-07-01"  # and its first date


def test_in_inbox_mode_a_repeat_sweep_adds_nothing_and_reports_skipped(piled):
    issues = [_issue("LOGIC", "new bug", "b.py")]
    isw.append_to_queue("marvin", issues)
    before = isw.queue_snapshot()
    assert isw.append_to_queue("other-project", issues)  # dedupe is by finding, not per project
    after = isw.queue_snapshot()
    assert before == after and len(_items()) == 2
    assert "skipped" in isw._report_outcome(True, before, after, "marvin", 1)


def test_in_inbox_mode_a_quarantined_block_adds_nothing(piled, monkeypatch):
    monkeypatch.setattr(isw, "_SAFETY_MONITOR_AVAILABLE", True)
    monkeypatch.setattr(isw, "pass_or_quarantine", lambda block, loop_name: False, raising=False)
    assert isw.append_to_queue("marvin", [_issue("LOGIC", "garbled", "c.py")]) is False
    assert len(_items()) == 1


def test_in_inbox_mode_an_unparseable_finding_is_kept_as_an_untyped_item(piled):
    isw.append_to_queue("marvin", [{"metadata": {"category": "anti-pattern"}, "document": "weird ünïcode finding"}])
    assert any(i["title"] == "weird ünïcode finding" and "kind" not in i["fields"] for i in _items().values())
    json.dumps(inbox.list_items("improvement-queue"))
