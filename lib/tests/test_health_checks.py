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


# ── machine reachability: a closed laptop is asleep, not broken ─────────────
# The Health tab marked the MacBook red whenever it was unreachable, i.e. every
# time the lid was closed. Red is supposed to mean "needs your immediate
# attention", so a normal lid-close taught the dashboard to cry wolf.
# Classification: kind=laptop + Tailscale reports it OFFLINE recently => "asleep"
# (neutral); online-but-unreachable or an always-on desktop down => red.

NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


def _peer(online, hours_ago=None):
    return {"online": online,
            "last_seen": None if hours_ago is None else NOW - timedelta(hours=hours_ago)}


def test_laptop_offline_recently_is_asleep_not_red():
    sev, detail = hc.classify_unreachable("laptop", _peer(False, hours_ago=3), NOW)
    assert sev == "asleep"
    assert "3" in detail


def test_laptop_offline_with_unknown_last_seen_is_still_asleep():
    sev, _ = hc.classify_unreachable("laptop", _peer(False, hours_ago=None), NOW)
    assert sev == "asleep"


def test_laptop_offline_for_days_escalates_to_yellow_not_silently_asleep_forever():
    sev, detail = hc.classify_unreachable("laptop", _peer(False, hours_ago=24 * 5), NOW)
    assert sev == "yellow"
    assert "5" in detail


def test_laptop_online_on_tailscale_but_ssh_failing_is_red():
    # Awake and on the network yet unreachable is a genuine fault, not a lid.
    sev, _ = hc.classify_unreachable("laptop", _peer(True), NOW)
    assert sev == "red"


def test_always_on_desktop_offline_is_red():
    sev, _ = hc.classify_unreachable("desktop", _peer(False, hours_ago=3), NOW)
    assert sev == "red"


def test_laptop_with_no_tailscale_state_is_yellow_not_red_and_not_asleep():
    sev, detail = hc.classify_unreachable("laptop", None, NOW)
    assert sev == "yellow"
    assert "cannot tell" in detail.lower() or "can't tell" in detail.lower()


def test_desktop_with_no_tailscale_state_stays_red():
    sev, _ = hc.classify_unreachable("desktop", None, NOW)
    assert sev == "red"


