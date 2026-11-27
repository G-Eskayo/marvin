#!/usr/bin/env python3
"""Tests for pipeline_purpose: diagnosing why a PR hasn't been raised."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import pipeline_purpose as pp  # noqa: E402


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TestPrRaisedSince:
    def test_no_prs(self, monkeypatch):
        def mock_run(*args, **kwargs):
            class Result:
                returncode = 0
                stdout = "[]"
            return Result()
        monkeypatch.setattr("subprocess.run", mock_run)
        result = pp.pr_raised_since("G-Eskayo/test", _now())
        assert result is not None
        assert "no PR was raised" in result

    def test_recent_pr(self, monkeypatch):
        now = _now()
        created = (now - timedelta(hours=1)).isoformat()

        def mock_run(*args, **kwargs):
            class Result:
                returncode = 0
                stdout = json.dumps([{"number": 1, "createdAt": created}])
            return Result()
        monkeypatch.setattr("subprocess.run", mock_run)
        result = pp.pr_raised_since("G-Eskayo/test", now)
        assert result is None

    def test_old_pr(self, monkeypatch):
        now = _now()
        created = (now - timedelta(days=5)).isoformat()

        def mock_run(*args, **kwargs):
            class Result:
                returncode = 0
                stdout = json.dumps([{"number": 1, "createdAt": created}])
            return Result()
        monkeypatch.setattr("subprocess.run", mock_run)
        result = pp.pr_raised_since("G-Eskayo/test", now, days=1)
        assert result is not None
        assert "no PR was raised" in result


class TestStageFailureReason:
    def test_no_stages_file(self, tmp_path):
        result = pp.stage_failure_reason("G-Eskayo/test", 123, _now(), stages_dir=tmp_path)
        assert result is None

    def test_no_failures(self, tmp_path, monkeypatch):
        stages_dir = tmp_path / "ticket-stages"
        stages_dir.mkdir()
        import ticket_stages as ts
        monkeypatch.setattr(ts, "STAGES_DIR", stages_dir)

        events_file = stages_dir / "g-eskayo__test-123.json"
        events_file.write_text(json.dumps([
            {"stage": "planning", "status": "passed", "detail": "done", "timestamp": _now().isoformat()}
        ]))

        result = pp.stage_failure_reason("G-Eskayo/test", 123, _now(), stages_dir=stages_dir)
        assert result is None

    def test_recent_failure(self, tmp_path, monkeypatch):
        stages_dir = tmp_path / "ticket-stages"
        stages_dir.mkdir()
        import ticket_stages as ts
        monkeypatch.setattr(ts, "STAGES_DIR", stages_dir)

        events_file = stages_dir / "g-eskayo__test-123.json"
        events_file.write_text(json.dumps([
            {"stage": "planning", "status": "passed", "detail": "planned", "timestamp": _now().isoformat()},
            {"stage": "executing", "status": "failed", "detail": "test failed", "timestamp": _now().isoformat()}
        ]))

        result = pp.stage_failure_reason("G-Eskayo/test", 123, _now(), stages_dir=stages_dir)
        assert result is not None
        assert "executing" in result
        assert "test failed" in result


class TestNoRunDispatched:
    def test_no_job_log(self, tmp_path):
        result = pp.no_run_dispatched("G-Eskayo/test", 123, _now(), job_log_path=tmp_path / "missing.json")
        assert result is not None
        assert "not found" in result

    def test_recent_run(self, tmp_path):
        job_log = tmp_path / "ticket-pipeline.json"
        now = _now()
        started = (now - timedelta(hours=1)).isoformat()
        job_log.write_text(json.dumps({
            "runs": [
                {
                    "id": "abc123",
                    "started_at": started,
                    "steps": [
                        {"detail": "Dispatched ticket #123"}
                    ]
                }
            ]
        }))
        result = pp.no_run_dispatched("G-Eskayo/test", 123, now, job_log_path=job_log)
        assert result is None

    def test_old_run(self, tmp_path):
        job_log = tmp_path / "ticket-pipeline.json"
        now = _now()
        started = (now - timedelta(hours=10)).isoformat()
        job_log.write_text(json.dumps({
            "runs": [
                {
                    "id": "abc123",
                    "started_at": started,
                    "steps": [
                        {"detail": "Dispatched ticket #123"}
                    ]
                }
            ]
        }))
        result = pp.no_run_dispatched("G-Eskayo/test", 123, now, job_log_path=job_log, hours=4)
        assert result is not None
        assert "no run dispatched" in result


class TestGuardRefusalReason:
    def test_no_trips(self, monkeypatch):
        def mock_tripped(*args, **kwargs):
            return []
        monkeypatch.setattr("failure_breaker.tripped", mock_tripped)
        result = pp.guard_refusal_reason("G-Eskayo/test")
        assert result is None

    def test_trip_for_repo(self, monkeypatch):
        def mock_tripped(*args, **kwargs):
            return [
                {"signature": "model-unavailable", "project": "G-Eskayo/test"}
            ]
        monkeypatch.setattr("failure_breaker.tripped", mock_tripped)
        result = pp.guard_refusal_reason("G-Eskayo/test")
        assert result is not None
        assert "model-unavailable" in result

    def test_trip_for_all_projects(self, monkeypatch):
        def mock_tripped(*args, **kwargs):
            return [
                {"signature": "code-stale", "project": "*"}
            ]
        monkeypatch.setattr("failure_breaker.tripped", mock_tripped)
        result = pp.guard_refusal_reason("G-Eskayo/test")
        assert result is not None
        assert "code-stale" in result


class TestMissedPurpose:
    def test_no_ready_tickets(self, monkeypatch):
        reason_id, reason = pp.missed_purpose("G-Eskayo/test", "mini", _now(), ready_count=0)
        assert reason_id is None
        assert reason is None

    def test_pr_raised_recently(self, monkeypatch):
        now = _now()
        created = (now - timedelta(hours=1)).isoformat()

        def mock_run(*args, **kwargs):
            class Result:
                returncode = 0
                stdout = json.dumps([{"number": 1, "createdAt": created}])
            return Result()
        monkeypatch.setattr("subprocess.run", mock_run)

        def mock_tripped(*args, **kwargs):
            return []
        monkeypatch.setattr("failure_breaker.tripped", mock_tripped)

        reason_id, reason = pp.missed_purpose("G-Eskayo/test", "mini", now, ready_count=5)
        assert reason_id is None
        assert reason is None

    def test_breaker_trip(self, monkeypatch):
        def mock_tripped(*args, **kwargs):
            return []
        monkeypatch.setattr("failure_breaker.tripped", mock_tripped)

        breaker_trips = [
            {"project": "G-Eskayo/test", "signature": "npm-build-failed", "example": "npm build failed"}
        ]
        reason_id, reason = pp.missed_purpose("G-Eskayo/test", "mini", _now(), ready_count=5, breaker_trips=breaker_trips)
        assert reason_id == "breaker-trip"
        assert "npm-build-failed" in reason or "npm build failed" in reason

    def test_stage_failure(self, monkeypatch, tmp_path):
        def mock_run(*args, **kwargs):
            class Result:
                returncode = 0
                stdout = "[]"
            return Result()
        monkeypatch.setattr("subprocess.run", mock_run)

        def mock_tripped(*args, **kwargs):
            return []
        monkeypatch.setattr("failure_breaker.tripped", mock_tripped)

        stages_dir = tmp_path / "ticket-stages"
        stages_dir.mkdir()
        import ticket_stages as ts
        monkeypatch.setattr(ts, "STAGES_DIR", stages_dir)

        events_file = stages_dir / "g-eskayo__test-0.json"
        events_file.write_text(json.dumps([
            {"stage": "executing", "status": "failed", "detail": "test timeout", "timestamp": _now().isoformat()}
        ]))

        reason_id, reason = pp.missed_purpose("G-Eskayo/test", "mini", _now(), ready_count=5,
                                              stages_dir=stages_dir)
        assert reason_id == "stage-failed"
        assert "executing" in reason

    def test_unknown_reason(self, monkeypatch):
        def mock_run(*args, **kwargs):
            class Result:
                returncode = 0
                stdout = "[]"
            return Result()
        monkeypatch.setattr("subprocess.run", mock_run)

        def mock_tripped(*args, **kwargs):
            return []
        monkeypatch.setattr("failure_breaker.tripped", mock_tripped)

        reason_id, reason = pp.missed_purpose("G-Eskayo/test", "mini", _now(), ready_count=5)
        assert reason_id in ("unknown", "no-run")


class TestDueBlocks:
    def test_no_due_date(self, monkeypatch):
        def mock_due(*args, **kwargs):
            return None
        monkeypatch.setattr("ticket_agents.due_for_repo", mock_due)
        result = pp.due_blocks("G-Eskayo/test", _now())
        assert result is None

    def test_due_in_future(self, monkeypatch):
        future = (_now() + timedelta(days=5)).isoformat()
        def mock_due(*args, **kwargs):
            return {"date": future, "hard": False}
        monkeypatch.setattr("ticket_agents.due_for_repo", mock_due)
        result = pp.due_blocks("G-Eskayo/test", _now())
        assert result is None

    def test_due_passed_soft(self, monkeypatch):
        past = (_now() - timedelta(hours=1)).isoformat()
        def mock_due(*args, **kwargs):
            return {"date": past, "hard": False}
        monkeypatch.setattr("ticket_agents.due_for_repo", mock_due)
        result = pp.due_blocks("G-Eskayo/test", _now())
        assert result is not None
        severity, detail = result
        assert severity == "yellow"
        assert "past" in detail or "passed" in detail

    def test_due_in_24_hours(self, monkeypatch):
        soon = (_now() + timedelta(hours=12)).isoformat()
        def mock_due(*args, **kwargs):
            return {"date": soon, "hard": True}
        monkeypatch.setattr("ticket_agents.due_for_repo", mock_due)
        result = pp.due_blocks("G-Eskayo/test", _now())
        assert result is not None
        severity, detail = result
        assert severity == "red"
        assert "hard" in detail
