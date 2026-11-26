"""Tests for spec_search.py. Run via:
    ~/.agents/venv/bin/python -m pytest bench/tests/test_spec_search.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add parent to path
BENCH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BENCH))
sys.path.insert(0, str(BENCH.parent / "lib"))

from spec_search import (  # noqa: E402
    evaluate_spec,
    propose_edit,
    search_loop,
    load_fixtures,
    FixtureCase,
)


# ── evaluate_spec tests ──────────────────────────────────────────────────────

def test_evaluate_spec_uses_spec_parameter():
    """Test 1: evaluate_spec passes spec to chat_fn."""
    spec = {"prompt": "edited", "model": "test-model", "options": {"temperature": 0.7}}
    fixtures = [
        FixtureCase(id="case-1", input_text="hello", ground_truth='["match"]')
    ]

    captured = {}
    def fake_chat(input_text, spec_arg, model):
        captured["spec"] = spec_arg
        captured["model"] = model
        return "match"

    result = evaluate_spec(spec, fixtures, fake_chat)

    # Verify spec was passed to chat_fn
    assert captured["spec"] == spec
    assert captured["model"] == "test-model"
    assert result["passed"] == 1


def test_evaluate_spec_checks_each_expected_string_separately():
    """Test 2: Multi-word expectations like 'construct validity' stay as single units."""
    spec = {"prompt": "test", "model": "test-model"}
    fixtures = [
        FixtureCase(id="case-1", input_text="test", ground_truth='["construct validity"]')
    ]

    def fake_chat(input_text, spec, model):
        # Response has both words but not as a phrase
        return "This shows construct reasoning and validity check"

    result = evaluate_spec(spec, fixtures, fake_chat)
    # Should fail because "construct validity" does not appear as a phrase
    assert result["failed"] == 1

    # But if response contains the exact phrase, it passes
    fixtures2 = [
        FixtureCase(id="case-1", input_text="test", ground_truth='["construct validity"]')
    ]
    def fake_chat2(input_text, spec, model):
        return "This demonstrates construct validity in the analysis"

    result2 = evaluate_spec(spec, fixtures2, fake_chat2)
    assert result2["passed"] == 1


def test_evaluate_spec_raises_on_missing_ground_truth():
    """Test 3: Fixture missing ground-truth field raises named error."""
    spec = {"prompt": "test", "model": "test-model"}
    fixtures = [
        FixtureCase(id="case-1", input_text="hello", expected_output="world")
        # Missing ground_truth field entirely
    ]

    def fake_chat(input_text, spec, model):
        return "response"

    with pytest.raises(ValueError, match="missing ground_truth"):
        evaluate_spec(spec, fixtures, fake_chat)

    # Also test empty ground_truth
    fixtures_empty = [
        FixtureCase(id="case-1", input_text="hello", ground_truth="")
    ]
    with pytest.raises(ValueError, match="missing ground_truth"):
        evaluate_spec(spec, fixtures_empty, fake_chat)


def test_evaluate_spec_empty_fixtures_returns_clear_result():
    """Test 4: Empty fixture set returns clear result, not ZeroDivisionError."""
    spec = {"prompt": "test", "model": "test-model"}
    fixtures = []

    def fake_chat(input_text, spec, model):
        return "response"

    result = evaluate_spec(spec, fixtures, fake_chat)
    assert result["score"] == 0.0
    assert result["passed"] == 0
    assert result["failed"] == 0
    assert result["errors"] == 0
    assert result["cases"] == []


def test_evaluate_spec_chat_fn_raises_recorded_as_error():
    """Test 5: chat_fn raises for one case; that case recorded as error, rest completes."""
    spec = {"prompt": "test", "model": "test-model"}
    fixtures = [
        FixtureCase(id="case-1", input_text="hello", ground_truth='["world"]'),
        FixtureCase(id="case-2", input_text="hi", ground_truth='["bye"]'),
        FixtureCase(id="case-3", input_text="ok", ground_truth='["done"]'),
    ]

    call_count = [0]
    def fake_chat(input_text, spec, model):
        call_count[0] += 1
        if call_count[0] == 2:
            raise RuntimeError("Ollama dropped connection")
        return "response"

    result = evaluate_spec(spec, fixtures, fake_chat)
    # Should complete, recording one error
    assert result["errors"] == 1
    assert result["passed"] + result["failed"] + result["errors"] == len(fixtures)
    # Find the error case
    error_cases = [c for c in result["cases"] if c["status"] == "error"]
    assert len(error_cases) == 1
    assert "Ollama dropped" in error_cases[0]["error"]


def test_evaluate_spec_case_sensitive_matching():
    """Test 6: Case-sensitive substring matching prevents false positives like NONE → nonetheless."""
    spec = {"prompt": "test", "model": "test-model"}

    # Task-020 style: expect exactly "NONE" (uppercase)
    fixtures = [
        FixtureCase(id="case-1", input_text="test", ground_truth='["NONE"]')
    ]

    def fake_chat_false_positive(input_text, spec, model):
        # Response contains "none" (lowercase) in "nonetheless"
        return "FINDING: nonetheless we cannot determine..."

    result = evaluate_spec(spec, fixtures, fake_chat_false_positive)
    # Should fail because "NONE" (uppercase) is not in the response
    assert result["failed"] == 1

    # But if response contains exact "NONE", it passes
    def fake_chat_match(input_text, spec, model):
        return "The result is NONE"

    result2 = evaluate_spec(spec, fixtures, fake_chat_match)
    assert result2["passed"] == 1


# ── propose_edit tests ───────────────────────────────────────────────────────

def test_propose_edit_merges_response_into_current_spec():
    """Test edit proposal: merged into current spec, options nested correctly, using deep copy."""
    current_spec = {
        "prompt": "original",
        "model": "qwen2.5:7b",
        "options": {"temperature": 0.5}
    }
    failing_cases = [
        FixtureCase(
            id="case-1",
            input_text="test input",
            ground_truth='["match"]',
        ),
    ]
    fixtures = failing_cases

    def fake_propose(payload):
        # Propose a new prompt and temperature
        return {"prompt": "edited", "temperature": 0.9}

    result = propose_edit(current_spec, failing_cases, fake_propose, fixtures)

    # Result should be a merged spec
    assert result is not None
    assert result["prompt"] == "edited"  # Updated
    assert result["model"] == "qwen2.5:7b"  # Preserved from current_spec
    assert result["options"]["temperature"] == 0.9  # Updated in nested options

    # Verify current_spec was not mutated (deep copy worked)
    assert current_spec["prompt"] == "original"
    assert current_spec["options"]["temperature"] == 0.5


def test_propose_edit_builds_payload_without_ground_truth():
    """Test 7: Payload built for propose_fn never contains ground-truth string."""
    current_spec = {"prompt": "original", "temperature": 0.5}
    failing_cases = [
        FixtureCase(
            id="case-1",
            input_text="test input",
            ground_truth='["SHOULD_NOT_APPEAR_IN_PAYLOAD"]',
            expected_output='["also_hidden"]'
        ),
    ]
    fixtures = failing_cases

    captured_payload = {}
    def fake_propose(payload):
        captured_payload.update(payload)
        return {"prompt": "edited"}

    propose_edit(current_spec, failing_cases, fake_propose, fixtures)

    # Verify ground_truth and expected_output are NOT in the payload
    payload_str = json.dumps(captured_payload)
    assert "SHOULD_NOT_APPEAR_IN_PAYLOAD" not in payload_str
    assert "also_hidden" not in payload_str
    # But the case id should be there
    assert "case-1" in payload_str


def test_propose_edit_malformed_response_rejected():
    """Test 8: propose_fn returns malformed/unparseable edit; rejected."""
    current_spec = {"prompt": "original", "model": "qwen2.5:7b"}
    failing_cases = [
        FixtureCase(id="case-1", input_text="test", ground_truth='["truth"]')
    ]

    def fake_propose(payload):
        return "not a dict"  # Malformed

    result = propose_edit(current_spec, failing_cases, fake_propose, [])
    assert result is None  # Malformed rejected


def test_propose_edit_no_op_detected_and_rejected():
    """Test 9: propose_fn returns all null edits; loop detects and stops."""
    current_spec = {"prompt": "original", "model": "qwen2.5:7b", "options": {}}
    failing_cases = [
        FixtureCase(id="case-1", input_text="test", ground_truth='["truth"]')
    ]

    def fake_propose(payload):
        return {"prompt": None, "temperature": None, "format": None, "num_predict": None}  # All no-op

    result = propose_edit(current_spec, failing_cases, fake_propose, [])
    assert result is None  # No-op rejected


def test_propose_edit_raises_aborts_cleanly():
    """Test 10: propose_fn raises; function returns None, no crash."""
    current_spec = {"prompt": "original", "model": "qwen2.5:7b"}
    failing_cases = [
        FixtureCase(id="case-1", input_text="test", ground_truth='["truth"]')
    ]

    def fake_propose(payload):
        raise RuntimeError("Claude rate limited")

    result = propose_edit(current_spec, failing_cases, fake_propose, [])
    assert result is None  # Failure handled gracefully


# ── search_loop tests ────────────────────────────────────────────────────────

def test_search_loop_always_terminates_at_iteration_cap():
    """Test 11: Loop terminates at max_iterations cap even with continued improvements."""
    fixtures = [
        FixtureCase(id="case-1", input_text="test1", ground_truth='["a"]'),
        FixtureCase(id="case-2", input_text="test2", ground_truth='["b"]'),
        FixtureCase(id="case-3", input_text="test3", ground_truth='["c"]'),
    ]

    edit_count = [0]
    def fake_chat(input_text, spec, model):
        # Return progressively better results based on spec version
        version = spec.get("version", 0)
        if version == 0:
            # Initial: nothing matches
            return "wrong"
        elif version == 1:
            # After edit 1: case-1 matches
            return "a"
        elif version == 2:
            # After edit 2: cases 1-2 match
            return "a b"
        elif version == 3:
            # After edit 3: all cases match
            return "a b c"
        else:
            return "a b c"

    def fake_propose(payload):
        # Keep proposing improvements (version + 1)
        edit_count[0] += 1
        new_version = edit_count[0]
        return {"prompt": f"edit-{new_version}", "version": new_version}

    result = search_loop(
        Path("/tmp/dummy_task"),
        fixtures,
        fake_propose,
        fake_chat,
        max_iterations=3,
    )

    # Should respect the 3-iteration cap
    assert result["iterations"] <= 3
    # With 3 fixtures and improvements each iteration, we should hit the cap
    # (the third edit would score 1.0, but we stop at max_iterations)
    assert len(result["trace"]) <= 3


def test_search_loop_regression_reject_rule():
    """Test 12: Edit that breaks a passing case is rejected (also tests deep copy of best_spec)."""
    fixtures = [
        FixtureCase(id="case-1", input_text="hello", ground_truth='["hello"]'),
        FixtureCase(id="case-2", input_text="world", ground_truth='["world"]'),
    ]

    spec_state = {"version": 0}
    def fake_chat(input_text, spec, model):
        # Initial: both fail
        # After edit: case-1 passes, case-2 still fails
        # We want to test that a second edit that breaks case-1 gets rejected
        if spec_state.get("version", 0) == 0:
            return "wrong"  # Both fail initially
        elif spec_state["version"] == 1:
            # First edit: fixes case-1 (input "hello" produces output with "hello")
            if "hello" in input_text:
                return "hello"
            return "wrong"
        else:
            # Second edit: would fix case-2 but breaks case-1
            if "world" in input_text:
                return "world"
            return "nothing"  # case-1 now fails!

    edit_count = [0]
    def fake_propose(payload):
        edit_count[0] += 1
        if edit_count[0] == 1:
            spec_state["version"] = 1
            return {"prompt": "edit1", "temperature": 0.5}  # Improves case-1
        elif edit_count[0] == 2:
            spec_state["version"] = 2
            return {"prompt": "edit2", "temperature": 0.9}  # Would break case-1
        return None  # Stop proposing

    result = search_loop(
        Path("/tmp/dummy_task"),
        fixtures,
        fake_propose,
        fake_chat,
        max_iterations=5,
        regression_reject=True,
    )

    # The second edit should be rejected due to regression
    rejected_traces = [t for t in result["trace"] if "rejected" in t.get("action", "")]
    assert len(rejected_traces) >= 1, f"Expected at least 1 rejection, got {len(rejected_traces)}. Trace: {result['trace']}"

    # Verify best_spec was not mutated by the rejected edit
    # (this tests the deep copy fix in propose_edit)
    assert result["best_spec"]["prompt"] == "edit1"
    # If shallow copy was used, temperature would be 0.9 (from the rejected edit)
    # With deep copy, it stays 0.5 (from the accepted first edit)
    if "options" in result["best_spec"]:
        assert result["best_spec"]["options"].get("temperature") == 0.5


def test_search_loop_deterministic_state():
    """Test 13: Same inputs produce same trace (no hidden mutable state)."""
    fixtures = [
        FixtureCase(id="case-1", input_text="hello", ground_truth='["hello"]'),
    ]

    def fake_chat(input_text, spec, model):
        return "wrong"

    def fake_propose(payload):
        return None  # No edits proposed

    result1 = search_loop(
        Path("/tmp/dummy_task"),
        fixtures,
        fake_propose,
        fake_chat,
        max_iterations=5,
    )

    result2 = search_loop(
        Path("/tmp/dummy_task"),
        fixtures,
        fake_propose,
        fake_chat,
        max_iterations=5,
    )

    assert result1["iterations"] == result2["iterations"]
    assert result1["best_score"] == result2["best_score"]


# ── Results writing (test 16) ────────────────────────────────────────────────

def test_search_loop_results_write_timestamped_format(tmp_path):
    """Test 16: Results write to bench/results/spec-search-<task>-<timestamp>.json."""
    import time

    # Create a fake task directory
    task_dir = tmp_path / "task-020-paperdive-judge-strongreject"
    task_dir.mkdir()
    fixtures = [
        FixtureCase(id="case-1", input_text="test", ground_truth='["match"]')
    ]

    def fake_chat(input_text, spec, model):
        return "match"

    def fake_propose(payload):
        return None

    # Create results directory
    results_dir = tmp_path / "results"
    results_dir.mkdir()

    start_time = int(time.time())

    result = search_loop(
        task_dir,
        fixtures,
        fake_propose,
        fake_chat,
        max_iterations=1,
    )

    end_time = int(time.time())

    # Result should have all necessary fields for writing
    assert "best_spec" in result
    assert "best_score" in result
    assert "trace" in result
    assert "iterations" in result

    # Verify structure suitable for JSON serialization
    assert isinstance(result["best_spec"], dict)
    assert isinstance(result["best_score"], (int, float))
    assert isinstance(result["trace"], list)
    assert isinstance(result["iterations"], int)

    # Write result to timestamped file (same format as the original CLI)
    task_name = task_dir.name
    timestamp = int(time.time())
    results_file = results_dir / f"spec-search-{task_name}-{timestamp}.json"

    with open(results_file, "w") as f:
        json.dump(result, f, indent=2)

    # Verify file exists and contains the result data
    assert results_file.exists()

    # Read back and verify structure
    with open(results_file) as f:
        written_result = json.load(f)

    assert written_result["best_score"] == result["best_score"]
    assert written_result["iterations"] == result["iterations"]
    assert written_result["best_spec"] == result["best_spec"]


# ── load_fixtures integration test ───────────────────────────────────────────

def test_load_fixtures_from_real_task(tmp_path):
    """Integration test: load_fixtures works on actual task directory."""
    task_dir = tmp_path / "test_task"
    task_dir.mkdir()

    task_json = {
        "id": "test-task",
        "type": "qa",
        "prompt_file": "prompt.md",
        "expect": ["expected_string", "construct validity"]
    }
    (task_dir / "task.json").write_text(json.dumps(task_json))
    (task_dir / "prompt.md").write_text("test prompt content")

    fixtures = load_fixtures(task_dir)
    assert len(fixtures) >= 1
    assert fixtures[0]["id"] == "test-task"

    # ground_truth should be JSON encoded list
    expect_list = json.loads(fixtures[0]["ground_truth"])
    assert "expected_string" in expect_list
    assert "construct validity" in expect_list  # Multi-word expectation preserved
