"""Tests for cleanup_sweep.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_cleanup_sweep.py -v
"""
from __future__ import annotations
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import cleanup_sweep as cs  # noqa: E402


NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).isoformat().replace("+00:00", "Z")


def _issue(number, labels, updated_hours_ago):
    return {"number": number, "labels": [{"name": l} for l in labels], "updatedAt": _iso(updated_hours_ago)}


@pytest.fixture
def log_path(tmp_path, monkeypatch):
    p = tmp_path / "mr-pipeline-sweep.md"
    monkeypatch.setattr(cs, "OUTPUT_PATH", p)
    return p


# ── stale claim detection ────────────────────────────────────────────────────

def test_finds_claim_stale_past_threshold():
    stale = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=30)],
        now=NOW,
    )
    assert len(stale) == 1
    assert stale[0]["issue_number"] == 7
    assert stale[0]["machine_id"] == "mac-mini"


def test_does_not_flag_claim_under_threshold():
    stale = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=2)],
        now=NOW,
    )
    assert stale == []


def test_threshold_boundary_is_exclusive():
    # exactly at threshold -- not yet stale
    at_threshold = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=24)],
        now=NOW,
    )
    assert at_threshold == []

    just_over = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=24.01)],
        now=NOW,
    )
    assert len(just_over) == 1


def test_ignores_issues_with_no_claim_label():
    stale = cs.find_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["ready-for-agent"], updated_hours_ago=100)],
        now=NOW,
    )
    assert stale == []


def test_sweep_stale_claims_releases_via_existing_primitive():
    import ticket_claim
    released = []
    result = cs.sweep_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=48)],
        release=lambda n, m: released.append((n, m)),
        now=NOW,
    )
    assert released == [(7, "mac-mini")]
    assert result == [{"issue_number": 7, "machine_id": "mac-mini", "age_hours": 48}]


def test_sweep_stale_claims_default_release_is_ticket_claims_release(monkeypatch):
    import ticket_claim
    calls = []
    monkeypatch.setattr(ticket_claim, "release", lambda n, m, **kw: calls.append((n, m)))
    cs.sweep_stale_claims(
        threshold_hours=24,
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=48)],
        now=NOW,
    )
    assert calls == [(7, "mac-mini")]


# ── orphaned worktree detection ─────────────────────────────────────────────

def test_finds_worktree_with_no_matching_open_claim(tmp_path):
    wt = tmp_path / "pipeline-g-eskayo-marvin-7"
    wt.mkdir()
    orphans = cs.find_orphaned_worktrees(
        list_worktrees=lambda: [(wt, "pipeline/g-eskayo/marvin#7")],
        list_claimed_open_issues=lambda: [],  # nothing currently claimed/open
    )
    assert orphans == [wt]


def test_does_not_flag_worktree_with_active_claim(tmp_path):
    wt = tmp_path / "pipeline-g-eskayo-marvin-7"
    wt.mkdir()
    orphans = cs.find_orphaned_worktrees(
        list_worktrees=lambda: [(wt, "pipeline/g-eskayo/marvin#7")],
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=1)],
    )
    assert orphans == []


def test_extracts_issue_number_regardless_of_case_folding():
    assert cs._extract_issue_number("pipeline/g-eskayo/marvin#7") == 7
    assert cs._extract_issue_number("pipeline/some-other-thing#123") == 123
    assert cs._extract_issue_number("not-a-pipeline-branch") is None


def test_sweep_orphaned_worktrees_removes_worktree_and_branch(tmp_path):
    wt = tmp_path / "pipeline-g-eskayo-marvin-7"
    wt.mkdir()
    removed = []
    result = cs.sweep_orphaned_worktrees(
        list_worktrees=lambda: [(wt, "pipeline/g-eskayo/marvin#7")],
        list_claimed_open_issues=lambda: [],
        remove_worktree=lambda path, branch: removed.append((path, branch)),
    )
    assert removed == [(wt, "pipeline/g-eskayo/marvin#7")]
    assert result == [wt]


def test_does_not_remove_worktree_with_active_claim(tmp_path):
    wt = tmp_path / "pipeline-g-eskayo-marvin-7"
    wt.mkdir()
    removed = []
    cs.sweep_orphaned_worktrees(
        list_worktrees=lambda: [(wt, "pipeline/g-eskayo/marvin#7")],
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=1)],
        remove_worktree=lambda path, branch: removed.append((path, branch)),
    )
    assert removed == []


# ── logging (visibility standard matching cron_health.py) ──────────────────

def test_run_daily_sweep_writes_log(log_path, tmp_path):
    wt = tmp_path / "pipeline-g-eskayo-marvin-9"
    wt.mkdir()
    cs.run_daily_sweep(
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=48)],
        list_worktrees=lambda: [(wt, "pipeline/g-eskayo/marvin#9")],
        release=lambda n, m: None,
        remove_worktree=lambda path, branch: None,
        now=NOW,
    )
    assert log_path.exists()
    content = log_path.read_text()
    assert "7" in content
    assert "mac-mini" in content


def test_run_daily_sweep_logs_nothing_removed_when_all_clean(log_path):
    cs.run_daily_sweep(
        list_claimed_open_issues=lambda: [],
        list_worktrees=lambda: [],
        now=NOW,
    )
    assert log_path.exists()
    assert "nothing" in log_path.read_text().lower() or "no stale" in log_path.read_text().lower()


def test_run_daily_sweep_returns_summary_dict(log_path, tmp_path):
    result = cs.run_daily_sweep(
        list_claimed_open_issues=lambda: [_issue(7, ["claimed:mac-mini"], updated_hours_ago=48)],
        list_worktrees=lambda: [],
        release=lambda n, m: None,
        now=NOW,
    )
    assert result["stale_claims_released"] == 1
    assert result["orphaned_worktrees_removed"] == 0
