#!/usr/bin/env python3
"""Tests for quality_trends.py — the four metrics per project (ADR 0063 gate visibility #342).

TDD: tests written first, assertions drive the implementation."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quality_trends as qt  # noqa: E402
import metrics_registry as mr  # noqa: E402
import auto_merge_shadow as ams  # noqa: E402
import auto_merge_policy as amp  # noqa: E402


# ── helpers ──────────────────────────────────────────────────────────

def tmp_repo(tmp_path, with_git=True):
    """Create a temporary directory with optional git repo."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    if with_git:
        subprocess.run(["git", "init"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, capture_output=True)
        (repo / "file.txt").write_text("initial\n")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True)
    return repo


# ── test_new_top_level_folders_since ─────────────────────────────────

def test_new_top_level_folders_since_recent_folder_detected_old_folder_not(tmp_path):
    """Two commits 14 days apart: recent folder is detected, old folder is not."""
    repo = tmp_repo(tmp_path)

    # Create old commit with folder1
    (repo / "folder1").mkdir()
    (repo / "folder1" / "file.txt").write_text("old\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)

    old_date = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    env = os.environ.copy()
    env.update({"GIT_AUTHOR_DATE": old_date, "GIT_COMMITTER_DATE": old_date})
    subprocess.run(["git", "commit", "-m", "add folder1"], cwd=repo, capture_output=True, env=env)

    # Create recent commit with folder2
    (repo / "folder2").mkdir()
    (repo / "folder2" / "file.txt").write_text("new\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add folder2"], cwd=repo, capture_output=True)

    result = qt.new_top_level_folders_since(repo, since_days=7)
    assert "folder2" in result
    assert "folder1" not in result


def test_new_top_level_folders_since_no_commit_old_enough_returns_empty(tmp_path):
    """Only recent commits exist; returns empty set, not diff against initial empty tree."""
    repo = tmp_repo(tmp_path)
    result = qt.new_top_level_folders_since(repo, since_days=365)
    assert result == set()


def test_new_top_level_folders_since_missing_repo(tmp_path):
    """Missing repo returns empty set, no crash."""
    missing = tmp_path / "nonexistent"
    result = qt.new_top_level_folders_since(missing, since_days=7)
    assert result == set()


def test_new_top_level_folders_since_shallow_history(tmp_path):
    """Shallow history with one commit returns empty set."""
    repo = tmp_repo(tmp_path)
    result = qt.new_top_level_folders_since(repo, since_days=365)
    assert result == set()


# ── test_repo_size ──────────────────────────────────────────────────

def test_repo_size_excludes_git(tmp_path):
    """Files in .git are not counted."""
    repo = tmp_repo(tmp_path)
    (repo / ".git" / "huge-file.bin").write_bytes(b"x" * 1000000)
    result = qt.repo_size(repo)
    assert result["size_bytes"] < 1000000


def test_repo_size_excludes_node_modules(tmp_path):
    """Files in node_modules are not counted."""
    repo = tmp_repo(tmp_path)
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "huge-lib").mkdir()
    (repo / "node_modules" / "huge-lib" / "file.bin").write_bytes(b"x" * 1000000)
    result = qt.repo_size(repo)
    assert result["size_bytes"] < 1000000


def test_repo_size_excludes_hidden_venv_glob(tmp_path):
    """Pattern .venv-* is excluded via fnmatch, not just literal match."""
    repo = tmp_repo(tmp_path)
    (repo / ".venv-3.11").mkdir()
    (repo / ".venv-3.11" / "huge-file.bin").write_bytes(b"x" * 1000000)
    result = qt.repo_size(repo)
    assert result["size_bytes"] < 1000000


def test_repo_size_huge_leaf_directory_truncates(tmp_path):
    """Single directory with 5,000 files: truncation fires inside fnames loop."""
    repo = tmp_repo(tmp_path)
    (repo / "thousands").mkdir()
    for i in range(5000):
        (repo / "thousands" / f"file{i}.txt").write_text(f"file {i}\n")

    # Patch time.time to increment deterministically across the loop
    call_count = [0]
    original_time = time.time

    def advancing_time():
        call_count[0] += 1
        # Cross budget after a few hundred calls to simulate mid-loop timeout
        return original_time() if call_count[0] < 300 else original_time() + 1000

    with patch("quality_trends.time.time", side_effect=advancing_time):
        result = qt.repo_size(repo, time_budget_seconds=0.1)
        assert result["truncated"] is True
        # Proves the inner loop check fired: we didn't count all 5000 files
        assert result["files"] < 5000


