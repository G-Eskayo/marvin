"""Tests for paper-dive fixture consistency. Run via:
    ~/.agents/venv/bin/python -m pytest bench/tests/test_paperdive_fixtures.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))

import pytest
from bench import load_task


# ── Fixture schema validation ──────────────────────────────────────────────

class TestPaperDiveFixtures:
    """Validate paper-dive task fixture schema and content consistency."""

    def test_task_033_schema(self):
        """Task 033 must have id, expect, and type fields."""
        task_dir = BENCH / "tasks" / "task-033-paperdive-judge-benchmark"
        assert task_dir.exists(), f"{task_dir} not found"

        task = load_task(task_dir)
        assert "id" in task, "Task must have 'id' field"
        assert "expect" in task, "Task must have 'expect' field (answer expectation)"
        assert task["id"] == "task-033-paperdive-judge-benchmark"
        assert isinstance(task["expect"], list), "'expect' must be a list"
        assert len(task["expect"]) > 0, "'expect' list must not be empty"

    def test_task_034_schema(self):
        """Task 034 must have id, expect, and type fields."""
        task_dir = BENCH / "tasks" / "task-034-paperdive-inference-survey"
        assert task_dir.exists(), f"{task_dir} not found"

        task = load_task(task_dir)
        assert "id" in task, "Task must have 'id' field"
        assert "expect" in task, "Task must have 'expect' field (answer expectation)"
        assert task["id"] == "task-034-paperdive-inference-survey"
        assert isinstance(task["expect"], list), "'expect' must be a list"
        assert len(task["expect"]) > 0, "'expect' list must not be empty"

    def test_task_033_expects_none(self):
        """Task 033 (judge benchmark) should expect NONE (no construct validity gaps)."""
        task_dir = BENCH / "tasks" / "task-033-paperdive-judge-benchmark"
        task = load_task(task_dir)
        assert task["expect"] == ["NONE"], \
            f"Task 033 should expect ['NONE'], got {task['expect']}"

    def test_task_034_expects_inductive(self):
        """Task 034 (survey inference) should expect inductive reasoning."""
        task_dir = BENCH / "tasks" / "task-034-paperdive-inference-survey"
        task = load_task(task_dir)
        assert task["expect"] == ["inductive"], \
            f"Task 034 should expect ['inductive'], got {task['expect']}"

    def test_task_033_prompt_mentions_strongreject(self):
        """Task 033 prompt should discuss StrongREJECT benchmark."""
        task_dir = BENCH / "tasks" / "task-033-paperdive-judge-benchmark"
        task = load_task(task_dir)
        assert "StrongREJECT" in task["prompt"], \
            "Task 033 prompt should mention StrongREJECT benchmark"

    def test_task_033_prompt_mentions_92_percent(self):
        """Task 033 should cite the 92% accuracy validation."""
        task_dir = BENCH / "tasks" / "task-033-paperdive-judge-benchmark"
        task = load_task(task_dir)
        assert "92%" in task["prompt"], \
            "Task 033 prompt should cite the 92% human agreement validation"

    def test_task_034_prompt_mentions_survey(self):
        """Task 034 prompt should discuss survey papers."""
        task_dir = BENCH / "tasks" / "task-034-paperdive-inference-survey"
        task = load_task(task_dir)
        assert "survey" in task["prompt"].lower(), \
            "Task 034 prompt should discuss survey papers"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
