"""The one alert path (mr_notification.py, #1123, ADR 0083). Tests try to break it: a channel that throws, hangs up or
lies; every channel failing; the record failing; memory that is corrupt, old-format or written by another version; a
flapping state; a thousand red checks at once.
Run: ~/.agents/venv/bin/python -m pytest lib/tests/test_mr_notification.py -v"""
from __future__ import annotations
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import job_events  # noqa: E402
import mr_notification as mn  # noqa: E402

D0 = date(2026, 11, 4)


@pytest.fixture
def chans(monkeypatch, tmp_path):
    """Fake channels that record calls; job_events writes into tmp (the suite's conftest also does)."""
    calls = {"desktop": [], "dashboard": [], "phone": []}
    monkeypatch.setattr(job_events, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(mn, "desktop_notify", lambda t, m, open_target=None: calls["desktop"].append((t, m, open_target)))
    monkeypatch.setattr(mn, "dashboard_refresh_ping", lambda: calls["dashboard"].append(True))
    monkeypatch.setattr(mn, "phone_notify", None)
    return calls


def _alerts_runs(tmp_path):
    return json.loads((tmp_path / "jobs" / "alerts.json").read_text())["runs"]


def test_mr_ready_reaches_desktop_with_a_click_to_the_pr_and_the_dashboard(chans):
    out = mn.notify_mr_ready("G-Eskayo/marvin#1", "https://github.com/G-Eskayo/marvin/pull/99")
    (title, msg, target), = chans["desktop"]
    assert target == "https://github.com/G-Eskayo/marvin/pull/99" and "G-Eskayo/marvin#1" in msg and len(msg) < 200
    assert chans["dashboard"] == [True]
    assert out["delivered"] == ["desktop", "dashboard"] and out["desktop_sent"] and out["dashboard_ping_succeeded"]


def test_the_phone_slot_is_empty_until_958_and_says_so_without_spending_a_claude_call(chans, monkeypatch):
    import marvin_launcher
    monkeypatch.setattr(marvin_launcher, "launch", lambda *a, **k: pytest.fail("no model call to send an alert"))
    out = mn.notify_needs_you("marvin#5", "parked")
    assert out["channels"]["phone"] == mn.PHONE_NOT_SET_UP and "phone" not in out["delivered"]
    assert out["push_attempted"] is False and not hasattr(mn, "push_notify")


def test_a_plugged_in_phone_channel_gets_every_alert(chans, monkeypatch):
    got = []
    monkeypatch.setattr(mn, "phone_notify", lambda t, m, o: got.append((t, m, o)))
    out = mn.notify_regression("MARVIN: x", "it came back", "https://x")
    assert got == [("MARVIN: x", "it came back", "https://x")] and "phone" in out["delivered"]


def test_one_channel_failing_never_stops_the_others_and_its_real_error_is_kept(chans, monkeypatch):
    def refused():
        raise OSError("Connection refused")
    monkeypatch.setattr(mn, "dashboard_refresh_ping", refused)
    out = mn.notify_mr_ready("r#1", "https://pr")
    assert out["delivered"] == ["desktop"]
    assert out["channels"]["dashboard"] == "failed: OSError: Connection refused"


def test_every_channel_failing_is_recorded_as_a_failed_alerts_run_and_a_not_told_step(chans, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("no banner")
    monkeypatch.setattr(mn, "desktop_notify", boom)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", boom)
    steps = []
    monkeypatch.setattr(job_events, "step", lambda name, detail="": steps.append((name, detail)))
    out = mn._fire("MARVIN: sync stuck", "body")
    assert out["delivered"] == []
    run = _alerts_runs(tmp_path)[-1]
    assert run["status"] == "failed" and "no channel delivered" in run["error"]
    assert {s["step"]: s["detail"] for s in run["steps"]}["desktop"] == "failed: RuntimeError: no banner"
    assert steps == [("Told the owner", "NOT delivered on any channel: MARVIN: sync stuck")]
    assert mn.told_text(out).startswith("COULD NOT tell the owner (desktop failed: RuntimeError: no banner;")


def test_a_delivered_alert_is_a_passed_run_with_one_step_per_channel(chans, tmp_path):
    mn._fire("MARVIN: t", "m")
    run = _alerts_runs(tmp_path)[-1]
    assert run["status"] == "passed" and run["summary"] == "MARVIN: t"
    assert [s["step"] for s in run["steps"]] == ["desktop", "dashboard", "phone"]


def test_recording_failing_never_stops_the_alert(chans, monkeypatch):
    def boom(*a, **k):
        raise PermissionError("read-only disk")
    monkeypatch.setattr(job_events, "job_run", boom)
    assert mn._fire("t", "m")["delivered"] == ["desktop", "dashboard"]


@pytest.mark.parametrize("title, message", [(None, None), ("", ""), ("x" * 50_000, "y" * 50_000), ("\x00\n", "é😀")])
def test_odd_titles_and_messages_are_bounded_and_never_raise(chans, title, message):
    mn._fire(title, message)
    t, m, _ = chans["desktop"][-1]
    assert len(t) <= 200 and len(m) <= 1000


def test_told_text_never_claims_told_without_a_delivery():
    assert mn.told_text({"delivered": ["desktop"]}) == "told the owner by desktop"
    assert mn.told_text(None) == "told the owner (result not reported)"
    assert mn.told_text({"delivered": [], "error": "boom"}) == "COULD NOT tell the owner (boom)"


def test_default_dashboard_ping_posts_to_the_webhook_servers_mr_ready_endpoint(monkeypatch):
    captured = {}
    monkeypatch.setattr(mn.urllib.request, "urlopen",
                        lambda req, timeout=None: captured.update(url=req.full_url, method=req.get_method(), timeout=timeout))
    mn._default_dashboard_refresh_ping()
    assert captured == {"url": "http://localhost:7878/mr-ready", "method": "POST", "timeout": mn.DASHBOARD_REFRESH_TIMEOUT_S}


# ── alert on a change, remind once a day ────────────────────────────────────────────────────────────────────────

def _run(path, states, day=D0, fired=None, **kw):
    fired = [] if fired is None else fired
    items = [{"key": k, "state": s, "title": f"MARVIN: {k}", "message": s} for k, s in states.items()]
    mn.alert_on_change(items, path, fire=lambda t, m: fired.append(t), today=day, **kw)
    return fired


def test_the_same_red_on_100_polls_in_a_day_alerts_once(tmp_path):
    fired = []
    for _ in range(100):
        _run(tmp_path / "m.json", {"sync": "red"}, fired=fired)
    assert fired == ["MARVIN: sync"]


def test_still_red_tomorrow_reminds_once_that_day_then_clears_once(tmp_path):
    p, fired = tmp_path / "m.json", []
    for day in range(3):
        for _ in range(5):
            _run(p, {"sync": "red"}, day=D0 + timedelta(days=day), fired=fired)
    assert fired == ["MARVIN: sync", "MARVIN: sync (daily reminder)", "MARVIN: sync (daily reminder)"]
    _run(p, {"sync": "green"}, day=D0 + timedelta(days=3), fired=fired)
    _run(p, {"sync": "green"}, day=D0 + timedelta(days=4), fired=fired)
    assert fired[-1] == "MARVIN: sync" and len(fired) == 4


def test_a_first_look_at_healthy_things_alerts_nothing_and_unknown_never_clears_or_alerts(tmp_path):
    p = tmp_path / "m.json"
    assert _run(p, {"a": "green", "b": "unmonitored", "c": None}) == []
    _run(p, {"a": "red"})
    assert _run(p, {"a": "unmonitored"}) == []  # a blip, not a fix
    assert _run(p, {"a": "red"}) == []          # still the same red episode
    assert json.loads(p.read_text())["a"]["state"] == "red"


def test_moving_between_two_bad_states_alerts_each_time(tmp_path):
    fired = []
    for s in ("expiring", "failed", "failed", "works"):
        _run(tmp_path / "m.json", {"tok": s}, fired=fired, bad=("expiring", "failed"))
    assert len(fired) == 3


def test_old_format_memory_is_read_as_alerted_today_so_upgrading_sends_no_burst(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"github@mini": "failed", "x": 5, "y": None}))
    assert _run(p, {"github@mini": "failed"}, bad=("failed",)) == []
    assert _run(p, {"github@mini": "failed"}, day=D0 + timedelta(days=1), bad=("failed",)) != []


