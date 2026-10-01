"""Tests for isolate_workdir QA task mechanism (task-018-isolated-memory-qa).

Validates that isolated-memory discriminator tasks construct the correct
subprocess invocation and that the QA task fixture is properly configured.

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_isolated_memory_task.py -v
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

LIB = Path(__file__).resolve().parents[1]
BENCH_ROOT = LIB.parent
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(BENCH_ROOT))

import pytest


class TestTask018IsolatedMemoryQAFixture:
    """Verify task-018-isolated-memory-qa fixture is correctly configured."""

    @pytest.fixture
    def task_018(self):
        """Load the actual task-018 task.json."""
        root = Path(__file__).resolve().parents[2]
        task_dir = root / "tasks" / "task-018-isolated-memory-qa"
        task_json = task_dir / "task.json"
        return json.loads(task_json.read_text()), task_dir

    def test_task_018_has_required_fields(self, task_018):
        """Verify task.json has isolate_workdir, disallow_tools, and expect fields."""
        task_data, _ = task_018
        assert task_data.get("isolate_workdir") is True
        assert "disallow_tools" in task_data
        assert "expect" in task_data
        assert isinstance(task_data["expect"], list)
        assert len(task_data["expect"]) > 0

    def test_task_018_expected_phrase_not_in_workdir_files(self, task_018):
        """Verify the expected phrase does NOT appear verbatim in any workdir file.

        This enforces AC1 (answer not derivable from disk) by construction.
        The exact phrase from task.json['expect'] must not appear in files/,
        proving the agent cannot simply read the answer from the isolated workdir.
        """
        task_data, task_dir = task_018
        expected_phrases = task_data.get("expect", [])

        files_dir = task_dir / "files"
        assert files_dir.exists(), "task-018 must have a files/ directory"

        # Collect all text from files in the workdir
        all_file_text = []
        for f in files_dir.rglob("*"):
            if f.is_file():
                try:
                    all_file_text.append(f.read_text(errors="ignore"))
                except OSError:
                    pass

        combined_text = "\n".join(all_file_text)

        # Verify none of the expected phrases appear in the workdir files
        for phrase in expected_phrases:
            assert (
                phrase not in combined_text
            ), f"Expected phrase '{phrase}' found in workdir files — AC1 violated"

    def test_task_018_expected_phrase_not_in_prompt(self, task_018):
        """Verify the expected phrase does NOT appear in prompt.md.

        This ensures the answer requires a knowledge base query, not inference
        from the prompt itself.
        """
        task_data, task_dir = task_018
        expected_phrases = task_data.get("expect", [])

        prompt_file = task_dir / "prompt.md"
        assert prompt_file.exists(), "task-018 must have a prompt.md file"

        prompt_text = prompt_file.read_text()

        # Verify none of the expected phrases appear in the prompt
        for phrase in expected_phrases:
            assert (
                phrase not in prompt_text
            ), f"Expected phrase '{phrase}' found in prompt.md — answer would be trivial"

    def test_task_018_disallow_tools_blocks_file_access(self, task_018):
        """Verify disallow_tools includes the tools that would bypass isolation."""
        task_data, _ = task_018
        disallowed = task_data.get("disallow_tools", [])

        # These tools must be blocked to enforce isolation:
        # - Read: direct file access
        # - Glob/Grep: discovery via filesystem search
        required_denials = {"Read", "Glob", "Grep"}
        actual_denials = set(disallowed)

        for tool in required_denials:
            assert (
                tool in actual_denials
            ), f"Tool '{tool}' must be in disallow_tools to enforce isolation"
