"""Tests for spec_search.py functions.
Run via: ~/.agents/venv/bin/python -m pytest bench/tests_spec_search.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

# Add bench directory to path for imports
BENCH = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH))

import pytest
from spec_search import compute_accuracy


class TestComputeAccuracy:
    """Tests for the compute_accuracy function."""

    def test_compute_accuracy_perfect_agreement(self):
        """compute_accuracy returns 1.0 when student and gold agree perfectly."""
        student = {
            "paper-1": [],  # no findings
            "paper-2": ["finding1"],  # has finding
            "paper-3": [],  # no findings
        }
        gold = {
            "paper-1": [],  # agrees: no findings
            "paper-2": ["some finding"],  # agrees: has finding (content doesn't matter)
            "paper-3": [],  # agrees: no findings
        }
        assert compute_accuracy(student, gold) == 1.0

    def test_compute_accuracy_partial_agreement(self):
        """compute_accuracy returns correct fraction for partial agreement."""
        student = {
            "paper-1": [],  # agrees with gold (both clean)
            "paper-2": ["finding"],  # disagrees: student says issue, gold says clean
            "paper-3": [],  # agrees with gold (both clean)
        }
        gold = {
            "paper-1": [],
            "paper-2": [],  # gold says clean
            "paper-3": ["issue"],  # disagrees: student says clean, gold says issue
        }
        # 1 perfect match + 2 mismatches = 1/3
        assert compute_accuracy(student, gold) == 1.0 / 3.0

    def test_compute_accuracy_no_agreement(self):
        """compute_accuracy returns 0.0 when no papers agree."""
        student = {
            "paper-1": [],  # student clean
            "paper-2": [],  # student clean
        }
        gold = {
            "paper-1": ["issue"],  # gold has issue
            "paper-2": ["issue"],  # gold has issue
        }
        assert compute_accuracy(student, gold) == 0.0

    def test_compute_accuracy_finding_count_ignored(self):
        """compute_accuracy only cares if there are findings, not how many."""
        student = {
            "paper-1": ["a", "b", "c"],  # 3 findings
            "paper-2": [],
        }
        gold = {
            "paper-1": ["x"],  # 1 finding, but both have findings
            "paper-2": [],
        }
        # Both agree: paper-1 has findings, paper-2 is clean
        assert compute_accuracy(student, gold) == 1.0

    def test_compute_accuracy_empty_student_raises(self):
        """compute_accuracy raises ValueError when student findings is empty."""
        gold = {"paper-1": []}

        with pytest.raises(ValueError, match="non-empty"):
            compute_accuracy({}, gold)

    def test_compute_accuracy_empty_gold_raises(self):
        """compute_accuracy raises ValueError when gold findings is empty."""
        student = {"paper-1": []}

        with pytest.raises(ValueError, match="non-empty"):
            compute_accuracy(student, {})

    def test_compute_accuracy_mismatched_keys_raises(self):
        """compute_accuracy raises ValueError when student and gold have different keys."""
        student = {"paper-1": [], "paper-2": []}
        gold = {"paper-1": [], "paper-3": []}  # different key

        with pytest.raises(ValueError, match="same paper keys"):
            compute_accuracy(student, gold)

    def test_compute_accuracy_subset_keys_raises(self):
        """compute_accuracy raises ValueError when keys don't match exactly."""
        student = {"paper-1": []}
        gold = {"paper-1": [], "paper-2": []}

        with pytest.raises(ValueError, match="same paper keys"):
            compute_accuracy(student, gold)


class TestSpecSearchErrorHandling:
    """Tests for error handling in spec_search's main loop."""

    def test_compute_accuracy_empty_dict_raises_not_returns_zero(self):
        """Design test 4: empty benchmark raises ValueError, not 0.0."""
        # This ensures the placeholder empty dicts don't get silently treated as perfect failure
        student = {}
        gold = {}

        with pytest.raises(ValueError, match="non-empty"):
            compute_accuracy(student, gold)

    def test_compute_accuracy_config_error_vs_judgment_error(self):
        """Design test 3: config errors (incompatible prompt) raise before compute_accuracy."""
        # When a prompt is malformed, judge_extraction raises ValueError.
        # This happens BEFORE we can call compute_accuracy, so config errors
        # don't get scored as if they were judgments.
        # The test verifies this via test_judge_extraction_malformed_prompt_raises_not_returns
        # in test_logic_auditor_prompt_override.py
        pass
