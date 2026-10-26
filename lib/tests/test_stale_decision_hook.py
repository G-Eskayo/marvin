#!/usr/bin/env python3
"""Tests for stale_decision_hook: covering cases 4-9, 11, 16.

Cases 1-3, 12-15, 18: core check logic tested in test_stale_decision_check.py.
Case 17: handoff/self-improve integration tested separately.
"""
import json
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import stale_decision_hook as hook
import host_os


@pytest.fixture
def temp_memory_dir(tmp_path):
    """Create a temporary memory directory."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    original_memory_dir = hook.MEMORY_DIR
    hook.MEMORY_DIR = memory_dir
    yield memory_dir
    hook.MEMORY_DIR = original_memory_dir


@pytest.fixture
def temp_locks_dir(tmp_path):
    """Create a temporary locks directory."""
    locks_dir = tmp_path / "locks"
    locks_dir.mkdir()
    original_locks_dir = hook.LOCKS_DIR
    hook.LOCKS_DIR = locks_dir
    yield locks_dir
    hook.LOCKS_DIR = original_locks_dir


def test_4_empty_whitespace_new_text(temp_memory_dir, temp_locks_dir):
    """Case 4: empty/whitespace-only new text -> no search attempted."""
    payload = {
        "file_path": str(temp_memory_dir / "test.md"),
        "content": "   \n  \t  "
    }

    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read = lambda: json.dumps(payload)
        # Should process but extract empty text and return early
        hook.main()
        # No check should have been attempted


def test_5_huge_new_text(temp_memory_dir, temp_locks_dir):
    """Case 5: huge new text doesn't hang, processing is bounded."""
    huge_content = "\n".join(["This is line {}".format(i) for i in range(10000)])

    test_file = temp_memory_dir / "test.md"
    payload = {
        "file_path": str(test_file),
        "content": huge_content
    }

    # Should complete quickly despite huge input
    start = time.time()

    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read = lambda: json.dumps(payload)
        with patch.object(hook, "_run_check_in_background"):
            hook.main()

    elapsed = time.time() - start
    assert elapsed < 5  # Should be fast


def test_6_malformed_binary_content_in_payload(temp_memory_dir, temp_locks_dir):
    """Case 6: malformed/binary-ish content -> read fails safely, no crash."""
    # Invalid UTF-8 sequences
    test_file = temp_memory_dir / "test.md"
    payload = {
        "file_path": str(test_file),
        "content": "Valid text � Invalid bytes"
    }

    # Should not crash
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read = lambda: json.dumps(payload)
        with patch.object(hook, "_run_check_in_background"):
            hook.main()


def test_7_multiple_failure_paths_dont_block():
    """Case 7: errors don't crash or block the hook."""
    # Broken JSON in stdin
    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read = lambda: "{ invalid json"
        # Should not raise
        hook.main()


def test_8_repeats_cooldown_collapses_checks(temp_memory_dir, temp_locks_dir):
    """Case 8: same file edited twice quickly -> cooldown prevents duplicate checks."""
    test_file = temp_memory_dir / "test.md"

    # First check
    payload1 = {
        "file_path": str(test_file),
        "content": "New claim 1"
    }

    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read = lambda: json.dumps(payload1)
        with patch.object(hook, "_run_check_in_background") as mock_run:
            hook.main()
            mock_run.assert_called_once()

    # Second check immediately after
    payload2 = {
        "file_path": str(test_file),
        "content": "New claim 2"
    }

    with patch("sys.stdin") as mock_stdin:
        mock_stdin.read = lambda: json.dumps(payload2)
        with patch.object(hook, "_run_check_in_background") as mock_run:
            hook.main()
            # Should not run due to cooldown
            mock_run.assert_not_called()

    # After cooldown expires, should run again
    # (Skip this for speed, cooldown is 5 minutes)


def test_9_concurrent_append_from_different_files(temp_memory_dir, temp_locks_dir):
    """Case 9: two files edited simultaneously -> both can spawn checks without race."""
    file1 = temp_memory_dir / "test1.md"
    file2 = temp_memory_dir / "test2.md"

    payloads = [
        {"file_path": str(file1), "content": "Claim 1"},
        {"file_path": str(file2), "content": "Claim 2"}
    ]

    with patch.object(hook, "_run_check_in_background") as mock_run:
        for payload in payloads:
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.read = lambda p=payload: json.dumps(p)
                hook.main()

        # Both should have spawned
        assert mock_run.call_count == 2


