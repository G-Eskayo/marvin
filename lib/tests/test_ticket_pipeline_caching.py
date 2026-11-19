"""Tests for ticket_pipeline.py caching of GitHub issue reads.
Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_pipeline_caching.py -v
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ticket_pipeline as tp  # noqa: E402


def test_caches_issues_to_disk(tmp_path, monkeypatch):
    """GitHub issue reads are cached to disk with a timestamp."""
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(tp, "ISSUE_CACHE_PATH", cache_path)

    issues = [{"number": 1, "title": "test", "updatedAt": "2026-01-01T00:00:00Z"}]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))

    result = tp._open_issues("test/repo")

    assert cache_path.exists()
    cached = json.loads(cache_path.read_text())
    assert "test/repo" in cached
    assert cached["test/repo"]["issues"] == issues
    assert "cached_at" in cached["test/repo"]


def test_returns_cached_issues_within_ttl(tmp_path, monkeypatch):
    """Within 5 minutes, cached issues are returned without calling gh."""
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(tp, "ISSUE_CACHE_PATH", cache_path)

    cached_issues = [{"number": 1, "title": "cached"}]
    cache_path.write_text(json.dumps({
        "test/repo": {
            "issues": cached_issues,
            "cached_at": time.time() - 100  # 100 seconds old (within 5-min TTL)
        }
    }))

    call_count = [0]
    def mock_run(*a, **kw):
        call_count[0] += 1
        return SimpleNamespace(returncode=0, stdout=json.dumps([{"number": 2}]), stderr="")

    monkeypatch.setattr(tp.subprocess, "run", mock_run)

    result = tp._open_issues("test/repo")

    assert result == cached_issues
    assert call_count[0] == 0  # gh was never called


def test_refreshes_cached_issues_after_ttl(tmp_path, monkeypatch):
    """After 5 minutes, cached issues are refreshed from GitHub."""
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(tp, "ISSUE_CACHE_PATH", cache_path)

    cached_issues = [{"number": 1, "title": "old"}]
    cache_path.write_text(json.dumps({
        "test/repo": {
            "issues": cached_issues,
            "cached_at": time.time() - 400  # 400 seconds old (older than 5-min TTL)
        }
    }))

    fresh_issues = [{"number": 2, "title": "fresh", "updatedAt": "2026-01-02T00:00:00Z"}]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(fresh_issues), stderr=""))

    result = tp._open_issues("test/repo")

    assert result == fresh_issues
    cached = json.loads(cache_path.read_text())
    assert cached["test/repo"]["issues"] == fresh_issues


def test_handles_missing_updatedat_in_issues(tmp_path, monkeypatch):
    """Issues without updatedAt are still cached properly."""
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(tp, "ISSUE_CACHE_PATH", cache_path)

    issues = [{"number": 1, "title": "no-date"}]  # No updatedAt
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))

    result = tp._open_issues("test/repo")

    assert result == issues
    cached = json.loads(cache_path.read_text())
    # Cache now stores max_updated_at instead of updatedAt
    assert cached["test/repo"]["max_updated_at"] is None


def test_cache_tracks_max_updated_at(tmp_path, monkeypatch):
    """Cache tracks max updatedAt timestamp to detect when issues change."""
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(tp, "ISSUE_CACHE_PATH", cache_path)

    issues = [
        {"number": 1, "title": "first", "updatedAt": "2026-01-01T00:00:00Z"},
        {"number": 2, "title": "second", "updatedAt": "2026-01-02T12:30:00Z"},
    ]
    monkeypatch.setattr(tp.subprocess, "run", lambda *a, **kw: SimpleNamespace(
        returncode=0, stdout=json.dumps(issues), stderr=""))

    result = tp._open_issues("test/repo")

    cached = json.loads(cache_path.read_text())
    assert cached["test/repo"]["max_updated_at"] == "2026-01-02T12:30:00Z"


def test_cache_invalidated_after_claim(tmp_path, monkeypatch):
    """Cache is invalidated after a claim so next fetch gets fresh data."""
    cache_path = tmp_path / "cache.json"
    monkeypatch.setattr(tp, "ISSUE_CACHE_PATH", cache_path)

    # Seed the cache with some issues
    cached_issues = [{"number": 1, "title": "unclaimed"}]
    cache_path.write_text(json.dumps({
        "test/repo": {
            "issues": cached_issues,
            "cached_at": time.time() - 100  # Fresh cache
        }
    }))

    # Mock GitHub calls
    fresh_issues = [{"number": 1, "title": "now claimed", "labels": [{"name": "claimed:test"}]}]
    call_count = [0]
    def mock_run(*a, **kw):
        call_count[0] += 1
        if "issue" in a[0] and "edit" in a[0]:
            # This is the claim call
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        # This is the view call
        return SimpleNamespace(returncode=0, stdout=json.dumps({"labels": []}), stderr="")

    def mock_view(*a, **kw):
        return SimpleNamespace(returncode=0, stdout=json.dumps({"labels": []}), stderr="")

    monkeypatch.setattr(tp.subprocess, "run", mock_run)
    monkeypatch.setattr(tp.ts, "record_stage", lambda *a, **k: None)
    monkeypatch.setattr(tp, "_ensure_board", lambda r: None)

    # Claim a ticket (which should invalidate the cache)
    tp._claim(1, "mac-mini-1", "test ticket", "test/repo", run_id="test-id")

    # Verify cache was invalidated (should be empty for this repo)
    cache = json.loads(cache_path.read_text())
    assert "test/repo" not in cache  # Cache was cleared for this repo


