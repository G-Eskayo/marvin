"""Tests for health_checks.py (ADR 0033). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_health_checks.py -v
"""
from __future__ import annotations
import json
import pytest
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

def test_check_repo_integrity_red_on_leftover_stash(tmp_path, monkeypatch):
    class FakeProc:
        def __init__(self, stdout):
            self.stdout = stdout
            self.returncode = 0

    def fake_run(cmd, **kw):
        if "stash list" in " ".join(cmd):
            return FakeProc("stash@{0}: WIP on main: abc123 msg\n")
        elif "stash show" in " ".join(cmd):
            # Return filenames of stashed files
            return FakeProc("file1.txt\nfile2.md\n")
        return FakeProc("")

    monkeypatch.setattr(hc.subprocess, "run", fake_run)
    result = hc.check_repo_integrity("~/.agents", ".agents")
    assert result["severity"] == "red"
    assert result["value"] == 1
    assert "file1.txt" in result["detail"] or "file2.md" in result["detail"]


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
H = 3600


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
    assert sev == "red"
    assert "7" in detail and "block" in detail.lower()
    assert value == 7


def test_evaluate_repo_sync_stashes_include_filenames_when_available():
    state = _state(stashes=2)
    state["stash_files"] = "file1.txt,file2.md"
    sev, detail, value = hc.evaluate_repo_sync(state, NOW)
    assert sev == "red"
    assert "file1.txt" in detail or "file2.md" in detail


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
    assert by_id["repo:sync:~/.agents@macbook-pro-1"]["severity"] == "red"
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


# ── pipeline circuit breaker is visible on the dashboard ────────────────────

def test_pipeline_breaker_check_is_green_when_not_tripped(monkeypatch):
    import failure_breaker as fb
    monkeypatch.setattr(fb, "tripped", lambda now=None: [])
    r = hc.check_pipeline_breaker()
    assert r["id"] == "pipeline:breaker" and r["severity"] == "green"


def test_pipeline_breaker_check_is_red_and_names_the_signature_and_tickets_when_tripped(monkeypatch):
    import failure_breaker as fb
    monkeypatch.setattr(fb, "tripped", lambda now=None: [
        {"signature": "measure:vitest-no-summary", "tickets": [32, 35, 37],
         "first_seen": "2026-10-02T01:00:00+00:00", "last_seen": "2026-10-02T01:02:00+00:00", "example": "e"}])
    r = hc.check_pipeline_breaker()
    assert r["severity"] == "red"
    assert "measure:vitest-no-summary" in r["detail"]
    assert "32" in r["detail"] and "paused" in r["detail"].lower()


# ── missing execution profiles for projects with ready tickets ─────────────────
# A project with ready-for-agent tickets but no profile will never dispatch.

def test_missing_profiles_empty_when_no_repos(monkeypatch):
    import ticket_agents
    monkeypatch.setattr(ticket_agents, "board_repos", lambda: [])
    results = hc.check_missing_profiles()
    assert results == []


def test_missing_profiles_red_when_ready_tickets_but_no_profile(tmp_path, monkeypatch):
    import ticket_agents
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    monkeypatch.setattr(ticket_agents, "ready_elsewhere", lambda snapshot, executable=None: {"owner/project1": 1})
    monkeypatch.setattr(ticket_agents, "collect", lambda repos, gh=None: {})
    monkeypatch.setattr(ticket_agents, "board_repos", lambda: ["owner/project1"])
    monkeypatch.setattr(ticket_agents, "_gh", None)

    results = hc.check_missing_profiles(profiles_dir=profiles_dir)
    assert len(results) == 1
    r = results[0]
    assert r["severity"] == "red"
    assert r["id"] == "profile:missing:owner/project1"
    assert r["label"] == "owner/project1"
    assert r["value"] == 1
    assert "ready-for-agent" in r["detail"].lower() or "ready" in r["detail"].lower()
    assert "no execution profile" in r["detail"].lower()


def test_missing_profiles_clears_when_profile_exists(tmp_path, monkeypatch):
    import ticket_agents
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile_file = profiles_dir / "project1.json"
    profile_file.write_text('{"repo": "owner/project1", "verify": [{"id": "test", "command": "echo ok"}]}')

    monkeypatch.setattr(ticket_agents, "ready_elsewhere", lambda snapshot, executable=None: {"owner/project1": 2})
    monkeypatch.setattr(ticket_agents, "collect", lambda repos, gh=None: {})
    monkeypatch.setattr(ticket_agents, "board_repos", lambda: ["owner/project1"])
    monkeypatch.setattr(ticket_agents, "_gh", None)

    results = hc.check_missing_profiles(profiles_dir=profiles_dir)
    assert not results


def test_missing_profiles_multiple_projects_sorted(tmp_path, monkeypatch):
    import ticket_agents
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    monkeypatch.setattr(ticket_agents, "ready_elsewhere", lambda snapshot, executable=None: {"zebra/p": 1, "apple/p": 2})
    monkeypatch.setattr(ticket_agents, "collect", lambda repos, gh=None: {})
    monkeypatch.setattr(ticket_agents, "board_repos", lambda: ["zebra/p", "apple/p"])
    monkeypatch.setattr(ticket_agents, "_gh", None)

    results = hc.check_missing_profiles(profiles_dir=profiles_dir)
    assert len(results) == 2
    assert results[0]["label"] == "apple/p"
    assert results[1]["label"] == "zebra/p"


