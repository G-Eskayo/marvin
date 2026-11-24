"""Tests for judgment_spec.py. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_judgment_spec.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest
import judgment_spec


def test_default_spec_has_required_fields():
    """Test that DEFAULT_SPEC contains all required fields."""
    required_fields = [
        "classify_model",
        "extraction_model",
        "judgment_model",
        "inference_model",
        "classify_prompt",
        "extraction_prompts",
        "judgment_prompts",
        "inference_prompt",
    ]

    for field in required_fields:
        assert field in judgment_spec.DEFAULT_SPEC, f"Missing field: {field}"


def test_default_spec_models_are_strings():
    """Test that model fields are non-empty strings."""
    model_fields = [
        "classify_model",
        "extraction_model",
        "judgment_model",
        "inference_model",
    ]

    for field in model_fields:
        value = judgment_spec.DEFAULT_SPEC[field]
        assert isinstance(value, str), f"{field} should be a string"
        assert len(value) > 0, f"{field} should not be empty"


def test_default_spec_prompts_are_strings():
    """Test that prompt fields are non-empty strings."""
    assert isinstance(judgment_spec.DEFAULT_SPEC["classify_prompt"], str)
    assert len(judgment_spec.DEFAULT_SPEC["classify_prompt"]) > 0

    assert isinstance(judgment_spec.DEFAULT_SPEC["extraction_prompts"], dict)
    for paper_type, prompt in judgment_spec.DEFAULT_SPEC["extraction_prompts"].items():
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    assert isinstance(judgment_spec.DEFAULT_SPEC["judgment_prompts"], dict)
    for paper_type, prompt in judgment_spec.DEFAULT_SPEC["judgment_prompts"].items():
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    assert isinstance(judgment_spec.DEFAULT_SPEC["inference_prompt"], str)
    assert len(judgment_spec.DEFAULT_SPEC["inference_prompt"]) > 0


def test_judge_findings_equivalence_basic():
    """Test _judge_findings_equivalence with mock judge."""
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "EQUIVALENT: yes\nRATIONALE: same issues identified"
        mock_run.return_value = mock_proc

        result = judgment_spec._judge_findings_equivalence(
            ["finding1", "finding2"],
            ["finding2", "finding1"],
        )

        assert result["equivalent"] is True
        assert "rationale" in result


def test_judge_findings_equivalence_handles_errors():
    """Test that _judge_findings_equivalence raises on judge failures."""
    from unittest.mock import patch

    with patch("subprocess.run") as mock_run:
        # Simulate a failed subprocess
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stderr = "error"
        mock_run.return_value = mock_proc

        with pytest.raises(RuntimeError, match="judge call failed"):
            judgment_spec._judge_findings_equivalence(["f1"], ["f2"])


def test_score_spec_returns_expected_structure():
    """Test that score_spec returns a dict with expected keys."""
    spec = judgment_spec.DEFAULT_SPEC
    benchmark = {
        "paper1": {
            "slug": "paper1",
            "title": "Test Paper 1",
            "abstract": "Test abstract 1",
            "paper_type": "empirical",
            "findings": [],
            "inference": {},
        },
        "paper2": {
            "slug": "paper2",
            "title": "Test Paper 2",
            "abstract": "Test abstract 2",
            "paper_type": "survey",
            "findings": [],
            "inference": {},
        },
    }

    with patch("judgment_spec.logic_auditor.classify_paper_type"):
        with patch("judgment_spec.logic_auditor.check_inference_validity"):
            with patch("judgment_spec.logic_auditor.extract_structure"):
                with patch("judgment_spec.logic_auditor.judge_extraction"):
                    with patch("judgment_spec._judge_findings_equivalence") as mock_equiv:
                        mock_equiv.return_value = {"equivalent": True, "rationale": ""}

                        result = judgment_spec.score_spec(spec, benchmark)

                        expected_keys = ["accuracy", "type_accuracy", "inference_accuracy", "findings_accuracy", "details"]
                        for key in expected_keys:
                            assert key in result, f"Missing key: {key}"

                        assert isinstance(result["accuracy"], float)
                        assert 0.0 <= result["accuracy"] <= 1.0
                        assert isinstance(result["details"], dict)
                        assert len(result["details"]) == len(benchmark)


def test_score_spec_handles_empty_benchmark():
    """Test that score_spec handles empty benchmark gracefully."""
    spec = judgment_spec.DEFAULT_SPEC
    result = judgment_spec.score_spec(spec, {})

    assert result["accuracy"] == 0.0
    assert result["type_accuracy"] == 0.0
    assert result["details"] == {}


def test_score_spec_requires_abstract_in_gold():
    """Test that score_spec requires abstract in gold entries."""
    spec = judgment_spec.DEFAULT_SPEC
    # Benchmark without abstract should still work (will use empty string)
    benchmark = {
        "paper1": {
            "slug": "paper1",
            "title": "Test",
            "paper_type": "empirical",
            "findings": [],
            "inference": {},
            # No abstract
        },
    }

    with patch("judgment_spec.logic_auditor.classify_paper_type") as mock_classify:
        mock_classify.return_value = "empirical"
        with patch("judgment_spec.logic_auditor.check_inference_validity"):
            with patch("judgment_spec.logic_auditor.extract_structure"):
                with patch("judgment_spec.logic_auditor.judge_extraction"):
                    with patch("judgment_spec._judge_findings_equivalence") as mock_equiv:
                        mock_equiv.return_value = {"equivalent": True, "rationale": ""}

                        result = judgment_spec.score_spec(spec, benchmark)

                        # Should complete without error
                        assert "accuracy" in result
                        assert len(result["details"]) == 1


def test_score_spec_compares_type_and_inference():
    """Test that score_spec actually compares type and inference labels."""
    spec = judgment_spec.DEFAULT_SPEC
    benchmark = {
        "paper1": {
            "slug": "paper1",
            "title": "Test",
            "abstract": "Test abstract",
            "paper_type": "empirical",
            "inference": {"reasoning_type": "inductive"},
            "findings": [],
        },
    }

    with patch("judgment_spec.logic_auditor.classify_paper_type") as mock_classify:
        mock_classify.return_value = "empirical"  # Matches gold
        with patch("judgment_spec.logic_auditor.check_inference_validity") as mock_infer:
            mock_infer.return_value = {"reasoning_type": "inductive"}  # Matches gold
            with patch("judgment_spec.logic_auditor.extract_structure"):
                with patch("judgment_spec.logic_auditor.judge_extraction"):
                    with patch("judgment_spec._judge_findings_equivalence") as mock_equiv:
                        mock_equiv.return_value = {"equivalent": True, "rationale": ""}

                        result = judgment_spec.score_spec(spec, benchmark)

                        # Type match should succeed
                        assert result["details"]["paper1"]["type_match"] is True
                        # Inference match should succeed
                        assert result["details"]["paper1"]["inference_match"] is True
                        # Findings should match
                        assert result["details"]["paper1"]["findings_equivalent"]["equivalent"] is True


def test_score_spec_rejects_mismatches():
    """Test that score_spec rejects when student output doesn't match gold."""
    spec = judgment_spec.DEFAULT_SPEC
    benchmark = {
        "paper1": {
            "slug": "paper1",
            "title": "Test",
            "abstract": "Test abstract",
            "paper_type": "empirical",
            "inference": {"reasoning_type": "inductive"},
            "findings": ["finding1", "finding2"],
        },
    }

    with patch("judgment_spec.logic_auditor.classify_paper_type") as mock_classify:
        mock_classify.return_value = "survey"  # Doesn't match gold "empirical"
        with patch("judgment_spec.logic_auditor.check_inference_validity") as mock_infer:
            mock_infer.return_value = {"reasoning_type": "deductive"}  # Doesn't match
            with patch("judgment_spec.logic_auditor.extract_structure"):
                with patch("judgment_spec.logic_auditor.judge_extraction"):
                    with patch("judgment_spec._judge_findings_equivalence") as mock_equiv:
                        mock_equiv.return_value = {"equivalent": False, "rationale": "different findings"}

                        result = judgment_spec.score_spec(spec, benchmark)

                        assert result["details"]["paper1"]["type_match"] is False
                        assert result["details"]["paper1"]["inference_match"] is False
                        assert result["details"]["paper1"]["findings_equivalent"]["equivalent"] is False
                        assert result["accuracy"] == 0.0