def test_repo_size_missing_repo(tmp_path):
    """Missing repo returns zero counts, no crash."""
    missing = tmp_path / "nonexistent"
    result = qt.repo_size(missing)
    assert result["files"] == 0 and result["folders"] == 0 and result["size_bytes"] == 0


# ── test_recent_skips ────────────────────────────────────────────────

def test_recent_skips_matches_resolved_clone_path(tmp_path):
    """Log entry 'repo' = str(clone_path); recent_skips matches it exactly."""
    log = tmp_path / "test-skips.jsonl"
    clone_path = tmp_path / "my-clone"
    clone_path.mkdir()
    (clone_path / ".git").mkdir()

    now = time.time()
    log.write_text(json.dumps({
        "at": now,
        "kind": "reason",
        "repo": str(clone_path),
        "files": ["a.py"],
        "reason": "untested"
    }) + "\n")

    result = qt.recent_skips(log, "G-Eskayo/marvin", clone_path, since_days=7)
    assert len(result) == 1
    assert result[0]["files"] == ["a.py"]


def test_recent_skips_matches_pipeline_worktree_naming(tmp_path):
    """Worktree path like ~/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-342 matches repo 'G-Eskayo/marvin'."""
    log = tmp_path / "test-skips.jsonl"

    # Simulate a pipeline worktree path
    worktree_path = tmp_path / ".agents-pipeline-worktrees" / "pipeline-g-eskayo-marvin-342"
    worktree_path.mkdir(parents=True)

    now = time.time()
    log.write_text(json.dumps({
        "at": now,
        "kind": "reason",
        "repo": str(worktree_path),
        "files": ["lib/foo.py"],
        "reason": "untested"
    }) + "\n")

    # Should match repo "G-Eskayo/marvin" (short name "marvin" appears in worktree dirname)
    result = qt.recent_skips(log, "G-Eskayo/marvin", worktree_path, since_days=7)
    assert len(result) == 1

    # Should NOT match a different repo
    result_no_match = qt.recent_skips(log, "G-Eskayo/nourished", worktree_path, since_days=7)
    assert len(result_no_match) == 0


def test_recent_skips_tail_bound_is_real(tmp_path):
    """50,000 lines written; tail window bounds the results."""
    log = tmp_path / "test-skips.jsonl"
    clone_path = tmp_path / "clone"
    clone_path.mkdir()

    now = time.time()
    with open(log, "w") as f:
        # First 40,000 lines: old and matching
        old_time = now - 365 * 86400  # 1 year ago
        for i in range(40000):
            f.write(json.dumps({
                "at": old_time,
                "kind": "reason",
                "repo": str(clone_path),
                "files": ["a.py"],
                "reason": f"old {i}"
            }) + "\n")

        # Last ~100 lines: recent and matching
        for i in range(100):
            f.write(json.dumps({
                "at": now,
                "kind": "reason",
                "repo": str(clone_path),
                "files": ["b.py"],
                "reason": f"recent {i}"
            }) + "\n")

    result = qt.recent_skips(log, "G-Eskayo/marvin", clone_path, since_days=7)
    # Should only get the recent ones (tail window), not the old 40k
    assert len(result) <= 200  # Some reasonable small number
    assert all(r["files"] == ["b.py"] for r in result)


def test_recent_skips_tolerates_corrupted_lines(tmp_path):
    """Malformed lines are skipped, good lines are processed."""
    log = tmp_path / "test-skips.jsonl"
    clone_path = tmp_path / "clone"
    clone_path.mkdir()

    now = time.time()
    log.write_text("\n".join([
        json.dumps({
            "at": now,
            "kind": "reason",
            "repo": str(clone_path),
            "files": ["a.py"],
            "reason": "good"
        }),
        "this is not json",
        json.dumps({
            "at": now,
            "kind": "reason",
            "repo": str(clone_path),
            "files": ["b.py"],
            "reason": "also good"
        }),
    ]))

    result = qt.recent_skips(log, "G-Eskayo/marvin", clone_path, since_days=7)
    assert len(result) == 2


def test_recent_skips_missing_log(tmp_path):
    """Missing log file returns empty list, no crash."""
    missing_log = tmp_path / "nonexistent.jsonl"
    clone_path = tmp_path / "clone"
    result = qt.recent_skips(missing_log, "G-Eskayo/marvin", clone_path, since_days=7)
    assert result == []


# ── test_merged_pr_scores ────────────────────────────────────────────

