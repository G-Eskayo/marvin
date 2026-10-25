"""Health P0 (plan docs/plans/health-metrics-redo-2026-10-21.md §9, PR #577): one failing check can never take the sweep
down, Health's history never goes into git again, and the dead checks are gone.

Measured 2026-10-21: 3 of the Mini's last 20 sweeps died on one uncaught ssh TimeoutExpired, and health-status.json then
showed old data as if current. 191 of ~200 auto-sync commits since 10-17 were bench/metrics/health-monitor.*, written by
an anomaly compare nothing displayed. These tests try to break both fixes. HOME is the suite's temp home (conftest.py).
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
REPO = LIB.parent
sys.path.insert(0, str(LIB))

import code_sync as cs  # noqa: E402
import health_checks as hc  # noqa: E402


def _boom_timeout():
    raise subprocess.TimeoutExpired(["ssh", "laptop", "bash -s"], 10)


# ── each check is guarded ────────────────────────────────────────────────

def test_a_check_that_raises_becomes_one_couldnt_measure_row_with_the_reason():
    rows = hc.guarded("pipeline:breaker", "Ticket pipeline circuit breaker", _boom_timeout, budget_s=5)
    assert len(rows) == 1
    r = rows[0]
    assert r["id"] == "pipeline:breaker"  # same id as a good result, so it replaces the old card instead of sitting beside it
    assert r["severity"] == hc.UNKNOWN
    assert r["measured"] is False
    assert r["detail"].startswith("couldn't measure")
    assert "TimeoutExpired" in r["detail"]
    assert r["checked_at"]


def test_a_check_that_hangs_is_cut_off_at_its_budget_and_the_sweep_moves_on():
    release = threading.Event()

    def hang():
        release.wait(30)
        return hc._result("x", "x", "green", "late")

    t0 = time.monotonic()
    rows = hc.guarded("slow:check", "Slow check", hang, budget_s=0.3)
    elapsed = time.monotonic() - t0
    release.set()
    assert elapsed < 3, f"guard waited {elapsed:.1f}s on a hung check"
    assert rows[0]["severity"] == hc.UNKNOWN and "timed out after" in rows[0]["detail"]


def test_a_check_returning_garbage_is_reported_not_trusted():
    for bad in ("green", 42, [{"no": "id"}], {"id": "x"}):
        rows = hc.guarded("weird:check", "Weird", lambda bad=bad: bad, budget_s=5)
        assert [r["severity"] for r in rows] == [hc.UNKNOWN], bad


def test_good_results_pass_through_untouched_and_none_means_nothing_to_report():
    one = hc._result("a", "A", "green", "fine")
    assert hc.guarded("a", "A", lambda: one, budget_s=5) == [one]
    two = [hc._result("b1", "B", "red", "x"), hc._result("b2", "B", "yellow", "y")]
    assert hc.guarded("b", "B", lambda: two, budget_s=5) == two
    assert hc.guarded("seal:beta-ingest", "Seal", lambda: None, budget_s=5) == []


def test_one_failing_check_never_stops_the_others():
    specs = [
        ("first", "First", lambda: hc._result("first", "First", "green", "ok"), 5),
        ("broken", "Broken", _boom_timeout, 5),
        ("last", "Last", lambda: hc._result("last", "Last", "red", "real problem"), 5),
    ]
    rows = hc.run_checks(specs)
    assert [r["id"] for r in rows] == ["first", "broken", "last"]
    assert [r["severity"] for r in rows] == ["green", hc.UNKNOWN, "red"]


def test_a_sweep_with_a_crashing_check_still_writes_status_and_never_leaves_old_data(tmp_path, monkeypatch):
    status_path = tmp_path / "health-status.json"
    status_path.write_text(json.dumps({"generated_at": "2026-10-15T19:40:17+00:00", "overall": "green", "checks": []}))
    monkeypatch.setattr(hc, "STATUS_PATH", status_path)
    monkeypatch.setattr(hc, "coverage", lambda results: {"known_jobs": [], "unmonitored_jobs": [], "covered": 0, "total": 0, "fraction": 1.0})
    specs = [("ok", "OK", lambda: hc._result("ok", "OK", "green", "fine"), 5), ("sync:stuck", "Code sync", _boom_timeout, 5)]
    out = hc.write_status(hc.run_all(checks=specs, recent_errors=[]))
    written = json.loads(status_path.read_text())
    assert written["generated_at"] == out["generated_at"] != "2026-10-15T19:40:17+00:00"
    assert {r["id"]: r["severity"] for r in written["checks"]} == {"ok": "green", "sync:stuck": hc.UNKNOWN}


def test_status_is_written_atomically_never_half_a_file(tmp_path, monkeypatch):
    status_path = tmp_path / "health-status.json"
    monkeypatch.setattr(hc, "STATUS_PATH", status_path)
    hc.write_status({"generated_at": "t", "overall": "green", "checks": []})
    assert json.loads(status_path.read_text())["overall"] == "green"
    assert [p.name for p in tmp_path.iterdir()] == ["health-status.json"]  # no temp file left behind


def test_couldnt_measure_reads_as_degraded_overall_never_green_and_never_red():
    assert hc.overall_severity(["green", hc.UNKNOWN]) == "yellow"
    assert hc.overall_severity([hc.UNKNOWN, hc.UNKNOWN]) == "yellow"
    assert hc.overall_severity(["red", hc.UNKNOWN]) == "red"
    assert hc.overall_severity(["green", "asleep"]) == "green"


# ── remote reads skip asleep Macs and survive ssh failures ───────────────

def test_breaker_skips_an_unreachable_mac_instead_of_hanging_on_it(monkeypatch):
    import failure_breaker
    monkeypatch.setattr(failure_breaker, "tripped", lambda: [])
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {"macbook-pro-1": {"tailscale_hostname": "laptop"}})
    calls = []
    r = hc.check_pipeline_breaker(reachability={"machine:macbook-pro-1": "asleep"}, remote=lambda host: calls.append(host) or [])
    assert calls == [] and r["severity"] == "green"


def test_breaker_reports_a_mac_it_couldnt_read_instead_of_crashing(monkeypatch):
    import failure_breaker
    monkeypatch.setattr(failure_breaker, "tripped", lambda: [])
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {"macbook-pro-1": {"tailscale_hostname": "laptop"}})

    def remote(host):
        raise subprocess.TimeoutExpired(["ssh", host], 10)

    r = hc.check_pipeline_breaker(reachability={"machine:macbook-pro-1": "green"}, remote=remote)
    assert r["severity"] == hc.UNKNOWN and "macbook-pro-1" in r["detail"]


def test_sync_stuck_skips_unreachable_macs_and_marks_unreadable_ones(monkeypatch, tmp_path):
    monkeypatch.setattr(hc, "HOME", tmp_path)
    monkeypatch.setattr(hc.machine_profile, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(hc.machine_profile, "remote_devices", lambda: {
        "macbook-pro-1": {"tailscale_hostname": "laptop"}, "mac-mini-2012": {"tailscale_hostname": "old"}})
    seen = []

    def remote(host):
        seen.append(host)
        raise subprocess.TimeoutExpired(["ssh", host], 10)

    rows = hc.check_sync_stuck(reachability={"machine:macbook-pro-1": "asleep", "machine:mac-mini-2012": "green"}, remote=remote)
    assert seen == ["old"]
    assert [(r["id"], r["severity"]) for r in rows] == [("sync:stuck@mac-mini-2012", hc.UNKNOWN)]


# ── dead and false checks are gone ───────────────────────────────────────

def test_the_dead_and_false_checks_are_deleted():
    for name in ("check_ticket_failure_streaks", "check_deploy_steps", "DECLARED_DEPLOY_STEPS", "check_repo_integrity",
                 "record_anomaly_metrics", "anomaly_or_red", "HIGHER_IS_BETTER"):
        assert not hasattr(hc, name), name
    assert "contents/README.md" not in hc._MACHINE_STATE_SCRIPT  # docs:access spent 3 GitHub calls a sweep on auth:gh's question
    assert "brain_data_ts" not in hc._MACHINE_STATE_SCRIPT


def test_machine_state_no_longer_yields_docs_access_or_brainmap_age():
    st = hc.parse_machine_state("gh_token=ok\ndesktoplive=running\n")
    st.update(app_built_ts=None, dashboard_commit_ts=None, webhook_server_start_ts=None, webhook_commit_ts=None)
    keys = {k for k, _, _ in hc.evaluate_machine_state(st, hc._now())}
    assert "docs:access" not in keys and "brainmap:data" not in keys
    assert {"auth:gh", "desktoplive:running"} <= keys


def test_the_default_sweep_lists_no_deleted_check_and_every_entry_has_a_budget():
    ids = [s[0] for s in hc.default_checks()]
    assert len(ids) == len(set(ids))
    for gone in ("ticket:streak", "deploy:missing", "repo:integrity", "health:anomaly-metrics"):
        assert not any(i.startswith(gone) for i in ids), gone
    assert all(isinstance(s[3], (int, float)) and 0 < s[3] <= 300 for s in hc.default_checks())


# ── Health's history never goes into git ─────────────────────────────────

def test_a_sweep_never_writes_bench_metrics(tmp_path, monkeypatch):
    import metrics_registry as mr
    monkeypatch.setattr(mr, "METRICS_DIR", tmp_path / "metrics")
    monkeypatch.setattr(hc, "STATUS_PATH", tmp_path / "health-status.json")
    monkeypatch.setattr(hc, "coverage", lambda results: {"known_jobs": [], "unmonitored_jobs": [], "covered": 0, "total": 0, "fraction": 1.0})
    specs = [("n", "N", lambda: hc._result("n", "N", "green", "x", value=7), 5)]
    out = hc.run_all(checks=specs, recent_errors=[])
    assert not (tmp_path / "metrics").exists()
    assert "anomaly" not in out


def test_the_health_history_files_are_ignored_in_this_repo():
    """Ignored now; untracked in a follow-up once both Macs run this code. Untracking in the same change would let a Mac
    still on the old writer commit the file, then hit a modify/delete conflict on its next pull and stop syncing."""
    for name in ("health-monitor.mac-mini.json", "health-monitor.macbook-pro.md", "health-monitor.json", "health-monitor.md"):
        ignored = subprocess.run(["git", "check-ignore", "--no-index", "-q", f"bench/metrics/{name}"], cwd=REPO)
        assert ignored.returncode == 0, name
    # ADR 0071: all of bench/metrics is ignored in the public engine now; ticket metrics are committed to the private
    # instance (~/.agents/instance/bench/metrics/) instead.
    moved = subprocess.run(["git", "check-ignore", "--no-index", "-q", "bench/metrics/clarity-captions-ticket-10.json"], cwd=REPO)
    assert moved.returncode == 0


def test_nothing_in_lib_writes_the_health_history_any_more():
    offenders = [p.name for p in LIB.glob("*.py") if 'record("health-monitor"' in p.read_text() or "mr.record(\"health-monitor\"" in p.read_text()]
    assert offenders == []


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def _origin_and_clone_tracking_health_history(tmp_path: Path) -> Path:
    """A Mac that hasn't pulled the untrack commit yet: the history file is tracked and nothing ignores it."""
    origin = tmp_path / "origin.git"
    origin.mkdir()
    _git(origin, "init", "--bare", "-b", "main")
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    _git(seed, "config", "user.email", "t@example.com")
    _git(seed, "config", "user.name", "T")
    (seed / "sync-log.md").write_text("# log\n")
    (seed / "file.md").write_text("v1\n")
    (seed / "bench" / "metrics").mkdir(parents=True)
    (seed / "bench" / "metrics" / "health-monitor.mac-mini.json").write_text("[]\n")
    (seed / "bench" / "metrics" / "clarity-captions-ticket-10.json").write_text("[]\n")
    _git(seed, "add", "-A")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "push", str(origin), "main")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", str(origin), str(clone)], check=True, capture_output=True)
    _git(clone, "config", "user.email", "t@example.com")
    _git(clone, "config", "user.name", "T")
    return clone


