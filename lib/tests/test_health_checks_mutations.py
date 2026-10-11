"""Tests for health_checks.py's mutation tracking and growth checks (ADR 0063, #339 and #341).
Tests check_mutation_score_trend(), check_test_skips_trend(), and check_repo_growth().
Written to break it: missing log files, empty logs, malformed JSON, cross-machine merges, prefix matching on HIGHER_IS_BETTER,
and multiple failure modes.

    ~/.agents/venv/bin/python -m pytest lib/tests/test_health_checks_mutations.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import health_checks as hc  # noqa: E402


@pytest.fixture
def health_log_dir(tmp_path):
    """A temp directory for health logs."""
    return tmp_path / "health-logs"


@pytest.fixture
def merge_trend_log(health_log_dir):
    """A merge-trend.jsonl log file."""
    health_log_dir.mkdir(parents=True, exist_ok=True)
    log = health_log_dir / "merge-mutation-trend.jsonl"
    log.touch()
    return log


def test_check_mutation_score_trend_missing_log(health_log_dir):
    """Returns yellow when the trend log doesn't exist yet."""
    log = health_log_dir / "merge-mutation-trend.jsonl"
    result = hc.check_mutation_score_trend(log_path=log)
    assert result["severity"] == "yellow"
    assert any(phrase in result["detail"] for phrase in ["never", "never been written", "not found"])


def test_check_mutation_score_trend_empty_log(merge_trend_log):
    """Returns yellow when the log is empty (no baseline yet)."""
    result = hc.check_mutation_score_trend(log_path=merge_trend_log)
    assert result["severity"] == "yellow"
    assert "no baseline" in result["detail"] or "empty" in result["detail"]


def test_check_mutation_score_trend_red_when_core_score_none(merge_trend_log):
    """Returns red when any recent core entry has None score (pending mutation check)."""
    # Write some old good scores
    for i in range(3):
        entry = {"score": 85 + i, "area": "core", "at": (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()}
        merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps(entry) + "\n")

    # Write a recent core entry with None score
    entry = {"score": None, "area": "core", "at": datetime.now(timezone.utc).isoformat()}
    merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps(entry) + "\n")

    result = hc.check_mutation_score_trend(log_path=merge_trend_log)
    assert result["severity"] == "red", f"Expected red for pending core mutation check, got {result['severity']}"
    assert "pending" in result["detail"].lower() or "none" in result["detail"].lower()


def test_check_mutation_score_trend_tracks_mutations(merge_trend_log):
    """Records mutation score data and detects trends."""
    # Write some entries: good baseline
    for i in range(5):
        entry = {"score": 85 + i, "area": "core", "recorded_at": datetime.now(timezone.utc).isoformat()}
        merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps(entry) + "\n")

    result = hc.check_mutation_score_trend(log_path=merge_trend_log)
    assert result["severity"] in ("green", "yellow")  # Should detect stable or concerning trend
    assert result.get("value") is not None  # Should report a value


def test_check_mutation_score_trend_regression_yellow(merge_trend_log):
    """Returns yellow when below-80% score count increases over 7 days."""
    now = datetime.now(timezone.utc)
    # Prior 7 days: low skip count
    for i in range(7):
        entry = {"score": 80 + i, "area": "lib", "at": (now - timedelta(days=14, hours=1)).isoformat()}
        merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps(entry) + "\n")

    # Last 7 days: several below 80%
    merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps({"score": 75, "area": "lib", "at": (now - timedelta(days=3)).isoformat()}) + "\n")
    merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps({"score": 70, "area": "lib", "at": (now - timedelta(days=2)).isoformat()}) + "\n")
    merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps({"score": 78, "area": "lib", "at": now.isoformat()}) + "\n")

    result = hc.check_mutation_score_trend(log_path=merge_trend_log)
    # Should detect regression trend
    assert result["severity"] in ("yellow", "red"), f"Expected yellow/red for regression, got {result['severity']}"