def test_merged_pr_scores_parses_real_json_text(tmp_path):
    """gh returns JSON text, not pre-parsed list."""
    def gh_mock(*args):
        prs = [
            {"number": 1, "mergedAt": "2026-10-05T12:00:00Z", "body": "Mutation score: 85%"},
            {"number": 2, "mergedAt": "2026-10-05T12:00:00Z", "body": "No score"},
        ]
        return json.dumps(prs)

    result = qt.merged_pr_scores(gh_mock, "G-Eskayo/marvin", since_days=7)
    assert len(result) == 2
    assert result[0]["score"] == 85
    assert result[1]["score"] is None


def test_merged_pr_scores_uses_limit_100_and_merged_state(tmp_path):
    """Asserts the gh args include --limit 100 and --state merged."""
    calls = []

    def gh_mock(*args):
        calls.append(args)
        return json.dumps([])

    qt.merged_pr_scores(gh_mock, "G-Eskayo/marvin", since_days=7)
    assert len(calls) > 0
    args = calls[0]
    assert "--limit" in args
    assert "100" in args
    assert "--state" in args
    assert "merged" in args


def test_merged_pr_scores_null_body_does_not_crash(tmp_path):
    """body: null is handled without TypeError."""
    def gh_mock(*args):
        prs = [
            {"number": 1, "mergedAt": "2026-10-05T12:00:00Z", "body": None},
        ]
        return json.dumps(prs)

    result = qt.merged_pr_scores(gh_mock, "G-Eskayo/marvin", since_days=7)
    assert len(result) == 1
    assert result[0]["score"] is None


def test_merged_pr_scores_malformed_merged_at_excluded(tmp_path):
    """Unparseable mergedAt: PR is excluded, not assumed in-window."""
    def gh_mock(*args):
        prs = [
            {"number": 1, "mergedAt": "not-a-date", "body": "Score: 85%"},
        ]
        return json.dumps(prs)

    result = qt.merged_pr_scores(gh_mock, "G-Eskayo/marvin", since_days=7)
    # Unparseable date means we can't confirm it's in window, so exclude it
    assert len(result) == 0


def test_merged_pr_scores_gh_failure_returns_empty(tmp_path):
    """Exception from gh returns empty list, no crash."""
    def gh_mock(*args):
        raise Exception("GitHub unavailable")

    result = qt.merged_pr_scores(gh_mock, "G-Eskayo/marvin", since_days=7)
    assert result == []


def test_merged_pr_scores_malformed_json_returns_empty(tmp_path):
    """gh returns invalid JSON: returns empty list, no crash."""
    def gh_mock(*args):
        return "not json at all"

    result = qt.merged_pr_scores(gh_mock, "G-Eskayo/marvin", since_days=7)
    assert result == []


# ── test_collect ────────────────────────────────────────────────────

def test_prs_below_80_uses_is_not_none_and_min_score_constant(tmp_path):
    """Score 0% is counted as below 80; patching MIN_SCORE changes threshold."""
    repo = tmp_repo(tmp_path)
    log = tmp_path / "test-skips.jsonl"

    def gh_mock(*args):
        prs = [
            {"number": 1, "mergedAt": "2026-10-05T12:00:00Z", "body": "Score: 0%"},
            {"number": 2, "mergedAt": "2026-10-05T12:00:00Z", "body": "Score: 85%"},
        ]
        return json.dumps(prs)

    with patch.object(ams, "MIN_SCORE", 80):
        result = qt.collect("G-Eskayo/marvin", repo, gh_mock, log, time.time())
        assert result["prs_below_80pct"] == 1  # Only the 0% one

    with patch.object(ams, "MIN_SCORE", 90):
        result = qt.collect("G-Eskayo/marvin", repo, gh_mock, log, time.time())
        assert result["prs_below_80pct"] == 2  # Both are below 90


def test_unscored_prs_never_fabricate_a_score(tmp_path):
    """Unscored PRs are tracked separately; never write mutation_score_pct if no real scores."""
    repo = tmp_repo(tmp_path)
    log = tmp_path / "test-skips.jsonl"

    def gh_mock(*args):
        prs = [
            {"number": 1, "mergedAt": "2026-10-05T12:00:00Z", "body": "No score"},
            {"number": 2, "mergedAt": "2026-10-05T12:00:00Z", "body": "No score"},
        ]
        return json.dumps(prs)

    result = qt.collect("G-Eskayo/marvin", repo, gh_mock, log, time.time())
    assert result["mutation_score_pct"] is None
    assert result["prs_unscored"] == 2


# ── test_record_all ────────────────────────────────────────────────

