"""session_start_report's pile counts read the inbox once a pile has moved in (ADR 0083), the old file until then."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import inbox  # noqa: E402
import session_start_report as ssr  # noqa: E402

SUGGESTIONS = ("## A\n**Priority**: 5\n**Status**: pending\n**Added**: 2026-10-01\n\n"
               "## B\n**Priority**: 4\n**Status**: open\n**Added**: 2026-10-02\n\n"
               "## C\n**Priority**: 3\n**Status**: promoted 2026-10-03 #9\n**Added**: 2026-10-02\n")
QUEUE = ("## 2026-07-01 — marvin\n- **[NAMING]** a (`x.py`)\n- **[NAMING]** b (`x.py`) — auto-fix: done, PR #1 merged\n"
         "## 2026-07-02 — marvin\n- **[NAMING]** a (`x.py`)\n")


@pytest.fixture
def claude(tmp_path, monkeypatch):
    d = tmp_path / ".claude"
    d.mkdir()
    (d / "suggestions.md").write_text(SUGGESTIONS)
    (d / "improvement-queue.md").write_text(QUEUE)
    monkeypatch.setattr(ssr, "CLAUDE_DIR", d)
    return d


def test_before_the_import_the_old_files_are_counted(claude):
    assert ssr.check_suggestions() == "1 architecture suggestion(s) pending in suggestions.md"
    assert ssr.check_improvement_queue() == "3 item(s) queued in improvement-queue.md"


def test_after_the_import_open_items_are_counted_once(claude):
    for pile in ("suggestions", "improvement-queue"):
        inbox.import_legacy(pile, claude / "inbox")
    assert ssr.check_suggestions() == "2 architecture suggestion(s) pending in the inbox"  # "open" counts as pending
    assert ssr.check_improvement_queue() == "1 item(s) queued in the improvement queue"  # repeats folded, done left out


def test_an_empty_pile_says_nothing(claude):
    (claude / "suggestions.md").write_text("")
    inbox.import_legacy("suggestions", claude / "inbox")
    assert ssr.check_suggestions() is None


def test_a_broken_item_file_does_not_break_the_report(claude):
    inbox.import_legacy("suggestions", claude / "inbox")
    (claude / "inbox" / "suggestions" / "junk.json").write_text("{")
    assert ssr.check_suggestions() == "2 architecture suggestion(s) pending in the inbox"
