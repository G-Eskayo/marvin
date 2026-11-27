"""Tests for health_checks.py (ADR 0033). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_health_checks.py -v
"""
from __future__ import annotations
import json
import subprocess
import pytest
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import cron_health as ch  # noqa: E402
import health_checks as hc  # noqa: E402
import model_registry as mr  # noqa: E402


# ── token files ──────────────────────────────────────────────────────────

def test_check_token_files_flags_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    results = hc.check_token_files()
    assert all(r["severity"] == "red" for r in results)
    assert all("does not exist" in r["detail"] for r in results)


def test_check_token_files_flags_embedded_whitespace(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    td = tmp_path / ".claude"
    td.mkdir()
    (td / ".oauth-token").write_text("abc\ndef")  # embedded newline
    (td / ".gh-token").write_text("xyz")
    results = hc.check_token_files()
    assert results[0]["severity"] == "red"
    assert "embedded whitespace" in results[0]["detail"]
    assert results[1]["severity"] == "green"


def test_check_token_files_flags_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    td = tmp_path / ".claude"
    td.mkdir()
    (td / ".oauth-token").write_text("")  # empty
    (td / ".gh-token").write_text("valid_token_string")
    results = hc.check_token_files()
    assert results[0]["severity"] == "red"
    assert "empty" in results[0]["detail"]
    assert results[1]["severity"] == "green"


def test_check_token_files_green(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    td = tmp_path / ".claude"
    td.mkdir()
    (td / ".oauth-token").write_text("token_abc123")
    (td / ".gh-token").write_text("token_xyz789")
    results = hc.check_token_files()
    assert all(r["severity"] == "green" for r in results)


# ── route.py ChromaDB collection ──────────────────────────────────────────

def test_check_intent_routing_collection_red_when_empty(tmp_path, monkeypatch):
    """The exact failure found live 2026-10-01."""
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    monkeypatch.setattr(hc, "HOME", tmp_path)

    class MockClient:
        def get_or_create_collection(self, name, metadata=None):
            class Col:
                def count(self):
                    return 0  # empty
            return Col()

    class MockChromaDB:
        def PersistentClient(self, path=None):
            return MockClient()

    monkeypatch.setitem(sys.modules, 'chromadb', MockChromaDB())
    result = hc.check_intent_routing_collection()
    assert result["severity"] == "red"
    assert "0 documents" in result["detail"]


def test_check_intent_routing_collection_green_when_populated(tmp_path, monkeypatch):
    chroma_dir = tmp_path / "chroma"
    chroma_dir.mkdir()
    monkeypatch.setattr(hc, "HOME", tmp_path)

    class MockClient:
        def get_or_create_collection(self, name, metadata=None):
            class Col:
                def count(self):
                    return 42
            return Col()

    class MockChromaDB:
        def PersistentClient(self, path=None):
            return MockClient()

    monkeypatch.setitem(sys.modules, 'chromadb', MockChromaDB())
    result = hc.check_intent_routing_collection()
    assert result["severity"] == "green"
    assert "42" in result["detail"]


# ── dispatch lock ────────────────────────────────────────────────────────

def test_check_dispatch_lock_green_when_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    dispatch_path = tmp_path / ".claude" / "dispatch-state.json"
    dispatch_path.parent.mkdir(parents=True)
    dispatch_path.write_text(json.dumps({"busy": False}))
    result = hc.check_dispatch_lock(dispatch_path)
    assert result["severity"] == "green"
    assert "idle" in result["detail"]


def test_check_dispatch_lock_yellow_when_busy_too_long(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    dispatch_path = tmp_path / ".claude" / "dispatch-state.json"
    dispatch_path.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=1)).isoformat()
    dispatch_path.write_text(json.dumps({"busy": True, "started_at": old, "task": "test"}))
    result = hc.check_dispatch_lock(dispatch_path)
    assert result["severity"] == "yellow"
    assert "60" in result["detail"]  # roughly 60 minutes


def test_check_dispatch_lock_red_when_busy_very_long(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    dispatch_path = tmp_path / ".claude" / "dispatch-state.json"
    dispatch_path.parent.mkdir(parents=True)
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=3)).isoformat()
    dispatch_path.write_text(json.dumps({"busy": True, "started_at": old, "task": "stuck"}))
    result = hc.check_dispatch_lock(dispatch_path)
    assert result["severity"] == "red"
    assert "almost certainly stuck" in result["detail"]


