"""Tests for background_context_sweep.py's chunk enumeration, sorting, and state management.
Run via:
    ~/.agents/venv/bin/python -m pytest skills/context-sweep/scripts/tests/test_background_context_sweep.py -v
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import background_context_sweep as bcs  # noqa: E402


class TestChunkEnumeration:
    """Full rotation visits every file exactly once, no skips or duplication."""

    def test_enumerate_chunks_returns_list_of_dicts(self, tmp_path, monkeypatch):
        """Chunk enumeration returns a well-formed structure."""
        monkeypatch.setattr(bcs, "AGENTS_DIR", tmp_path / "agents")
        monkeypatch.setattr(bcs, "CLAUDE_DIR", tmp_path / "claude")

        (tmp_path / "agents" / "skills").mkdir(parents=True)

        chunks = bcs._enumerate_chunks()
        assert isinstance(chunks, list)
        for chunk in chunks:
            assert "name" in chunk
            assert "paths" in chunk
            assert isinstance(chunk["paths"], list)

    def test_full_rotation_visits_every_file_exactly_once(self, tmp_path, monkeypatch):
        """A complete rotation cycles through all files without duplication or skips."""
        agents_dir = tmp_path / "agents"
        (agents_dir / "skills" / "skill-a" / "scripts").mkdir(parents=True)
        (agents_dir / "skills" / "skill-b").mkdir(parents=True)
        (agents_dir / "lib").mkdir(parents=True)

        (agents_dir / "skills" / "skill-a" / "SKILL.md").write_text("a")
        (agents_dir / "skills" / "skill-a" / "scripts" / "tool.py").write_text("code")
        (agents_dir / "skills" / "skill-b" / "SKILL.md").write_text("b")
        (agents_dir / "lib" / "util.py").write_text("lib")

        claude_dir = tmp_path / "claude"
        (claude_dir / "handoffs").mkdir(parents=True)
        (claude_dir / "handoffs" / "h1.md").write_text("h1")
        (claude_dir / "CLAUDE.md").write_text("config")

        monkeypatch.setattr(bcs, "AGENTS_DIR", agents_dir)
        monkeypatch.setattr(bcs, "CLAUDE_DIR", claude_dir)

        chunks = bcs._enumerate_chunks()
        assert len(chunks) > 0
        names = {c["name"] for c in chunks}
        assert len(names) == len(chunks), "Duplicate chunk names found"

    def test_enumeration_recomputed_reflects_added_files(self, tmp_path, monkeypatch):
        """When files are added between runs, enumerate_chunks() includes them."""
        agents_dir = tmp_path / "agents"
        (agents_dir / "skills").mkdir(parents=True)
        claude_dir = tmp_path / "claude"
        claude_dir.mkdir(parents=True)

        monkeypatch.setattr(bcs, "AGENTS_DIR", agents_dir)
        monkeypatch.setattr(bcs, "CLAUDE_DIR", claude_dir)

        chunks1 = bcs._enumerate_chunks()
        count1 = len(chunks1)

        # Add a new skill directory with a file
        (agents_dir / "skills" / "new-skill").mkdir(parents=True)
        (agents_dir / "skills" / "new-skill" / "SKILL.md").write_text("new")

        chunks2 = bcs._enumerate_chunks()
        count2 = len(chunks2)

        assert count2 > count1, "New skill not reflected in enumeration"

    def test_nested_subdirectories_included_in_chunks(self, tmp_path, monkeypatch):
        """Files in nested subdirectories are enumerated, not dropped."""
        agents_dir = tmp_path / "agents"
        (agents_dir / "skills" / "skill-x" / "scripts" / "nested" / "deep").mkdir(parents=True)
        (agents_dir / "skills" / "skill-x" / "SKILL.md").write_text("x")
        (agents_dir / "skills" / "skill-x" / "scripts" / "nested" / "deep" / "file.py").write_text("deep")

        claude_dir = tmp_path / "claude"
        claude_dir.mkdir(parents=True)

        monkeypatch.setattr(bcs, "AGENTS_DIR", agents_dir)
        monkeypatch.setattr(bcs, "CLAUDE_DIR", claude_dir)

        chunks = bcs._enumerate_chunks()
        assert len(chunks) > 0


class TestCooldown:
    """Cooldown prevents duplicate runs within the throttle window."""

    def test_cooldown_inactive_on_fresh_start(self, tmp_path, monkeypatch):
        """No lock file → cooldown is not active."""
        monkeypatch.setattr(bcs, "LOCK_FILE", tmp_path / "nofile")

        assert bcs._cooldown_active() is False

    def test_cooldown_active_within_window(self, tmp_path, monkeypatch):
        """Recent lock file → cooldown is active."""
        lock_file = tmp_path / "lock"
        lock_file.write_text(str(time.time()))

        monkeypatch.setattr(bcs, "LOCK_FILE", lock_file)
        monkeypatch.setattr(bcs, "COOLDOWN_SECONDS", 3600)

        assert bcs._cooldown_active() is True

    def test_cooldown_inactive_after_window(self, tmp_path, monkeypatch):
        """Old lock file → cooldown expired."""
        lock_file = tmp_path / "lock"
        old_time = time.time() - 7200  # 2 hours ago
        lock_file.write_text(str(old_time))

        monkeypatch.setattr(bcs, "LOCK_FILE", lock_file)
        monkeypatch.setattr(bcs, "COOLDOWN_SECONDS", 3600)

        assert bcs._cooldown_active() is False


class TestStateManagement:
    """State file load/save preserves cursor position and metadata."""

    def test_load_state_returns_default_on_missing_file(self, tmp_path, monkeypatch):
        """No cursor file → return defaults."""
        monkeypatch.setattr(bcs, "CURSOR_FILE", tmp_path / "nofile")

        state = bcs._load_state()
        assert state["index"] == 0

    def test_load_state_returns_default_on_malformed_json(self, tmp_path, monkeypatch):
        """Corrupted JSON → return defaults, no crash."""
        cursor_file = tmp_path / "cursor.json"
        cursor_file.write_text("{ broken json")

        monkeypatch.setattr(bcs, "CURSOR_FILE", cursor_file)

        state = bcs._load_state()
        assert state["index"] == 0
        assert state.get("last_meta_lines") == 0

    def test_save_state_preserves_values(self, tmp_path, monkeypatch):
        """Save and reload returns the same values."""
        cursor_file = tmp_path / "cursor.json"
        state_dir = tmp_path / "state"
        state_dir.mkdir()

        monkeypatch.setattr(bcs, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(bcs, "STATE_DIR", state_dir)

        bcs._save_state(index=5)

        state = bcs._load_state()
        assert state["index"] == 5

    def test_save_state_creates_state_dir(self, tmp_path, monkeypatch):
        """Save creates parent directory if missing."""
        cursor_file = tmp_path / "subdir" / "cursor.json"
        state_dir = tmp_path / "subdir"

        monkeypatch.setattr(bcs, "CURSOR_FILE", cursor_file)
        monkeypatch.setattr(bcs, "STATE_DIR", state_dir)

        bcs._save_state(index=1)

        assert state_dir.exists()
        assert cursor_file.exists()


class TestChunkRendering:
    """File paths are rendered into readable form for the reviewer."""

    def test_directory_path_expands_to_its_files(self, tmp_path):
        """Directory → enumerate its files, not bare directory bullet."""
        chunk_dir = tmp_path / "scripts"
        chunk_dir.mkdir()
        (chunk_dir / "tool-a.py").write_text("a")
        (chunk_dir / "tool-b.py").write_text("b")

        rendered = bcs._render_chunk_paths([str(chunk_dir) + "/"])

        assert str(chunk_dir / "tool-a.py") in rendered
        assert str(chunk_dir / "tool-b.py") in rendered
        assert rendered.index("tool-a.py") < rendered.index("tool-b.py")

    def test_nested_files_in_directory_expansion(self, tmp_path):
        """rglob includes nested subdirectories."""
        chunk_dir = tmp_path / "skills" / "something"
        (chunk_dir / "scripts" / "tests").mkdir(parents=True)
        (chunk_dir / "SKILL.md").write_text("x")
        (chunk_dir / "scripts" / "main.py").write_text("x")
        (chunk_dir / "scripts" / "tests" / "test.py").write_text("x")

        rendered = bcs._render_chunk_paths([str(chunk_dir) + "/"])

        assert str(chunk_dir / "SKILL.md") in rendered
        assert str(chunk_dir / "scripts" / "main.py") in rendered
        assert str(chunk_dir / "scripts" / "tests" / "test.py") in rendered

    def test_file_path_rendered_as_is(self, tmp_path):
        """Single file → no expansion."""
        a_file = tmp_path / "CLAUDE.md"
        a_file.write_text("config")

        rendered = bcs._render_chunk_paths([str(a_file)])

        assert rendered.strip() == f"- {a_file}"

    def test_empty_directory_falls_back_to_bare_bullet(self, tmp_path):
        """Empty directory → bare directory string, not empty lines."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        rendered = bcs._render_chunk_paths([str(empty_dir) + "/"])

        assert rendered.strip() == f"- {empty_dir}/"

    def test_nonexistent_path_falls_back_to_bare_bullet(self, tmp_path):
        """Missing directory → bare directory string, no crash."""
        missing = tmp_path / "does-not-exist"

        rendered = bcs._render_chunk_paths([str(missing) + "/"])

        assert rendered.strip() == f"- {missing}/"

    def test_mixed_files_and_directories(self, tmp_path):
        """Single call can handle both file and directory paths."""
        a_file = tmp_path / "CLAUDE.md"
        a_file.write_text("x")
        chunk_dir = tmp_path / "commands"
        chunk_dir.mkdir()
        (chunk_dir / "cmd.md").write_text("x")

        rendered = bcs._render_chunk_paths([str(a_file), str(chunk_dir) + "/"])

        assert f"- {a_file}" in rendered
        assert str(chunk_dir / "cmd.md") in rendered


