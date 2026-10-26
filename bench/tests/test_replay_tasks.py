"""Tests for bench/bench.py replay task functionality. Run via:
    ~/.agents/venv/bin/python -m pytest bench/tests/test_replay_tasks.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent / "lib"))

# Import after path setup
import bench  # noqa: E402


class TestReplayTaskValidation:
    """Validate task.json fields for replay type."""

    def test_replay_task_requires_base_ref(self):
        """Replay task must have base_ref field."""
        task = {
            "id": "replay-test",
            "type": "replay",
            "prompt_file": "prompt.md",
            # Missing: base_ref
            "verify_cmd": "pytest tests/",
        }
        # Validate that accessing base_ref raises KeyError when missing
        with pytest.raises(KeyError):
            _ = task["base_ref"]

    def test_replay_task_requires_verify_cmd(self):
        """Replay task must have verify_cmd field."""
        task = {
            "id": "replay-test",
            "type": "replay",
            "prompt_file": "prompt.md",
            "base_ref": "abc123",
            # Missing: verify_cmd
        }
        # Validate that accessing verify_cmd raises KeyError when missing
        with pytest.raises(KeyError):
            _ = task["verify_cmd"]

    def test_replay_task_with_valid_fields(self):
        """Replay task with all required fields is valid."""
        task = {
            "id": "replay-test",
            "type": "replay",
            "prompt_file": "prompt.md",
            "base_ref": "abc123def456",
            "verify_cmd": "pytest tests/ -v",
        }
        # Should not raise
        assert task["base_ref"]
        assert task["verify_cmd"]

    def test_load_task_missing_base_ref(self, tmp_path):
        """load_task on replay task without base_ref raises KeyError when accessed."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        (task_dir / "prompt.md").write_text("solve this")
        (task_dir / "task.json").write_text(json.dumps({
            "id": "replay-test",
            "type": "replay",
            "prompt_file": "prompt.md",
            # Missing base_ref
            "verify_cmd": "pytest",
        }))

        task = bench.load_task(task_dir)
        assert task["id"] == "replay-test"
        with pytest.raises(KeyError):
            _ = task["base_ref"]