def test_check_machine_reachability_reports_asleep_for_a_closed_laptop(monkeypatch):
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {
        "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "lap"}})

    class Fail:
        returncode = 255
        stderr = "ssh: connect to host lap port 22: Operation timed out"

    monkeypatch.setattr(hc.subprocess, "run", lambda *a, **k: Fail())
    monkeypatch.setattr(hc, "_tailscale_peer", lambda host: _peer(False, hours_ago=2))
    monkeypatch.setattr(hc, "_now", lambda: NOW)

    [r] = hc.check_machine_reachability()
    assert r["severity"] == "asleep"
    assert r["id"] == "machine:macbook-pro-1"


def test_asleep_does_not_make_the_overall_status_red_or_yellow():
    assert hc.overall_severity(["green", "asleep", "green"]) == "green"
    assert hc.overall_severity(["green", "asleep", "red"]) == "red"
    assert hc.overall_severity(["yellow", "asleep"]) == "yellow"


def test_tailscale_peer_parses_online_state_and_last_seen(monkeypatch):
    payload = json.dumps({"Peer": {
        "k1": {"HostName": "Lap", "DNSName": "lap.tail1.ts.net.", "Online": False,
               "LastSeen": "2026-10-02T09:00:00Z"},
        "k2": {"HostName": "other", "DNSName": "other.tail1.ts.net.", "Online": True,
               "LastSeen": "0001-01-01T00:00:00Z"}}})

    class R:
        returncode = 0
        stdout = payload

    monkeypatch.setattr(hc.subprocess, "run", lambda *a, **k: R())
    peer = hc._tailscale_peer("lap")
    assert peer["online"] is False
    assert peer["last_seen"] == datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    assert hc._tailscale_peer("nope") is None


# ── sync / parity health: measured on BOTH machines, in time not commits ────
# repo integrity only inspected the local machine, so the laptop's 7 leftover
# stashes (which make code_sync REFUSE to run) never showed on the dashboard
# while ~/.agents quietly drifted. One state reader runs locally or over ssh and
# one pure evaluator judges it.

def _state(**kw):
    base = {"head": "abc1234", "stashes": 0, "conflicts": 0, "fetch_ok": True,
            "behind": 0, "behind_oldest_ts": None, "ahead": 0, "ahead_oldest_ts": None}
    base.update(kw)
    return base


def _ago(hours):
    return int((NOW - timedelta(hours=hours)).timestamp())


def test_parse_repo_state_reads_key_value_output():
    text = "head=abc1234\nstashes=7\nconflicts=0\nfetch_ok=1\nbehind=2\nbehind_oldest_ts=1759000000\nahead=0\nahead_oldest_ts=\n"
    st = hc.parse_repo_state(text)
    assert st["head"] == "abc1234" and st["stashes"] == 7 and st["fetch_ok"] is True
    assert st["behind"] == 2 and st["behind_oldest_ts"] == 1759000000
    assert st["ahead_oldest_ts"] is None


def test_evaluate_repo_sync_green_when_converged_and_clean():
    sev, detail, _ = hc.evaluate_repo_sync(_state(), NOW)
    assert sev == "green"


def test_evaluate_repo_sync_stashes_block_sync_and_are_flagged():
    sev, detail, value = hc.evaluate_repo_sync(_state(stashes=7), NOW)
    assert sev == "yellow"
    assert "7" in detail and "block" in detail.lower()
    assert value == 7


def test_evaluate_repo_sync_conflict_is_red():
    sev, _, _ = hc.evaluate_repo_sync(_state(conflicts=1), NOW)
    assert sev == "red"


def test_evaluate_repo_sync_behind_is_judged_by_age_of_oldest_missing_commit():
    assert hc.evaluate_repo_sync(_state(behind=1, behind_oldest_ts=_ago(0.5)), NOW)[0] == "green"
    assert hc.evaluate_repo_sync(_state(behind=3, behind_oldest_ts=_ago(5)), NOW)[0] == "yellow"
    sev, detail, _ = hc.evaluate_repo_sync(_state(behind=9, behind_oldest_ts=_ago(30)), NOW)
    assert sev == "red" and "30" in detail


def test_evaluate_repo_sync_unpushed_commits_age_the_same_way():
    assert hc.evaluate_repo_sync(_state(ahead=2, ahead_oldest_ts=_ago(5)), NOW)[0] == "yellow"
    assert hc.evaluate_repo_sync(_state(ahead=2, ahead_oldest_ts=_ago(30)), NOW)[0] == "red"


def test_evaluate_repo_sync_fetch_failure_is_yellow_not_silently_green():
    sev, detail, _ = hc.evaluate_repo_sync(_state(fetch_ok=False), NOW)
    assert sev == "yellow" and "fetch" in detail.lower()


def test_evaluate_repo_sync_reports_the_worst_condition():
    sev, _, _ = hc.evaluate_repo_sync(_state(stashes=2, behind=9, behind_oldest_ts=_ago(40)), NOW)
    assert sev == "red"


def test_repo_state_script_against_real_git_repos(tmp_path):
    import subprocess as sp, shlex

    def g(cwd, *a):
        sp.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *a],
               check=True, capture_output=True)

    bare = tmp_path / "origin.git"
    sp.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    a, b = tmp_path / "a", tmp_path / "home" / "repo"
    sp.run(["git", "clone", "-q", str(bare), str(a)], check=True, capture_output=True)
    (a / "f").write_text("1"); g(a, "add", "."); g(a, "commit", "-qm", "one"); g(a, "push", "-q", "origin", "HEAD:main")
    (tmp_path / "home").mkdir()
    sp.run(["git", "clone", "-q", str(bare), str(b)], check=True, capture_output=True)
    (a / "f").write_text("2"); g(a, "add", "."); g(a, "commit", "-qm", "two"); g(a, "push", "-q", "origin", "HEAD:main")
    (b / "g").write_text("x"); g(b, "add", "."); g(b, "commit", "-qm", "local-only")
    (b / "h").write_text("y"); g(b, "stash", "push", "-u", "-q", "-m", "left over")

    out = sp.run(["bash", "-s"], input=hc.repo_state_script("repo"), capture_output=True, text=True,
                 env={"HOME": str(tmp_path / "home"), "PATH": "/usr/bin:/bin:/opt/homebrew/bin"})
    st = hc.parse_repo_state(out.stdout)
    assert st["fetch_ok"] is True
    assert st["behind"] == 1 and st["behind_oldest_ts"] is not None
    assert st["ahead"] == 1 and st["ahead_oldest_ts"] is not None
    assert st["stashes"] == 1


def test_check_repo_sync_everywhere_covers_local_and_reachable_remote(monkeypatch):
    monkeypatch.setattr(hc, "SYNCED_REPOS", {"~/.agents": ".agents"})
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {
        "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "lap"}})
    monkeypatch.setattr(hc, "_now", lambda: NOW)
    calls = []

    def runner(target, rel):
        calls.append((target, rel))
        return "head=abc\nstashes=7\nconflicts=0\nfetch_ok=1\nbehind=0\nbehind_oldest_ts=\nahead=0\nahead_oldest_ts=\n" \
            if target == "lap" else "head=abc\nstashes=0\nconflicts=0\nfetch_ok=1\nbehind=0\nbehind_oldest_ts=\nahead=0\nahead_oldest_ts=\n"

    reach = {"machine:macbook-pro-1": "green"}
    results = hc.check_repo_sync_everywhere(reach, runner=runner)

    by_id = {r["id"]: r for r in results}
    assert by_id["repo:sync:~/.agents@mac-mini-1"]["severity"] == "green"
    assert by_id["repo:sync:~/.agents@macbook-pro-1"]["severity"] == "yellow"
    assert ("lap", ".agents") in calls


def test_check_repo_sync_everywhere_marks_an_asleep_laptop_asleep_not_failed(monkeypatch):
    monkeypatch.setattr(hc, "SYNCED_REPOS", {"~/.agents": ".agents"})
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {
        "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "lap"}})
    monkeypatch.setattr(hc, "_now", lambda: NOW)
    local = "head=abc\nstashes=0\nconflicts=0\nfetch_ok=1\nbehind=0\nbehind_oldest_ts=\nahead=0\nahead_oldest_ts=\n"
    runner = lambda target, rel: local

    results = hc.check_repo_sync_everywhere({"machine:macbook-pro-1": "asleep"}, runner=runner)

    remote = [r for r in results if r["id"].endswith("@macbook-pro-1")][0]
    assert remote["severity"] == "asleep"