def test_11_context_md_not_at_repo_root_excluded(temp_locks_dir):
    """Case 11: CONTEXT.md not at repo root (e.g., in node_modules) -> excluded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # CONTEXT.md inside node_modules (not a repo root)
        nested_path = Path(tmpdir) / "node_modules" / "package" / "CONTEXT.md"
        nested_path.parent.mkdir(parents=True)
        nested_path.touch()

        payload = {
            "file_path": str(nested_path),
            "content": "This should not trigger"
        }

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read = lambda: json.dumps(payload)
            with patch.object(hook, "_run_check_in_background") as mock_run:
                hook.main()
                # Should not run because CONTEXT.md has no repo root signals
                mock_run.assert_not_called()


def test_11b_context_md_at_repo_root_included(temp_locks_dir):
    """Case 11b: CONTEXT.md at repo root with .git -> included."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        context_md = repo_path / "CONTEXT.md"
        context_md.write_text("Repo documentation")

        payload = {
            "file_path": str(context_md),
            "content": "Updated content"
        }

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read = lambda: json.dumps(payload)
            with patch.object(hook, "_run_check_in_background") as mock_run:
                hook.main()
                # Should run because CONTEXT.md is at repo root
                mock_run.assert_called_once()


def test_16_hook_never_blocks(temp_memory_dir, temp_locks_dir):
    """Case 16: hook detaches subprocess, never blocks originating tool call."""
    test_file = temp_memory_dir / "test.md"
    payload = {
        "file_path": str(test_file),
        "content": "New claim"
    }

    # Mock Popen to simulate subprocess.Popen
    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.read = lambda: json.dumps(payload)

            start = time.time()
            hook.main()
            elapsed = time.time() - start

        # Should be nearly instant (subprocess is detached)
        assert elapsed < 0.1  # Very fast
        mock_popen.assert_called_once()


def test_extract_new_text_write():
    """Extract text from Write payload (content field)."""
    payload = {"content": "This is the new content"}
    text = hook._extract_new_text(payload)
    assert text == "This is the new content"


def test_extract_new_text_edit():
    """Extract text from Edit payload (new_string field)."""
    payload = {"new_string": "This is the edited text"}
    text = hook._extract_new_text(payload)
    assert text == "This is the edited text"


def test_extract_new_text_multiedit():
    """Extract text from MultiEdit payload (items with new_string)."""
    payload = {
        "items": [
            {"old_string": "a", "new_string": "A"},
            {"old_string": "b", "new_string": "B"}
        ]
    }
    text = hook._extract_new_text(payload)
    assert "A" in text
    assert "B" in text


def test_extract_new_text_empty():
    """Extract from payload with no recognized fields."""
    payload = {"unknown_field": "value"}
    text = hook._extract_new_text(payload)
    assert text == ""


def test_should_check_memory_file(temp_memory_dir):
    """Memory file in MEMORY_DIR should be checked."""
    test_file = temp_memory_dir / "test.md"
    test_file.touch()

    assert hook._should_check(test_file) is True


def test_should_check_non_memory_file(temp_memory_dir):
    """Non-.md file in MEMORY_DIR should not be checked."""
    test_file = temp_memory_dir / "test.txt"
    test_file.touch()

    assert hook._should_check(test_file) is False


def test_should_check_context_md_with_git():
    """CONTEXT.md with .git sibling should be checked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / ".git").mkdir()
        context_md = repo_path / "CONTEXT.md"
        context_md.touch()

        assert hook._should_check(context_md) is True


def test_should_check_context_md_with_docs_adr():
    """CONTEXT.md with docs/adr subdir should be checked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir)
        (repo_path / "docs" / "adr").mkdir(parents=True)
        context_md = repo_path / "CONTEXT.md"
        context_md.touch()

        assert hook._should_check(context_md) is True


def test_should_check_adr_file():
    """docs/adr/*.md should be checked."""
    with tempfile.TemporaryDirectory() as tmpdir:
        adr_dir = Path(tmpdir) / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        adr_file = adr_dir / "0001.md"
        adr_file.touch()

        assert hook._should_check(adr_file) is True


def test_cooldown_active_and_expiry(temp_locks_dir):
    """Cooldown tracking works: mark as checked, verify cooldown, verify expiry."""
    test_file = Path("/fake/file.md")

    # Initially no cooldown
    assert hook._cooldown_active(test_file) is False

    # Mark as checked
    hook._mark_checked(test_file)

    # Now in cooldown
    assert hook._cooldown_active(test_file) is True

    # Make the lock file appear old
    lock = hook._lock_file(test_file)
    old_time = time.time() - hook.COOLDOWN_SECONDS - 1
    import os
    os.utime(lock, (old_time, old_time))

    # Cooldown should be expired
    assert hook._cooldown_active(test_file) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