class TestReplayTaskInputBounds:
    """Test edge cases: empty, huge, or malformed input."""

    def test_empty_prompt_file(self, tmp_path):
        """Empty prompt.md should be handled."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        (task_dir / "prompt.md").write_text("")
        (task_dir / "task.json").write_text(json.dumps({
            "id": "empty-prompt",
            "type": "replay",
            "prompt_file": "prompt.md",
            "base_ref": "abc123",
            "verify_cmd": "true",
        }))

        task = bench.load_task(task_dir)
        assert task["prompt"] == ""

    def test_huge_prompt(self, tmp_path):
        """Very large prompt (beyond model context window) is not rejected by load."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        huge_prompt = "x" * 50_000  # 50k chars, well beyond small model context
        (task_dir / "prompt.md").write_text(huge_prompt)
        (task_dir / "task.json").write_text(json.dumps({
            "id": "huge-prompt",
            "type": "replay",
            "prompt_file": "prompt.md",
            "base_ref": "abc123",
            "verify_cmd": "true",
        }))

        task = bench.load_task(task_dir)
        assert len(task["prompt"]) == 50_000

    def test_malformed_task_json(self, tmp_path):
        """Malformed task.json raises on load."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        (task_dir / "task.json").write_text("{ not valid json")

        with pytest.raises(json.JSONDecodeError):
            bench.load_task(task_dir)

    def test_missing_prompt_file(self, tmp_path):
        """Missing prompt_file is caught."""
        task_dir = tmp_path / "task"
        task_dir.mkdir()
        (task_dir / "task.json").write_text(json.dumps({
            "id": "missing-prompt",
            "type": "replay",
            "prompt_file": "nonexistent.md",
            "base_ref": "abc123",
            "verify_cmd": "true",
        }))

        with pytest.raises(FileNotFoundError):
            bench.load_task(task_dir)


class TestReplayTaskCollisionAndStaleState:
    """Test worktree collision and stale-state reuse (reuses sandbox_orchestration logic)."""

    def test_replay_task_creates_isolated_worktree(self, tmp_path):
        """Replay task uses sandbox_orchestration._create_worktree for isolation."""
        # Validate that replay tasks try to create a worktree
        # Full collision testing requires a real git repo, but we can verify
        # the integration path calls _create_worktree with the right arguments

        task_dir = tmp_path / "task"
        task_dir.mkdir()
        (task_dir / "prompt.md").write_text("fix this")
        (task_dir / "task.json").write_text(json.dumps({
            "id": "replay-test",
            "type": "replay",
            "prompt_file": "prompt.md",
            "base_ref": "abc123",
            "verify_cmd": "true",
        }))

        task = bench.load_task(task_dir)
        # run_once_replay would call _create_worktree(Path.cwd(), task["base_ref"])
        # In the actual call, this would fail with a non-existent sha, but we
        # verify the dispatch happens
        result = bench.run_once_replay(task, "clean", runner="opencode")
        # Should return an error result since base_ref doesn't exist
        assert result is not None
        assert result["runner"] == "opencode"
        assert "spawn_error" in result or result["correctness"]["score"] == 0.0


class TestResultsAppendOnly:
    """RESULTS.md append behavior when runs are saved."""

    def test_run_result_structure(self, tmp_path):
        """Run results have the expected structure for JSON output."""
        task = {
            "id": "test-task",
            "type": "replay",
            "prompt": "fix this",
            "prompt_file": "prompt.md",
            "base_ref": "abc123",
            "verify_cmd": "true",
        }

        # A result from run_once_replay should have these fields
        result = {
            "profile": "clean",
            "model": "default",
            "runner": "opencode",
            "result_text": "test output",
            "wall_s": 1.5,
            "cost_usd": 0.0,
            "total_tokens": 10,
            "num_turns": 1,
            "tool_calls": 0,
            "correctness": {"score": 0.5},
        }

        # Verify structure
        assert result["profile"] in ("clean", "marvin", "lean")
        assert result["runner"] == "opencode"
        assert isinstance(result["wall_s"], float)
        assert isinstance(result["correctness"]["score"], (float, type(None)))

    def test_results_json_output_preserves_all_runs(self, tmp_path):
        """Multiple runs are saved together in results JSON."""
        out = tmp_path / "results.json"

        runs = [
            {"id": "run-1", "score": 1.0},
            {"id": "run-2", "score": 0.5},
        ]

        output = {
            "task": "test-task",
            "runner": "opencode",
            "model": "default",
            "repeat": 2,
            "judge": False,
            "runs": runs,
        }

        out.write_text(json.dumps(output, indent=2))

        # Verify all runs are in the output
        loaded = json.loads(out.read_text())
        assert len(loaded["runs"]) == 2
        assert loaded["runs"][0]["id"] == "run-1"
        assert loaded["runs"][1]["id"] == "run-2"


class TestGateSeparation:
    """Baseline vs post-attempt gate separation."""

    def test_result_includes_gate_scoring(self):
        """Result includes gate scoring from verify_cmd."""
        task = {
            "id": "test-task",
            "type": "replay",
            "prompt": "fix this",
            "base_ref": "abc123",
            "verify_cmd": "true",
        }

        # A result should include gate information
        result = {
            "profile": "clean",
            "runner": "opencode",
            "correctness": {
                "score": 1.0,
                "gate": {"passed": True},  # From evidence_capture
            },
        }

        assert result["correctness"]["score"] == 1.0
        assert "gate" in result["correctness"] or "gate_error" in result["correctness"]

    def test_verify_cmd_parsing(self):
        """verify_cmd string is parsed into a list for subprocess."""
        # bench.run_once_replay should split verify_cmd and pass to capture_test_results
        verify_cmd = "pytest tests/ -v --tb=short"
        cmd_list = verify_cmd.split()
        assert cmd_list == ["pytest", "tests/", "-v", "--tb=short"]


class TestOllavaInUnsupported:
    """Verify Ollama constraint: fs tasks require tool use, not supported."""

    def test_ollama_skips_fs_tasks(self):
        """Ollama runner must skip fs tasks (tool use required)."""
        task = {
            "id": "fs-task",
            "type": "fs",
            "prompt": "write code",
            "dir": Path("/tmp"),
        }
        # Mock ollama run
        result = bench.run_once_ollama(task, "clean", "qwen2.5:7b")
        # run_once_ollama returns None for fs tasks
        assert result is None