def test_missing_profiles_counts_tickets_per_repo(tmp_path, monkeypatch):
    import ticket_agents
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    monkeypatch.setattr(ticket_agents, "ready_elsewhere", lambda snapshot, executable=None: {"owner/project": 3})
    monkeypatch.setattr(ticket_agents, "collect", lambda repos, gh=None: {})
    monkeypatch.setattr(ticket_agents, "board_repos", lambda: ["owner/project"])
    monkeypatch.setattr(ticket_agents, "_gh", None)

    results = hc.check_missing_profiles(profiles_dir=profiles_dir)
    assert len(results) == 1
    assert results[0]["value"] == 3


def test_missing_profiles_snapshot_passed_directly(tmp_path, monkeypatch):
    import ticket_agents
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()

    monkeypatch.setattr(ticket_agents, "ready_elsewhere", lambda snapshot, executable=None: {"owner/project": 5})
    board_repos_called = []
    collect_called = []
    monkeypatch.setattr(ticket_agents, "board_repos", lambda: (board_repos_called.append(True), [])[1])
    monkeypatch.setattr(ticket_agents, "collect", lambda repos, gh=None: (collect_called.append(True), {})[1])

    results = hc.check_missing_profiles(snapshot={}, profiles_dir=profiles_dir)

    assert not board_repos_called
    assert not collect_called
    assert len(results) == 1
    assert results[0]["value"] == 5


# ── per-machine state that silently rots: dashboard build + GitHub credential ──
# 2026-10-02: Approve "didn't merge" on the laptop for TWO reasons nothing watched:
# its installed dashboard app was a month behind the code (it only rebuilds where a
# merge happened), and its GitHub credential had expired. The existing token check
# only verified the file EXISTS, not that the token works.

def _mstate(**kw):
    base = {"app_built_ts": int((NOW - timedelta(hours=1)).timestamp()),
            "dashboard_commit_ts": int((NOW - timedelta(hours=3)).timestamp()),
            "webhook_server_start_ts": int((NOW - timedelta(hours=1)).timestamp()),
            "webhook_commit_ts": int((NOW - timedelta(hours=3)).timestamp()),
            "gh_token": "ok"}
    base.update(kw)
    return base


def test_parse_machine_state_reads_key_value_output():
    st = hc.parse_machine_state("app_built_ts=1759000000\ndashboard_commit_ts=1759100000\ngh_token=invalid\n")
    assert st["app_built_ts"] == 1759000000 and st["dashboard_commit_ts"] == 1759100000 and st["gh_token"] == "invalid"
    assert st["docs_access"] == "" and st["brain_data_ts"] is None


def test_parse_machine_state_missing_app_is_none():
    st = hc.parse_machine_state("app_built_ts=\ndashboard_commit_ts=5\ngh_token=ok\n")
    assert st["app_built_ts"] is None


def test_build_is_green_when_the_app_is_at_least_as_new_as_the_latest_dashboard_commit():
    res = dict((k, (s, d)) for k, s, d in hc.evaluate_machine_state(_mstate(), NOW))
    assert res["dashboard:build"][0] == "green"


def test_build_is_yellow_when_a_few_hours_behind_and_red_when_a_day_or_more_behind():
    two = hc.evaluate_machine_state(_mstate(app_built_ts=int((NOW - timedelta(hours=9)).timestamp()),
                                            dashboard_commit_ts=int((NOW - timedelta(hours=3)).timestamp())), NOW)
    assert dict((k, s) for k, s, _ in two)["dashboard:build"] == "yellow"
    old = hc.evaluate_machine_state(_mstate(app_built_ts=int((NOW - timedelta(days=32)).timestamp()),
                                            dashboard_commit_ts=int((NOW - timedelta(hours=1)).timestamp())), NOW)
    sev, detail = [(s, d) for k, s, d in old if k == "dashboard:build"][0]
    assert sev == "red" and "31" in detail or "32" in detail


def test_missing_app_is_yellow_not_silently_green():
    res = dict((k, s) for k, s, _ in hc.evaluate_machine_state(_mstate(app_built_ts=None), NOW))
    assert res["dashboard:build"] == "yellow"


def test_invalid_github_token_is_red_and_says_what_breaks():
    sev, detail = [(s, d) for k, s, d in hc.evaluate_machine_state(_mstate(gh_token="invalid"), NOW) if k == "auth:gh"][0]
    assert sev == "red"
    assert "merge" in detail.lower()


def test_missing_github_token_file_is_yellow_and_valid_is_green():
    assert dict((k, s) for k, s, _ in hc.evaluate_machine_state(_mstate(gh_token="missing"), NOW))["auth:gh"] == "yellow"
    assert dict((k, s) for k, s, _ in hc.evaluate_machine_state(_mstate(gh_token="ok"), NOW))["auth:gh"] == "green"


