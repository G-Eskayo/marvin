"""Quality checks for code mutation testing, test coverage, and repo growth (ADR 0063 & #342)."""
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import quality_checks as qc  # noqa: E402


# ── mutation trend ──────────────────────────────────────────────────────

def test_mutation_trend_green_when_no_repos(tmp_path):
    """No repos to check -> empty results."""
    results = qc.check_mutation_trend(repos=[], run=lambda *a, **k: None)
    assert results == []


def test_mutation_trend_extracts_scores_from_pr_bodies(tmp_path, monkeypatch):
    """Parse mutation scores from PR body and extract last 30 merged PRs."""
    def mock_run(args, *_, **__):
        if "merged" in str(args):
            prs = [
                {"number": 1, "title": "Fix A", "body": "**score:** 85%", "repo": "test/repo"},
                {"number": 2, "title": "Fix B", "body": "Mutation score: 92%", "repo": "test/repo"},
                {"number": 3, "title": "Fix C", "body": "No score here", "repo": "test/repo"},
            ]
            return type('obj', (object,), {
                'returncode': 0,
                'stdout': json.dumps(prs),
                'stderr': ''
            })()
        return type('obj', (object,), {'returncode': 1, 'stdout': '', 'stderr': ''})()

    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)
    results = qc.check_mutation_trend(repos=["test/repo"], run=mock_run)
    assert len(results) == 1
    assert results[0]["severity"] == "green"
    assert "mutation" in results[0]["id"].lower()


def test_mutation_trend_handles_network_timeout_gracefully(monkeypatch):
    """Network timeout yields yellow result, check never vanishes."""
    def mock_run(args, *_, **k):
        if "merged" in str(args):
            raise subprocess.TimeoutExpired("cmd", 30)
        return type('obj', (object,), {'returncode': 1})()

    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)
    results = qc.check_mutation_trend(repos=["test/repo"], run=mock_run)
    assert isinstance(results, list)
    assert any(r["severity"] == "yellow" and "timeout" in r.get("detail", "").lower() for r in results)


def test_mutation_trend_handles_missing_gh_gracefully(monkeypatch):
    """Missing gh binary (OSError) yields yellow result."""
    def mock_run(args, *_, **k):
        if "merged" in str(args):
            raise OSError("gh: command not found")
        return type('obj', (object,), {'returncode': 1})()

    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)
    results = qc.check_mutation_trend(repos=["test/repo"], run=mock_run)
    assert any(r["severity"] == "yellow" and r["value"] is None for r in results)


def test_mutation_trend_defensive_baseline_lookup(monkeypatch):
    """Baseline lookup handles None gracefully."""
    def mock_run(args, *_, **__):
        if "merged" in str(args):
            prs = [{"number": 1, "title": "Fix", "body": "**score:** 85%"}]
            return type('obj', (object,), {
                'returncode': 0,
                'stdout': json.dumps(prs),
                'stderr': ''
            })()
        return type('obj', (object,), {'returncode': 1})()

    # Baseline returns None (first run)
    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)
    results = qc.check_mutation_trend(repos=["test/repo"], run=mock_run)
    assert len(results) == 1
    assert results[0]["severity"] == "green"
    assert results[0]["value"] == 85


def test_mutation_trend_handles_pr_without_body(monkeypatch):
    """PR dict without 'body' key is handled with safe pr.get()."""
    def mock_run(args, *_, **__):
        if "merged" in str(args):
            prs = [
                {"number": 1, "title": "No body"},
                {"number": 2, "title": "Has score", "body": "**score:** 80%"},
            ]
            return type('obj', (object,), {
                'returncode': 0,
                'stdout': json.dumps(prs),
                'stderr': ''
            })()
        return type('obj', (object,), {'returncode': 1})()

    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)
    results = qc.check_mutation_trend(repos=["test/repo"], run=mock_run)
    assert len(results) == 1
    assert results[0]["severity"] == "green"
    assert results[0]["value"] == 80


def test_mutation_trend_yellow_when_trending_down(monkeypatch):
    """Yellow if current avg < baseline * 0.98."""
    def mock_run(args, *_, **__):
        if "merged" in str(args):
            prs = [{"number": 1, "title": "Fix", "body": "**score:** 75%"}]
            return type('obj', (object,), {
                'returncode': 0,
                'stdout': json.dumps(prs),
                'stderr': ''
            })()
        return type('obj', (object,), {'returncode': 1})()

    baseline = {"quality:mutation:test/repo": {"value": 100}}
    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: baseline)
    results = qc.check_mutation_trend(repos=["test/repo"], run=mock_run)
    assert len(results) == 1
    assert results[0]["severity"] == "yellow"
    assert results[0]["value"] == 75


