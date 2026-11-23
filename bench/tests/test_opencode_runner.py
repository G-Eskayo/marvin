"""Tests for opencode_runner.py — thin wrapper mirroring bench.py's ollama patterns.
~/.agents/venv/bin/python -m pytest bench/tests/test_opencode_runner.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH / "lib"))

import opencode_runner as ocr


class TestOpenCodeAvailable:
    def test_available_returns_true_when_opencode_exists(self):
        """Test that opencode_available returns True when opencode is found."""
        with patch("shutil.which", return_value="/usr/local/bin/opencode"):
            ok, err = ocr.opencode_available()
            assert ok is True
            assert err == ""

    def test_available_returns_false_when_opencode_missing(self):
        """Test that opencode_available returns False when opencode is not found."""
        with patch("shutil.which", return_value=None):
            ok, err = ocr.opencode_available()
            assert ok is False
            assert "opencode" in err.lower()


class TestRunOnceOpencode:
    def test_run_once_opencode_returns_none_for_fs_tasks(self):
        """Test that run_once_opencode returns None for fs tasks (no tool use)."""
        task = {
            "id": "task-001",
            "prompt": "test prompt",
            "type": "fs",  # filesystem task
        }

        result = ocr.run_once_opencode(task, "/tmp", "qwen2.5:7b", 30)
        assert result is None

    def test_successful_run_returns_dict_with_required_fields(self):
        """Test that successful run returns dict with all required fields."""
        task = {
            "id": "task-001",
            "prompt": "test prompt",
            "type": "qa",
        }
        mock_result = MagicMock()
        mock_result.stdout = "test output"
        mock_result.stderr = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = ocr.run_once_opencode(task, "/tmp", "qwen2.5:7b", 30)

        assert result is not None
        assert "spawn_error" in result
        assert "result_text" in result
        assert "returncode" in result
        assert "wall_s" in result
        assert "total_tokens" in result
        assert result["result_text"] == "test output"
        assert result["returncode"] == 0

    def test_run_sets_ollama_environment_variable(self):
        """Test that run_once_opencode sets OLLAMA_BASE_URL."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}
        mock_result = MagicMock()
        mock_result.stdout = "output"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            with patch("os.environ", {}):
                ocr.run_once_opencode(task, "/tmp", "qwen2.5:7b", 30)

                # Verify OLLAMA_BASE_URL was set
                call_kwargs = mock_run.call_args[1]
                env = call_kwargs.get("env", {})
                assert "OLLAMA_BASE_URL" in env
                assert "localhost:11434" in env["OLLAMA_BASE_URL"]

    def test_run_uses_correct_opencode_cli_syntax(self):
        """Test that run_once_opencode uses 'opencode run -m' syntax."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ocr.run_once_opencode(task, "/tmp", "qwen2.5:7b", 30)

            call_args = mock_run.call_args
            cmd = call_args[0][0]

            # Should be: opencode run -m ollama/model prompt
            assert "opencode" in cmd
            assert "run" in cmd
            assert "-m" in cmd
            assert "ollama/qwen2.5:7b" in cmd

    def test_failed_run_returns_spawn_error_no_raise(self):
        """Test that failed run returns spawn_error and never raises."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}

        with patch("subprocess.run", side_effect=Exception("command not found")):
            result = ocr.run_once_opencode(task, "/tmp", "qwen2.5:7b", 30)

        assert result is not None
        assert result["spawn_error"] is not None
        assert "command not found" in result["spawn_error"]

    def test_timeout_returns_appropriate_error(self):
        """Test that subprocess.TimeoutExpired is handled and returns error dict."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 30)):
            result = ocr.run_once_opencode(task, "/tmp", "qwen2.5:7b", 30)

        assert result is not None
        assert result["spawn_error"] is not None
        assert "timeout" in result["spawn_error"].lower()

    def test_run_captures_stdout_stderr_and_returncode(self):
        """Test that stdout, stderr, and returncode are captured."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}
        mock_result = MagicMock()
        mock_result.stdout = "output text"
        mock_result.stderr = "error text"
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = ocr.run_once_opencode(task, "/tmp", "qwen2.5:14b", 60)

        assert result["result_text"] == "output text"
        assert result["stderr"] == "error text"
        assert result["returncode"] == 1

    def test_timeout_param_passed_to_subprocess_run(self):
        """Test that timeout is passed to subprocess.run."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            ocr.run_once_opencode(task, "/tmp", "model", 120)

            call_kwargs = mock_run.call_args[1]
            assert call_kwargs.get("timeout") == 120

    def test_wall_time_is_measured(self):
        """Test that wall_s (wall clock time) is measured."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            with patch("time.time", side_effect=[0.0, 5.5]):  # 5.5 seconds
                result = ocr.run_once_opencode(task, "/tmp", "model", 30)

        assert result["wall_s"] == 5.5

    def test_spawn_error_is_none_on_success(self):
        """Test that spawn_error is None when returncode is 0."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}
        mock_result = MagicMock()
        mock_result.stdout = "success"
        mock_result.returncode = 0

        with patch("subprocess.run", return_value=mock_result):
            result = ocr.run_once_opencode(task, "/tmp", "model", 30)

        assert result["spawn_error"] is None

    def test_spawn_error_set_on_nonzero_exit(self):
        """Test that spawn_error is set when returncode is non-zero."""
        task = {"id": "task-001", "prompt": "test", "type": "qa"}
        mock_result = MagicMock()
        mock_result.stdout = "failed"
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            result = ocr.run_once_opencode(task, "/tmp", "model", 30)

        assert result["spawn_error"] is not None