def test_webhook_build_is_green_when_the_server_is_at_least_as_new_as_the_latest_webhook_commit():
    res = dict((k, (s, d)) for k, s, d in hc.evaluate_machine_state(_mstate(), NOW))
    assert res.get("webhook:build", ("green", ""))[0] == "green"


def test_webhook_build_is_yellow_when_a_few_hours_behind_and_red_when_a_day_or_more_behind():
    two = hc.evaluate_machine_state(_mstate(webhook_server_start_ts=int((NOW - timedelta(hours=9)).timestamp()),
                                            webhook_commit_ts=int((NOW - timedelta(hours=3)).timestamp())), NOW)
    res = dict((k, s) for k, s, _ in two)
    assert res.get("webhook:build") == "yellow"
    old = hc.evaluate_machine_state(_mstate(webhook_server_start_ts=int((NOW - timedelta(days=32)).timestamp()),
                                            webhook_commit_ts=int((NOW - timedelta(hours=1)).timestamp())), NOW)
    sev, detail = [(s, d) for k, s, d in old if k == "webhook:build"][0]
    assert sev == "red" and ("31" in detail or "32" in detail)


def test_webhook_build_is_yellow_when_server_is_not_running():
    res = dict((k, s) for k, s, _ in hc.evaluate_machine_state(_mstate(webhook_server_start_ts=None), NOW))
    assert res.get("webhook:build") == "yellow"


def test_webhook_build_skips_when_there_is_no_webhook_commit_to_compare_against():
    res = dict((k, s) for k, s, _ in hc.evaluate_machine_state(_mstate(webhook_commit_ts=None), NOW))
    assert "webhook:build" not in res


def test_check_machine_state_everywhere_covers_every_device_and_marks_asleep(monkeypatch):
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {
        "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "lap"}})
    monkeypatch.setattr(hc, "_now", lambda: NOW)
    good = f"app_built_ts={int((NOW - timedelta(hours=1)).timestamp())}\ndashboard_commit_ts={int((NOW - timedelta(hours=2)).timestamp())}\ngh_token=ok\n"
    bad = f"app_built_ts={int((NOW - timedelta(days=30)).timestamp())}\ndashboard_commit_ts={int((NOW - timedelta(hours=2)).timestamp())}\ngh_token=invalid\n"

    results = hc.check_machine_state_everywhere({"machine:macbook-pro-1": "green"},
                                                runner=lambda target, script: good if target is None else bad)
    by_id = {r["id"]: r["severity"] for r in results}
    assert by_id["dashboard:build@mac-mini-1"] == "green"
    assert by_id["dashboard:build@macbook-pro-1"] == "red"
    assert by_id["auth:gh@macbook-pro-1"] == "red"

    asleep = hc.check_machine_state_everywhere({"machine:macbook-pro-1": "asleep"}, runner=lambda t, s: good)
    assert {r["severity"] for r in asleep if r["id"].endswith("@macbook-pro-1")} == {"asleep"}


# ── dashboard trigger coverage guard ────────────────────────────────────────

def _miss(at, topic="activity", key="o/r"):
    return json.dumps({"topic": topic, "key": key, "at": at.isoformat(), "note": "poll found a change no trigger announced"})


def test_trigger_check_is_green_with_no_log_or_no_recent_misses(tmp_path):
    now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    assert hc.check_trigger_coverage(tmp_path / "nope.jsonl", now=now)["severity"] == "green"
    log = tmp_path / "m.jsonl"
    log.write_text(_miss(now - timedelta(days=3)) + "\n")
    assert hc.check_trigger_coverage(log, now=now)["severity"] == "green"


def test_trigger_check_is_yellow_and_names_what_was_missed(tmp_path):
    now = datetime(2026, 10, 3, 12, tzinfo=timezone.utc)
    log = tmp_path / "m.jsonl"
    log.write_text("\n".join([_miss(now - timedelta(hours=1)), _miss(now - timedelta(hours=2), key="o/other"), "garbage"]) + "\n")
    r = hc.check_trigger_coverage(log, now=now)
    assert r["id"] == "triggers:missed" and r["severity"] == "yellow"
    assert r["value"] == 2 and "o/r" in r["detail"] and "o/other" in r["detail"]


# ── project catalog freshness ────────────────────────────────────────────────

def test_catalog_check_is_green_when_fresh_amber_when_stale_red_when_missing_or_ancient(tmp_path):
    now = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)
    f = tmp_path / "projects.dev.json"

    def write(age_h):
        f.write_text(json.dumps({"generated_at": (now - timedelta(hours=age_h)).isoformat(), "projects": [{}] * 30}))

    write(1)
    assert hc.check_catalog_fresh(f, now=now)["severity"] == "green"
    write(6)
    assert hc.check_catalog_fresh(f, now=now)["severity"] == "yellow"
    write(40)
    assert hc.check_catalog_fresh(f, now=now)["severity"] == "red"
    assert hc.check_catalog_fresh(tmp_path / "none.json", now=now)["severity"] == "yellow"
    r = hc.check_catalog_fresh(f, now=now)
    assert r["id"] == "catalog:fresh" and "30" in r["detail"]


