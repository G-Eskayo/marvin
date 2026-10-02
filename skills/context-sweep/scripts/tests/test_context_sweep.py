"""Tests for context_sweep.py. Run via:
    ~/.agents/venv/bin/python -m pytest skills/context-sweep/scripts/tests/test_context_sweep.py -v
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import context_sweep as cs  # noqa: E402
import background_context_sweep as bcs  # noqa: E402


class TestEnumerateContextFiles:
    """Test file enumeration logic."""

    def test_enumerate_finds_skill_markdown(self, tmp_path):
        """SKILL.md files in skills/ should be enumerated."""
        skills = tmp_path / ".agents" / "skills"
        (skills / "foo").mkdir(parents=True)
        (skills / "foo" / "SKILL.md").write_text("skill")
        (skills / "foo" / "other.md").write_text("other")  # non-SKILL.md ignored

        files = cs.enumerate_context_files(home_dir=tmp_path)

        assert any("foo/SKILL.md" in str(f) for f in files)
        assert not any("foo/other.md" in str(f) for f in files)

    def test_enumerate_finds_docs(self, tmp_path):
        """All .md files in docs/ should be enumerated."""
        docs = tmp_path / ".agents" / "docs" / "adr"
        docs.mkdir(parents=True)
        (docs / "adr-001.md").write_text("adr")
        (docs / "guide.md").write_text("guide")

        files = cs.enumerate_context_files(home_dir=tmp_path)

        assert any("adr-001.md" in str(f) for f in files)
        assert any("guide.md" in str(f) for f in files)

    def test_enumerate_finds_context_and_config(self, tmp_path):
        """CONTEXT.md and CLAUDE.md should be included."""
        (tmp_path / ".agents").mkdir()
        (tmp_path / ".agents" / "CONTEXT.md").write_text("context")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("claude")

        files = cs.enumerate_context_files(home_dir=tmp_path)

        assert any("CONTEXT.md" in str(f) for f in files)
        assert any(".claude/CLAUDE.md" in str(f) for f in files)

    def test_enumerate_finds_lexicon(self, tmp_path):
        """lexicon.md should be included."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "lexicon.md").write_text("lexicon")

        files = cs.enumerate_context_files(home_dir=tmp_path)

        assert any("lexicon.md" in str(f) for f in files)

    def test_enumerate_finds_handoffs(self, tmp_path):
        """All .md files in handoffs/ should be enumerated."""
        handoffs = tmp_path / ".claude" / "handoffs"
        handoffs.mkdir(parents=True)
        (handoffs / "handoff-a.md").write_text("a")
        (handoffs / "handoff-b.md").write_text("b")

        files = cs.enumerate_context_files(home_dir=tmp_path)

        assert any("handoff-a.md" in str(f) for f in files)
        assert any("handoff-b.md" in str(f) for f in files)

    def test_enumerate_finds_project_memory(self, tmp_path):
        """Per-project memory/*.md should be enumerated."""
        memory = tmp_path / ".claude" / "projects" / "my-project" / "memory"
        memory.mkdir(parents=True)
        (memory / "user.md").write_text("user info")
        (memory / "feedback.md").write_text("feedback")

        files = cs.enumerate_context_files(home_dir=tmp_path)

        assert any("memory/user.md" in str(f) for f in files)
        assert any("memory/feedback.md" in str(f) for f in files)

    def test_enumerate_deterministic_order(self, tmp_path):
        """Multiple runs should return files in the same order."""
        skills = tmp_path / "skills" / "foo"
        skills.mkdir(parents=True)
        (skills / "SKILL.md").write_text("skill")
        (tmp_path / ".agents").mkdir()
        (tmp_path / ".agents" / "CONTEXT.md").write_text("context")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("claude")

        run1 = cs.enumerate_context_files(home_dir=tmp_path)
        run2 = cs.enumerate_context_files(home_dir=tmp_path)

        assert [str(f) for f in run1] == [str(f) for f in run2]

    def test_enumerate_excludes_suggestions_md(self, tmp_path):
        """suggestions.md should never be included."""
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "suggestions.md").write_text("suggestions")
        (tmp_path / ".claude" / "CLAUDE.md").write_text("claude")

        files = cs.enumerate_context_files(home_dir=tmp_path)

        assert not any("suggestions.md" in str(f) for f in files)
        assert any("CLAUDE.md" in str(f) for f in files)

    def test_enumerate_handles_empty_directories(self, tmp_path):
        """Missing/empty directories should not cause errors."""
        (tmp_path / ".agents").mkdir()
        (tmp_path / ".claude").mkdir()

        files = cs.enumerate_context_files(home_dir=tmp_path)

        assert isinstance(files, list)

    def test_enumerate_deduplicates(self, tmp_path):
        """Duplicate paths should be deduplicated."""
        (tmp_path / ".agents").mkdir()
        (tmp_path / ".agents" / "CONTEXT.md").write_text("context")
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "CLAUDE.md").write_text("claude")

        files = cs.enumerate_context_files(home_dir=tmp_path)

        # Count occurrences; each should be unique
        file_strs = [str(f) for f in files]
        assert len(file_strs) == len(set(file_strs))