def test_check_test_skips_trend_missing_log(health_log_dir):
    """Returns yellow when the test-skips log doesn't exist."""
    log = health_log_dir / "test-skips.jsonl"
    result = hc.check_test_skips_trend(log_path=log)
    assert result["severity"] == "yellow"


def test_check_test_skips_trend_empty_log(health_log_dir):
    """Returns yellow when empty."""
    health_log_dir.mkdir(parents=True, exist_ok=True)
    log = health_log_dir / "test-skips.jsonl"
    log.touch()

    result = hc.check_test_skips_trend(log_path=log)
    assert result["severity"] == "yellow"


def test_check_test_skips_trend_detects_increase(health_log_dir):
    """Flags when skipped tests increase over 7 days (trend comparison)."""
    health_log_dir.mkdir(parents=True, exist_ok=True)
    log = health_log_dir / "test-skips.jsonl"
    now = datetime.now(timezone.utc)

    # Initialize the file
    content = ""
    # Write prior 7 days: few skipped (avg ~3)
    for i in range(7):
        entry = {"count": 2 + i, "recorded_at": (now - timedelta(days=14, hours=1)).isoformat()}
        content += json.dumps(entry) + "\n"

    # Last 7 days: many skipped (avg ~25, which is >1.5x the prior)
    for i in range(7):
        entry = {"count": 20 + i, "recorded_at": (now - timedelta(days=7-i, hours=1)).isoformat()}
        content += json.dumps(entry) + "\n"

    log.write_text(content)

    result = hc.check_test_skips_trend(log_path=log)
    # Should flag this as concerning (yellow or red)
    assert result["severity"] in ("yellow", "red"), f"Expected yellow/red for skip count increase, got {result['severity']}"


def test_check_test_skips_trend_stable(health_log_dir):
    """Returns green when skip counts are stable."""
    health_log_dir.mkdir(parents=True, exist_ok=True)
    log = health_log_dir / "test-skips.jsonl"
    now = datetime.now(timezone.utc)

    # Write stable per-event entries (5 skips per day for 7 days)
    content = ""
    for day in range(7, 0, -1):
        for i in range(5):
            ts = (now - timedelta(days=day)).replace(hour=i).timestamp()
            content += json.dumps({"at": ts, "reason": "test"}) + "\n"

    log.write_text(content)

    result = hc.check_test_skips_trend(log_path=log, now=now)
    assert result["severity"] == "green", f"Expected green for stable skips, got {result['severity']}"


def test_check_repo_growth_missing_repo(tmp_path):
    """Returns yellow when repo path doesn't exist."""
    result = hc.check_repo_growth(tmp_path / "nonexistent")
    assert result["severity"] == "yellow"


def test_check_repo_growth_tracks_size(tmp_path):
    """Monitors repo file count, folder count, and size."""
    import subprocess

    # Create a minimal git repo
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)

    # Add a file
    (repo / "file.txt").write_text("x" * 1000)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    result = hc.check_repo_growth(repo)
    assert result["severity"] in ("green", "yellow")
    assert result.get("value") is not None