def test_machine_state_parity_checks_docs_background_and_data():
    st = hc.parse_machine_state("docs_access=failed\ndesktoplive=stopped\nbrain_data_ts=%d\n" % int((NOW - timedelta(days=9)).timestamp()))
    res = {k: s for k, s, _ in hc.evaluate_machine_state(_mstate(**{k: st[k] for k in ("docs_access", "desktoplive", "brain_data_ts")}), NOW)}
    assert res["docs:access"] == "red" and res["desktoplive:running"] == "yellow" and res["brainmap:data"] == "yellow"
    ok = {k: s for k, s, _ in hc.evaluate_machine_state(_mstate(docs_access="ok", desktoplive="running", brain_data_ts=int(NOW.timestamp())), NOW)}
    assert ok["docs:access"] == ok["desktoplive:running"] == ok["brainmap:data"] == "green"


def test_job_placement_flags_missing_stray_and_unplaced_jobs():
    laptop_jobs = [j for j, w in hc.JOB_PLACEMENT.items() if w in ("both", "laptop")]
    assert hc.evaluate_job_placement(laptop_jobs, "laptop")[0] == "green"
    sev, detail = hc.evaluate_job_placement(laptop_jobs + ["architecture-review", "brand-new"], "laptop")
    assert sev == "yellow" and "architecture-review" in detail and "brand-new" in detail
    sev, detail = hc.evaluate_job_placement([j for j in laptop_jobs if j != "code-sync-push"], "laptop")
    assert sev == "yellow" and "missing: code-sync-push" in detail


# ── GitHub request budget (the pipeline, merge gate and dashboard all draw on one hourly allowance) ──

def _budget(remaining, limit=5000, reset="2026-10-06T05:00:00Z"):
    return lambda: {"limit": limit, "remaining": remaining, "resetAt": reset}


def test_github_budget_is_green_with_plenty_left():
    r = hc.check_github_budget(query=_budget(4200))
    assert r["id"] == "github:budget" and r["severity"] == "green"
    assert "4,200 of 5,000" in r["detail"] and "resets 05:00 UTC" in r["detail"]


def test_github_budget_warns_when_low_and_goes_red_near_empty():
    assert hc.check_github_budget(query=_budget(900))["severity"] == "yellow"
    assert hc.check_github_budget(query=_budget(150))["severity"] == "red"
    r = hc.check_github_budget(query=_budget(0))
    assert r["severity"] == "red" and "resets" in r["detail"]


def test_github_budget_says_so_when_exhausted_makes_the_query_itself_fail():
    def boom():
        raise RuntimeError("GraphQL: API rate limit already exceeded for user ID 1")
    r = hc.check_github_budget(query=boom)
    assert r["severity"] == "red" and "exhausted" in r["detail"].lower()


def test_github_budget_is_yellow_not_red_when_it_simply_cannot_be_read():
    def offline():
        raise RuntimeError("could not resolve host")
    r = hc.check_github_budget(query=offline)
    assert r["severity"] == "yellow"


# ── disk space: found 2026-10-06 the mac-mini at 94% full (13 GiB free) with nothing
# watching -- leaked pipeline worktrees, and iCloud then evicting the files jobs read.

def test_parse_machine_state_reads_disk_and_worktrees():
    st = hc.parse_machine_state("disk_free_kb=13631488\ndisk_total_kb=239075328\nworktrees_kb=41104384\nworktrees_n=33\n")
    assert st["disk_free_kb"] == 13631488 and st["disk_total_kb"] == 239075328
    assert st["worktrees_kb"] == 41104384 and st["worktrees_n"] == 33


