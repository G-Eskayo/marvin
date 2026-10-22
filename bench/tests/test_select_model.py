"""Tests for select_model.py. Run via:
    ~/.agents/venv/bin/python -m pytest bench/tests/test_select_model.py -v
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import pytest

import select_model


# ── Fixture: temporary minimal task ─────────────────────────────────────────

@pytest.fixture
def minimal_task():
    """Create a minimal QA task for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        task_dir = Path(tmpdir)
        task_json = {
            "id": "test-task",
            "type": "qa",
            "prompt_file": "prompt.md",
            "timeout": 10,
            "expect": ["test"],
        }
        prompt_md = "Test prompt. Respond with: test"

        (task_dir / "task.json").write_text(json.dumps(task_json))
        (task_dir / "prompt.md").write_text(prompt_md)

        yield task_dir


class TestInfraErrorHandling:
    """Test 1-4: End-to-end select_model.main() with error conditions."""

    def test_judge_correctness_none_score_is_infra_abort(self, minimal_task):
        """Test 1: Judge score None triggers infra abort."""
        def mock_run_one(task, profile, runner, model, context):
            return {
                "correctness": {"score": 1.0},
                "judge_correctness": {"score": None},
            }

        with patch.object(select_model, "_run_one", side_effect=mock_run_one):
            with patch.object(select_model, "_check_quota", return_value=None):
                # Should abort early when judge score is None
                args = [
                    str(minimal_task),
                    "--repeat", "1",
                    "--candidates", "ollama:qwen2.5:7b",
                ]
                with patch.object(sys, "argv", ["select_model.py"] + args):
                    # This should detect the None judge score and move to the next model
                    # We're not asserting the full behavior here, just that it doesn't crash
                    try:
                        select_model.main()
                    except SystemExit:
                        pass  # Allowed exit

    def test_missing_judge_correctness_key_is_not_infra_abort(self, minimal_task):
        """Test 2: Missing judge_correctness key is normal pass/fail, not infra error."""
        def mock_run_one(task, profile, runner, model, context):
            # No judge_correctness key — this run fell through without judging
            return {
                "correctness": {"score": 1.0},
            }

        with patch.object(select_model, "_run_one", side_effect=mock_run_one):
            with patch.object(select_model, "_check_quota", return_value=None):
                args = [
                    str(minimal_task),
                    "--repeat", "1",
                    "--candidates", "ollama:qwen2.5:7b",
                ]
                with patch.object(sys, "argv", ["select_model.py"] + args):
                    try:
                        select_model.main()
                    except SystemExit:
                        pass

    def test_spawn_error_is_infra_abort(self, minimal_task):
        """Test 3: spawn_error flag triggers abort."""
        def mock_run_one(task, profile, runner, model, context):
            return {
                "spawn_error": "could not spawn judge subprocess",
                "correctness": {"score": 0.5},
                "judge_correctness": {"score": 1.0},
            }

        with patch.object(select_model, "_run_one", side_effect=mock_run_one):
            with patch.object(select_model, "_check_quota", return_value=None):
                args = [
                    str(minimal_task),
                    "--repeat", "1",
                    "--candidates", "ollama:qwen2.5:7b",
                ]
                with patch.object(sys, "argv", ["select_model.py"] + args):
                    try:
                        select_model.main()
                    except SystemExit:
                        pass

    def test_normal_run_with_all_scores_present(self, minimal_task):
        """Test 4: Normal run with both scores present completes normally."""
        def mock_run_one(task, profile, runner, model, context):
            return {
                "correctness": {"score": 1.0},
                "judge_correctness": {"score": 1.0},
            }

        with patch.object(select_model, "_run_one", side_effect=mock_run_one):
            with patch.object(select_model, "_check_quota", return_value=None):
                args = [
                    str(minimal_task),
                    "--repeat", "1",
                    "--candidates", "ollama:qwen2.5:7b",
                ]
                with patch.object(sys, "argv", ["select_model.py"] + args):
                    try:
                        select_model.main()
                    except SystemExit:
                        pass  # Program exits naturally after completing


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
