"""Tests for browser_close_guard.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_browser_close_guard.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import browser_close_guard as bcg  # noqa: E402


# ── _strip_comments ────────────────────────────────────────────────────────

def test_strip_comments_removes_inline_comments():
    line = "const x = 5  // this is a comment"
    assert bcg._strip_comments(line) == "const x = 5  "


def test_strip_comments_preserves_quoted_strings():
    line = 'const msg = "hello // world"  // real comment'
    assert bcg._strip_comments(line) == 'const msg = "hello // world"  '


def test_strip_comments_preserves_single_quoted_strings():
    line = "const msg = 'hello // world'  // real comment"
    assert bcg._strip_comments(line) == "const msg = 'hello // world'  "


def test_strip_comments_escaping():
    # Escaped quotes should not affect comment detection
    line = r'const msg = "hello \" world"  // comment'
    result = bcg._strip_comments(line)
    # The \" inside the string should not end the string
    assert "//" not in result or "comment" not in result


# ── check_file ────────────────────────────────────────────────────────────

def test_check_file_detects_bare_launch(tmp_path):
    test_file = tmp_path / "test.mjs"
    test_file.write_text("chromium.launch({ channel: 'chrome' })")

    violations = bcg.check_file(test_file)
    assert len(violations) >= 1
    assert "bare chromium.launch()" in violations[0]


def test_check_file_ignores_non_mjs_files(tmp_path):
    test_file = tmp_path / "test.js"
    test_file.write_text("chromium.launch()")

    violations = bcg.check_file(test_file)
    assert violations == []


def test_check_file_detects_launch_without_close(tmp_path):
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "const browser = await chromium.launch()\n"
        "// do something\n"
        "// never close"
    )

    violations = bcg.check_file(test_file)
    assert any("has no close() call" in v for v in violations)


def test_check_file_detects_unwaited_close(tmp_path):
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "const browser = await chromium.launch()\n"
        "after(() => browser?.close())"
    )

    violations = bcg.check_file(test_file)
    assert any("is not awaited" in v for v in violations)


def test_check_file_accepts_awaited_close(tmp_path):
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "const browser = await chromium.launch()\n"
        "after(async () => { await browser?.close() })"
    )

    violations = bcg.check_file(test_file)
    assert violations == []


def test_check_file_skips_whole_line_comments(tmp_path):
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "// const x = await chromium.launch()\n"
        "const browser = await chromium.launch()\n"
        "after(async () => { await browser?.close() })"
    )

    violations = bcg.check_file(test_file)
    assert len(violations) == 0


def test_check_file_handles_missing_file(tmp_path):
    test_file = tmp_path / "nonexistent.mjs"
    violations = bcg.check_file(test_file)
    assert violations == []


# ── check_repo ────────────────────────────────────────────────────────────

def test_check_repo_finds_multiple_violations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    test1 = tmp_path / "test1.test.mjs"
    test1.write_text("const b = await chromium.launch()")

    test2 = tmp_path / "test2.test.mjs"
    test2.write_text("chromium.launch()")

    violations = bcg.check_repo()
    assert len(violations) >= 2


def test_check_repo_excludes_node_modules(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    # Create a file in node_modules
    nm = tmp_path / "node_modules"
    nm.mkdir()
    bad_test = nm / "test.test.mjs"
    bad_test.write_text("chromium.launch()")

    # Create a good file outside node_modules
    good_test = tmp_path / "test.test.mjs"
    good_test.write_text(
        "const b = await chromium.launch()\n"
        "after(async () => { await b?.close() })"
    )

    violations = bcg.check_repo()
    # Should not include violations from node_modules
    assert not any("node_modules" in v for v in violations)


# ── Optional-chaining and variable-assignment fixes ────────────────────────

def test_check_file_accepts_unassigned_launch_without_decl(tmp_path):
    """Test that 'browser = await chromium.launch()' works (var declared earlier)."""
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "let browser;\n"
        "async function setup() {\n"
        "  browser = await chromium.launch()\n"
        "}\n"
        "after(async () => { await browser?.close() })"
    )

    violations = bcg.check_file(test_file)
    # Should not report violations for the assignment without 'const/let/var'
    assert not any("bare chromium.launch()" in v for v in violations)
    # And should recognize the close() call
    assert not any("has no close() call" in v for v in violations)


def test_check_file_optional_chaining_dot_escape(tmp_path):
    """Test that both 'browser.close()' and 'browser?.close()' are detected."""
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "const b = await chromium.launch()\n"
        "after(async () => { await b.close() })"  # No optional chaining
    )

    violations = bcg.check_file(test_file)
    # Should recognize b.close() without the ?
    assert not any("has no close() call" in v for v in violations)


def test_check_file_detects_channel_chrome_without_comment(tmp_path):
    """Test that channel: 'chrome' without comment is flagged."""
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "const b = await chromium.launch({ channel: 'chrome' })"
    )

    violations = bcg.check_file(test_file)
    assert any("channel: 'chrome' without comment" in v for v in violations)


def test_check_file_accepts_channel_chrome_with_inline_comment(tmp_path):
    """Test that channel: 'chrome' with inline comment is accepted."""
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "const b = await chromium.launch({ channel: 'chrome' }) // macOS only"
    )

    violations = bcg.check_file(test_file)
    assert not any("channel: 'chrome' without comment" in v for v in violations)


def test_check_file_accepts_channel_chrome_with_preceding_comment(tmp_path):
    """Test that channel: 'chrome' with preceding comment line is accepted."""
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "// macOS only\n"
        "const b = await chromium.launch({ channel: 'chrome' })"
    )

    violations = bcg.check_file(test_file)
    assert not any("channel: 'chrome' without comment" in v for v in violations)


def test_check_file_whole_line_comment_detection_fixed(tmp_path):
    """Test that whole-line comments are correctly skipped (raw line non-empty, stripped empty)."""
    test_file = tmp_path / "test.mjs"
    test_file.write_text(
        "  // const b = await chromium.launch()\n"
        "const b = await chromium.launch()\n"
        "after(async () => { await b?.close() })"
    )

    violations = bcg.check_file(test_file)
    # Should not flag the commented-out line as a launch without close
    launch_violations = [v for v in violations if "has no close() call" in v or "bare chromium" in v]
    assert launch_violations == []