@pytest.mark.parametrize("free_pct,expected", [(30, "green"), (15, "yellow"), (6, "red")])
def test_disk_space_severity_by_free_share(free_pct, expected):
    total = 100 * 1024 * 1024
    res = dict((k, (s, d)) for k, s, d in hc.evaluate_machine_state(
        _mstate(disk_free_kb=total * free_pct // 100, disk_total_kb=total, worktrees_kb=2 * 1024 * 1024, worktrees_n=4), NOW))
    sev, detail = res["disk:space"]
    assert sev == expected
    assert "GiB free" in detail and "4 pipeline worktrees" in detail


def test_no_disk_reading_means_no_disk_check():
    assert "disk:space" not in dict((k, s) for k, s, _ in hc.evaluate_machine_state(_mstate(), NOW))


# ── job exit codes: found 2026-10-06 the laptop tidy-agent failing nightly since 2026-07-13
# (PermissionError, no Full Disk Access) with nothing watching -- health-check runs on the
# mini and only scanned the mini's own logs. launchd's last exit code is read on every machine.

def test_parse_machine_state_reads_job_exits():
    st = hc.parse_machine_state("job_exits=com.giles.tidy-agent:-:1,com.marvin.desktoplive:1163:0,\n")
    assert st["job_exits"] == [("com.giles.tidy-agent", None, 1), ("com.marvin.desktoplive", 1163, 0)]


def test_job_that_last_exited_nonzero_and_is_not_running_is_red():
    res = dict((k, (s, d)) for k, s, d in hc.evaluate_machine_state(
        _mstate(job_exits=[("com.giles.tidy-agent", None, 1), ("com.marvin.daily-digest", None, 0)]), NOW))
    sev, detail = res["jobs:exit"]
    assert sev == "red"
    assert "com.giles.tidy-agent" in detail and "exit 1" in detail and "daily-digest" not in detail


def test_running_job_with_old_nonzero_status_is_green():
    # a KeepAlive job restarted by SIGTERM reports -15 while its new instance runs
    res = dict((k, (s, d)) for k, s, d in hc.evaluate_machine_state(
        _mstate(job_exits=[("com.marvin.dashboard-webhook", 10952, -15), ("com.giles.tidy-agent", None, 0)]), NOW))
    assert res["jobs:exit"][0] == "green"


def test_no_job_exit_reading_means_no_exit_check():
    assert "jobs:exit" not in dict((k, s) for k, s, _ in hc.evaluate_machine_state(_mstate(), NOW))


def test_machine_state_script_reports_giles_and_marvin_job_exits():
    assert "job_exits=" in hc._MACHINE_STATE_SCRIPT and "giles" in hc._MACHINE_STATE_SCRIPT


# ── main branch health ──

def test_main_is_green_when_its_last_check_passed(tmp_path):
    import json
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"sha": "abc1234", "ok": True, "failed": [], "summary": "1137 passed", "checked_at": hc._now().isoformat()}))
    r = hc.check_main_health(path=p)
    assert r["id"] == "main:green" and r["severity"] == "green" and "abc1234" in r["detail"]


def test_main_is_red_and_names_the_failing_tests(tmp_path):
    import json
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"sha": "def5678", "ok": False, "failed": ["tests/test_a.py::test_x"], "summary": "1 failed", "checked_at": hc._now().isoformat()}))
    r = hc.check_main_health(path=p)
    assert r["severity"] == "red"
    assert "tests/test_a.py::test_x" in r["detail"] and "merges" in r["detail"].lower()


def test_main_health_is_yellow_when_never_checked_or_stale(tmp_path):
    import json
    assert hc.check_main_health(path=tmp_path / "missing.json")["severity"] == "yellow"
    p = tmp_path / "old.json"
    p.write_text(json.dumps({"sha": "a", "ok": True, "failed": [], "summary": "ok", "checked_at": (hc._now() - timedelta(days=2)).isoformat()}))
    assert hc.check_main_health(path=p)["severity"] == "yellow"


# ── parallel dispatch: keeping up with the queue ──────────────────────────────

def test_parallel_dispatch_green_when_off():
    settings = {"parallel": False, "max_total": 2, "max_per_project": 1}
    pools = {"G-Eskayo/marvin": []}
    inflight = {"G-Eskayo/marvin": 0}
    sev, detail = hc.evaluate_parallel_dispatch(settings, pools, inflight, 0, lambda *a, **k: None)
    assert sev == "green" and "off" in detail.lower()


def test_parallel_dispatch_green_when_all_slots_busy():
    settings = {"parallel": True, "max_total": 2, "max_per_project": 1, "machine_slots": {"mac-mini-1": 2}}
    pools = {"G-Eskayo/marvin": [{"number": 1}]}
    inflight = {"G-Eskayo/marvin": 2}
    sev, detail = hc.evaluate_parallel_dispatch(settings, pools, inflight, 0, lambda *a, **k: None)
    assert sev == "green" and "2 of 2" in detail


def test_parallel_dispatch_green_when_nothing_waiting():
    settings = {"parallel": True, "max_total": 2, "max_per_project": 1}
    pools = {"G-Eskayo/marvin": []}
    inflight = {"G-Eskayo/marvin": 0}
    sev, detail = hc.evaluate_parallel_dispatch(settings, pools, inflight, 0, lambda *a, **k: None)
    assert sev == "green" and "nothing waiting" in detail.lower()


def test_parallel_dispatch_yellow_project_at_limit():
    settings = {"parallel": True, "max_total": 2, "max_per_project": 1}
    pools = {"G-Eskayo/marvin": [{"number": 1}]}
    inflight = {"G-Eskayo/marvin": 1}
    sev, detail = hc.evaluate_parallel_dispatch(settings, pools, inflight, 0, lambda *a, **k: None)
    assert sev == "yellow" and "project at its limit" in detail.lower()


def test_parallel_dispatch_yellow_guard_refusal():
    settings = {"parallel": True, "max_total": 2, "max_per_project": 1}
    pools = {"G-Eskayo/marvin": [{"number": 1}]}
    inflight = {"G-Eskayo/marvin": 0}
    refusals = ["disk 9 GB free on mac-mini-1, minimum 15"]

    def stub_select(profile, s, taken=None, local_base=0, refusals=None):
        if refusals is not None:
            refusals.extend(["disk 9 GB free on mac-mini-1, minimum 15"])
        return None

    sev, detail = hc.evaluate_parallel_dispatch(settings, pools, inflight, 0, stub_select)
    assert sev == "yellow" and "guard refusal" in detail


