"""Tests for spec_search.py. Run via:
    ~/.agents/venv/bin/python -m pytest bench/tests/test_spec_search.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

BENCH = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENCH))

import pytest
import spec_search


def test_apply_edit_basic():
    """Test _apply_edit creates a new spec with the edit applied."""
    spec = {"model": "qwen", "temperature": 0.7}
    edited = spec_search._apply_edit(spec, "model", "llama")

    assert edited["model"] == "llama"
    assert edited["temperature"] == 0.7
    assert spec["model"] == "qwen"  # Original unchanged


def test_apply_edit_adds_field():
    """Test _apply_edit can add a new field."""
    spec = {"model": "qwen"}
    edited = spec_search._apply_edit(spec, "temperature", "0.5")

    assert edited["temperature"] == "0.5"
    assert "temperature" not in spec


def test_apply_edit_overwrites_field():
    """Test _apply_edit overwrites existing field."""
    spec = {"model": "qwen", "temperature": 0.7}
    edited = spec_search._apply_edit(spec, "temperature", 0.9)

    assert edited["temperature"] == 0.9


def test_make_edit_proposal_parsing():
    """Test _make_edit_proposal parses valid EDIT response."""
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.stdout = """EDIT:
FIELD: classify_model
NEW_VALUE: qwen2.5:14b
RATIONALE: larger model for better classification accuracy"""
        mock_run.return_value = mock_proc

        proposal = spec_search._make_edit_proposal(
            {"classify_model": "qwen2.5:7b"},
            '{"baseline_accuracy": 0.85}'
        )

        assert proposal["field"] == "classify_model"
        assert proposal["new_value"] == "qwen2.5:14b"
        assert "accuracy" in proposal["rationale"].lower()


def test_make_edit_proposal_stop():
    """Test _make_edit_proposal detects STOP response."""
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.stdout = "STOP\nREASON: Further optimization unlikely with current settings"
        mock_run.return_value = mock_proc

        proposal = spec_search._make_edit_proposal(
            {"model": "qwen"},
            "{}"
        )

        assert proposal["stop"] is True
        assert "unlikely" in proposal["rationale"].lower()


def test_make_edit_proposal_handles_errors():
    """Test _make_edit_proposal raises on judge errors."""
    with patch("subprocess.run", side_effect=Exception("subprocess failed")):
        with pytest.raises(RuntimeError, match="edit proposal failed"):
            spec_search._make_edit_proposal({"model": "qwen"}, "{}")


def test_run_search_basic_flow():
    """Test run_search basic iteration flow."""
    baseline_spec = {"model": "qwen", "temperature": 0.7}

    # Mock score function that improves over iterations
    score_calls = [
        {"accuracy": 0.80},  # Initial baseline
        {"accuracy": 0.85},  # Improvement on edit 1
        {"accuracy": 0.90},  # Improvement on edit 2
    ]
    score_call_count = [0]

    def mock_score_fn(spec, benchmark):
        result = score_calls[score_call_count[0]]
        score_call_count[0] = min(score_call_count[0] + 1, len(score_calls) - 1)
        return result

    with patch("spec_search._check_quota", return_value=None):
        with patch("spec_search._make_edit_proposal") as mock_proposal:
            # First proposal: edit model (improves)
            # Second proposal: edit temperature (improves further)
            mock_proposal.side_effect = [
                {"field": "model", "new_value": "qwen2.5:14b", "rationale": "larger"},
                {"field": "temperature", "new_value": 0.5, "rationale": "lower"},
            ]

            benchmark = {"paper1": {}, "paper2": {}}

            result = spec_search.run_search(
                baseline_spec=baseline_spec,
                score_fn=mock_score_fn,
                benchmark=benchmark,
                max_iterations=2,
                accuracy_threshold=0.95,
            )

            assert result["baseline"]["accuracy"] == 0.80
            assert result["best"]["accuracy"] == 0.90  # Both edits accepted
            assert len(result["trace"]) == 2
            assert result["trace"][0]["decision"] == "accepted (improvement)"
            assert result["trace"][1]["decision"] == "accepted (improvement)"
            assert result["best"]["spec"]["model"] == "qwen2.5:14b"
            assert result["best"]["spec"]["temperature"] == 0.5


def test_run_search_stops_at_threshold():
    """Test run_search stops when accuracy threshold is reached."""
    baseline_spec = {"model": "qwen"}

    def mock_score_fn(spec, benchmark):
        return {"accuracy": 0.95}

    with patch("spec_search._check_quota", return_value=None):
        with patch("spec_search._make_edit_proposal"):
            result = spec_search.run_search(
                baseline_spec=baseline_spec,
                score_fn=mock_score_fn,
                benchmark={"paper1": {}},
                max_iterations=10,
                accuracy_threshold=0.90,
            )

            assert result["stopped_reason"] == "threshold_reached"
            assert result["best"]["accuracy"] >= 0.90


def test_run_search_stops_at_max_iterations():
    """Test run_search stops at max iterations."""
    baseline_spec = {"model": "qwen"}

    def mock_score_fn(spec, benchmark):
        return {"accuracy": 0.50}  # Never reaches threshold

    with patch("spec_search._check_quota", return_value=None):
        with patch("spec_search._make_edit_proposal") as mock_proposal:
            mock_proposal.return_value = {
                "field": "dummy",
                "new_value": "value",
                "rationale": "test"
            }

            result = spec_search.run_search(
                baseline_spec=baseline_spec,
                score_fn=mock_score_fn,
                benchmark={"paper1": {}},
                max_iterations=3,
                accuracy_threshold=0.99,
            )

            assert result["stopped_reason"] == "max_iterations"
            assert result["total_iterations"] == 3


def test_run_search_rejects_regressions():
    """Test that run_search rejects edits that lower accuracy."""
    baseline_spec = {"model": "qwen"}
    scores = [0.85, 0.80, 0.90]  # Baseline, then regression, then improvement
    score_call_count = [0]

    def mock_score_fn(spec, benchmark):
        result = scores[min(score_call_count[0], len(scores) - 1)]
        score_call_count[0] += 1
        return {"accuracy": result}

    with patch("spec_search._check_quota", return_value=None):
        with patch("spec_search._make_edit_proposal") as mock_proposal:
            mock_proposal.side_effect = [
                {"field": "model", "new_value": "bad_model", "rationale": "test"},
                {"field": "model", "new_value": "good_model", "rationale": "test"},
                {"stop": True, "rationale": "done"},
            ]

            result = spec_search.run_search(
                baseline_spec=baseline_spec,
                score_fn=mock_score_fn,
                benchmark={"paper1": {}},
                max_iterations=5,
                accuracy_threshold=0.99,
            )

            # First edit should be rejected (regressed to 0.80)
            assert result["trace"][0]["decision"].startswith("rejected")
            assert result["trace"][0]["accuracy"] == 0.80

            # Second edit should be accepted (improved to 0.90, which is > baseline 0.85)
            assert result["trace"][1]["decision"] == "accepted (improvement)"
            assert result["trace"][1]["accuracy"] == 0.90

            # Final best should be the accepted edit (0.90)
            assert result["best"]["accuracy"] == 0.90
            assert result["best"]["spec"]["model"] == "good_model"

            # Baseline should remain unchanged
            assert result["baseline"]["accuracy"] == 0.85


def test_make_edit_proposal_parsing_multiline_value():
    """Test that _make_edit_proposal captures multi-line values."""
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.stdout = """EDIT:
FIELD: classify_prompt
NEW_VALUE: This is a prompt
with multiple lines
and continues here
RATIONALE: multi-line is better"""
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        proposal = spec_search._make_edit_proposal(
            {"classify_prompt": "original"},
            '{"baseline_accuracy": 0.85}'
        )

        assert proposal["field"] == "classify_prompt"
        assert "multiple lines" in proposal["new_value"]
        assert "continues here" in proposal["new_value"]


def test_make_edit_proposal_parsing_json_value():
    """Test that _make_edit_proposal parses JSON values correctly."""
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.stdout = """EDIT:
FIELD: temperature
NEW_VALUE: 0.5
RATIONALE: lower temperature"""
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        proposal = spec_search._make_edit_proposal(
            {"temperature": 0.7},
            '{"baseline_accuracy": 0.85}'
        )

        # Should parse as float, not string
        assert proposal["new_value"] == 0.5
        assert isinstance(proposal["new_value"], float)


def test_make_edit_proposal_stop_before_edit():
    """Test that STOP is detected correctly even with 'stop' in rationale."""
    with patch("subprocess.run") as mock_run:
        mock_proc = MagicMock()
        mock_proc.stdout = """STOP