@pytest.mark.parametrize("junk", ["{oops", "[]", "null", "", "\x00\x01"])
def test_corrupt_memory_starts_over_rather_than_crashing(tmp_path, junk):
    p = tmp_path / "m.json"
    p.write_text(junk)
    assert _run(p, {"a": "red"}) == ["MARVIN: a"]


def test_bad_items_are_skipped_not_fatal(tmp_path):
    items = [None, "x", {"state": "red"}, {"key": "", "state": "red"}, {"key": 5, "state": "red"}, {"key": "ok", "state": "red"}]
    fired = []
    mn.alert_on_change(items, tmp_path / "m.json", fire=lambda t, m: fired.append(t), today=D0)
    assert fired == ["ok"]


def test_many_changes_in_one_poll_go_out_as_one_summary_banner(tmp_path):
    p = tmp_path / "m.json"
    fired = _run(p, {f"c{i}": "red" for i in range(1000)}, batch_over=3)
    assert fired == ["MARVIN: 1000 things turned red"]
    fired = _run(p, {f"c{i}": ("green" if i < 2 else "red") for i in range(1000)}, batch_over=3)
    assert fired == ["MARVIN: c0", "MARVIN: c1"]  # two cleared: under the batch line, one banner each


def test_an_alert_that_throws_never_stops_the_others_and_memory_is_still_written(tmp_path):
    p, fired = tmp_path / "m.json", []
    def fire(t, m):
        fired.append(t)
        raise RuntimeError("down")
    mn.alert_on_change([{"key": "a", "state": "red"}, {"key": "b", "state": "red"}], p, fire=fire, today=D0)
    assert fired == ["a", "b"] and set(json.loads(p.read_text())) == {"a", "b"}