def test_parallel_dispatch_yellow_no_suitable_machine():
    settings = {"parallel": True, "max_total": 2, "max_per_project": 1}
    pools = {"G-Eskayo/marvin": [{"number": 1}]}
    inflight = {"G-Eskayo/marvin": 0}

    def stub_select(profile, s, taken=None, local_base=0, refusals=None):
        if refusals is not None:
            refusals.append("mac-mini-1 is full: 2 of 2 slots in use")
        return None

    sev, detail = hc.evaluate_parallel_dispatch(settings, pools, inflight, 0, stub_select)
    assert sev == "yellow" and "no suitable machine" in detail


def test_parallel_dispatch_yellow_nothing_eligible_on_unrecognized_refusal():
    settings = {"parallel": True, "max_total": 2, "max_per_project": 1}
    pools = {"G-Eskayo/marvin": [{"number": 1}]}
    inflight = {"G-Eskayo/marvin": 0}

    def stub_select(profile, s, taken=None, local_base=0, refusals=None):
        if refusals is not None:
            refusals.append("some unrecognized refusal shape")
        return None

    sev, detail = hc.evaluate_parallel_dispatch(settings, pools, inflight, 0, stub_select)
    assert sev == "yellow" and "nothing eligible" in detail


def test_classify_stall_reason_guard_refusal():
    assert hc._classify_stall_reason(["disk 9 GB free, minimum 15"]) == "guard refusal"
    assert hc._classify_stall_reason(["GitHub request budget 5% left, minimum 20%"]) == "guard refusal"
    assert hc._classify_stall_reason(["circuit breaker tripped for foo"]) == "guard refusal"
    assert hc._classify_stall_reason(["lacks tools: python"]) == "guard refusal"


def test_classify_stall_reason_no_suitable_machine():
    assert hc._classify_stall_reason([]) == "no suitable machine"
    assert hc._classify_stall_reason(["mac-mini-1 is full: 2 of 2 slots in use"]) == "no suitable machine"


def test_classify_stall_reason_nothing_eligible():
    assert hc._classify_stall_reason(["unknown refusal type"]) == "nothing eligible"


def test_parallel_dispatch_green_when_idle_slot_and_selectable():
    settings = {"parallel": True, "max_total": 2, "max_per_project": 1}
    pools = {"G-Eskayo/marvin": [{"number": 1}]}
    inflight = {"G-Eskayo/marvin": 0}

    def stub_select(profile, s, taken=None, local_base=0, refusals=None):
        return ("mac-mini-1", {"is_self": True})

    sev, detail = hc.evaluate_parallel_dispatch(settings, pools, inflight, 0, stub_select)
    assert sev == "green" and "idle slot" in detail.lower()


def test_run_all_includes_parallel_dispatch_check(monkeypatch):
    import dispatch_concurrency
    monkeypatch.setattr(dispatch_concurrency, "load", lambda path=None: {"parallel": False})
    monkeypatch.setattr(hc.mr, "latest", lambda subsystem: None)
    monkeypatch.setattr(hc.mr, "record", lambda subsystem, metrics: None)
    monkeypatch.setattr(hc.mr, "compare", lambda subsystem, baseline, current: None)
    out = hc.run_all()
    check_ids = {r["id"] for r in out["checks"]}
    assert "dispatch:parallel" in check_ids


# ── pipeline circuit breaker (cross-machine) ───────────────────────────────

def test_check_pipeline_breaker_includes_local_trips(monkeypatch):
    import failure_breaker as fb
    monkeypatch.setattr(fb, "tripped", lambda now=None, project=None: [
        {"project": "G-Eskayo/marvin", "signature": "vitest-no-summary", "tickets": [32, 35],
         "first_seen": "2026-10-02T01:00:00+00:00", "last_seen": "2026-10-02T01:02:00+00:00", "example": "e"}])
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    r = hc.check_pipeline_breaker()
    assert r["severity"] == "red"
    assert "paused" in r["detail"].lower()
    assert "vitest-no-summary" in r["detail"]
    assert "2026-10-02T01:00:00" in r["detail"]


def test_pipeline_breaker_remote_query_handles_unreachable_machines(monkeypatch):
    import failure_breaker as fb
    monkeypatch.setattr(fb, "tripped", lambda now=None, project=None: [])
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {
        "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "lap"}})

    def fail_ssh(*a, **k):
        class Fail:
            returncode = 255
            stdout = ""
        return Fail()

    monkeypatch.setattr(hc.subprocess, "run", fail_ssh)
    r = hc.check_pipeline_breaker()
    assert r["severity"] == "green"


# ── sync stuck detection ────────────────────────────────────────────────────

def test_parse_sync_log_entries_extracts_machine_repo_and_status():
    text = """## 2026-10-02T12:00:00Z — push-sync (mac-mini-1) [~/.agents]
REFUSING to push due to unresolved merge conflict
## 2026-10-02T11:00:00Z — pull-sync (mac-mini-1) [~/.agents]
pulled successfully
## 2026-10-02T10:00:00Z — push-sync (macbook-pro-1) [~/.claude]
CONFLICT detected in working tree
"""
    entries = hc._parse_sync_log_entries(text)
    assert len(entries) == 3
    assert entries[0] == ("mac-mini-1", "~/.agents", "REFUSING to push due to unresolved merge conflict",
                          datetime(2026, 10, 2, 12, 0, 0, tzinfo=timezone.utc))
    assert entries[1][2] == "pulled successfully"
    assert entries[2][1] == "~/.claude"


def test_check_sync_stuck_green_when_no_stuck_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "sync-log.md").write_text("""## 2026-10-02T12:00:00Z — push-sync (mac-mini-1) [~/.agents]
pushed successfully
""")
    results = hc.check_sync_stuck()
    assert not results