def test_code_sync_never_commits_health_history_even_where_it_is_still_tracked(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    clone = _origin_and_clone_tracking_health_history(tmp_path)
    (clone / "bench" / "metrics" / "health-monitor.mac-mini.json").write_text('[{"t": 1}]\n')
    (clone / "bench" / "metrics" / "health-monitor.mac-mini.md").write_text("# new narrative\n")
    (clone / "file.md").write_text("v2\n")
    cs.push(clone)
    origin = tmp_path / "origin.git"
    files = _git(origin, "show", "--name-only", "--format=", "main").split()
    assert files == ["file.md"]


def test_code_sync_makes_no_commit_when_only_health_history_changed(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    clone = _origin_and_clone_tracking_health_history(tmp_path)
    before = _git(clone, "rev-parse", "HEAD")
    (clone / "bench" / "metrics" / "health-monitor.mac-mini.json").write_text('[{"t": 2}]\n')
    cs.push(clone)
    assert _git(clone, "rev-parse", "HEAD") == before
    assert _git(tmp_path / "origin.git", "rev-parse", "main") == before


def test_code_sync_still_commits_ticket_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "LOG_PATH", tmp_path / "log.md")
    monkeypatch.setattr(cs, "notify", lambda *a, **kw: None)
    clone = _origin_and_clone_tracking_health_history(tmp_path)
    (clone / "bench" / "metrics" / "clarity-captions-ticket-10.json").write_text('[{"t": 3}]\n')
    cs.push(clone)
    files = _git(tmp_path / "origin.git", "show", "--name-only", "--format=", "main").split()
    assert files == ["bench/metrics/clarity-captions-ticket-10.json"]