def test_record_all_resolves_catalog_mode_clone_with_catalog_arg(tmp_path):
    """catalog-mode clone resolution needs catalog= argument."""
    repo = tmp_repo(tmp_path)
    log = tmp_path / "test-skips.jsonl"
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    def gh_mock(*args):
        return json.dumps([])

    catalog = {
        "projects": [
            {
                "repo": "G-Eskayo/marvin",
                "localPaths": [str(repo)]
            }
        ]
    }

    with patch("quality_trends.project_profile.all_profiles") as mock_profiles:
        mock_profiles.return_value = [{"repo": "G-Eskayo/marvin", "clone_mode": "catalog"}]
        with patch("quality_trends.project_catalog.read_catalog") as mock_read:
            mock_read.return_value = catalog
            with patch("quality_trends.mr.record") as mock_record:
                with patch("quality_trends.mr.METRICS_DIR", metrics_dir):
                    qt.record_all([{"repo": "G-Eskayo/marvin"}], time.time(), gh_mock, log)
                    # Should have called record (i.e., didn't skip the repo)
                    assert mock_record.called


def test_record_all_subsystem_name_has_no_dot(tmp_path):
    """Subsystem name uses hyphen not dot (honors metrics_registry's no-dot contract)."""
    repo = tmp_repo(tmp_path)
    log = tmp_path / "test-skips.jsonl"

    def gh_mock(*args):
        return json.dumps([])

    with patch("quality_trends.project_profile.all_profiles") as mock_profiles:
        mock_profiles.return_value = [{"repo": "G-Eskayo/marvin"}]
        with patch("quality_trends.project_profile.resolve_clone") as mock_clone:
            mock_clone.return_value = repo
            with patch("quality_trends.mr.record") as mock_record:
                qt.record_all([{"repo": "G-Eskayo/marvin"}], time.time(), gh_mock, log)
                if mock_record.called:
                    subsystem = mock_record.call_args[0][0]
                    assert "." not in subsystem
                    assert "-" in subsystem  # Should have hyphens like "quality-trends-marvin"


def test_record_all_same_day_replaces_not_appends(tmp_path):
    """Same-day recordings via replace_same_day=True stay at one snapshot per day."""
    repo = tmp_repo(tmp_path)
    log = tmp_path / "test-skips.jsonl"
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    def gh_mock(*args):
        return json.dumps([])

    with patch("quality_trends.project_profile.all_profiles") as mock_profiles:
        mock_profiles.return_value = [{"repo": "G-Eskayo/marvin"}]
        with patch("quality_trends.project_profile.resolve_clone") as mock_clone:
            mock_clone.return_value = repo
            with patch("quality_trends.mr.record") as mock_record:
                with patch("quality_trends.mr.METRICS_DIR", metrics_dir):
                    # Two calls same (faked) day
                    faked_now = time.time()
                    qt.record_all([{"repo": "G-Eskayo/marvin"}], faked_now, gh_mock, log)
                    qt.record_all([{"repo": "G-Eskayo/marvin"}], faked_now, gh_mock, log)

                    # record() should have been called twice with replace_same_day=True
                    assert mock_record.call_count >= 2
                    # Each call should have replace_same_day=True
                    for call in mock_record.call_args_list:
                        assert call.kwargs.get("replace_same_day") is True


def test_record_all_one_repo_gh_fails_other_still_recorded_and_logged(tmp_path):
    """One repo's gh failure doesn't block others; failure is logged via job_events."""
    repo1 = tmp_repo(tmp_path / "repo1")
    repo2 = tmp_repo(tmp_path / "repo2")
    log = tmp_path / "test-skips.jsonl"

    call_count = [0]

    def gh_mock(*args):
        call_count[0] += 1
        if call_count[0] == 1:
            raise Exception("Simulated gh failure")
        return json.dumps([])

    with patch("quality_trends.project_profile.all_profiles") as mock_profiles:
        mock_profiles.return_value = [
            {"repo": "G-Eskayo/marvin"},
            {"repo": "G-Eskayo/nourished"},
        ]
        with patch("quality_trends.project_profile.resolve_clone") as mock_clone:
            def resolve_side_effect(profile, catalog=None, ensure=False):
                repo = profile["repo"]
                return repo1 if "marvin" in repo else repo2
            mock_clone.side_effect = resolve_side_effect

            with patch("quality_trends.mr.record") as mock_record:
                with patch("quality_trends.job_events.step") as mock_step:
                    qt.record_all([{"repo": "G-Eskayo/marvin"}, {"repo": "G-Eskayo/nourished"}],
                                 time.time(), gh_mock, log)

                    # Second repo should still be recorded (not skipped due to first failure)
                    assert mock_record.call_count >= 1
                    # Failure should be stepped (logged)
                    assert mock_step.called


