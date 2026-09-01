"""Unit tests for cross_model_report aggregation logic.

Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_cross_model_report.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import pytest
from cross_model_report import (
    load_results, latest_per_task_model, compute_deltas, tier_rollup, _model_to_tier,
    format_markdown_table,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

def make_result_file(
    task: str,
    model: str,
    profiles: dict[str, dict],  # {profile_name: {cost, tokens, score}}
) -> dict:
    """Helper to construct a result file structure."""
    runs = []
    for profile_name, stats in profiles.items():
        runs.append({
            "profile": profile_name,
            "model": model,
            "cost_usd": stats.get("cost", 0.0),
            "total_tokens": stats.get("tokens", 0),
            "correctness": {"score": stats.get("score", 1.0)},
        })
    return {
        "task": task,
        "model": model,
        "runner": "claude",
        "repeat": 1,
        "judge": False,
        "runs": runs,
    }


# ── Tests ──────────────────────────────────────────────────────────────

def test_model_to_tier():
    """Test model ID → tier mapping."""
    assert _model_to_tier("claude-haiku-4-5-20251001") == "Haiku"
    assert _model_to_tier("claude-sonnet-5") == "Sonnet"
    assert _model_to_tier("claude-opus-5") == "Opus"
    assert _model_to_tier("default") == "Sonnet"  # default = sonnet


def test_latest_per_task_model_deduplication():
    """Test dedup to newest run per (task, model, profile)."""
    results = [
        make_result_file(
            "task-001",
            "claude-haiku-4-5-20251001",
            {
                "clean": {"cost": 0.10, "tokens": 1000, "score": 1.0},
                "marvin": {"cost": 0.08, "tokens": 900, "score": 1.0},
            },
        ),
    ]

    latest = latest_per_task_model(results)

    # Should have entries for both clean and marvin
    assert ("task-001", "claude-haiku-4-5-20251001", "clean") in latest
    assert ("task-001", "claude-haiku-4-5-20251001", "marvin") in latest

    clean = latest[("task-001", "claude-haiku-4-5-20251001", "clean")]
    assert clean["cost_usd"] == 0.10
    assert clean["total_tokens"] == 1000
    assert clean["correctness_score"] == 1.0


def test_compute_deltas_single_task_single_model():
    """Test delta computation (marvin - clean) for a single task/model."""
    latest = {
        ("task-001", "claude-haiku-4-5-20251001", "clean"): {
            "task": "task-001",
            "model": "claude-haiku-4-5-20251001",
            "profile": "clean",
            "timestamp": "20260801-120000",
            "cost_usd": 0.10,
            "total_tokens": 1000,
            "correctness_score": 1.0,
        },
        ("task-001", "claude-haiku-4-5-20251001", "marvin"): {
            "task": "task-001",
            "model": "claude-haiku-4-5-20251001",
            "profile": "marvin",
            "timestamp": "20260801-120000",
            "cost_usd": 0.08,
            "total_tokens": 900,
            "correctness_score": 1.0,
        },
    }

    deltas = compute_deltas(latest)

    assert len(deltas) == 1
    delta = deltas[0]
    assert delta["task"] == "task-001"
    assert delta["tier"] == "Haiku"
    assert delta["model"] == "claude-haiku-4-5-20251001"
    assert delta["clean_cost"] == 0.10
    assert delta["marvin_cost"] == 0.08
    assert delta["cost_delta"] == pytest.approx(-0.02)  # marvin - clean = 0.08 - 0.10
    assert delta["clean_tokens"] == 1000
    assert delta["marvin_tokens"] == 900
    assert delta["token_delta"] == -100  # marvin - clean = 900 - 1000
    assert delta["clean_correctness"] == 1.0
    assert delta["marvin_correctness"] == 1.0


def test_compute_deltas_skips_missing_profiles():
    """Test that deltas are skipped if clean or marvin profile is missing."""
    latest = {
        ("task-001", "claude-haiku-4-5-20251001", "clean"): {
            "task": "task-001",
            "model": "claude-haiku-4-5-20251001",
            "profile": "clean",
            "timestamp": "20260801-120000",
            "cost_usd": 0.10,
            "total_tokens": 1000,
            "correctness_score": 1.0,
        },
        # Missing marvin profile
    }

    deltas = compute_deltas(latest)

    # Should skip task-001 because marvin is missing
    assert len(deltas) == 0


def test_tier_rollup_averaging():
    """Test that tier_rollup correctly averages deltas by tier."""
    deltas = [
        {
            "task": "task-001",
            "tier": "Haiku",
            "model": "claude-haiku-4-5-20251001",
            "clean_cost": 0.10,
            "marvin_cost": 0.08,
            "cost_delta": -0.02,
            "clean_tokens": 1000,
            "marvin_tokens": 900,
            "token_delta": -100,
            "clean_correctness": 1.0,
            "marvin_correctness": 1.0,
        },
        {
            "task": "task-002",
            "tier": "Haiku",
            "model": "claude-haiku-4-5-20251001",
            "clean_cost": 0.05,
            "marvin_cost": 0.04,
            "cost_delta": -0.01,
            "clean_tokens": 500,
            "marvin_tokens": 450,
            "token_delta": -50,
            "clean_correctness": 1.0,
            "marvin_correctness": 1.0,
        },
        {
            "task": "task-003",
            "tier": "Sonnet",
            "model": "claude-sonnet-5",
            "clean_cost": 0.20,
            "marvin_cost": 0.21,
            "cost_delta": 0.01,
            "clean_tokens": 2000,
            "marvin_tokens": 2100,
            "token_delta": 100,
            "clean_correctness": 1.0,
            "marvin_correctness": 1.0,
        },
    ]

    rollups = tier_rollup(deltas, ["Haiku", "Sonnet", "Opus"])

    # Haiku: avg of -0.02 and -0.01 = -0.015
    assert rollups["Haiku"]["mean_cost_delta"] == -0.015
    assert rollups["Haiku"]["mean_token_delta"] == -75.0
    assert rollups["Haiku"]["tasks"] == 2

    # Sonnet: avg of 0.01 = 0.01
    assert rollups["Sonnet"]["mean_cost_delta"] == 0.01
    assert rollups["Sonnet"]["mean_token_delta"] == 100.0
    assert rollups["Sonnet"]["tasks"] == 1

    # Opus: not present, should have zero values
    assert rollups["Opus"]["tasks"] == 0


def test_tier_rollup_correctness_delta():
    """Test correctness delta computation in tier_rollup."""
    deltas = [
        {
            "task": "task-001",
            "tier": "Haiku",
            "model": "claude-haiku-4-5-20251001",
            "clean_cost": 0.10,
            "marvin_cost": 0.08,
            "cost_delta": -0.02,
            "clean_tokens": 1000,
            "marvin_tokens": 900,
            "token_delta": -100,
            "clean_correctness": 0.80,  # clean scored 0.80
            "marvin_correctness": 1.0,   # marvin scored 1.0
        },
    ]

    rollups = tier_rollup(deltas, ["Haiku"])

    # correctness_delta = 1.0 - 0.80 = 0.20
    assert rollups["Haiku"]["mean_correctness_delta"] == pytest.approx(0.20)


def test_tier_rollup_monotonic_trend_shrinking():
    """Test trend detection: cost delta shrinking across tiers (hypothesis)."""
    deltas = [
        # Haiku: strong negative cost delta (MARVIN cheaper)
        {
            "task": "task-001",
            "tier": "Haiku",
            "model": "claude-haiku-4-5-20251001",
            "clean_cost": 0.10,
            "marvin_cost": 0.08,
            "cost_delta": -0.02,
            "clean_tokens": 1000,
            "marvin_tokens": 900,
            "token_delta": -100,
            "clean_correctness": 1.0,
            "marvin_correctness": 1.0,
        },
        # Sonnet: weaker negative cost delta
        {
            "task": "task-001",
            "tier": "Sonnet",
            "model": "claude-sonnet-5",
            "clean_cost": 0.20,
            "marvin_cost": 0.195,
            "cost_delta": -0.005,
            "clean_tokens": 2000,
            "marvin_tokens": 1950,
            "token_delta": -50,
            "clean_correctness": 1.0,
            "marvin_correctness": 1.0,
        },
        # Opus: even weaker / nearly zero
        {
            "task": "task-001",
            "tier": "Opus",
            "model": "claude-opus-5",
            "clean_cost": 0.40,
            "marvin_cost": 0.405,
            "cost_delta": 0.005,
            "clean_tokens": 4000,
            "marvin_tokens": 4100,
            "token_delta": 100,
            "clean_correctness": 1.0,
            "marvin_correctness": 1.0,
        },
    ]

    rollups = tier_rollup(deltas, ["Haiku", "Sonnet", "Opus"])

    # Verify the trend: -0.02 → -0.005 → 0.005 (shrinking/increasing towards zero)
    haiku_delta = rollups["Haiku"]["mean_cost_delta"]
    sonnet_delta = rollups["Sonnet"]["mean_cost_delta"]
    opus_delta = rollups["Opus"]["mean_cost_delta"]

    # Haiku should be most negative (strongest advantage)
    assert haiku_delta == -0.02
    # Sonnet should be less negative
    assert sonnet_delta == -0.005
    # Opus should be least negative (weakest advantage, or slightly positive overhead)
    assert opus_delta == 0.005
    # Monotonic trend: each successive tier has higher (less negative) cost delta
    assert haiku_delta <= sonnet_delta <= opus_delta


def test_format_markdown_table():
    """Test markdown table formatting."""
    deltas = [
        {
            "task": "task-001",
            "tier": "Haiku",
            "model": "claude-haiku-4-5-20251001",
            "clean_cost": 0.10,
            "marvin_cost": 0.08,
            "cost_delta": -0.02,
            "clean_tokens": 1000,
            "marvin_tokens": 900,
            "token_delta": -100,
            "clean_correctness": 1.0,
            "marvin_correctness": 1.0,
        },
    ]

    table = format_markdown_table(deltas)
    # Just verify it has the task name and model in it
    assert "task-001" in table
    assert "Haiku" in table
    assert "claude-haiku-4-5-20251001" in table
    assert "1,000" in table or "1000" in table
    assert "-100" in table


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
