"""Tests for background_review.py. Run via:
    ~/.agents/venv/bin/python -m pytest skills/self-improve/scripts/tests/test_background_review.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import background_review as br


def test_diff_lines_added_only():
    """_diff_lines detects only added lines when before is empty."""
    before = ""
    after = "line1\nline2\nline3"
    added, removed = br._diff_lines(before, after)
    assert added == ["line1", "line2", "line3"]
    assert removed == []


def test_diff_lines_removed_only():
    """_diff_lines detects only removed lines when after is empty."""
    before = "line1\nline2\nline3"
    after = ""
    added, removed = br._diff_lines(before, after)
    assert added == []
    assert removed == ["line1", "line2", "line3"]


def test_diff_lines_both_added_and_removed():
    """_diff_lines detects both added and removed lines."""
    before = "line1\nline2\nline3"
    after = "line2\nline4\nline5"
    added, removed = br._diff_lines(before, after)
    assert added == ["line4", "line5"]
    assert removed == ["line1", "line3"]


def test_diff_lines_with_duplicates():
    """_diff_lines handles duplicate lines correctly via Counter."""
    before = "line1\nline1\nline2"
    after = "line1\nline2\nline2"
    added, removed = br._diff_lines(before, after)
    assert added == ["line2"]
    assert removed == ["line1"]


def test_diff_lines_no_changes():
    """_diff_lines returns empty lists when before equals after."""
    before = "line1\nline2"
    after = "line1\nline2"
    added, removed = br._diff_lines(before, after)
    assert added == []
    assert removed == []


def test_remove_lines_simple():
    """_remove_lines removes specified lines from text."""
    text = "line1\nline2\nline3"
    lines_to_remove = ["line2"]
    result = br._remove_lines(text, lines_to_remove)
    assert result == "line1\nline3"


def test_remove_lines_last_occurrence_when_duplicates():
    """_remove_lines removes the LAST occurrence of duplicated lines.
    This catches the bug where the first occurrence was removed instead,
    causing log reordering when undoing an append."""
    # Text ends with newline so all lines get one from splitlines(keepends=True)
    text = "X\nY\nX\n"
    lines_to_remove = ["X"]
    result = br._remove_lines(text, lines_to_remove)
    # Should remove the last X, not the first, leaving "X\nY\n"
    assert result == "X\nY\n"
    # Verify it's NOT the first X that was removed
    assert not result.startswith("Y")


def test_remove_lines_preserves_trailing_newline():
    """_remove_lines preserves the file's trailing newline.
    This catches the bug where splitlines() without keepends drops
    the trailing newline, causing the file to be rewritten."""
    text = "line1\nline2\nline3\n"
    lines_to_remove = ["line2"]
    result = br._remove_lines(text, lines_to_remove)
    # Must preserve the trailing newline
    assert result == "line1\nline3\n"
    assert result.endswith("\n")


def test_remove_lines_preserves_windows_line_endings():
    """_remove_lines preserves original line endings (\\r\\n, \\n, etc).
    This catches the bug where splitlines() without keepends
    normalizes all line endings to \\n."""
    text = "line1\r\nline2\r\nline3\r\n"
    lines_to_remove = ["line2"]
    result = br._remove_lines(text, lines_to_remove)
    # Must preserve \r\n, not convert to \n
    assert result == "line1\r\nline3\r\n"
    assert "\r\n" in result


def test_atomic_write_creates_new_file(tmp_path):
    """_atomic_write creates a new file atomically."""
    target = tmp_path / "test_file.txt"
    content = "test content"
    br._atomic_write(target, content)
    assert target.read_text() == content


def test_atomic_write_overwrites_existing_file(tmp_path):
    """_atomic_write overwrites existing file atomically and preserves permissions."""
    target = tmp_path / "test_file.txt"
    target.write_text("old content")
    target.chmod(0o644)
    old_mode = target.stat().st_mode & 0o777

    new_content = "new content"
    br._atomic_write(target, new_content)

    assert target.read_text() == new_content
    assert target.stat().st_mode & 0o777 == old_mode


def test_remove_lines_no_trailing_newline_ending_in_space():
    """_remove_lines correctly removes a line without trailing newline that ends in space.
    This catches the bug where checking for space as a line ending fails to match
    lines without any line ending. splitlines() doesn't treat space as a separator."""
    text = "entry "
    lines_to_remove = ["entry "]
    result = br._remove_lines(text, lines_to_remove)
    assert result == ""


def test_remove_lines_with_vertical_tab():
    """_remove_lines handles vertical tab (\\v = \\x0b), a splitlines() separator
    not in the previous hardcoded list. This catches missing line separators."""
    text = "line1\x0bline2\n"
    lines_to_remove = ["line1"]
    result = br._remove_lines(text, lines_to_remove)
    assert result == "line2\n"


def test_remove_lines_last_line_with_form_feed():
    """_remove_lines correctly handles form feed (\\f = \\x0c), a splitlines() separator.
    Form feed is in splitlines() separators but was incorrectly placed in the
    check-for-space position."""
    text = "line1\fline2\n"
    lines_to_remove = ["line1"]
    result = br._remove_lines(text, lines_to_remove)
    assert result == "line2\n"


def test_remove_lines_preserves_unicode_line_separators():
    """_remove_lines handles Unicode line separators (\\u2028, \\u2029)."""
    text = "line1 line2\n"
    lines_to_remove = ["line1"]
    result = br._remove_lines(text, lines_to_remove)
    assert result == "line2\n"


def test_verify_and_reconcile_calls_verify_even_when_removed_is_nonempty(tmp_path, monkeypatch):
    """_verify_and_reconcile must call verify() on added lines even when removed is non-empty.
    This catches the bug where the function returned early when removed != [], skipping
    verification entirely. The design says to log and continue, not return."""
    # Mock dependencies
    verify_called = []

    def mock_verify(lines, loop_name=None):
        verify_called.append(True)
        return 0.1  # score below tau

    log_mock = MagicMock()

    # Patch the safety-monitor imports and functions
    monkeypatch.setattr(br, "verify", mock_verify)
    monkeypatch.setattr(br, "get_tau", lambda x: 0.5)
    monkeypatch.setattr(br, "_SAFETY_MONITOR_AVAILABLE", True)

    # Set up RETRO_LOG to return content with both added and removed lines
    before = "old_line\n"
    after = "new_line\n"  # removed old_line, added new_line

    retro_log_mock = MagicMock()
    retro_log_mock.exists.return_value = True
    retro_log_mock.read_text.return_value = after
    monkeypatch.setattr(br, "RETRO_LOG", retro_log_mock)

    # Call the function
    br._verify_and_reconcile(before, log_mock)

    # Verify that verify() was called even though removed was non-empty
    assert verify_called, "verify() should be called even when removed is non-empty"

    # Check that the function logged about the non-additive change
    log_calls = [str(call) for call in log_mock.write.call_args_list]
    assert any("changed non-additively" in str(call) for call in log_calls), \
        "Should log about non-additive change"