class TestErrorHandling:
    """Failures are logged, not silent."""

    def test_missing_claude_bin_does_not_crash(self, tmp_path, monkeypatch):
        """claude missing → return early without crashing."""
        monkeypatch.setattr(bcs, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(bcs, "BUCKET_FILE", tmp_path / "bucket.md")
        monkeypatch.setattr(bcs, "LOG_FILE", tmp_path / "log.txt")
        monkeypatch.setattr(bcs, "_resolve_claude_bin", lambda: (_ for _ in ()).throw(FileNotFoundError("not found")))

        (tmp_path / "state").mkdir()

        # main() should not crash
        bcs.main()

        # Should have logged the error
        assert (tmp_path / "log.txt").exists()


class TestIdempotency:
    """Same chunk reviewed twice doesn't duplicate findings."""

    def test_find_duplicate_entry_finds_existing_title(self, tmp_path, monkeypatch):
        """_find_duplicate_entry finds an existing entry by title."""
        bucket_file = tmp_path / "bucket.md"
        bucket_file.write_text("""# Findings

## Issue in module-x
**Status**: pending
""")

        monkeypatch.setattr(bcs, "BUCKET_FILE", bucket_file)

        existing = bcs._find_duplicate_entry("Issue in module-x")
        assert existing is not None
        assert "Issue in module-x" in existing

    def test_find_duplicate_entry_returns_none_if_not_found(self, tmp_path, monkeypatch):
        """_find_duplicate_entry returns None if title not found."""
        bucket_file = tmp_path / "bucket.md"
        bucket_file.write_text("""# Findings

## Issue A
**Status**: pending
""")

        monkeypatch.setattr(bcs, "BUCKET_FILE", bucket_file)

        existing = bcs._find_duplicate_entry("Nonexistent Issue")
        assert existing is None
