"""Tests for pr_cost.py (marvin#449).
    ~/.agents/venv/bin/python -m pytest lib/tests/test_pr_cost.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import history_store as hs  # noqa: E402
import pr_cost  # noqa: E402


@pytest.fixture
def db(tmp_path):
    conn = hs.connect(tmp_path / "history.db")
    yield conn
    conn.close()


def _line(i, **extra):
    return json.dumps({"t": 1791498937.0 + i, "caller": "c", "rc": 0, "ms": i, **extra})


def test_merged_tickets_keys_by_the_real_ticket_ref_string(tmp_path):
    """merged_tickets() keys by ticket ref string f'{repo}#{number}' via parse_stage_key()."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    # Create a stage file with a merged ticket
    stage_file = stages_dir / "g-eskayo__marvin-123.json"
    stage_file.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://github.com/G-Eskayo/marvin/pull/456", "timestamp": 1791498937.0},
    ]))

    merged = pr_cost.merged_tickets(stages_dir)
    assert "G-Eskayo/marvin#123" in merged
    assert merged["G-Eskayo/marvin#123"] == 1791498937.0


def test_merged_tickets_dedupes_duplicate_merge_events(tmp_path):
    """merged_tickets() takes the first merged event for each ticket, ignoring later ones."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    # Create a stage file with multiple merge events (shouldn't happen, but be defensive)
    stage_file = stages_dir / "g-eskayo__marvin-456.json"
    stage_file.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://example.com/pr/1", "timestamp": 1791498937.0},
        {"stage": "done", "status": "passed", "detail": "merged: https://example.com/pr/2", "timestamp": 1791498938.0},
    ]))

    merged = pr_cost.merged_tickets(stages_dir)
    assert "G-Eskayo/marvin#456" in merged
    assert merged["G-Eskayo/marvin#456"] == 1791498937.0  # first one


def test_merged_tickets_keys_another_projects_ticket_by_its_own_repo_not_marvins_numbering(tmp_path):
    """Multiple projects with same ticket numbers are keyed separately."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    # Create stage files for two projects, both with ticket #7
    stage_file_1 = stages_dir / "g-eskayo__marvin-7.json"
    stage_file_1.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://example.com/pr/1", "timestamp": 1791498937.0},
    ]))
    stage_file_2 = stages_dir / "g-eskayo__clarity-captions-7.json"
    stage_file_2.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://example.com/pr/2", "timestamp": 1791498938.0},
    ]))

    merged = pr_cost.merged_tickets(stages_dir)
    assert "G-Eskayo/marvin#7" in merged
    assert "G-Eskayo/clarity-captions#7" in merged
    assert len(merged) == 2


def test_merged_tickets_ignores_non_merged_stages(tmp_path):
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    stage_file = stages_dir / "g-eskayo__marvin-789.json"
    stage_file.write_text(json.dumps([
        {"stage": "in-progress", "status": "running", "detail": "working on it"},
        {"stage": "done", "status": "failed", "detail": "failed"},
        {"stage": "done", "status": "passed", "detail": "no merge info"},
    ]))

    merged = pr_cost.merged_tickets(stages_dir)
    assert len(merged) == 0


def test_merged_tickets_handles_missing_directory(tmp_path):
    stages_dir = tmp_path / "nonexistent"
    merged = pr_cost.merged_tickets(stages_dir)
    assert merged == {}


