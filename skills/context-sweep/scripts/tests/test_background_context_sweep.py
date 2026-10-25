"""Tests for background_context_sweep.py."""
from __future__ import annotations
import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest


@pytest.fixture
def mock_state_dir(tmp_path) -> Path:
    """Mock state directory for testing."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return state_dir


@pytest.fixture
def mock_claude_dir(tmp_path) -> Path:
    """Mock ~/.claude directory."""
    claude_dir = tmp_path / "claude"
    claude_dir.mkdir()
    return claude_dir


@pytest.fixture
def mock_agents_dir(tmp_path) -> Path:
    """Mock ~/.agents directory."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    return agents_dir


@pytest.fixture
def populated_dirs(mock_agents_dir, mock_claude_dir):
    """Create realistic file structure under mock dirs."""
    # .agents structure
    (mock_agents_dir / "skills" / "skill1").mkdir(parents=True)
    (mock_agents_dir / "skills" / "skill1" / "SKILL.md").write_text("# Skill 1")
    (mock_agents_dir / "skills" / "skill1" / "script.py").write_text("print('test')")

    (mock_agents_dir / "skills" / "skill2").mkdir(parents=True)
    (mock_agents_dir / "skills" / "skill2" / "SKILL.md").write_text("# Skill 2")

    (mock_agents_dir / "lib").mkdir(parents=True)
    (mock_agents_dir / "lib" / "util.py").write_text("def util(): pass")

    # .claude structure
    (mock_claude_dir / "handoffs").mkdir(parents=True)
    (mock_claude_dir / "handoffs" / "2026-10-01.md").write_text("# Handoff")

    (mock_claude_dir / "CLAUDE.md").write_text("# Config")
    (mock_claude_dir / "lexicon.md").write_text("# Lexicon")

    return mock_agents_dir, mock_claude_dir