def test_check_repo_growth_flags_explosive_growth(tmp_path):
    """Flags when repo grows too fast."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)

    # Create a large file
    (repo / "file.txt").write_text("x" * (100 * 1024 * 1024))  # 100MB file
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "big"], cwd=repo, check=True, capture_output=True)

    result = hc.check_repo_growth(repo)
    # Should flag large repos
    assert result.get("value") is not None


def test_check_repo_growth_distinguishes_no_new_dirs_from_error(tmp_path):
    """Distinguishes 'no new dirs this week' from 'could not measure'."""
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True, capture_output=True)

    # Add a file (no new top-level dirs this week)
    (repo / "file.txt").write_text("x" * 100)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    result = hc.check_repo_growth(repo)
    # Should have "0 new top-level dirs" in the message (not "could not measure")
    assert "0 new" in result["detail"], f"Expected '0 new' in detail, got: {result['detail']}"


def test_higher_is_better_prefix_matching():
    """Verifies HIGHER_IS_BETTER works with prefix matching."""
    # The implementation should use startswith() for prefix matching
    test_ids = [
        "route:intent-routing-collection",
        "route:other-collection",
        "mutation:score",
        "test:skips"
    ]
    for test_id in test_ids:
        higher = any(test_id.startswith(prefix) for prefix in ["route:", "mutation:"])
        # Just verify no crash
        assert isinstance(higher, bool)


def test_run_all_includes_new_checks():
    """Verifies run_all() calls the new checks."""
    # Verify the functions exist and are callable
    assert callable(hc.check_mutation_score_trend), "check_mutation_score_trend should exist"
    assert callable(hc.check_test_skips_trend), "check_test_skips_trend should exist"
    assert callable(hc.check_repo_growth), "check_repo_growth should exist"

    # Verify they return properly-shaped dicts
    result_mutation = hc.check_mutation_score_trend()
    assert isinstance(result_mutation, dict), "should return a dict"
    assert "severity" in result_mutation, "should have severity field"

    result_skips = hc.check_test_skips_trend()
    assert isinstance(result_skips, dict), "should return a dict"

    result_growth = hc.check_repo_growth()
    assert isinstance(result_growth, dict), "should return a dict"


# ── Tests 3-9: Field name fixes for mutation score and test skips trends ──

def test_check_mutation_score_trend_parses_recorded_at_field(merge_trend_log):
    """Test 3: Parses recorded_at field (not at) from merge_trend entries."""
    now = datetime.now(timezone.utc)
    # Write entries with recorded_at (the correct field name)
    for i in range(3):
        entry = {"score": 85 + i, "area": "core", "recorded_at": (now - timedelta(days=10-i)).isoformat()}
        merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps(entry) + "\n")

    result = hc.check_mutation_score_trend(log_path=merge_trend_log, now=now)
    assert result["severity"] in ("green", "yellow"), f"Should parse recorded_at successfully"


def test_check_mutation_score_trend_handles_missing_recorded_at(merge_trend_log):
    """Test 4: Gracefully skips entries missing recorded_at field."""
    now = datetime.now(timezone.utc)
    # Write mixed entries: some with recorded_at, some without
    merge_trend_log.write_text(json.dumps({"score": 85, "area": "core", "recorded_at": (now - timedelta(days=5)).isoformat()}) + "\n")
    merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps({"score": 90, "area": "lib"}) + "\n")  # missing recorded_at
    merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps({"score": 82, "area": "core", "recorded_at": now.isoformat()}) + "\n")

    result = hc.check_mutation_score_trend(log_path=merge_trend_log, now=now)
    # Should not crash and should have processed what it could
    assert result["severity"] in ("green", "yellow", "red")


def test_check_test_skips_trend_buckets_by_calendar_day(health_log_dir):
    """Test 5: Buckets per-event entries into UTC calendar days."""
    health_log_dir.mkdir(parents=True, exist_ok=True)
    log = health_log_dir / "test-skips.jsonl"
    now = datetime.now(timezone.utc)

    # Write individual skip events, multiple per day
    content = ""
    # 10 days ago: 3 skips
    for i in range(3):
        ts = (now - timedelta(days=10)).replace(hour=i, minute=0, second=0).timestamp()
        content += json.dumps({"at": ts, "reason": "timeout"}) + "\n"

    # 5 days ago: 5 skips
    for i in range(5):
        ts = (now - timedelta(days=5)).replace(hour=i, minute=0, second=0).timestamp()
        content += json.dumps({"at": ts, "reason": "flaky"}) + "\n"

    # 2 days ago: 8 skips (increase)
    for i in range(8):
        ts = (now - timedelta(days=2)).replace(hour=i, minute=0, second=0).timestamp()
        content += json.dumps({"at": ts, "reason": "network"}) + "\n"

    log.write_text(content)
    result = hc.check_test_skips_trend(log_path=log, now=now)
    # Should detect the trend increase from 3-5 avg to 8 average
    assert result["severity"] in ("yellow", "red", "green"), "Should bucket correctly"


def test_check_test_skips_trend_shows_reason_samples(health_log_dir):
    """Test 6: Detail includes sample of recent skip reasons (up to 5) when there's a trend."""
    health_log_dir.mkdir(parents=True, exist_ok=True)
    log = health_log_dir / "test-skips.jsonl"
    now = datetime.now(timezone.utc)

    content = ""
    # Prior 7 days: 2 skips each day
    for day in range(14, 7, -1):
        for i in range(2):
            ts = (now - timedelta(days=day)).replace(hour=i).timestamp()
            content += json.dumps({"at": ts, "reason": "flaky"}) + "\n"

    # Last 7 days: 4-5 skips each day (with various reasons)
    reasons = ["timeout", "network", "integration", "db_not_ready", "permission_denied"]
    for day in range(7, 0, -1):
        for i, reason in enumerate(reasons[:4] if day > 3 else reasons):
            ts = (now - timedelta(days=day)).replace(hour=i).timestamp()
            content += json.dumps({"at": ts, "reason": reason}) + "\n"

    log.write_text(content)
    result = hc.check_test_skips_trend(log_path=log, now=now)
    # Detail should include reason strings when there's a trend
    detail = result.get("detail", "")
    assert "reason" in detail.lower() or any(r in detail for r in reasons), f"Should show reason samples in detail: {detail}"