def test_cost_per_merged_pr_joins_launches_by_the_real_ticket_field(db, tmp_path):
    """cost_per_merged_pr() joins on the ticket string field."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    # Set up merged tickets
    stage_file = stages_dir / "g-eskayo__marvin-100.json"
    stage_file.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://github.com/G-Eskayo/marvin/pull/123", "timestamp": 1791498937.0},
    ]))

    # Add launches for this ticket with different models
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1791498937.0, "ticket": "G-Eskayo/marvin#100", "model": "claude-opus-5-5", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.01}),
        json.dumps({"t": 1791498938.0, "ticket": "G-Eskayo/marvin#100", "model": "claude-opus-5-5", "input_tokens": 80, "output_tokens": 40, "cost_usd": 0.02}),
        json.dumps({"t": 1791498939.0, "ticket": "G-Eskayo/marvin#100", "model": "claude-haiku-4-5", "input_tokens": 50, "output_tokens": 25, "cost_usd": 0.001}),
    ])

    # Query costs
    costs = pr_cost.cost_per_merged_pr(db, stages_dir)
    # Should have 1 row: aggregated per ticket
    assert len(costs) == 1

    entry = costs[0]
    assert entry["ticket"] == "G-Eskayo/marvin#100"
    assert entry["rows"] == 3  # all 3 launches
    assert entry["cost_usd"] == pytest.approx(0.031)
    assert entry["paid_cost"] == pytest.approx(0.031)  # all are claude-* models
    assert entry["local_cost"] == pytest.approx(0.0)
    assert "claude-opus-5-5" in entry["tokens_by_model"]
    assert entry["tokens_by_model"]["claude-opus-5-5"]["input"] == 180
    assert entry["tokens_by_model"]["claude-opus-5-5"]["output"] == 90
    assert "claude-haiku-4-5" in entry["tokens_by_model"]
    assert entry["tokens_by_model"]["claude-haiku-4-5"]["input"] == 50
    assert entry["tokens_by_model"]["claude-haiku-4-5"]["output"] == 25


def test_cost_per_merged_pr_returns_one_row_per_ticket_with_paid_and_local_split_and_tokens_by_model(db, tmp_path):
    """cost_per_merged_pr() returns one row per ticket with paid/local split and tokens_by_model."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    stage_file = stages_dir / "g-eskayo__marvin-200.json"
    stage_file.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://example.com/pr/1", "timestamp": 1791498937.0},
    ]))

    # Mixed paid (claude-*) and local (ollama) models
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1.0, "ticket": "G-Eskayo/marvin#200", "model": "claude-opus-5-5", "input_tokens": 100, "output_tokens": 50, "cost_usd": 0.1}),
        json.dumps({"t": 2.0, "ticket": "G-Eskayo/marvin#200", "model": "qwen2.5:14b", "input_tokens": 200, "output_tokens": 100, "cost_usd": 0.0}),
    ])

    costs = pr_cost.cost_per_merged_pr(db, stages_dir)
    assert len(costs) == 1

    entry = costs[0]
    assert entry["ticket"] == "G-Eskayo/marvin#200"
    assert entry["cost_usd"] == pytest.approx(0.1)
    assert entry["paid_cost"] == pytest.approx(0.1)
    assert entry["local_cost"] == pytest.approx(0.0)
    assert entry["tokens_by_model"]["claude-opus-5-5"]["input"] == 100
    assert entry["tokens_by_model"]["qwen2.5:14b"]["input"] == 200


def test_cost_per_merged_pr_returns_empty_when_no_merges(db, tmp_path):
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    # No stage files, so no merged tickets
    hs.load(db, "launches", "d", [json.dumps({"t": 1791498937.0, "ticket": "G-Eskayo/marvin#999", "cost_usd": 0.01})])

    costs = pr_cost.cost_per_merged_pr(db, stages_dir)
    assert costs == []


def test_cost_per_merged_pr_ignores_unmapped_tickets(db, tmp_path):
    """cost_per_merged_pr() filters to only merged tickets."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    # Set up one merged ticket
    stage_file = stages_dir / "g-eskayo__marvin-200.json"
    stage_file.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://github.com/G-Eskayo/marvin/pull/789", "timestamp": 1791498937.0},
    ]))

    # Add launches for both merged and unmerged tickets
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1791498937.0, "ticket": "G-Eskayo/marvin#200", "model": "claude-opus-5-5", "cost_usd": 0.01}),
        json.dumps({"t": 1791498938.0, "ticket": "G-Eskayo/marvin#999", "model": "claude-opus-5-5", "cost_usd": 0.02}),
    ])

    costs = pr_cost.cost_per_merged_pr(db, stages_dir)
    assert len(costs) == 1
    assert costs[0]["ticket"] == "G-Eskayo/marvin#200"
    assert costs[0]["cost_usd"] == pytest.approx(0.01)


def test_a_merged_ticket_with_no_launches_reports_zero_not_omitted(db, tmp_path):
    """A merged ticket with no launches still appears with zero cost."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    # Set up a merged ticket
    stage_file = stages_dir / "g-eskayo__marvin-250.json"
    stage_file.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://example.com/pr/1", "timestamp": 1791498937.0},
    ]))

    # No launches for this ticket
    costs = pr_cost.cost_per_merged_pr(db, stages_dir)
    assert len(costs) == 1
    assert costs[0]["ticket"] == "G-Eskayo/marvin#250"
    assert costs[0]["cost_usd"] == 0.0
    assert costs[0]["rows"] == 0


