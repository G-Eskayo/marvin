#!/usr/bin/env python3
"""Tests for spike_opencode_ollama driver. Run via:
    ~/.agents/venv/bin/python -m pytest tests/test_spike_opencode_ollama.py -v

Tests cases 11-12 from the design doc.
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent / "lib"))

import pytest
from spike_opencode_ollama import (
    _load_task,
    run_spike_task,
    _measure_usage_from_proxy_log,
)


class TestSpikeDriver:
    """Test cases 11-12 from the design doc."""

    def test_case_11_patch_leaves_worktree_dirty(self):
        """Test case 11: opencode's patch leaves worktree dirty/doesn't apply.
        verify_dir's existing error/env_missing classification surfaces in row,
        never collapsed to bare pass/fail.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Mock task
            task = {
                "id": "test-11",
                "prompt": "Fix something",
                "base_commit": "abc123",
            }

            # Mock project_profile.verify_dir to return an error classification
            with patch("spike_opencode_ollama.project_profile") as mock_pp:
                mock_pp.load_profile.return_value = {"repo": "marvin"}
                mock_pp.verify_dir.return_value = {
                    "ok": False,
                    "kind": "error",
                    "summary": "Patch failed to apply",
                    "tiers": [],
                    "output_tail": "...",
                }

                # Run with mocked worktree creation and opencode
                with patch("spike_opencode_ollama._create_worktree") as mock_wt:
                    mock_wt.return_value = (tmpdir, tmpdir, "branch")

                    with patch("spike_opencode_ollama._run_opencode") as mock_oc:
                        mock_oc.return_value = "Error: patch failed"

                        # Mock samplers
                        result = run_spike_task(
                            task,
                            "test-model",
                            tmpdir,
                            "abc123",
                            None,  # no proxy
                            None,  # no energy
                        )

                        # Verify that the error classification from verify_dir is preserved
                        assert result["gate"]["kind"] == "error"
                        assert "Patch failed" in result["gate"]["summary"]

    def test_case_12_worktree_not_writable(self):
        """Test case 12: Worktree directory not writable.
        Surfaces as env_missing, not silently skipped.
        """
        # Mock project_profile.verify_dir to return env_missing
        with patch("spike_opencode_ollama.project_profile") as mock_pp:
            mock_pp.load_profile.return_value = {"repo": "marvin"}
            mock_pp.verify_dir.return_value = {
                "ok": False,
                "kind": "env_missing",
                "summary": "Worktree not writable (permission denied)",
                "tiers": [],
            }

            with patch("spike_opencode_ollama._create_worktree") as mock_wt:
                with tempfile.TemporaryDirectory() as tmpdir:
                    tmpdir = Path(tmpdir)
                    mock_wt.return_value = (tmpdir, tmpdir, "branch")

                    with patch("spike_opencode_ollama._run_opencode"):
                        task = {
                            "id": "test-12",
                            "prompt": "Do something",
                            "base_commit": "def456",
                        }

                        result = run_spike_task(
                            task,
                            "test-model",
                            tmpdir,
                            "def456",
                            None,
                            None,
                        )

                        # Should surface the env_missing classification
                        assert result["gate"]["kind"] == "env_missing"
                        assert "not writable" in result["gate"]["summary"]


class TestResultStructure:
    """Test the structure of results produced by the driver."""

    def test_result_has_required_fields(self):
        """Test that each result has all required fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            task = {
                "id": "test-task",
                "prompt": "Do something",
                "base_commit": "abc123",
            }

            with patch("spike_opencode_ollama._create_worktree") as mock_wt:
                mock_wt.return_value = (tmpdir, tmpdir, "branch")

                with patch("spike_opencode_ollama._run_opencode"):
                    with patch("spike_opencode_ollama.project_profile") as mock_pp:
                        mock_pp.load_profile.return_value = {"repo": "marvin"}
                        mock_pp.verify_dir.return_value = {
                            "ok": True,
                            "kind": "passed",
                            "summary": "All checks passed",
                            "tiers": [],
                        }

                        result = run_spike_task(
                            task,
                            "test-model",
                            tmpdir,
                            "abc123",
                            None,
                            None,
                        )

                        # Check required fields
                        assert "task_id" in result
                        assert "status" in result
                        assert "gate" in result
                        assert "usage" in result
                        assert "energy" in result
                        assert "wall_s" in result
                        assert "error" in result

    def test_gate_result_preserved(self):
        """Test that gate result is correctly captured."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            task = {
                "id": "gate-test",
                "prompt": "Test",
                "base_commit": "abc123",
            }

            gate_response = {
                "ok": True,
                "kind": "passed",
                "summary": "Build passed, tests passed",
                "tiers": [{"id": "test", "passed": 10}],
            }

            with patch("spike_opencode_ollama._create_worktree") as mock_wt:
                mock_wt.return_value = (tmpdir, tmpdir, "branch")

                with patch("spike_opencode_ollama._run_opencode"):
                    with patch("spike_opencode_ollama.project_profile") as mock_pp:
                        mock_pp.load_profile.return_value = {"repo": "marvin"}
                        mock_pp.verify_dir.return_value = gate_response

                        result = run_spike_task(
                            task,
                            "test-model",
                            tmpdir,
                            "abc123",
                            None,
                            None,
                        )

                        assert result["gate"]["ok"] is True
                        assert result["gate"]["kind"] == "passed"
                        assert "Build passed" in result["gate"]["summary"]


class TestLoadTask:
    """Test task loading."""

    def test_load_task_reads_json_and_prompt(self):
        """Test that load_task correctly reads task.json and prompt.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Write task files
            task_json = {"id": "test-task", "type": "fs", "prompt_file": "prompt.md"}
            (tmpdir / "task.json").write_text(json.dumps(task_json))
            (tmpdir / "prompt.md").write_text("This is the prompt text")

            task = _load_task(tmpdir)

            assert task["id"] == "test-task"
            assert task["type"] == "fs"
            assert task["prompt"] == "This is the prompt text"
            assert task["dir"] == tmpdir


class TestUsageLogging:
    """Test usage measurement from proxy logfile."""

    def test_measure_usage_from_proxy_log(self):
        """Test that usage is correctly summed from proxy log."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            logfile = Path(f.name)
            # Write some usage entries
            f.write(json.dumps({
                "timestamp": 1.0,
                "path": "/api/chat",
                "prompt_tokens": 100,
                "gen_tokens": 50,
            }) + "\n")
            f.write(json.dumps({
                "timestamp": 2.0,
                "path": "/api/chat",
                "prompt_tokens": 200,
                "gen_tokens": 75,
            }) + "\n")

        try:
            usage = _measure_usage_from_proxy_log(logfile)
            assert usage["prompt_tokens"] == 300  # 100 + 200
            assert usage["gen_tokens"] == 125     # 50 + 75
        finally:
            logfile.unlink()

    def test_measure_usage_empty_logfile(self):
        """Test usage measurement on empty logfile."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            logfile = Path(f.name)

        try:
            usage = _measure_usage_from_proxy_log(logfile)
            assert usage["prompt_tokens"] == 0
            assert usage["gen_tokens"] == 0
        finally:
            logfile.unlink()

    def test_measure_usage_nonexistent_logfile(self):
        """Test usage measurement on nonexistent logfile."""
        logfile = Path("/tmp/nonexistent-log-12345.jsonl")
        usage = _measure_usage_from_proxy_log(logfile)
        assert usage["prompt_tokens"] == 0
        assert usage["gen_tokens"] == 0