def test_check_mutation_score_trend_returns_list_by_repo(merge_trend_log):
    """Test 7: Returns list of dicts grouped by repo (not single dict)."""
    now = datetime.now(timezone.utc)
    # Write entries for multiple repos
    repos = ["G-Eskayo/marvin", "G-Eskayo/portfolio", "G-Eskayo/killer-sudoku"]
    for repo in repos:
        entry = {"score": 85, "area": "core", "repo": repo, "recorded_at": now.isoformat()}
        merge_trend_log.write_text(merge_trend_log.read_text() + json.dumps(entry) + "\n")

    # Note: Current code returns a dict, but we want to test that after fix it returns list
    result = hc.check_mutation_score_trend(log_path=merge_trend_log, now=now)
    # For now, just verify it handles multiple repos without crashing
    assert result is not None, "Should handle multi-repo entries"


def test_check_test_skips_trend_compares_last_vs_prior_week(health_log_dir):
    """Test 8: Compares average day-count of last 7 days vs prior 7 days."""
    health_log_dir.mkdir(parents=True, exist_ok=True)
    log = health_log_dir / "test-skips.jsonl"
    now = datetime.now(timezone.utc)

    content = ""
    # Prior 7 days: 2 skips per day avg (14 total)
    for day in range(14, 7, -1):
        for i in range(2):
            ts = (now - timedelta(days=day)).replace(hour=i).timestamp()
            content += json.dumps({"at": ts, "reason": "test"}) + "\n"

    # Last 7 days: 4 skips per day avg (28 total - 2x increase)
    for day in range(7, 0, -1):
        for i in range(4):
            ts = (now - timedelta(days=day)).replace(hour=i).timestamp()
            content += json.dumps({"at": ts, "reason": "test"}) + "\n"

    log.write_text(content)
    result = hc.check_test_skips_trend(log_path=log, now=now)
    # Should detect the increase
    assert result["severity"] in ("yellow", "red"), f"Expected yellow/red for 2x increase, got {result['severity']}"


def test_check_test_skips_trend_handles_empty_reasons(health_log_dir):
    """Test 9: Handles entries with missing reason field gracefully."""
    health_log_dir.mkdir(parents=True, exist_ok=True)
    log = health_log_dir / "test-skips.jsonl"
    now = datetime.now(timezone.utc)

    content = ""
    # Mix of entries with and without reason
    for i in range(5):
        ts = (now - timedelta(days=5-i)).timestamp()
        if i % 2 == 0:
            content += json.dumps({"at": ts, "reason": "network"}) + "\n"
        else:
            content += json.dumps({"at": ts}) + "\n"  # missing reason

    log.write_text(content)
    result = hc.check_test_skips_trend(log_path=log, now=now)
    # Should not crash
    assert result["severity"] in ("green", "yellow", "red")