REASON: non-stop improvements unlikely"""
        mock_proc.returncode = 0
        mock_run.return_value = mock_proc

        proposal = spec_search._make_edit_proposal(
            {"model": "qwen"},
            "{}"
        )

        # Should recognize STOP, not get confused by "stop" in reason
        assert proposal.get("stop") is True
        assert "unlikely" in proposal["rationale"]


def test_run_search_budget_tracking():
    """Test that run_search tracks budget and stops when exhausted."""
    baseline_spec = {"model": "qwen"}

    score_calls = [{"accuracy": 0.85}, {"accuracy": 0.86}, {"accuracy": 0.87}]
    score_call_count = [0]

    def mock_score_fn(spec, benchmark):
        result = score_calls[min(score_call_count[0], len(score_calls) - 1)]
        score_call_count[0] += 1
        return result

    with patch("spec_search._check_quota", return_value=None):
        with patch("spec_search._make_edit_proposal") as mock_proposal:
            mock_proposal.side_effect = [
                {"field": "model", "new_value": "qwen2", "rationale": "test"},
                {"field": "model", "new_value": "qwen3", "rationale": "test"},
            ]

            result = spec_search.run_search(
                baseline_spec=baseline_spec,
                score_fn=mock_score_fn,
                benchmark={"paper1": {}},
                max_iterations=10,
                accuracy_threshold=0.99,
                budget_tokens=1000,  # Very small budget
            )

            # Should stop due to budget
            assert result["stopped_reason"] == "budget_exhausted"
            # Should have made at least one iteration before exhausting budget
            assert len(result["trace"]) >= 1


def test_run_search_invalid_field_rejected():
    """Test that edits to non-existent fields are rejected."""
    baseline_spec = {"model": "qwen", "temperature": 0.7}

    def mock_score_fn(spec, benchmark):
        return {"accuracy": 0.85}

    with patch("spec_search._check_quota", return_value=None):
        with patch("spec_search._make_edit_proposal") as mock_proposal:
            mock_proposal.side_effect = [
                {"field": "nonexistent", "new_value": "value", "rationale": "test"},
                {"stop": True, "rationale": "done"},
            ]

            result = spec_search.run_search(
                baseline_spec=baseline_spec,
                score_fn=mock_score_fn,
                benchmark={"paper1": {}},
                max_iterations=5,
                accuracy_threshold=0.99,
            )

            # First edit should be rejected (invalid field)
            assert result["trace"][0]["decision"] == "rejected (invalid field)"


def test_run_search_consecutive_no_change_records_final_iteration():
    """Test that the final iteration triggering consecutive_no_change >= 3 is recorded in trace.

    This catches the bug where trace.append() was called AFTER the stop check,
    so the iteration that triggered the stop was dropped from the trace."""
    baseline_spec = {"model": "qwen"}
    scores = [0.85, 0.85, 0.85, 0.85]  # Baseline + 3 neutral edits
    score_call_count = [0]

    def mock_score_fn(spec, benchmark):
        result = scores[min(score_call_count[0], len(scores) - 1)]
        score_call_count[0] += 1
        return {"accuracy": result}

    with patch("spec_search._check_quota", return_value=None):
        with patch("spec_search._make_edit_proposal") as mock_proposal:
            mock_proposal.side_effect = [
                {"field": "model", "new_value": "edit1", "rationale": "test1"},
                {"field": "model", "new_value": "edit2", "rationale": "test2"},
                {"field": "model", "new_value": "edit3", "rationale": "test3"},
            ]

            result = spec_search.run_search(
                baseline_spec=baseline_spec,
                score_fn=mock_score_fn,
                benchmark={"paper1": {}},
                max_iterations=10,
                accuracy_threshold=0.99,
            )

            # Should have stopped after 3 neutral/rejected edits
            assert result["stopped_reason"] == "consecutive_no_change"
            # Critical: all 3 iterations should be in the trace (not dropping the 3rd)
            assert len(result["trace"]) == 3
            assert result["trace"][0]["iteration"] == 1
            assert result["trace"][1]["iteration"] == 2
            assert result["trace"][2]["iteration"] == 3
            # All should be neutral (same accuracy as baseline)
            for i, entry in enumerate(result["trace"]):
                assert entry["accuracy"] == 0.85
