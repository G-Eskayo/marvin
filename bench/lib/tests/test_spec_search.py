"""Tests for spec_search.py. Run via:
    ~/.agents/venv/bin/python -m pytest bench/lib/tests/test_spec_search.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from spec_search import SpecSearchEngine, SpecSearchResult


# ── SpecSearchEngine ─────────────────────────────────────────────────────────

def test_spec_search_empty_samples():
    """Raises ValueError if frozen_samples is empty."""
    engine = SpecSearchEngine(
        initial_prompt="test",
        score_fn=lambda p, s: {},
        teacher_fn=lambda p, a, r: ("new", 10),
    )
    with pytest.raises(ValueError, match="empty"):
        engine.run({})


def test_spec_search_score_fn_returns_empty():
    """Raises ValueError if score_fn returns no scores."""
    engine = SpecSearchEngine(
        initial_prompt="test",
        score_fn=lambda p, s: {},
        teacher_fn=lambda p, a, r: ("new", 10),
    )
    with pytest.raises(ValueError, match="no scores"):
        engine.run({"sample1": {}})


def test_spec_search_teacher_fn_fails():
    """Raises RuntimeError if teacher_fn fails."""
    def failing_teacher(p, a, r):
        raise ValueError("teacher error")

    engine = SpecSearchEngine(
        initial_prompt="test",
        score_fn=lambda p, s: {"sample1": 0.5},
        teacher_fn=failing_teacher,
    )
    with pytest.raises(RuntimeError, match="teacher_fn failed"):
        engine.run({"sample1": {}})


def test_spec_search_score_fn_fails():
    """Raises RuntimeError if score_fn fails on a proposal."""
    call_count = [0]
    def failing_score(p, s):
        call_count[0] += 1
        if call_count[0] == 1:
            # First call (initial) succeeds
            return {"sample1": 0.5}
        else:
            # Second call (on proposal) fails
            raise ValueError("score error")

    engine = SpecSearchEngine(
        initial_prompt="test",
        score_fn=failing_score,
        teacher_fn=lambda p, a, r: ("new", 10),
    )
    with pytest.raises(RuntimeError, match="score_fn failed"):
        engine.run({"sample1": {}})


def test_spec_search_no_op_terminates():
    """Search terminates if teacher proposes a no-op (same as current)."""
    engine = SpecSearchEngine(
        initial_prompt="original",
        score_fn=lambda p, s: {"sample1": 0.5},
        teacher_fn=lambda p, a, r: (p, 10),  # Return current prompt unchanged
    )
    final, history = engine.run({"sample1": {}})

    assert final == "original"
    assert len(history) == 1
    assert history[0].proposal == "original"
    assert not history[0].accepted


def test_spec_search_repeated_rejection_terminates():
    """Search terminates if teacher proposes same rejected edit twice."""
    proposals = ["edit1", "edit1"]  # Same proposal twice
    proposal_idx = [0]

    def teacher_fn(p, a, r):
        idx = proposal_idx[0]
        proposal_idx[0] += 1
        return (proposals[idx], 10)

    def score_fn(p, s):
        # edit1 causes regression
        if p == "edit1":
            return {"sample1": 0.3}  # Worse than initial 0.5
        return {"sample1": 0.5}

    engine = SpecSearchEngine(
        initial_prompt="original",
        score_fn=score_fn,
        teacher_fn=teacher_fn,
    )
    final, history = engine.run({"sample1": {}})

    assert final == "original"
    assert len(history) == 2
    assert history[0].proposal == "edit1"
    assert not history[0].accepted
    assert history[1].proposal == "edit1"
    # Second one not scored (just terminated without scoring)
    assert not history[1].accepted


def test_spec_search_accepts_improvement():
    """Search accepts an edit that improves accuracy."""
    proposals = ["edit1"]
    proposal_idx = [0]

    def teacher_fn(p, a, r):
        idx = proposal_idx[0]
        proposal_idx[0] += 1
        if idx < len(proposals):
            return (proposals[idx], 10)
        else:
            return (p, 0)  # No-op to terminate

    def score_fn(p, s):
        if p == "edit1":
            return {"sample1": 1.0}  # Improvement
        return {"sample1": 0.5}

    engine = SpecSearchEngine(
        initial_prompt="original",
        score_fn=score_fn,
        teacher_fn=teacher_fn,
    )
    final, history = engine.run({"sample1": {}})

    assert final == "edit1"
    assert len(history) == 2
    assert history[0].proposal == "edit1"
    assert history[0].accepted
    assert history[1].proposal == "edit1"  # No-op terminates


def test_spec_search_rejects_regression():
    """Search rejects an edit that causes any regression."""
    proposals = ["edit1"]
    proposal_idx = [0]

    def teacher_fn(p, a, r):
        idx = proposal_idx[0]
        proposal_idx[0] += 1
        if idx < len(proposals):
            return (proposals[idx], 10)
        else:
            return (p, 0)  # No-op to terminate

    def score_fn(p, s):
        if p == "edit1":
            # Improve sample1 but regress sample2
            return {"sample1": 1.0, "sample2": 0.3}
        return {"sample1": 0.5, "sample2": 0.7}

    engine = SpecSearchEngine(
        initial_prompt="original",
        score_fn=score_fn,
        teacher_fn=teacher_fn,
    )
    final, history = engine.run({"sample1": {}, "sample2": {}})

    assert final == "original"  # Didn't accept the regression
    assert len(history) == 2
    assert history[0].proposal == "edit1"
    assert not history[0].accepted
    assert "sample2" in history[0].regressions


def test_spec_search_respects_max_rounds():
    """Search terminates after max_rounds even without convergence."""
    def always_propose(p, a, r):
        return ("new_" + p, 10)

    def always_improves(p, s):
        # Every edit slightly improves, so search never auto-terminates
        return {"sample1": len(p) / 100.0}

    engine = SpecSearchEngine(
        initial_prompt="a",
        score_fn=always_improves,
        teacher_fn=always_propose,
        max_rounds=5,
    )
    final, history = engine.run({"sample1": {}})

    assert len(history) == 5


def test_spec_search_result_structure():
    """SpecSearchResult has all expected fields."""
    proposals = ["edit1"]
    proposal_idx = [0]

    def teacher_fn(p, a, r):
        idx = proposal_idx[0]
        proposal_idx[0] += 1
        return (proposals[idx] if idx < len(proposals) else p, 42)

    def score_fn(p, s):
        if p == "edit1":
            return {"sample1": 1.0, "sample2": 1.0}  # Both improve
        return {"sample1": 0.5, "sample2": 0.5}

    engine = SpecSearchEngine(
        initial_prompt="original",
        score_fn=score_fn,
        teacher_fn=teacher_fn,
    )
    final, history = engine.run({"sample1": {}, "sample2": {}})

    result = history[0]
    assert result.round_num == 1
    assert result.proposal == "edit1"
    assert result.accepted is True
    assert isinstance(result.before_scores, dict)
    assert isinstance(result.after_scores, dict)
    assert isinstance(result.regressions, list)
    assert isinstance(result.accuracy_before, float)
    assert isinstance(result.accuracy_after, float)
    assert result.cost_tokens == 42