# ── "Can MARVIN reach you?" ──────────────────────────────────────────────────────────────────────────────────────

def test_reach_reads_the_last_alert_and_its_channels(chans, tmp_path):
    assert mn.reach(tmp_path / "jobs")["verdict"] == "unknown"
    mn._fire("MARVIN: first", "m")
    r = mn.reach(tmp_path / "jobs")
    assert r["verdict"] == "reachable" and r["last"]["title"] == "MARVIN: first"
    assert r["last"]["channels"]["desktop"] == "sent" and r["phone"] == mn.PHONE_NOT_SET_UP


def test_reach_says_unreachable_when_the_last_alert_went_nowhere(chans, monkeypatch, tmp_path):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(mn, "desktop_notify", boom)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", boom)
    mn._fire("MARVIN: lost", "m")
    assert mn.reach(tmp_path / "jobs")["verdict"] == "unreachable"


@pytest.mark.parametrize("junk", ["{", "[]", '{"runs": 5}', '{"runs": [5, null, {"steps": "x"}]}'])
def test_reach_survives_a_mangled_run_log(tmp_path, junk):
    (tmp_path / "alerts.json").write_text(junk)
    assert mn.reach(tmp_path)["verdict"] in ("unknown", "reachable")


def test_the_cli_test_alert_exits_non_zero_when_nothing_was_delivered(chans, monkeypatch, capsys):
    assert mn.main(["test"]) == 0
    assert json.loads(capsys.readouterr().out)["delivered"] == ["desktop", "dashboard"]
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(mn, "desktop_notify", boom)
    monkeypatch.setattr(mn, "dashboard_refresh_ping", boom)
    assert mn.main(["test"]) == 1
    assert mn.main(["rm", "-rf"]) == 2
