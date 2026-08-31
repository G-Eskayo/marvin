"""Tests for bench.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_bench.py -v

Tests the isolated_workdir feature and disallow_tools command construction
without actually invoking the claude CLI (monkeypatched).
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BENCH_DIR = Path(__file__).resolve().parents[2]
LIB_DIR = Path(__file__).resolve().parents[1]
# Set up paths so bench.py's imports can find score.py and memory_rag.py
sys.path.insert(0, str(LIB_DIR))
sys.path.insert(0, str(BENCH_DIR))

import bench  # noqa: E402


class TestIsolatedWorkdir:
    """Tests for isolated_workdir task type."""

    def test_isolated_qa_task_gets_fresh_temp_workdir(self, monkeypatch, tmp_path):
        """isolated_workdir: true on a qa task should create a fresh temp dir,
        not use task.get("cwd")."""
        task = {
            "id": "test-task",
            "type": "qa",
            "isolated_workdir": True,
            "prompt": "test prompt",
            "cwd": str(tmp_path / "should-not-be-used"),  # should be ignored
        }
        created_workdirs = []

        def fake_run(cmd, *args, **kwargs):
            created_workdirs.append(kwargs.get("cwd"))
            return MagicMock(
                stdout='{"type":"final","result_text":"result"}',
                stderr="",
                returncode=0,
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        bench.run_once(task, "clean")

        assert len(created_workdirs) == 1
        workdir = created_workdirs[0]
        # Should be a temp path, not the specified cwd
        assert str(workdir) != str(tmp_path / "should-not-be-used")
        # Should be under /tmp or similar (temp directory)
        assert isinstance(workdir, Path)

    def test_isolated_workdir_omits_bypassPermissions_flag(self, monkeypatch):
        """isolated_workdir tasks should NOT include --permission-mode bypassPermissions."""
        task = {
            "id": "test-task",
            "type": "qa",
            "isolated_workdir": True,
            "prompt": "test prompt",
        }
        commands_run = []

        def fake_run(cmd, *args, **kwargs):
            commands_run.append(cmd)
            return MagicMock(
                stdout='{"type":"final","result_text":"result"}',
                stderr="",
                returncode=0,
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        bench.run_once(task, "clean")

        assert len(commands_run) == 1
        cmd = commands_run[0]
        # Verify that --permission-mode bypassPermissions is NOT in the command
        assert "--permission-mode" not in cmd
        assert "bypassPermissions" not in cmd

    def test_fs_task_still_includes_bypassPermissions_flag(self, monkeypatch, tmp_path):
        """fs tasks should still include --permission-mode bypassPermissions."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        task = {
            "id": "test-task",
            "type": "fs",
            "prompt": "test prompt",
            "dir": task_dir,
        }
        commands_run = []

        def fake_run(cmd, *args, **kwargs):
            commands_run.append(cmd)
            return MagicMock(
                stdout='{"type":"final","result_text":"result"}',
                stderr="",
                returncode=0,
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        bench.run_once(task, "clean")

        assert len(commands_run) == 1
        cmd = commands_run[0]
        # Verify that --permission-mode bypassPermissions IS in the command
        assert "--permission-mode" in cmd
        idx = cmd.index("--permission-mode")
        assert cmd[idx + 1] == "bypassPermissions"


class TestDisallowTools:
    """Tests for disallow_tools command construction."""

    def test_disallow_tools_on_qa_task_constructs_disallowedTools_flag(self, monkeypatch):
        """disallow_tools on a qa task should add --disallowedTools to the command."""
        task = {
            "id": "test-task",
            "type": "qa",
            "prompt": "test prompt",
            "disallow_tools": ["Read", "Glob", "Grep"],
        }
        commands_run = []

        def fake_run(cmd, *args, **kwargs):
            commands_run.append(cmd)
            return MagicMock(
                stdout='{"type":"final","result_text":"result"}',
                stderr="",
                returncode=0,
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        bench.run_once(task, "clean")

        assert len(commands_run) == 1
        cmd = commands_run[0]
        assert "--disallowedTools" in cmd
        idx = cmd.index("--disallowedTools")
        tools_arg = cmd[idx + 1]
        # Should be comma-joined
        assert "Read" in tools_arg
        assert "Glob" in tools_arg
        assert "Grep" in tools_arg
        assert tools_arg == "Read,Glob,Grep"

    def test_disallow_tools_on_fs_task_constructs_disallowedTools_flag(self, monkeypatch, tmp_path):
        """disallow_tools on an fs task should also add --disallowedTools to the command."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        task = {
            "id": "test-task",
            "type": "fs",
            "prompt": "test prompt",
            "disallow_tools": ["Read", "WebSearch"],
            "dir": task_dir,
        }
        commands_run = []

        def fake_run(cmd, *args, **kwargs):
            commands_run.append(cmd)
            return MagicMock(
                stdout='{"type":"final","result_text":"result"}',
                stderr="",
                returncode=0,
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        bench.run_once(task, "clean")

        assert len(commands_run) == 1
        cmd = commands_run[0]
        assert "--disallowedTools" in cmd
        idx = cmd.index("--disallowedTools")
        tools_arg = cmd[idx + 1]
        assert tools_arg == "Read,WebSearch"

    def test_disallow_tools_empty_list_still_adds_flag(self, monkeypatch):
        """If disallow_tools is an empty list, --disallowedTools should still be added
        (though with an empty value, which is valid)."""
        task = {
            "id": "test-task",
            "type": "qa",
            "prompt": "test prompt",
            "disallow_tools": [],
        }
        commands_run = []

        def fake_run(cmd, *args, **kwargs):
            commands_run.append(cmd)
            return MagicMock(
                stdout='{"type":"final","result_text":"result"}',
                stderr="",
                returncode=0,
            )

        monkeypatch.setattr(subprocess, "run", fake_run)

        bench.run_once(task, "clean")

        assert len(commands_run) == 1
        cmd = commands_run[0]
        # Empty disallow_tools list should NOT add the flag (falsy check in the code)
        assert "--disallowedTools" not in cmd


class TestLoadTask:
    """Tests for load_task function."""

    def test_load_task_round_trips_isolated_workdir_field(self, tmp_path):
        """load_task should preserve the isolated_workdir field from task.json."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        task_json = {
            "id": "test-task",
            "type": "qa",
            "isolated_workdir": True,
            "prompt_file": "prompt.md",
            "timeout": 180,
            "expect": ["QA-TEST-"],
            "disallow_tools": ["Read"],
        }
        (task_dir / "task.json").write_text(json.dumps(task_json))
        (task_dir / "prompt.md").write_text("Test prompt")

        loaded = bench.load_task(task_dir)

        assert loaded["id"] == "test-task"
        assert loaded["type"] == "qa"
        assert loaded["isolated_workdir"] is True
        assert loaded["prompt"] == "Test prompt"
        assert loaded["expect"] == ["QA-TEST-"]
        assert loaded["disallow_tools"] == ["Read"]
        assert loaded["dir"] == task_dir

    def test_load_task_defaults_isolated_workdir_to_false(self, tmp_path):
        """load_task should default isolated_workdir to False if not present."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        task_json = {
            "id": "test-task",
            "type": "qa",
            "prompt_file": "prompt.md",
        }
        (task_dir / "task.json").write_text(json.dumps(task_json))
        (task_dir / "prompt.md").write_text("Test prompt")

        loaded = bench.load_task(task_dir)

        # bool(None) or bool(missing) should be False
        assert bool(loaded.get("isolated_workdir")) is False


class TestTask015Structure:
    """Tests for task-015-isolated-kb-recall structural sanity."""

    def test_task_015_exists_and_is_valid(self):
        """task-015 should exist with valid structure."""
        root = Path(__file__).resolve().parents[3]
        task_dir = root / "bench" / "tasks" / "task-015-isolated-kb-recall"
        assert task_dir.exists(), f"task-015 directory not found at {task_dir}"

    def test_task_015_json_is_valid(self):
        """task.json should be valid JSON with required fields."""
        root = Path(__file__).resolve().parents[3]
        task_json_path = root / "bench" / "tasks" / "task-015-isolated-kb-recall" / "task.json"
        assert task_json_path.exists(), f"task.json not found at {task_json_path}"

        task = json.loads(task_json_path.read_text())
        assert task["id"] == "task-015-isolated-kb-recall"
        assert task["type"] == "qa"
        assert task["isolated_workdir"] is True
        assert "disallow_tools" in task
        assert "expect" in task

    def test_task_015_has_no_files_directory(self):
        """task-015 should NOT have a files/ subdirectory (isolation by design)."""
        root = Path(__file__).resolve().parents[3]
        task_dir = root / "bench" / "tasks" / "task-015-isolated-kb-recall"
        files_dir = task_dir / "files"
        assert not files_dir.exists(), (
            f"task-015 should not have a files/ directory; "
            f"isolated_workdir tasks get empty temp dirs by design"
        )

    def test_task_015_prompt_does_not_contain_expect_string(self):
        """task-015 prompt.md should NOT contain the expect token (cannot be leaked)."""
        root = Path(__file__).resolve().parents[3]
        task_dir = root / "bench" / "tasks" / "task-015-isolated-kb-recall"
        task_json_path = task_dir / "task.json"
        prompt_path = task_dir / "prompt.md"

        task = json.loads(task_json_path.read_text())
        prompt = prompt_path.read_text()
        expect_values = task.get("expect", [])

        for expect in expect_values:
            # For prefix matches like "QA-ISOLATE-", check that the exact
            # prefix is NOT in the prompt. We allow the general concept but
            # not the specific token/prefix.
            assert expect not in prompt, (
                f"prompt.md must not contain the expect value '{expect}' "
                f"(would leak the token/prefix)"
            )

    def test_task_015_disallow_tools_covers_file_and_web_tools(self):
        """task-015 disallow_tools should include Read, Glob, Grep, WebSearch, WebFetch."""
        root = Path(__file__).resolve().parents[3]
        task_json_path = root / "bench" / "tasks" / "task-015-isolated-kb-recall" / "task.json"
        task = json.loads(task_json_path.read_text())

        disallow_tools = task.get("disallow_tools", [])
        required_tools = {"Read", "Glob", "Grep", "WebSearch", "WebFetch"}
        actual_tools = set(disallow_tools)

        assert required_tools.issubset(actual_tools), (
            f"task-015 disallow_tools must include {required_tools}; "
            f"got {actual_tools}"
        )

    def test_task_015_expect_uses_prefix_match(self):
        """task-015 expect should use a prefix match (starts with QA-ISOLATE-)."""
        root = Path(__file__).resolve().parents[3]
        task_json_path = root / "bench" / "tasks" / "task-015-isolated-kb-recall" / "task.json"
        task = json.loads(task_json_path.read_text())

        expect = task.get("expect", [])
        assert expect, "task-015 must have an expect array"
        # Should start with the prefix (allows flexibility in the random token generation)
        assert any(s.startswith("QA-ISOLATE-") for s in expect), (
            f"expect array should include a prefix starting with 'QA-ISOLATE-'; "
            f"got {expect}"
        )