def test_check_sync_stuck_yellow_when_stuck_between_30min_and_4hours(monkeypatch, tmp_path):
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc, "_now", lambda: now)
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    (tmp_path / ".claude").mkdir()
    # Stuck for 1 hour, which is between 30min (yellow threshold) and 4 hours (red threshold)
    (tmp_path / ".claude" / "sync-log.md").write_text(f"""## {(now - timedelta(hours=1)).isoformat()} — push-sync (mac-mini-1) [~/.agents]
REFUSING to push due to unresolved conflict
""")
    results = hc.check_sync_stuck()
    assert len(results) == 1
    assert results[0]["severity"] == "yellow"
    assert "~/.agents" in results[0]["detail"]


def test_check_sync_stuck_red_when_stuck_over_4_hours(monkeypatch, tmp_path):
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc, "_now", lambda: now)
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    (tmp_path / ".claude").mkdir()
    # Stuck for 6 hours, which exceeds 4 hour red threshold
    (tmp_path / ".claude" / "sync-log.md").write_text(f"""## {(now - timedelta(hours=6)).isoformat()} — push-sync (mac-mini-1) [~/.agents]
CONFLICT in working tree
""")
    results = hc.check_sync_stuck()
    assert len(results) == 1
    assert results[0]["severity"] == "red"


# ── deploy steps check ──────────────────────────────────────────────────────

def test_check_deploy_steps_green_when_plist_exists_and_job_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc, "LAUNCHAGENTS_DIR", tmp_path / "Library" / "LaunchAgents")
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    agents = tmp_path / ".claude" / "logs" / "jobs"
    agents.mkdir(parents=True)
    (agents / "snapshot-deploy.json").write_text("{}")
    launchagents = tmp_path / "Library" / "LaunchAgents"
    launchagents.mkdir(parents=True)
    (launchagents / "com.marvin.snapshot-deploy-nightly.plist").write_text("")
    (launchagents / "com.marvin.snapshot-deploy-reactive.plist").write_text("")

    results = hc.check_deploy_steps()
    snap = [r for r in results if "snapshot-deploy" in r["id"]]
    assert snap and all(r["severity"] == "green" for r in snap)


def test_check_deploy_steps_red_when_plist_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc, "LAUNCHAGENTS_DIR", tmp_path / "Library" / "LaunchAgents")
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    launchagents = tmp_path / "Library" / "LaunchAgents"
    launchagents.mkdir(parents=True)

    results = hc.check_deploy_steps()
    snap = [r for r in results if "snapshot-deploy" in r["id"]]
    assert snap and any(r["severity"] == "red" and "not installed" in r["detail"] for r in snap)


def test_check_deploy_steps_red_when_job_never_ran(tmp_path, monkeypatch):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc, "LAUNCHAGENTS_DIR", tmp_path / "Library" / "LaunchAgents")
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {})
    launchagents = tmp_path / "Library" / "LaunchAgents"
    launchagents.mkdir(parents=True)
    (launchagents / "com.marvin.snapshot-deploy-nightly.plist").write_text("")
    (launchagents / "com.marvin.snapshot-deploy-reactive.plist").write_text("")

    results = hc.check_deploy_steps()
    snap = [r for r in results if "snapshot-deploy" in r["id"]]
    assert snap and any(r["severity"] == "red" and "never actually run" in r["detail"] for r in snap)


def test_check_parallel_dispatch_calls_the_real_selector_with_its_keywords(monkeypatch):
    """Regression: the wrapper in check_parallel_dispatch named its params (s, t, l, rf) while
    evaluate_parallel_dispatch calls it with taken=/local_base=/refusals=, so every run raised
    TypeError and health-status.json was never written. Exercise the real wiring end to end."""
    import dispatch_concurrency
    import failure_breaker
    import project_profile as pp
    import ticket_pipeline as tp

    calls = []

    def real_shaped_select(profile, settings=None, taken=None, local_base=0, refusals=None):
        calls.append({"taken": taken, "local_base": local_base})
        return "mac-mini-1"

    monkeypatch.setattr(dispatch_concurrency, "load", lambda: {"parallel": True, "max_total": 2, "max_per_project": 1})
    monkeypatch.setattr(pp, "dispatchable_repos", lambda: [])
    monkeypatch.setattr(failure_breaker, "tripped", lambda: [])
    monkeypatch.setattr(tp, "_unclaimed_ready_tickets", lambda repo: [{"number": 1}])
    monkeypatch.setattr(tp, "_inflight_by_repo", lambda repos: {r: 0 for r in repos})
    monkeypatch.setattr(tp, "_local_slots_used", lambda: 0)
    monkeypatch.setattr(tp, "_select_for_profile", real_shaped_select)

    result = hc.check_parallel_dispatch()

    assert calls, "selector was never reached"
    assert result["severity"] in {"green", "yellow", "red"}