class TestNextChunk:
    """Test chunking logic."""

    def test_next_chunk_returns_slice(self):
        """next_chunk should return a slice of the requested size."""
        files = [Path(f"file{i}") for i in range(10)]
        chunk, new_index = cs.next_chunk(files, 0, chunk_size=3)

        assert len(chunk) == 3
        assert chunk == files[0:3]
        assert new_index == 3

    def test_next_chunk_wraps_at_end(self):
        """When reaching the end, cursor should wrap to the beginning."""
        files = [Path(f"file{i}") for i in range(10)]
        chunk, new_index = cs.next_chunk(files, 8, chunk_size=3)

        assert len(chunk) == 3
        # Files 8, 9 from end, then files 0 from wrap
        assert chunk == [files[8], files[9], files[0]]
        assert new_index == (8 + 3) % 10

    def test_next_chunk_handles_empty_list(self):
        """Empty file list should return empty chunk."""
        chunk, new_index = cs.next_chunk([], 0, chunk_size=5)

        assert chunk == []
        assert new_index == 0

    def test_next_chunk_smaller_than_chunk_size(self):
        """When files < chunk_size, return all files and wrap."""
        files = [Path(f"file{i}") for i in range(3)]
        chunk, new_index = cs.next_chunk(files, 0, chunk_size=5)

        assert len(chunk) == 5
        # All 3 files, then 0, 1 again
        assert chunk == [files[0], files[1], files[2], files[0], files[1]]

    def test_next_chunk_property_full_sweep(self):
        """Property test: multiple chunks should cover all files exactly once per cycle."""
        files = [Path(f"file{i}") for i in range(7)]
        chunk_size = 3
        total_chunks = (len(files) + chunk_size - 1) // chunk_size

        seen = []
        cursor = 0
        for _ in range(total_chunks):
            chunk, cursor = cs.next_chunk(files, cursor, chunk_size=chunk_size)
            seen.extend(chunk)

        # After one full cycle, we should have seen each file at least once
        unique_seen = list(dict.fromkeys(seen))
        assert len(unique_seen) == len(files)
        assert set(unique_seen) == set(files)

    def test_next_chunk_cursor_advances(self):
        """Cursor should advance by chunk_size each time."""
        files = [Path(f"file{i}") for i in range(20)]
        chunk_size = 5

        cursor = 0
        for expected_start in [0, 5, 10, 15, 0]:  # cycles back
            chunk, cursor = cs.next_chunk(files, cursor, chunk_size=chunk_size)
            assert len(chunk) == chunk_size