def test_cost_per_merged_pr_sorts_by_per_pr_cost_descending(db, tmp_path):
    """cost_per_merged_pr() sorts by total per-ticket cost descending."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    # Set up two merged tickets
    stage_file_1 = stages_dir / "g-eskayo__marvin-300.json"
    stage_file_2 = stages_dir / "g-eskayo__marvin-301.json"
    stage_file_1.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://github.com/G-Eskayo/marvin/pull/123", "timestamp": 1791498937.0},
    ]))
    stage_file_2.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://github.com/G-Eskayo/marvin/pull/124", "timestamp": 1791498938.0},
    ]))

    # Ticket 300 has cost from one model, 301 has cost from two that together exceed 300's single-model cost
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1791498937.0, "ticket": "G-Eskayo/marvin#300", "model": "claude-opus-5-5", "cost_usd": 0.08}),
        json.dumps({"t": 1791498938.0, "ticket": "G-Eskayo/marvin#301", "model": "claude-opus-5-5", "cost_usd": 0.03}),
        json.dumps({"t": 1791498939.0, "ticket": "G-Eskayo/marvin#301", "model": "claude-haiku-4-5", "cost_usd": 0.06}),
    ])

    costs = pr_cost.cost_per_merged_pr(db, stages_dir)
    assert len(costs) == 2
    assert costs[0]["ticket"] == "G-Eskayo/marvin#301"  # 0.09 total
    assert costs[1]["ticket"] == "G-Eskayo/marvin#300"  # 0.08 total


def test_cost_per_merged_pr_tolerates_a_malformed_launches_line(db, tmp_path):
    """A non-JSON launches line is silently skipped; valid rows still appear."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    stage_file = stages_dir / "g-eskayo__marvin-350.json"
    stage_file.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://example.com/pr/1", "timestamp": 1791498937.0},
    ]))

    # Load both malformed and valid launches
    hs.load(db, "launches", "d", [
        "{not json",
        json.dumps({"t": 1.0, "ticket": "G-Eskayo/marvin#350", "model": "claude-opus-5-5", "cost_usd": 0.05}),
    ])

    costs = pr_cost.cost_per_merged_pr(db, stages_dir)
    assert len(costs) == 1
    assert costs[0]["ticket"] == "G-Eskayo/marvin#350"
    assert costs[0]["cost_usd"] == pytest.approx(0.05)


def test_cost_per_merged_pr_handles_null_token_counts(db, tmp_path):
    """cost_per_merged_pr() handles missing token fields gracefully."""
    stages_dir = tmp_path / "stages"
    stages_dir.mkdir()

    stage_file = stages_dir / "g-eskayo__marvin-400.json"
    stage_file.write_text(json.dumps([
        {"stage": "done", "status": "passed", "detail": "merged: https://github.com/G-Eskayo/marvin/pull/999", "timestamp": 1791498937.0},
    ]))

    # Add launches without token fields
    hs.load(db, "launches", "d", [
        json.dumps({"t": 1791498937.0, "ticket": "G-Eskayo/marvin#400", "model": "claude-opus-5-5", "cost_usd": 0.01}),
    ])

    costs = pr_cost.cost_per_merged_pr(db, stages_dir)
    assert len(costs) == 1
    assert costs[0]["tokens_by_model"]["claude-opus-5-5"]["input"] == 0
    assert costs[0]["tokens_by_model"]["claude-opus-5-5"]["output"] == 0