# ── pipeline breaker (failure_breaker.py) ───────────────────────────────

def test_check_pipeline_breaker_includes_local_trips(monkeypatch):
    """The breaker trips when the same failure hits 3+ different tickets."""
    import failure_breaker

    trips = [
        {"project": "G-Eskayo/marvin", "signature": "npm-build-failed", "tickets": [1, 2, 3],
         "first_seen": "2026-10-15T10:00:00+00:00", "last_seen": "2026-10-15T11:00:00+00:00",
         "example": "npm ERR! code ERESOLVE"}
    ]
    monkeypatch.setattr(failure_breaker, "tripped", lambda: trips)
    monkeypatch.setattr(failure_breaker, "code_freshness", lambda *a, **k: {"state": "current", "detail": "up to date"})
    monkeypatch.setattr(failure_breaker, "code_trip", lambda *a, **k: None)
    monkeypatch.setattr(hc, "_reachable", lambda r, d: True)  # all reachable
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})  # no remotes

    result = hc.check_pipeline_breaker()
    assert result["severity"] == "red"
    assert "npm-build-failed" in result["detail"]
    assert "[1, 2, 3]" in result["detail"]


def test_check_pipeline_breaker_green_when_not_tripped(monkeypatch):
    import failure_breaker

    monkeypatch.setattr(failure_breaker, "tripped", lambda: [])
    monkeypatch.setattr(failure_breaker, "code_freshness", lambda *a, **k: {"state": "current", "detail": ""})
    monkeypatch.setattr(failure_breaker, "code_trip", lambda *a, **k: None)
    monkeypatch.setattr(hc, "_reachable", lambda r, d: True)
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})

    result = hc.check_pipeline_breaker()
    assert result["severity"] == "green"
    assert "not tripped" in result["detail"]


# ── sync stuck ───────────────────────────────────────────────────────────

def test_check_sync_stuck_green_when_no_stuck_entries(monkeypatch, tmp_path):
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    sync_log = claude_dir / "sync-log.md"
    sync_log.write_text("## 2026-10-15T10:00:00Z — pull (mac-mini) [~/.agents]\nSUCCESS")
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc, "_reachable", lambda r, d: True)
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})

    results = hc.check_sync_stuck(remote=lambda h: "")
    assert all(r["severity"] == "green" for r in results)


def test_check_sync_stuck_yellow_when_stuck_between_30min_and_4hours(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=1)).isoformat()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    sync_log = claude_dir / "sync-log.md"
    sync_log.write_text(f"## {old} — push (mac-mini) [~/.agents]\nREFUSING merge conflict")
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc, "_reachable", lambda r, d: True)
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})

    results = hc.check_sync_stuck(remote=lambda h: "")
    assert any(r["severity"] == "yellow" for r in results)


def test_check_sync_stuck_red_when_stuck_over_4_hours(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    old = (now - timedelta(hours=5)).isoformat()
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    sync_log = claude_dir / "sync-log.md"
    sync_log.write_text(f"## {old} — push (mac-mini) [~/.agents]\nREFUSING conflict")
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc, "_reachable", lambda r, d: True)
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})

    results = hc.check_sync_stuck(remote=lambda h: "")
    assert any(r["severity"] == "red" for r in results)


# ── model availability ───────────────────────────────────────────────────

def test_check_model_availability_config_drift(tmp_path, monkeypatch):
    """Config drift: empty capability list."""
    class MockRegistry:
        def all(self):
            return {
                "capabilities": {"empty-cap": []},  # empty list
                "models": {"qwen2.5:7b": {"runtime": "ollama"}}
            }
    monkeypatch.setattr(mr, "ModelRegistry", lambda: MockRegistry())
    monkeypatch.setattr(mr, "pulled_models", lambda: ["qwen2.5:7b"])
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    result = hc.check_model_availability()
    assert result["severity"] == "red"
    assert "Config drift" in result["detail"]
    assert "empty" in result["detail"]