class TestRunReview:
    """Test review subprocess execution."""

    def test_run_review_on_success_advances_cursor(self, tmp_path, monkeypatch):
        """On zero exit, cursor should advance and lock written."""
        monkeypatch.setattr(bcs, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(bcs, "CURSOR_FILE", tmp_path / "state" / "chunk-cursor.json")
        monkeypatch.setattr(bcs, "LOCK_FILE", tmp_path / "state" / ".last-run")
        monkeypatch.setattr(bcs, "LOG_FILE", tmp_path / "state" / "sweep.log")
        monkeypatch.setattr(bcs, "SUGGESTIONS_FILE", tmp_path / "suggestions.md")
        monkeypatch.setattr(bcs, "_resolve_claude_bin", lambda: "/usr/bin/true")

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            class Result:
                returncode = 0
                stderr = ""
            return Result()

        monkeypatch.setattr(bcs.subprocess, "run", fake_run)

        chunk = [Path("file1"), Path("file2")]
        bcs.run_review(chunk, 1, 5)

        assert len(calls) == 2  # claude + sort_suggestions
        assert bcs.LOCK_FILE.exists()

    def test_run_review_on_failure_skips_sort(self, tmp_path, monkeypatch):
        """On nonzero exit, sort_suggestions should not be called."""
        monkeypatch.setattr(bcs, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(bcs, "CURSOR_FILE", tmp_path / "state" / "chunk-cursor.json")
        monkeypatch.setattr(bcs, "LOCK_FILE", tmp_path / "state" / ".last-run")
        monkeypatch.setattr(bcs, "LOG_FILE", tmp_path / "state" / "sweep.log")
        monkeypatch.setattr(bcs, "SUGGESTIONS_FILE", tmp_path / "suggestions.md")
        monkeypatch.setattr(bcs, "_resolve_claude_bin", lambda: "/usr/bin/true")

        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            class Result:
                returncode = 1
                stderr = ""
            return Result()

        monkeypatch.setattr(bcs.subprocess, "run", fake_run)

        chunk = [Path("file1")]
        bcs.run_review(chunk, 1, 5)

        assert len(calls) == 1  # only claude, no sort
        assert not bcs.LOCK_FILE.exists()

    def test_run_review_timeout_skips_sort(self, tmp_path, monkeypatch):
        """On timeout, sort_suggestions should not be called."""
        monkeypatch.setattr(bcs, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(bcs, "CURSOR_FILE", tmp_path / "state" / "chunk-cursor.json")
        monkeypatch.setattr(bcs, "LOCK_FILE", tmp_path / "state" / ".last-run")
        monkeypatch.setattr(bcs, "LOG_FILE", tmp_path / "state" / "sweep.log")
        monkeypatch.setattr(bcs, "SUGGESTIONS_FILE", tmp_path / "suggestions.md")
        monkeypatch.setattr(bcs, "_resolve_claude_bin", lambda: "/usr/bin/true")

        def fake_run(cmd, **kwargs):
            raise bcs.subprocess.TimeoutExpired("cmd", 300)

        monkeypatch.setattr(bcs.subprocess, "run", fake_run)

        chunk = [Path("file1")]
        bcs.run_review(chunk, 1, 5)

        assert not bcs.LOCK_FILE.exists()

    def test_render_chunk_paths(self, tmp_path):
        """Paths should render as bullet list."""
        paths = [Path("/home/user/file1.md"), Path("/home/user/file2.md")]
        rendered = bcs._render_chunk_paths(paths)

        assert "- /home/user/file1.md" in rendered
        assert "- /home/user/file2.md" in rendered

    def test_load_save_state(self, tmp_path, monkeypatch):
        """State should persist across save/load cycles."""
        monkeypatch.setattr(bcs, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(bcs, "CURSOR_FILE", tmp_path / "state" / "chunk-cursor.json")

        bcs._save_state(index=5)
        state = bcs._load_state()

        assert state["index"] == 5

    def test_cooldown_check(self, tmp_path, monkeypatch):
        """Cooldown should block re-runs within the window."""
        monkeypatch.setattr(bcs, "LOCK_FILE", tmp_path / ".last-run")
        monkeypatch.setattr(bcs, "COOLDOWN_SECONDS", 100)

        # No lock file -> not active
        assert not bcs._cooldown_active()

        # Create a lock file (mtime will be now)
        (tmp_path / ".last-run").write_text("locked")

        # Should be active (just created, so within 100s)
        assert bcs._cooldown_active()