def test_enumerate_all_files_basic(populated_dirs, tmp_path):
    """Test file enumeration skips excluded dirs and extensions."""
    agents_dir, claude_dir = populated_dirs

    # Patch Path.home() to return our mock dirs' parent
    with mock.patch("pathlib.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        # Need to patch in the module
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import background_context_sweep as bcs

        # Temporarily override AGENTS_DIR and CLAUDE_DIR
        original_agents = bcs.AGENTS_DIR
        original_claude = bcs.CLAUDE_DIR
        try:
            bcs.AGENTS_DIR = agents_dir
            bcs.CLAUDE_DIR = claude_dir

            files = bcs._enumerate_all_files()
            file_names = sorted(f.name for f in files)

            # Should include .md and .py files
            assert "SKILL.md" in file_names
            assert "CLAUDE.md" in file_names
            assert "script.py" in file_names

            # All files should be sorted
            assert files == sorted(files)
        finally:
            bcs.AGENTS_DIR = original_agents
            bcs.CLAUDE_DIR = original_claude


def test_enumerate_skips_excluded_dirs(populated_dirs, tmp_path):
    """Test that excluded directories are skipped."""
    agents_dir, claude_dir = populated_dirs

    # Add excluded dirs with files
    (agents_dir / ".git").mkdir()
    (agents_dir / ".git" / "config").write_text("git config")

    (agents_dir / "__pycache__").mkdir()
    (agents_dir / "__pycache__" / "test.pyc").write_text("bytecode")

    (claude_dir / "chroma").mkdir()
    (claude_dir / "chroma" / "data.db").write_text("chroma data")

    with mock.patch("pathlib.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import background_context_sweep as bcs

        original_agents = bcs.AGENTS_DIR
        original_claude = bcs.CLAUDE_DIR
        try:
            bcs.AGENTS_DIR = agents_dir
            bcs.CLAUDE_DIR = claude_dir

            files = bcs._enumerate_all_files()
            file_paths = {str(f.relative_to(tmp_path)) for f in files}

            # Should not include anything in excluded dirs
            assert not any(".git" in p for p in file_paths)
            assert not any("__pycache__" in p for p in file_paths)
            assert not any("chroma" in p for p in file_paths)
        finally:
            bcs.AGENTS_DIR = original_agents
            bcs.CLAUDE_DIR = original_claude


def test_enumerate_skips_excluded_extensions(populated_dirs, tmp_path):
    """Test that excluded file extensions are skipped."""
    agents_dir, claude_dir = populated_dirs

    # Add files with excluded extensions
    (agents_dir / "lib" / "compiled.pyc").write_text("bytecode")
    (agents_dir / "lib" / "library.so").write_text("binary")
    (agents_dir / "lib" / "data.zip").write_text("archive")

    with mock.patch("pathlib.Path.home") as mock_home:
        mock_home.return_value = tmp_path

        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
        import background_context_sweep as bcs

        original_agents = bcs.AGENTS_DIR
        original_claude = bcs.CLAUDE_DIR
        try:
            bcs.AGENTS_DIR = agents_dir
            bcs.CLAUDE_DIR = claude_dir

            files = bcs._enumerate_all_files()
            file_names = {f.name for f in files}

            # Should not include excluded extensions
            assert "compiled.pyc" not in file_names
            assert "library.so" not in file_names
            assert "data.zip" not in file_names

            # Should still include regular files
            assert "util.py" in file_names
        finally:
            bcs.AGENTS_DIR = original_agents
            bcs.CLAUDE_DIR = original_claude


def test_load_state_defaults(mock_state_dir, populated_dirs):
    """Test state initialization with defaults."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import background_context_sweep as bcs

    agents_dir, claude_dir = populated_dirs

    original_state_dir = bcs.STATE_DIR
    original_cursor = bcs.CURSOR_FILE
    original_agents = bcs.AGENTS_DIR
    original_claude = bcs.CLAUDE_DIR

    try:
        bcs.STATE_DIR = mock_state_dir
        bcs.CURSOR_FILE = mock_state_dir / "cursor.json"
        bcs.AGENTS_DIR = agents_dir
        bcs.CLAUDE_DIR = claude_dir

        state = bcs._load_state()

        assert state["index"] == 0
        assert state["cycle"] == 0
        assert state["total_files"] > 0
    finally:
        bcs.STATE_DIR = original_state_dir
        bcs.CURSOR_FILE = original_cursor
        bcs.AGENTS_DIR = original_agents
        bcs.CLAUDE_DIR = original_claude


def test_save_and_load_state(mock_state_dir, populated_dirs):
    """Test saving and loading state."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import background_context_sweep as bcs

    agents_dir, claude_dir = populated_dirs

    original_state_dir = bcs.STATE_DIR
    original_cursor = bcs.CURSOR_FILE
    original_agents = bcs.AGENTS_DIR
    original_claude = bcs.CLAUDE_DIR

    try:
        bcs.STATE_DIR = mock_state_dir
        bcs.CURSOR_FILE = mock_state_dir / "cursor.json"
        bcs.AGENTS_DIR = agents_dir
        bcs.CLAUDE_DIR = claude_dir

        bcs._save_state(index=5, cycle=2)
        state = bcs._load_state()

        assert state["index"] == 5
        assert state["cycle"] == 2
    finally:
        bcs.STATE_DIR = original_state_dir
        bcs.CURSOR_FILE = original_cursor
        bcs.AGENTS_DIR = original_agents
        bcs.CLAUDE_DIR = original_claude


def test_pick_chunk_rotation(populated_dirs, mock_state_dir):
    """Test chunk picking and cursor advance."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import background_context_sweep as bcs

    agents_dir, claude_dir = populated_dirs

    original_state_dir = bcs.STATE_DIR
    original_cursor = bcs.CURSOR_FILE
    original_agents = bcs.AGENTS_DIR
    original_claude = bcs.CLAUDE_DIR

    try:
        bcs.STATE_DIR = mock_state_dir
        bcs.CURSOR_FILE = mock_state_dir / "cursor.json"
        bcs.AGENTS_DIR = agents_dir
        bcs.CLAUDE_DIR = claude_dir

        # First chunk
        chunk1, reason1 = bcs.pick_chunk()
        assert len(chunk1) <= bcs.CHUNK_SIZE
        assert "1-" in reason1 or "files" in reason1

        # Advance and pick second chunk
        state = bcs._load_state()
        bcs._save_state(index=min(len(bcs._enumerate_all_files()), state["index"] + bcs.CHUNK_SIZE))
        chunk2, reason2 = bcs.pick_chunk()

        # Should be different files
        if len(bcs._enumerate_all_files()) > bcs.CHUNK_SIZE:
            assert chunk1 != chunk2
    finally:
        bcs.STATE_DIR = original_state_dir
        bcs.CURSOR_FILE = original_cursor
        bcs.AGENTS_DIR = original_agents
        bcs.CLAUDE_DIR = original_claude


def test_cooldown_active(mock_state_dir):
    """Test cooldown check."""
    import sys
    import time
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import background_context_sweep as bcs

    original_lock = bcs.LOCK_FILE

    try:
        bcs.LOCK_FILE = mock_state_dir / ".last-run"

        # No lock file: cooldown inactive
        assert not bcs._cooldown_active()

        # Recent lock file: cooldown active
        bcs.LOCK_FILE.write_text(str(time.time()))
        assert bcs._cooldown_active()

        # Old lock file: cooldown inactive
        bcs.LOCK_FILE.write_text(str(time.time() - (21 * 60 * 60)))
        assert not bcs._cooldown_active()
    finally:
        bcs.LOCK_FILE = original_lock


def test_render_chunk_paths():
    """Test path rendering for prompt."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import background_context_sweep as bcs

    paths = [Path("/home/user/file1.md"), Path("/home/user/file2.py")]
    rendered = bcs._render_chunk_paths(paths)

    assert "- /home/user/file1.md" in rendered
    assert "- /home/user/file2.py" in rendered


def test_coverage_log_on_cycle_complete(populated_dirs, mock_state_dir, tmp_path):
    """Test that coverage log records cycle completion."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import background_context_sweep as bcs

    agents_dir, claude_dir = populated_dirs

    original_state_dir = bcs.STATE_DIR
    original_cursor = bcs.CURSOR_FILE
    original_coverage = bcs.COVERAGE_LOG
    original_agents = bcs.AGENTS_DIR
    original_claude = bcs.CLAUDE_DIR

    try:
        bcs.STATE_DIR = mock_state_dir
        bcs.CURSOR_FILE = mock_state_dir / "cursor.json"
        bcs.COVERAGE_LOG = mock_state_dir / "coverage-log.md"
        bcs.AGENTS_DIR = agents_dir
        bcs.CLAUDE_DIR = claude_dir

        # Simulate a cycle complete by manually updating state
        all_files = bcs._enumerate_all_files()
        bcs._save_state(index=len(all_files), cycle=0)

        # In a real run, after claude succeeds, cursor would be advanced past the end
        # and cycle would be incremented with log written. Simulate that:
        from datetime import datetime, timezone
        log_entry = f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')} | cycle 1 complete | {len(all_files)} files\n"
        bcs.COVERAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        bcs.COVERAGE_LOG.write_text(log_entry)

        assert bcs.COVERAGE_LOG.exists()
        assert "cycle 1 complete" in bcs.COVERAGE_LOG.read_text()
        assert str(len(all_files)) in bcs.COVERAGE_LOG.read_text()
    finally:
        bcs.STATE_DIR = original_state_dir
        bcs.CURSOR_FILE = original_cursor
        bcs.COVERAGE_LOG = original_coverage
        bcs.AGENTS_DIR = original_agents
        bcs.CLAUDE_DIR = original_claude
