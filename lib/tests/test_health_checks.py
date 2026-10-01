"""Tests for health_checks.py (ADR 0033). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_health_checks.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import cron_health as ch  # noqa: E402
import health_checks as hc  # noqa: E402


# ── token files ──────────────────────────────────────────────────────────

def test_check_token_files_flags_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    results = hc.check_token_files()
    assert all(r["severity"] == "red" for r in results)
    assert all("does not exist" in r["detail"] for r in results)


def test_check_token_files_flags_embedded_whitespace(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".oauth-token").write_text("sk-ant-oat01-abc\ndef")
    (tmp_path / ".claude" / ".gh-token").write_text("gho_validtoken")
    results = {r["id"]: r for r in hc.check_token_files()}
    assert results["token:oauth-token"]["severity"] == "red"
    assert "whitespace" in results["token:oauth-token"]["detail"]
    assert results["token:gh-token"]["severity"] == "green"


def test_check_token_files_green_when_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / ".oauth-token").write_text("sk-ant-oat01-cleantoken\n")
    (tmp_path / ".claude" / ".gh-token").write_text("gho_cleantoken\n")
    results = hc.check_token_files()
    assert all(r["severity"] == "green" for r in results)


# ── dispatch lock ────────────────────────────────────────────────────────

def test_check_dispatch_lock_green_when_no_file(tmp_path):
    result = hc.check_dispatch_lock(state_path=tmp_path / "nope.json")
    assert result["severity"] == "green"


def test_check_dispatch_lock_green_when_idle(tmp_path):
    p = tmp_path / "dispatch-state.json"
    p.write_text(json.dumps({"busy": False}))
    assert hc.check_dispatch_lock(state_path=p)["severity"] == "green"


def test_check_dispatch_lock_red_after_15_days():
    # The exact incident: a lock left busy since before the mac-mini's
    # 2026-09-15 crash, still busy 2026-09-30 when found live.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "dispatch-state.json"
        stale = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        p.write_text(json.dumps({"busy": True, "task": "ticket #30", "started_at": stale}))
        result = hc.check_dispatch_lock(state_path=p)
    assert result["severity"] == "red"
    assert "ticket #30" in result["detail"]


def test_check_dispatch_lock_yellow_in_warning_window():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "dispatch-state.json"
        aged = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        p.write_text(json.dumps({"busy": True, "task": "t", "started_at": aged}))
        result = hc.check_dispatch_lock(state_path=p)
    assert result["severity"] == "yellow"


def test_check_dispatch_lock_green_shortly_after_start():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "dispatch-state.json"
        fresh = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        p.write_text(json.dumps({"busy": True, "task": "t", "started_at": fresh}))
        result = hc.check_dispatch_lock(state_path=p)
    assert result["severity"] == "green"


# ── coverage / auto-discovery ────────────────────────────────────────────

def test_coverage_flags_jobs_with_no_registered_check(monkeypatch):
    monkeypatch.setattr(hc, "discover_launchd_jobs",
                        lambda: ["daily-digest", "ticket-pipeline", "auto-fix"])
    results = [{"id": "cron:daily-digest", "severity": "green"}]
    cov = hc.coverage(results)
    assert cov["total"] == 3
    assert cov["covered"] == 1
    assert set(cov["unmonitored_jobs"]) == {"ticket-pipeline", "auto-fix"}
    assert cov["fraction"] == round(1 / 3, 2)


def test_coverage_full_when_everything_discovered_has_a_check(monkeypatch):
    monkeypatch.setattr(hc, "discover_launchd_jobs", lambda: ["daily-digest"])
    cov = hc.coverage([{"id": "cron:daily-digest", "severity": "green"}])
    assert cov["fraction"] == 1.0
    assert cov["unmonitored_jobs"] == []


def test_plist_label_to_job_name_strips_known_prefixes():
    assert hc._plist_label_to_job_name("com.marvin.ticket-pipeline") == "ticket-pipeline"
    assert hc._plist_label_to_job_name("com.giles.tidy-agent") == "tidy-agent"
    assert hc._plist_label_to_job_name("com.apple.something") == "com.apple.something"


# ── cron job log scan (wraps cron_health.check_job -- its own offset-
# tracking behavior is already covered by exercising it through here) ───

def test_check_cron_job_log_establishes_baseline_on_first_run(tmp_path, monkeypatch):
    # cron_health.check_job()'s own documented behavior: first-ever run for
    # a log establishes a baseline offset and does NOT report pre-existing
    # history as new -- exercised here since my earlier naive
    # reimplementation regressed exactly this.
    monkeypatch.setattr(ch, "HOME", tmp_path)
    log_dir = tmp_path / ".claude" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "daily-digest.log").write_text("old stuff")
    (log_dir / "daily-digest-error.log").write_text("Traceback: old pre-existing failure\n")
    state = {}
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    result = hc.check_cron_job_log("daily-digest", state, now)
    assert result["severity"] == "green"


def test_check_cron_job_log_flags_genuinely_new_failures(tmp_path, monkeypatch):
    monkeypatch.setattr(ch, "HOME", tmp_path)
    log_dir = tmp_path / ".claude" / "logs"
    log_dir.mkdir(parents=True)
    err = log_dir / "daily-digest-error.log"
    (log_dir / "daily-digest.log").write_text("")
    err.write_text("")
    state = {}
    now = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    hc.check_cron_job_log("daily-digest", state, now)  # baseline run
    err.write_text("Traceback: a real new failure\n")
    result = hc.check_cron_job_log("daily-digest", state, now)
    assert result["severity"] == "red"


def test_check_cron_job_log_returns_none_for_unmapped_job():
    assert hc.check_cron_job_log("some-job-with-no-known-logs", {}, datetime.now(timezone.utc)) is None


# ── repo integrity ────────────────────────────────────────────────────────

def test_check_repo_integrity_yellow_on_leftover_stash(tmp_path, monkeypatch):
    class FakeProc:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(cmd, **kw):
        if "stash" in cmd:
            return FakeProc("stash@{0}: WIP on main: abc123 msg\n")
        return FakeProc("")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    result = hc.check_repo_integrity("~/.agents", ".agents")
    assert result["severity"] == "yellow"
    assert result["value"] == 1


def test_check_repo_integrity_red_on_unresolved_conflict(monkeypatch):
    class FakeProc:
        def __init__(self, stdout):
            self.stdout = stdout

    def fake_run(cmd, **kw):
        if "stash" in cmd:
            return FakeProc("")
        return FakeProc("UU quarantine.md\n")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    result = hc.check_repo_integrity("~/.claude", ".claude")
    assert result["severity"] == "red"


def test_check_repo_integrity_green_when_clean(monkeypatch):
    class FakeProc:
        def __init__(self, stdout):
            self.stdout = stdout

    monkeypatch.setattr(hc.subprocess, "run", lambda cmd, **kw: FakeProc(""))
    result = hc.check_repo_integrity("~/.agents", ".agents")
    assert result["severity"] == "green"


# ── numeric anomaly recording ────────────────────────────────────────────

def test_record_anomaly_metrics_returns_none_with_no_numeric_values():
    assert hc.record_anomaly_metrics([{"id": "x", "value": None}]) is None


def test_record_anomaly_metrics_returns_none_with_no_prior_baseline(monkeypatch):
    monkeypatch.setattr(hc.mr, "latest", lambda subsystem: None)
    recorded = {}
    monkeypatch.setattr(hc.mr, "record", lambda subsystem, metrics: recorded.update(metrics))
    out = hc.record_anomaly_metrics([{"id": "cron:daily-digest", "value": 3}])
    assert out is None
    assert recorded["cron:daily-digest"]["value"] == 3
    assert recorded["cron:daily-digest"]["higher_is_better"] is False


def test_record_anomaly_metrics_compares_against_prior_baseline(monkeypatch):
    monkeypatch.setattr(hc.mr, "latest", lambda subsystem: {"cron:daily-digest": {"value": 0, "higher_is_better": False}})
    monkeypatch.setattr(hc.mr, "record", lambda subsystem, metrics: None)
    captured = {}

    def fake_compare(subsystem, baseline, current):
        captured["baseline"] = baseline
        captured["current"] = current
        return {"verdict": "regressed"}

    monkeypatch.setattr(hc.mr, "compare", fake_compare)
    out = hc.record_anomaly_metrics([{"id": "cron:daily-digest", "value": 5}])
    assert out == {"verdict": "regressed"}
    assert captured["baseline"]["cron:daily-digest"]["value"] == 0
    assert captured["current"]["cron:daily-digest"]["value"] == 5


def test_higher_is_better_only_for_the_one_registered_metric():
    assert "route:intent-routing-collection" in hc.HIGHER_IS_BETTER
    assert "dispatch:lock-age" not in hc.HIGHER_IS_BETTER