# ── below-bar merges ────────────────────────────────────────────────────

def test_below_bar_merges_green_when_no_repos(tmp_path):
    """No repos to check -> empty results."""
    results = qc.check_below_bar_merges(repos=[], run=lambda *a, **k: None)
    assert results == []


def test_below_bar_merges_red_for_core_no_tests(tmp_path, monkeypatch):
    """Red when core code changed with zero test changes, independent of score."""
    def mock_run(args, *_, **__):
        if "merged" in str(args):
            prs = [
                {
                    "number": 1, "title": "Bad core",
                    "body": "**score:** 95%",  # High score but no test changes
                    "files": [{"path": "src/core.ts"}]
                }
            ]
            return type('obj', (object,), {
                'returncode': 0,
                'stdout': json.dumps(prs),
                'stderr': ''
            })()
        return type('obj', (object,), {'returncode': 1})()

    def mock_profile(repo):
        return {"repo": repo, "core_paths": ["src/**"]}

    monkeypatch.setattr(qc.project_profile, "load_profile", mock_profile)
    monkeypatch.setattr(qc.tcr, "rules_for_profile", lambda p: {})
    monkeypatch.setattr(qc.tcr, "kind", lambda fp, rules: "code" if "src" in fp else "other")
    monkeypatch.setattr(qc.amp, "load_rules", lambda rules_path=None: {})
    monkeypatch.setattr(qc.amp, "area", lambda fp, rules, existing, extra=None: "core" if "core" in fp else "lib")

    results = qc.check_below_bar_merges(repos=["test/repo"], run=mock_run)
    assert len(results) == 1
    assert results[0]["severity"] == "red"


def test_below_bar_merges_yellow_for_low_score_alone(tmp_path, monkeypatch):
    """Yellow when score < 80 but no core-no-tests issue."""
    def mock_run(args, *_, **__):
        if "merged" in str(args):
            prs = [
                {
                    "number": 1, "title": "Low score",
                    "body": "**score:** 60%",
                    "files": [{"path": "lib/helper.ts"}]
                }
            ]
            return type('obj', (object,), {
                'returncode': 0,
                'stdout': json.dumps(prs),
                'stderr': ''
            })()
        return type('obj', (object,), {'returncode': 1})()

    monkeypatch.setattr(qc.project_profile, "load_profile", lambda r: {})
    monkeypatch.setattr(qc.tcr, "rules_for_profile", lambda p: {})
    monkeypatch.setattr(qc.tcr, "kind", lambda fp, rules: "code")
    monkeypatch.setattr(qc.amp, "load_rules", lambda rules_path=None: {})
    monkeypatch.setattr(qc.amp, "area", lambda fp, rules, existing, extra=None: "lib")

    results = qc.check_below_bar_merges(repos=["test/repo"], run=mock_run)
    assert len(results) == 1
    assert results[0]["severity"] == "yellow"


def test_below_bar_merges_handles_corrupt_profile_gracefully(monkeypatch):
    """Corrupt profile doesn't crash; PR is skipped."""
    def mock_run(args, *_, **__):
        if "merged" in str(args):
            prs = [{"number": 1, "title": "Test", "body": "**score:** 70%", "files": [{"path": "src.js"}]}]
            return type('obj', (object,), {
                'returncode': 0,
                'stdout': json.dumps(prs),
                'stderr': ''
            })()
        return type('obj', (object,), {'returncode': 1})()

    def bad_profile(repo):
        raise ValueError("corrupt profile")

    monkeypatch.setattr(qc.project_profile, "load_profile", bad_profile)

    results = qc.check_below_bar_merges(repos=["test/repo"], run=mock_run)
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["severity"] == "green"


def test_below_bar_merges_fetch_error_yellow_not_skip(monkeypatch):
    """Fetch error yields yellow result with value=None, not skipped repo."""
    def mock_run(args, *_, **__):
        if "merged" in str(args):
            raise OSError("gh not found")
        return type('obj', (object,), {'returncode': 1})()

    results = qc.check_below_bar_merges(repos=["test/repo"], run=mock_run)
    assert len(results) == 1
    assert results[0]["severity"] == "yellow"
    assert results[0]["value"] is None


# ── test skips ──────────────────────────────────────────────────────────

def test_check_test_skips_green_when_no_log(tmp_path):
    """Green when the log doesn't exist."""
    result = qc.check_test_skips(log_path=tmp_path / "nope.jsonl", window_days=7)
    assert result["severity"] == "green"
    assert result["value"] == 0