# ── project tags (ADR 0060, #298) ───────────────────────────────────────────

def _tags(tmp_path, unclear=(), pending=0, at="2026-10-08T12:00:00+00:00"):
    f = tmp_path / "project-tags.json"
    f.write_text(json.dumps({"generated_at": at, "pending": pending, "unclear": list(unclear)}))
    return f


def test_project_tags_green_when_every_ticket_is_where_it_belongs(tmp_path):
    now = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
    assert hc.check_project_tags(_tags(tmp_path), now=now)["severity"] == "green"


def test_project_tags_lists_unclear_tickets_by_number_and_title(tmp_path):
    now = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
    u = {"repo": "G-Eskayo/marvin", "number": 7, "title": "APNs on the MARVIN page", "candidates": ["marvin-mobile", "portfolio-website-updater"]}
    r = hc.check_project_tags(_tags(tmp_path, [u]), now=now)
    assert r["severity"] == "yellow" and r["value"] == 1
    assert "marvin#7 APNs on the MARVIN page" in r["detail"] and "marvin-mobile or portfolio-website-updater" in r["detail"]


def test_project_tags_red_when_drift_grows(tmp_path):
    now = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
    assert hc.check_project_tags(_tags(tmp_path, pending=hc.PROJECT_TAGS_RED_AT), now=now)["severity"] == "red"


def test_project_tags_yellow_when_missing_or_stale(tmp_path):
    now = datetime(2026, 10, 8, 23, tzinfo=timezone.utc)
    assert hc.check_project_tags(tmp_path / "none.json", now=now)["severity"] == "yellow"
    assert "hours" in hc.check_project_tags(_tags(tmp_path), now=now)["detail"]


# ── GitHub gate (bin/gh) ────────────────────────────────────────────────────

def _gate(tmp_path, rows, state=None):
    log = tmp_path / "gh-calls.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    st = tmp_path / "gh-gate.json"
    st.write_text(json.dumps(state or {}))
    return log, st


def test_gh_gate_green_shows_who_used_github_in_the_last_hour(tmp_path):
    now = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
    t = now.timestamp()
    rows = [{"t": t - 60, "caller": "com.marvin.ticket-pipeline", "rc": 0}] * 3 + [{"t": t - 30, "caller": "MARVIN Metrics", "rc": 0},
            {"t": t - 7200, "caller": "old", "rc": 0}]
    r = hc.check_gh_gate(*_gate(tmp_path, rows), now=now)
    assert r["severity"] == "green" and r["value"] == 4
    assert "ticket-pipeline 3" in r["detail"] and "old" not in r["detail"]


def test_gh_gate_red_during_a_cooldown_and_yellow_after_refusals(tmp_path):
    now = datetime(2026, 10, 8, 13, tzinfo=timezone.utc)
    t = now.timestamp()
    rows = [{"t": t - 60, "caller": "x", "rc": 1, "refused": "burst"}, {"t": t - 50, "caller": "y", "rc": 75, "deferred": "defer"}]
    red = hc.check_gh_gate(*_gate(tmp_path, rows, {"cooldown_until": t + 90, "reason": "burst"}), now=now)
    assert red["severity"] == "red" and "cooling down" in red["detail"]
    yellow = hc.check_gh_gate(*_gate(tmp_path, rows, {"cooldown_until": t - 10}), now=now)
    assert yellow["severity"] == "yellow" and "1 refused" in yellow["detail"] and "1 deferred" in yellow["detail"]


def test_gh_gate_yellow_when_not_installed(tmp_path):
    r = hc.check_gh_gate(tmp_path / "none.jsonl", tmp_path / "none.json", now=datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert r["severity"] == "yellow"


def test_missed_purposes_are_red_and_an_unreadable_list_is_yellow():
    red = hc.check_missed_purposes(lambda: [{"number": 277, "title": "Allow read-only tools", "state": "closed"}])
    assert red[0]["severity"] == "red" and "#277 Allow read-only tools" in red[0]["detail"]
    assert hc.check_missed_purposes(lambda: [])[0]["severity"] == "green"
    assert hc.check_missed_purposes(lambda: (_ for _ in ()).throw(OSError("rate limited")))[0]["severity"] == "yellow"


def test_output_contracts_reach_health(monkeypatch):
    import output_contracts
    monkeypatch.setattr(output_contracts, "health_findings", lambda: [{"id": "contract:x", "severity": "red"}])
    assert hc.check_output_contracts() == [{"id": "contract:x", "severity": "red"}]
