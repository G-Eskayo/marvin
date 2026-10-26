"""Tests for paper_dive_benchmark.py. Run via:
    ~/.agents/venv/bin/python -m pytest bench/lib/tests/test_paper_dive_benchmark.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from paper_dive_benchmark import BenchmarkSample, score_finding, format_messages_to_prompt, score_student_model


# ── Finding score calculation ────────────────────────────────────────────────

def test_finding_score_teacher_has_zero_student_has_zero():
    """When teacher found 0 findings and student found 0, score is 1.0 (perfect agreement)."""
    finding_score = score_finding(teacher_count=0, student_findings=[])
    assert finding_score == 1.0


def test_finding_score_teacher_has_zero_student_has_findings():
    """When teacher found 0 but student invented findings, score is 0.0 (false positives)."""
    finding_score = score_finding(teacher_count=0, student_findings=["a", "b", "c"])
    assert finding_score == 0.0


def test_finding_score_teacher_has_findings_student_has_zero():
    """When teacher found findings but student found none, score reflects no recall but no false positives."""
    finding_score = score_finding(teacher_count=5, student_findings=[])
    # recall = 0/5 = 0.0, precision = 1.0 (no false positives), score = 0.5
    assert finding_score == 0.5


def test_finding_score_teacher_has_5_student_has_5():
    """When both found same count, score should be 1.0 (perfect recall and precision)."""
    finding_score = score_finding(teacher_count=5, student_findings=["a", "b", "c", "d", "e"])
    assert finding_score == 1.0


def test_finding_score_teacher_has_5_student_has_3():
    """When student found fewer, score reflects recall loss but maintains precision."""
    finding_score = score_finding(teacher_count=5, student_findings=["a", "b", "c"])
    # recall = 3/5 = 0.6, precision = 1.0, score = (0.6 + 1.0) / 2 = 0.8
    assert finding_score == 0.8


def test_finding_score_teacher_has_5_student_has_10():
    """When student over-generates, precision penalizes the over-generation."""
    student_findings = [f"finding_{i}" for i in range(10)]
    finding_score = score_finding(teacher_count=5, student_findings=student_findings)
    # recall = min(10/5, 1.0) = 1.0, precision = 5/10 = 0.5, score = (1.0 + 0.5) / 2 = 0.75
    assert finding_score == 0.75


def test_finding_score_handles_non_iterable_student_findings():
    """When student_findings is not iterable (e.g., object), score handles gracefully by returning 0."""
    # Pass a non-iterable object (an integer, which has no len())
    finding_score = score_finding(teacher_count=5, student_findings=42)
    # Non-iterable should be caught by TypeError and treated as 0 findings
    # recall = 0/5 = 0.0, precision = 1.0, score = 0.5
    assert finding_score == 0.5


def test_finding_score_handles_none_student_findings():
    """When student_findings is None, score treats it as empty."""
    finding_score = score_finding(teacher_count=5, student_findings=None)
    # recall = 0/5 = 0.0, precision = 1.0, score = 0.5
    assert finding_score == 0.5


# ── format_messages_to_prompt ──────────────────────────────────────────────

def test_format_messages_to_prompt_formats_all_messages():
    """format_messages_to_prompt forwards all messages (system + user), not just the first."""
    messages = [
        {"role": "system", "content": "You are a paper analyzer."},
        {"role": "user", "content": "Analyze this abstract: ..."},
    ]

    full_prompt = format_messages_to_prompt(messages)

    expected = "SYSTEM:\nYou are a paper analyzer.\n\nUSER:\nAnalyze this abstract: ..."
    assert full_prompt == expected


def test_format_messages_to_prompt_single_message():
    """format_messages_to_prompt handles single message without crashing."""
    messages = [
        {"role": "user", "content": "What is 2+2?"},
    ]

    full_prompt = format_messages_to_prompt(messages)

    expected = "USER:\nWhat is 2+2?"
    assert full_prompt == expected


def test_format_messages_to_prompt_many_messages():
    """format_messages_to_prompt handles multiple message rounds."""
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "First user message"},
        {"role": "assistant", "content": "First assistant response"},
        {"role": "user", "content": "Follow-up question"},
    ]

    full_prompt = format_messages_to_prompt(messages)

    # Should include all four messages
    assert "SYSTEM:" in full_prompt
    assert "First user message" in full_prompt
    assert "ASSISTANT:" in full_prompt
    assert "Follow-up question" in full_prompt


def test_format_messages_to_prompt_handles_missing_role():
    """format_messages_to_prompt defaults to USER if role is missing."""
    messages = [
        {"content": "Message without role"},
    ]

    full_prompt = format_messages_to_prompt(messages)

    assert "USER:" in full_prompt
    assert "Message without role" in full_prompt


# ── Exception handling for Ollama errors ─────────────────────────────────────

def test_score_student_model_aborts_on_subprocess_error():
    """When Ollama subprocess fails, abort loudly (raise), not silently score 0.0."""
    with mock.patch("paper_dive_benchmark.load_frozen_benchmark") as mock_load:
        # Set up a benchmark with one sample
        mock_load.return_value = {
            "test_slug": BenchmarkSample(
                slug="test_slug",
                title="Test Paper",
                abstract="Abstract",
                paper_type="empirical",
                layer1_findings=["finding1"],
                layer2_result={"reasoning_type": "deductive"},
            )
        }

        with mock.patch("paper_dive_benchmark.extract_all") as mock_extract:
            # Make extract_all raise CalledProcessError
            mock_extract.side_effect = subprocess.CalledProcessError(1, "ollama run")

            # Verify that the exception is re-raised, not silently caught
            with pytest.raises(subprocess.CalledProcessError):
                score_student_model()


def test_score_student_model_aborts_on_connection_error():
    """When Ollama connection fails, abort loudly (raise), not silently score 0.0."""
    with mock.patch("paper_dive_benchmark.load_frozen_benchmark") as mock_load:
        mock_load.return_value = {
            "test_slug": BenchmarkSample(
                slug="test_slug",
                title="Test Paper",
                abstract="Abstract",
                paper_type="empirical",
                layer1_findings=["finding1"],
                layer2_result={"reasoning_type": "deductive"},
            )
        }

        with mock.patch("paper_dive_benchmark.extract_all") as mock_extract:
            # Make extract_all raise ConnectionError
            mock_extract.side_effect = ConnectionError("Failed to connect to Ollama")

            # Verify that the exception is re-raised, not silently caught
            with pytest.raises(ConnectionError):
                score_student_model()


def test_score_student_model_aborts_on_keyerror():
    """When a KeyError occurs (missing extraction), abort loudly, not silently score 0.0."""
    with mock.patch("paper_dive_benchmark.load_frozen_benchmark") as mock_load:
        mock_load.return_value = {
            "test_slug": BenchmarkSample(
                slug="test_slug",
                title="Test Paper",
                abstract="Abstract",
                paper_type="empirical",
                layer1_findings=["finding1"],
                layer2_result={"reasoning_type": "deductive"},
            )
        }

        with mock.patch("paper_dive_benchmark.extract_all") as mock_extract:
            # Make extract_all raise KeyError
            mock_extract.side_effect = KeyError("extraction_result")

            # Verify that the exception is re-raised, not silently caught
            with pytest.raises(KeyError):
                score_student_model()


def test_score_student_model_aborts_on_runtime_error():
    """When a RuntimeError occurs, abort loudly, not silently score 0.0."""
    with mock.patch("paper_dive_benchmark.load_frozen_benchmark") as mock_load:
        mock_load.return_value = {
            "test_slug": BenchmarkSample(
                slug="test_slug",
                title="Test Paper",
                abstract="Abstract",
                paper_type="empirical",
                layer1_findings=["finding1"],
                layer2_result={"reasoning_type": "deductive"},
            )
        }

        with mock.patch("paper_dive_benchmark.extract_all") as mock_extract:
            # Make extract_all raise RuntimeError
            mock_extract.side_effect = RuntimeError("Unexpected error during model execution")

            # Verify that the exception is re-raised, not silently caught
            with pytest.raises(RuntimeError):
                score_student_model()


def test_score_student_model_handles_non_iterable_findings():
    """Verify score_student_model handles non-iterable student_findings without crashing."""
    with mock.patch("paper_dive_benchmark.load_frozen_benchmark") as mock_load:
        with mock.patch("paper_dive_benchmark.extract_all") as mock_extract:
            with mock.patch("paper_dive_benchmark.judge_all") as mock_judge:
                with mock.patch("paper_dive_benchmark.check_inference_validity_all") as mock_check:
                    with mock.patch("paper_dive_benchmark.Path") as mock_path:
                        # Mock the file writing to avoid side effects
                        mock_path.return_value = mock.MagicMock()

                        mock_load.return_value = {
                            "test_slug": BenchmarkSample(
                                slug="test_slug",
                                title="Test Paper",
                                abstract="Abstract",
                                paper_type="empirical",
                                layer1_findings=["finding1", "finding2"],
                                layer2_result={"reasoning_type": "deductive"},
                            )
                        }

                        # extract_all returns a dict
                        mock_extract.return_value = {"test_slug": "extraction"}

                        # judge_all returns a non-iterable (integer, not a list)
                        # This should be handled gracefully by score_finding
                        mock_judge.return_value = {"test_slug": 42}

                        # check_inference_validity_all returns valid dict
                        mock_check.return_value = {"test_slug": {"reasoning_type": "deductive"}}

                        # Open and read the saved file content instead of checking exact location
                        with mock.patch("builtins.open", mock.mock_open()):
                            with mock.patch("json.dump"):
                                scores = score_student_model()

                                # The function should return scores, not crash
                                assert isinstance(scores, dict)
                                assert "test_slug" in scores
                                # With 2 teacher findings and non-iterable (0) student findings:
                                # recall = 0/2 = 0.0, precision = 1.0, finding_score = 0.5
                                # reasoning match = 1.0 (both deductive)
                                # combined = 0.5 * 0.7 + 1.0 * 0.3 = 0.35 + 0.3 = 0.65
                                assert scores["test_slug"] == pytest.approx(0.65)