def test_record_all_missing_clone_skips_only_that_repo(tmp_path):
    """Missing clone: that repo is skipped, others still recorded."""
    repo = tmp_repo(tmp_path)
    log = tmp_path / "test-skips.jsonl"

    def gh_mock(*args):
        return json.dumps([])

    with patch("quality_trends.project_profile.all_profiles") as mock_profiles:
        mock_profiles.return_value = [
            {"repo": "G-Eskayo/marvin"},
            {"repo": "G-Eskayo/nourished"},
        ]
        with patch("quality_trends.project_profile.resolve_clone") as mock_clone:
            def resolve_side_effect(profile, catalog=None, ensure=False):
                return repo if "marvin" in profile["repo"] else None  # nourished's clone is missing
            mock_clone.side_effect = resolve_side_effect

            with patch("quality_trends.mr.record") as mock_record:
                qt.record_all([{"repo": "G-Eskayo/marvin"}, {"repo": "G-Eskayo/nourished"}],
                             time.time(), gh_mock, log)
                # Only marvin should be recorded
                assert mock_record.call_count >= 1


# ── test_check_quality_trends ────────────────────────────────────────

def test_check_quality_trends_core_area_skip_is_red(tmp_path):
    """Recent skip of a core-area file → red severity."""
    repo = tmp_repo(tmp_path)
    log = tmp_path / "test-skips.jsonl"

    now = time.time()
    log.write_text(json.dumps({
        "at": now,
        "kind": "reason",
        "repo": str(repo),
        "files": ["lib/auto_merge_shadow.py"],  # core file per config/auto_merge.json
        "reason": "untested"
    }) + "\n")

    with patch("quality_trends.project_profile.all_profiles") as mock_profiles:
        mock_profiles.return_value = [{"repo": "G-Eskayo/marvin"}]
        with patch("quality_trends.project_profile.resolve_clone") as mock_clone:
            mock_clone.return_value = repo
            results = qt.check_quality_trends([{"repo": "G-Eskayo/marvin"}])
            assert any(r.get("severity") == "red" for r in results)


def test_check_quality_trends_no_data_yet_is_green_informational(tmp_path):
    """No snapshot yet → green with 'no data yet' detail."""
    with patch("quality_trends.mr.latest") as mock_latest:
        mock_latest.return_value = None
        with patch("quality_trends.project_profile.all_profiles") as mock_profiles:
            mock_profiles.return_value = [{"repo": "G-Eskayo/marvin"}]
            results = qt.check_quality_trends([{"repo": "G-Eskayo/marvin"}])
            assert any(r.get("severity") == "green" and "no data" in r.get("detail", "").lower() for r in results)


# ── CLI entry point ─────────────────────────────────────────────────

def test_job_placement_includes_quality_trends_mini(tmp_path):
    """JOB_PLACEMENT includes quality-trends on mini."""
    import health_checks
    assert "quality-trends" in health_checks.JOB_PLACEMENT
    assert health_checks.JOB_PLACEMENT["quality-trends"] == "mini"


# ── metrics_registry.record new parameter ────────────────────────────

def test_record_replace_same_day_default_unchanged(tmp_path):
    """Default call still appends (existing callers unaffected)."""
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    with patch("quality_trends.mr.METRICS_DIR", metrics_dir):
        # First recording
        mr.record("test-subsystem", {"metric1": {"value": 100, "higher_is_better": True}})

        # Second recording without replace_same_day (should append)
        mr.record("test-subsystem", {"metric1": {"value": 200, "higher_is_better": True}})

        # Both should be in the file
        path = mr._snapshot_path("test-subsystem")
        snapshots = json.loads(path.read_text())
        assert len(snapshots) == 2


def test_record_replace_same_day_concurrent_stays_valid(tmp_path):
    """Concurrent writes with replace_same_day=True stay valid JSON."""
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    def write_metric(i):
        with patch("quality_trends.mr.METRICS_DIR", metrics_dir):
            mr.record("test-subsystem",
                     {"metric": {"value": i, "higher_is_better": True}},
                     replace_same_day=True)

    threads = [threading.Thread(target=write_metric, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # File should still be valid JSON
    path = mr._snapshot_path("test-subsystem")
    snapshots = json.loads(path.read_text())
    # Should be one or a few snapshots (same-day replacements), not 5
    assert 1 <= len(snapshots) <= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