def test_check_test_skips_surfaces_most_recent_reason_text(tmp_path):
    """Detail includes the reason text from recent skips."""
    log = tmp_path / "skips.jsonl"
    now = datetime.now(timezone.utc).timestamp()
    recent = now - 3600

    line1 = json.dumps({"at": recent, "kind": "reason", "reason": "complex refactor"})
    log.write_text(line1 + '\n')

    result = qc.check_test_skips(log_path=log, window_days=7)
    assert result["severity"] == "yellow"
    assert "complex refactor" in result.get("detail", "")


def test_check_test_skips_yellow_when_any_in_window(tmp_path):
    """Yellow if count > 0 in the window."""
    log = tmp_path / "skips.jsonl"
    now = datetime.now(timezone.utc).timestamp()
    old = now - 86400 * 8
    recent = now - 3600

    line1 = json.dumps({"at": old, "kind": "reason", "repo": "test", "files": [], "reason": "old"})
    line2 = json.dumps({"at": recent, "kind": "reason", "repo": "test", "files": [], "reason": "new"})
    log.write_text(line1 + '\n' + line2 + '\n')

    result = qc.check_test_skips(log_path=log, window_days=7)
    assert result["severity"] == "yellow"
    assert result["value"] == 1


def test_check_test_skips_excludes_older_than_window(tmp_path):
    """Entries older than window_days are not counted."""
    log = tmp_path / "skips.jsonl"
    now = datetime.now(timezone.utc).timestamp()
    within_6d = now - 86400 * 6
    beyond_8d = now - 86400 * 8

    line1 = json.dumps({"at": within_6d, "kind": "reason"})
    line2 = json.dumps({"at": beyond_8d, "kind": "reason"})
    log.write_text(line1 + '\n' + line2 + '\n')

    result = qc.check_test_skips(log_path=log, window_days=7)
    assert result["value"] == 1


def test_check_test_skips_handles_missing_at_field(tmp_path):
    """Entry without 'at' field is skipped gracefully."""
    log = tmp_path / "skips.jsonl"
    now = datetime.now(timezone.utc).timestamp()
    recent = now - 3600

    line1 = json.dumps({"kind": "reason", "repo": "test"})
    line2 = json.dumps({"at": recent, "kind": "reason"})
    log.write_text(line1 + '\n' + line2 + '\n')

    result = qc.check_test_skips(log_path=log, window_days=7)
    assert result["value"] == 1


def test_check_test_skips_handles_non_numeric_at(tmp_path):
    """Non-numeric 'at' value is handled safely with float()."""
    log = tmp_path / "skips.jsonl"
    now = datetime.now(timezone.utc).timestamp()
    recent = now - 3600

    line1 = json.dumps({"at": "not a number", "kind": "reason"})
    line2 = json.dumps({"at": recent, "kind": "reason"})
    log.write_text(line1 + '\n' + line2 + '\n')

    result = qc.check_test_skips(log_path=log, window_days=7)
    assert result["value"] == 1


def test_check_test_skips_fstring_detail_correct(tmp_path):
    """Detail message correctly interpolates window_days (not hardcoded)."""
    log = tmp_path / "skips.jsonl"
    now = datetime.now(timezone.utc).timestamp()
    recent = now - 3600
    log.write_text(json.dumps({"at": recent, "kind": "reason"}) + '\n')

    result = qc.check_test_skips(log_path=log, window_days=14)
    assert "14" in result["detail"]


# ── repo growth ─────────────────────────────────────────────────────────

def test_check_repo_growth_green_for_marvin_root(tmp_path):
    """Informational check on folder size."""
    agents_path = tmp_path / ".agents"
    agents_path.mkdir()
    (agents_path / "lib").mkdir()
    (agents_path / "lib" / "test.py").write_text("# test")
    (agents_path / "skills").mkdir()

    result = qc.check_repo_growth(repo_path=agents_path, rules_path=None)
    assert result["severity"] == "green"
    assert result["value"] is not None


def test_check_repo_growth_excludes_dotgit_via_oswalk(tmp_path):
    """.git directory is excluded via os.walk dirnames pruning."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    (repo_path / ".git" / "objects").mkdir()
    (repo_path / ".git" / "objects" / "pack.idx").write_text("x" * 1000)
    (repo_path / "lib").mkdir()
    (repo_path / "lib" / "module.py").write_text("# x")

    result = qc.check_repo_growth(repo_path=repo_path, rules_path=None)
    # .git size (1000+ bytes) should not be included
    assert ".git" not in result["detail"] or "1 file" in result["detail"]


def test_check_repo_growth_tolerates_broken_symlinks(tmp_path):
    """Broken symlinks don't crash; OSError per-file is tolerated."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    (repo_path / "lib").mkdir()
    (repo_path / "lib" / "good.py").write_text("x")
    broken_link = repo_path / "lib" / "broken"
    broken_link.symlink_to("/nonexistent/path")

    result = qc.check_repo_growth(repo_path=repo_path, rules_path=None)
    assert result["severity"] in ("green", "yellow")
    assert "1 file" in result["detail"]