def test_check_model_availability_unknown_when_remote_machine_unreachable(tmp_path, monkeypatch):
    """Incomplete evidence: remote machine's listing couldn't be read, models missing."""
    class MockRegistry:
        def all(self):
            return {
                "capabilities": {"test-cap": ["qwen2.5:7b"]},
                "models": {"qwen2.5:7b": {"runtime": "ollama"}}
            }
    monkeypatch.setattr(mr, "ModelRegistry", lambda: MockRegistry())
    monkeypatch.setattr(mr, "pulled_models", lambda: [])  # local doesn't have it
    monkeypatch.setattr(hc.machine_profile, "remote_devices",
                       lambda: {"mac-mini": {"tailscale_hostname": "mini.local"}})
    # Simulate remote machine query failing (returns None)
    monkeypatch.setattr(hc, "_query_ollama_models_remote", lambda h: None)
    result = hc.check_model_availability(reachability={"machine:mac-mini": "green"})
    assert result["severity"] == "unknown"
    assert "couldn't verify" in result["detail"]


def test_check_model_availability_untagged_model_match(tmp_path, monkeypatch):
    """Untagged models in registry should match ollama's ':latest' reports."""
    class MockRegistry:
        def all(self):
            return {
                "capabilities": {"test-cap": ["nomic-embed-text"]},
                "models": {"nomic-embed-text": {"runtime": "ollama"}}
            }
    monkeypatch.setattr(mr, "ModelRegistry", lambda: MockRegistry())
    # Ollama reports untagged pulls as "name:latest"
    monkeypatch.setattr(mr, "pulled_models", lambda: ["nomic-embed-text:latest"])
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    result = hc.check_model_availability()
    assert result["severity"] == "green"
    assert "all 1 ollama models present" in result["detail"]


# ── pipeline purpose (I5, ADR 0080) ──────────────────────────────────────

def test_check_pipeline_purpose_green_when_no_ready_tickets(monkeypatch):
    """Green when every repo has 0 ready tickets (nothing stuck)."""
    import ticket_pipeline as tp
    import project_profile as prof
    import failure_breaker

    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda repo=None: [])
    monkeypatch.setattr(prof, "runnable_repos", lambda: [])
    monkeypatch.setattr(failure_breaker, "tripped", lambda: [])

    results = hc.check_pipeline_purpose()
    assert len(results) == 1
    assert results[0]["severity"] == "green"
    assert "every ready ticket has a PR" in results[0]["detail"]


def test_check_pipeline_purpose_yellow_when_stage_failed(monkeypatch):
    """Yellow when a ready ticket's stage failed."""
    import ticket_pipeline as tp
    import project_profile as prof
    import failure_breaker
    import pipeline_purpose as pp_check

    mock_ticket = {"number": 42, "title": "test"}
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets",
                       lambda repo=None: [mock_ticket] if repo == "G-Eskayo/test" else [])
    monkeypatch.setattr(prof, "runnable_repos", lambda: ["G-Eskayo/test"])
    monkeypatch.setattr(failure_breaker, "tripped", lambda: [])

    def mock_missed(*args, **kwargs):
        return ("stage-failed", "executing: test timeout")
    monkeypatch.setattr(pp_check, "missed_purpose", mock_missed)

    results = hc.check_pipeline_purpose()
    assert any(r["severity"] == "yellow" for r in results)
    assert any("stage-failed" in r["detail"] for r in results)


def test_check_pipeline_purpose_red_when_breaker_tripped(monkeypatch):
    """Red when the circuit breaker is tripped."""
    import ticket_pipeline as tp
    import project_profile as prof
    import failure_breaker
    import pipeline_purpose as pp_check

    mock_ticket = {"number": 42, "title": "test"}
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets",
                       lambda repo=None: [mock_ticket] if repo == "G-Eskayo/test" else [])
    monkeypatch.setattr(prof, "runnable_repos", lambda: ["G-Eskayo/test"])
    monkeypatch.setattr(failure_breaker, "tripped", lambda: [])

    def mock_missed(*args, **kwargs):
        return ("breaker-trip", "npm-build-failed")
    monkeypatch.setattr(pp_check, "missed_purpose", mock_missed)

    results = hc.check_pipeline_purpose()
    assert any(r["severity"] == "red" for r in results)
    assert any("breaker-trip" in r["detail"] for r in results)


def test_check_pipeline_purpose_unknown_on_read_error(monkeypatch):
    """Unknown when ticket_pipeline can't be read."""
    import ticket_pipeline as tp

    def mock_unclaimed(*args, **kwargs):
        raise Exception("mock error")
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", mock_unclaimed)

    results = hc.check_pipeline_purpose()
    assert len(results) == 1
    assert results[0]["severity"] == "unknown"
    assert "couldn't measure" in results[0]["detail"]
