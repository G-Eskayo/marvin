"""Tests for spec_search.py — specification search and optimization loop.

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_spec_search.py -v
"""
import json
import pytest
import sys
from pathlib import Path

# Import the module under test
spec_search_path = Path(__file__).resolve().parents[1] / "spec_search.py"
sys.path.insert(0, str(spec_search_path.parent))


def test_evaluate_scores_extraction_against_gold_standard():
    """Test #1: evaluate() calls student_fn once per sample and scores results."""
    from spec_search import evaluate

    spec = {"temperature": 0.5}
    samples = [
        {"id": "s1", "extraction": {"field": "value1"}, "gold": "category_a"},
        {"id": "s2", "extraction": {"field": "value2"}, "gold": "category_b"},
    ]

    results = []
    def student_fn(extraction, spec):
        results.append((extraction, spec))
        return "category_a" if extraction["field"] == "value1" else "category_b"

    def score_fn(prediction, sample):
        return prediction == sample["gold"]

    accuracy = evaluate(spec, samples, student_fn, score_fn)

    assert len(results) == 2
    assert results[0] == (samples[0]["extraction"], spec)
    assert accuracy == 1.0


def test_evaluate_returns_accuracy_as_fraction():
    """Test #2: evaluate() returns decimal accuracy between 0 and 1."""
    from spec_search import evaluate

    spec = {}
    samples = [
        {"gold": True},
        {"gold": False},
        {"gold": False},
        {"gold": True},
    ]

    call_count = [0]
    def student_fn(extraction, spec):
        call_count[0] += 1
        return call_count[0] <= 2

    def score_fn(pred, sample):
        return pred == sample["gold"]

    accuracy = evaluate(spec, samples, student_fn, score_fn)
    assert accuracy == 2/4


def test_propose_edit_calls_teacher_once_per_failing_sample():
    """Test #3: propose_edit() gathers failing samples and calls teacher once."""
    from spec_search import propose_edit

    spec = {"temperature": 0.7}
    failing_samples = [
        {"id": "fail1", "extraction": {"x": 1}},
        {"id": "fail2", "extraction": {"x": 2}},
    ]

    teacher_calls = []
    def teacher_fn(failing, current_spec):
        teacher_calls.append((failing, current_spec))
        return json.dumps({"temperature": 0.8, "extra": "field"})

    result = propose_edit(spec, failing_samples, teacher_fn)

    assert len(teacher_calls) == 1
    assert teacher_calls[0] == (failing_samples, spec)


def test_propose_edit_parses_valid_json_response():
    """Test #4: propose_edit() returns parsed JSON from teacher."""
    from spec_search import propose_edit

    spec = {"a": 1}
    failing_samples = []

    def teacher_fn(failing, current_spec):
        return json.dumps({"a": 2, "b": 3})

    result = propose_edit(spec, failing_samples, teacher_fn)
    assert result == {"a": 2, "b": 3}


def test_propose_edit_validates_teacher_json():
    """Test #5: propose_edit() no-ops on invalid JSON from teacher."""
    from spec_search import propose_edit

    spec = {"valid": True}
    failing_samples = []

    def teacher_fn(failing, current_spec):
        return "{ invalid json"

    result = propose_edit(spec, failing_samples, teacher_fn)
    assert result is None


def test_propose_edit_returns_none_on_empty_response():
    """Test #6: propose_edit() no-ops on empty teacher response."""
    from spec_search import propose_edit

    spec = {}
    failing_samples = []

    def teacher_fn(failing, current_spec):
        return ""

    result = propose_edit(spec, failing_samples, teacher_fn)
    assert result is None


def test_search_iterates_until_perfect_score():
    """Test #7: search() stops early when accuracy reaches 1.0."""
    from spec_search import search

    spec = {"version": 1}
    samples = [{"gold": True}, {"gold": True}]

    def student_fn(extraction, spec):
        return spec.get("version", 0) >= 2

    def score_fn(pred, sample):
        return pred == sample["gold"]

    teacher_calls = [0]
    def teacher_fn(failing, current_spec):
        # Bump version to make student succeed
        teacher_calls[0] += 1
        new_spec = dict(current_spec)
        new_spec["version"] = 2
        return json.dumps(new_spec)

    result = search(spec, samples, student_fn, teacher_fn, score_fn, max_iterations=10)
    # Should reach perfect accuracy and stop early (iteration 1)
    assert result["accuracy"] == 1.0
    assert result["iterations"] <= 1


def test_search_respects_max_iterations():
    """Test #8: search() stops after max_iterations even if not perfect."""
    from spec_search import search

    spec = {"v": 0}
    samples = [{"gold": True}]

    iterations = [0]
    def student_fn(extraction, spec):
        return False

    def score_fn(pred, sample):
        return pred

    def teacher_fn(failing, current_spec):
        iterations[0] += 1
        return json.dumps({"v": iterations[0]})

    result = search(spec, samples, student_fn, teacher_fn, score_fn, max_iterations=3)
    assert iterations[0] <= 3


def test_search_returns_history_of_edits():
    """Test #9: search() returns final_spec and iteration history."""
    from spec_search import search

    spec = {"step": 0}
    samples = [{"gold": True}]

    def student_fn(extraction, spec):
        return spec.get("step", 0) >= 2

    def score_fn(pred, sample):
        return pred == sample["gold"]

    def teacher_fn(failing, current_spec):
        new_spec = dict(current_spec)
        new_spec["step"] = new_spec.get("step", 0) + 1
        return json.dumps(new_spec)

    result = search(spec, samples, student_fn, teacher_fn, score_fn, max_iterations=5)

    # Result should be a dict with spec, accuracy, iterations, and history
    assert isinstance(result, dict)
    assert "spec" in result
    assert "accuracy" in result
    assert "iterations" in result
    assert "history" in result
    assert isinstance(result["history"], list)