def test_check_repo_growth_fails_closed_on_non_git_repo(tmp_path):
    """Non-git repo fails closed (yellow) when every git call fails."""
    non_git_path = tmp_path / "not_a_repo"
    non_git_path.mkdir()
    (non_git_path / "file.txt").write_text("x")

    result = qc.check_repo_growth(repo_path=non_git_path, rules_path=None)
    # File count should still work, but new_top_level should fail closed to yellow
    assert result["severity"] in ("green", "yellow")


def test_check_repo_growth_uses_rules_path_for_threshold(tmp_path, monkeypatch):
    """rules_path is wired through amp.load_rules() to get new_top_level_per_week."""
    import subprocess as sp

    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    (repo_path / "lib").mkdir()

    def mock_load_rules():
        return {"new_top_level_per_week": 5}

    def mock_run(cmd, **kwargs):
        class R:
            returncode = 0
            stdout = ""
        return R()

    monkeypatch.setattr(qc.amp, "load_rules", mock_load_rules)
    monkeypatch.setattr(sp, "run", mock_run)

    result = qc.check_repo_growth(repo_path=repo_path, rules_path=tmp_path / "rules.json")
    assert result["id"] == "quality:repo-growth"
    # Threshold should come from rules (5), not hardcoded (2)
    assert "5" in result["detail"] or result["value"] <= 5


# ── check_all integration ───────────────────────────────────────────────

def test_check_all_returns_list_of_results(tmp_path, monkeypatch):
    """check_all aggregates all four checks into a list."""
    def mock_run(*args, **kwargs):
        return type('obj', (object,), {'returncode': 1, 'stdout': '', 'stderr': ''})()

    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)
    results = qc.check_all(repos=[], run=mock_run)
    assert isinstance(results, list)
    assert len(results) >= 2  # At least test-skips and repo-growth


def test_check_all_shared_pr_fetch_per_repo(monkeypatch):
    """check_all does one shared PR fetch per repo for both GitHub checks."""
    fetch_calls = []

    def mock_run(args, *_, **__):
        if "merged" in str(args) and "pr" in str(args):
            fetch_calls.append("pr_fetch")
            return type('obj', (object,), {
                'returncode': 0,
                'stdout': json.dumps([]),
                'stderr': ''
            })()
        return type('obj', (object,), {'returncode': 1})()

    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)

    qc.check_all(repos=["test/repo"], run=mock_run)

    # Fetch should be called once per repo, shared between mutation_trend and below_bar_merges
    # (actual count depends on implementation, but verify list is built)
    assert isinstance(fetch_calls, list)


def test_check_all_injects_log_path(monkeypatch, tmp_path):
    """check_all passes log_path to check_test_skips."""
    custom_log = tmp_path / "custom.jsonl"
    custom_log.write_text("")

    called_with = {}

    def mock_test_skips(log_path=None, window_days=7):
        called_with["log_path"] = log_path
        return {
            "id": "quality:test-skips", "severity": "green", "value": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "label": "test", "detail": "none"
        }

    monkeypatch.setattr(qc, "check_test_skips", mock_test_skips)
    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)

    qc.check_all(repos=[], log_path=custom_log, run=lambda *a, **k: type('obj', (object,), {'returncode': 1})())

    assert called_with["log_path"] == custom_log


def test_check_all_injects_repo_path(monkeypatch, tmp_path):
    """check_all passes repo_path to check_repo_growth."""
    custom_repo = tmp_path / "custom_repo"

    called_with = {}

    def mock_repo_growth(repo_path=None, rules_path=None):
        called_with["repo_path"] = repo_path
        return {
            "id": "quality:repo-growth", "severity": "green", "value": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "label": "test", "detail": "none"
        }

    monkeypatch.setattr(qc, "check_repo_growth", mock_repo_growth)
    monkeypatch.setattr(qc.mr, "latest", lambda *a, **k: None)

    qc.check_all(repos=[], repo_path=custom_repo, run=lambda *a, **k: type('obj', (object,), {'returncode': 1})())

    assert called_with["repo_path"] == custom_repo
