"""Tests for github_usage.py (the Metrics tab's GitHub section). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_github_usage.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import github_usage as gu  # noqa: E402

NOW = datetime(2026, 10, 9, 12, 30, tzinfo=timezone.utc)
T = NOW.timestamp()


def row(ago_min, caller, cmd="pr list", **kw):
    return {"t": T - ago_min * 60, "caller": caller, "cmd": cmd, "rc": kw.pop("rc", 0), **kw}


def test_callers_fall_into_groups_people_recognise():
    assert gu.group_of("application.com.gileskayo.marvin-metrics-dashboard.1.2") == "dashboard"
    assert gu.group_of("com.marvin.dashboard-webhook") == "dashboard"
    assert gu.group_of("Python -m pytest") == "tests"
    assert gu.group_of("ticket_pipeline.py") == "pipeline"
    assert gu.group_of("com.marvin.ticket-pipeline") == "pipeline"
    assert gu.group_of("rework_status.py") == "pipeline"
    assert gu.group_of("com.marvin.health-check") == "health"
    assert gu.group_of("zsh") == "people"
    assert gu.group_of("probe.py") == "other"


def test_hourly_calls_are_stacked_by_group_with_refusals_and_holds():
    rows = [row(5, "ticket_pipeline.py"), row(10, "ticket_pipeline.py", refused="burst", rc=1),
            row(20, "MARVIN dashboard", deferred="defer", rc=75), row(70, "Python -m pytest")]
    s = gu.summarize(rows, [], NOW, hours=3)
    assert [h["hour"] for h in s["hours"]] == ["2026-10-09T10:00Z", "2026-10-09T11:00Z", "2026-10-09T12:00Z"]
    last = s["hours"][-1]
    assert last["total"] == 3 and last["groups"]["pipeline"] == 2 and last["refused"] == 1 and last["deferred"] == 1
    assert s["hours"][-2]["groups"]["tests"] == 1


def test_top_callers_of_the_last_day_with_what_they_ran():
    rows = [row(5, "ticket_pipeline.py", "issue list")] * 3 + [row(6, "ticket_pipeline.py", "pr list"), row(7, "zsh", "api x"),
            row(60 * 30, "old.py")]
    top = gu.summarize(rows, [], NOW)["top"]
    assert top[0]["caller"] == "ticket_pipeline.py" and top[0]["calls"] == 4 and top[0]["group"] == "pipeline"
    assert top[0]["commands"][0] == {"cmd": "issue list", "calls": 3}
    assert all(t["caller"] != "old.py" for t in top)


def test_budget_is_the_lowest_reading_each_hour_with_gaps_where_there_were_none():
    # GitHub refills the allowance every hour, so raw readings make a sawtooth (marvin#417): keep each hour's low point.
    budget = [{"at": T - 7200, "graphql": 0.9, "core": 1.0}, {"at": T - 60, "graphql": 0.4, "core": 0.99, "reset": None},
              {"at": T - 120, "graphql": 0.7, "core": 1.0}, {"at": T - 3 * 86400, "graphql": 0.1, "core": 1.0}]
    s = gu.summarize([], budget, NOW, hours=3)
    assert [h["budget_min"] for h in s["hours"]] == [0.9, None, 0.4]
    assert [h["budget_readings"] for h in s["hours"]] == [1, 0, 2]
    assert s["latest_budget"]["graphql"] == 0.4
    assert "budget" not in s  # raw readings are no longer shipped: the payload must not grow with run time


def test_an_hour_that_ran_out_keeps_zero_not_none():
    s = gu.summarize([], [{"at": T - 60, "graphql": 0.0}, {"at": T - 30, "graphql": 0.6}], NOW, hours=1)
    assert s["hours"][0]["budget_min"] == 0.0


def test_unusable_budget_readings_are_ignored():
    budget = [{"at": T - 60, "graphql": None}, {"at": "soon", "graphql": 0.2}, {"graphql": 0.1}, {"at": T - 30, "graphql": "low"},
              {"at": T - 20, "graphql": 0.5}]
    s = gu.summarize([], budget, NOW, hours=1)
    assert s["hours"][0]["budget_min"] == 0.5 and s["hours"][0]["budget_readings"] == 1


def test_each_hour_names_its_top_callers():
    rows = [row(5, "ticket_pipeline.py")] * 4 + [row(6, "zsh")] * 2 + [row(7, f"job{i}.py") for i in range(6)]
    h = gu.summarize(rows, [], NOW, hours=1)["hours"][0]
    assert h["callers"][0] == {"caller": "ticket_pipeline.py", "group": "pipeline", "calls": 4}
    assert h["callers"][1]["caller"] == "zsh" and len(h["callers"]) == 5


def test_payload_is_bounded_to_the_requested_hours_however_long_it_has_run():
    rows = [row(m, "zsh") for m in range(0, 60 * 24 * 40, 90)]  # 40 days of calls
    s = gu.summarize(rows, [], NOW)
    assert len(s["hours"]) == gu.KEEP_HOURS == 720
    assert s["hours"][0]["hour"] == "2026-09-09T13:00Z" and s["hours"][-1]["hour"] == "2026-10-09T12:00Z"


def test_calls_from_a_clock_skewed_peer_a_little_in_the_future_land_in_this_hour():
    s = gu.summarize([row(-4, "zsh")], [], NOW, hours=2)
    assert s["hours"][-1]["total"] == 1


# ── the hourly cache: read only what's new ──────────────────────────────────

def _write(p, rows):
    with open(p, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def _paths(tmp_path):
    return tmp_path / "gh-calls.jsonl", tmp_path / "gh-budget.jsonl", tmp_path / "gh-usage-hourly.json"


def test_incremental_update_matches_a_full_rebuild(tmp_path):
    calls, budget, cache = _paths(tmp_path)
    first = [row(200, "zsh"), row(100, "ticket_pipeline.py", refused="x")]
    second = [row(50, "zsh"), row(5, "MARVIN dashboard", deferred="d")]
    _write(calls, first)
    _write(budget, [{"at": T - 6000, "graphql": 0.8}])
    gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)
    _write(calls, second)
    _write(budget, [{"at": T - 100, "graphql": 0.3}])
    inc = gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)
    full = gu.summarize(first + second, [{"at": T - 6000, "graphql": 0.8}, {"at": T - 100, "graphql": 0.3}], NOW)
    assert inc["hours"] == full["hours"] and inc["top"] == full["top"] and inc["latest_budget"] == full["latest_budget"]


def test_second_read_only_parses_new_bytes(tmp_path, monkeypatch):
    calls, budget, cache = _paths(tmp_path)
    _write(calls, [row(m, "zsh") for m in range(0, 600, 3)])
    gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)
    parsed = []
    real = gu._parse_lines
    monkeypatch.setattr(gu, "_parse_lines", lambda data: (parsed.append(len(data)), real(data))[1])
    _write(calls, [row(1, "zsh")])
    s = gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)
    assert sum(h["total"] for h in s["hours"]) == 201
    assert max(parsed) < 200  # only the one new line, not the whole log


def test_a_half_written_last_line_waits_for_the_rest(tmp_path):
    calls, budget, cache = _paths(tmp_path)
    line = json.dumps(row(5, "zsh"))
    calls.write_text(json.dumps(row(6, "zsh")) + "\n" + line[:10])
    assert sum(h["total"] for h in gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)["hours"]) == 1
    with open(calls, "a") as f:
        f.write(line[10:] + "\n")
    assert sum(h["total"] for h in gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)["hours"]) == 2


def test_a_replaced_or_shrunk_log_is_rebuilt_not_double_counted(tmp_path):
    calls, budget, cache = _paths(tmp_path)
    _write(calls, [row(5, "zsh")] * 10)
    gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)
    calls.unlink()
    _write(calls, [row(4, "zsh")] * 3)  # wiped and restarted (it happened 2026-10-09)
    assert sum(h["total"] for h in gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)["hours"]) == 3


def test_a_corrupt_cache_is_rebuilt(tmp_path):
    calls, budget, cache = _paths(tmp_path)
    _write(calls, [row(5, "zsh")] * 4)
    for junk in ("{nope", "[]", json.dumps({"version": 99})):
        cache.write_text(junk)
        assert sum(h["total"] for h in gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)["hours"]) == 4


def test_missing_logs_give_empty_hours_not_a_crash(tmp_path):
    calls, budget, cache = _paths(tmp_path)
    s = gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)
    assert len(s["hours"]) == 720 and all(h["total"] == 0 and h["budget_min"] is None for h in s["hours"])
    assert s["latest_budget"] is None and s["top"] == []


def test_old_hours_are_pruned_from_the_cache(tmp_path):
    calls, budget, cache = _paths(tmp_path)
    _write(calls, [row(60 * 24 * 35, "zsh"), row(5, "zsh")])
    gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)
    kept = json.loads(cache.read_text())["hours"]
    assert len(kept) == 1


def test_concurrent_reports_never_double_count(tmp_path):
    import threading
    calls, budget, cache = _paths(tmp_path)
    _write(calls, [row(m % 600, "zsh") for m in range(3000)])
    errs = []

    def go():
        try:
            gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)
        except Exception as e:  # pragma: no cover
            errs.append(e)
    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs
    assert sum(h["total"] for h in gu.report(NOW, calls_path=calls, budget_path=budget, cache_path=cache)["hours"]) == 3000


def test_read_jsonl_skips_bad_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"t": 1}\nnot json\n{"t": 2}\n')
    assert [r["t"] for r in gu.read_jsonl(p)] == [1, 2]
    assert gu.read_jsonl(tmp_path / "none.jsonl") == []


def test_cli_prints_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gu, "CALLS_PATH", tmp_path / "c.jsonl")
    monkeypatch.setattr(gu, "BUDGET_PATH", tmp_path / "b.jsonl")
    monkeypatch.setattr(gu, "HOURLY_PATH", tmp_path / "h.json")
    gu.main([])
    out = json.loads(capsys.readouterr().out)
    assert "hours" in out and "top" in out and out["machine"]


def test_the_dashboard_app_is_one_caller_across_launches():
    rows = [row(5, "application.com.gileskayo.marvin-metrics-dashboard.1.2"), row(6, "application.com.gileskayo.marvin-metrics-dashboard.3.4"),
            row(7, "com.marvin.ticket-pipeline")]
    top = {t["caller"]: t for t in gu.summarize(rows, [], NOW)["top"]}
    assert top["MARVIN dashboard app"]["calls"] == 2 and top["MARVIN dashboard app"]["group"] == "dashboard"
    assert top["ticket-pipeline"]["group"] == "pipeline"


def test_top_callers_count_their_own_refusals_and_holds():
    rows = [row(5, "ticket_pipeline.py", refused="burst", rc=1), row(6, "ticket_pipeline.py"), row(7, "ticket_pipeline.py", deferred="d", rc=75),
            row(8, "zsh", refused="burst", rc=1)]
    top = {t["caller"]: t for t in gu.summarize(rows, [], NOW)["top"]}
    assert (top["ticket_pipeline.py"]["refused"], top["ticket_pipeline.py"]["deferred"]) == (1, 1)
    assert (top["zsh"]["refused"], top["zsh"]["deferred"]) == (1, 0)


# ── reading from the history store (ADR 0066 G4) ───────────────────────────
import history_store as hs  # noqa: E402


def _db_with(tmp_path, rows_by_device: dict, budget_by_device: dict | None = None):
    conn = hs.connect(tmp_path / "history.db")
    for device, rows in rows_by_device.items():
        hs.load(conn, "gh-calls", device, [json.dumps(r) for r in rows])
    for device, rows in (budget_by_device or {}).items():
        hs.load(conn, "gh-budget", device, [json.dumps(r) for r in rows])
    return conn


def _report_db(tmp_path, conn, me="mac-mini-1", calls=None, budget=None):
    return gu.report(NOW, cache_path=tmp_path / "cache.json", db=conn, device=me,
                     local_calls=calls or tmp_path / "none.jsonl", local_budget=budget or tmp_path / "none-b.jsonl")


def _total(report):
    return sum(h["total"] for h in report["hours"])


def test_a_macs_report_counts_only_its_own_calls_so_the_dashboard_merge_never_double_counts(tmp_path):
    conn = _db_with(tmp_path, {"mac-mini-1": [row(5, "a"), row(6, "b")], "macbook-pro-1": [row(5, "c")]})
    assert _total(_report_db(tmp_path, conn, "mac-mini-1")) == 2
    assert _total(gu.report(NOW, cache_path=tmp_path / "other.json", db=conn, device="macbook-pro-1",
                            local_calls=tmp_path / "x", local_budget=tmp_path / "y")) == 1


def test_each_report_reads_only_rows_added_since_the_last(tmp_path):
    conn = _db_with(tmp_path, {"mac-mini-1": [row(i, "a") for i in range(1, 50)]})
    _report_db(tmp_path, conn)
    seen = json.loads((tmp_path / "cache.json").read_text())["db"]["after_id"]
    hs.load(conn, "gh-calls", "mac-mini-1", [json.dumps(row(0.5, "a"))])
    assert _total(_report_db(tmp_path, conn)) == 50
    assert json.loads((tmp_path / "cache.json").read_text())["db"]["after_id"] == seen + 1


def test_this_macs_newest_calls_come_from_its_log_until_the_database_has_them(tmp_path):
    """The laptop's copy lags (or stops, away from home): its own newest calls still show."""
    conn = _db_with(tmp_path, {"macbook-pro-1": [row(30, "a")]})
    log = tmp_path / "gh-calls.jsonl"
    log.write_text("".join(json.dumps(r) + "\n" for r in [row(30, "a"), row(2, "b"), row(1, "c")]))
    r = gu.report(NOW, cache_path=tmp_path / "c.json", db=conn, device="macbook-pro-1", local_calls=log,
                  local_budget=tmp_path / "nb")
    assert _total(r) == 3


def test_newest_calls_shown_from_the_log_are_never_counted_twice_once_the_database_catches_up(tmp_path):
    conn = _db_with(tmp_path, {"macbook-pro-1": [row(30, "a")]})
    log = tmp_path / "gh-calls.jsonl"
    rows = [row(30, "a"), row(2, "b")]
    log.write_text("".join(json.dumps(r) + "\n" for r in rows))
    kw = dict(cache_path=tmp_path / "c.json", db=conn, device="macbook-pro-1", local_calls=log, local_budget=tmp_path / "nb")
    gu.report(NOW, **kw)
    hs.load(conn, "gh-calls", "macbook-pro-1", [json.dumps(rows[1])])  # the copy catches up
    assert _total(gu.report(NOW, **kw)) == 2


def test_budget_readings_come_from_the_database_too(tmp_path):
    conn = _db_with(tmp_path, {}, {"mac-mini-1": [{"at": T - 600, "graphql": 4000, "core": 4900}]})
    assert _report_db(tmp_path, conn)["latest_budget"]["graphql"] == 4000


def test_explicit_log_paths_never_touch_the_real_database(tmp_path, monkeypatch):
    monkeypatch.setattr(hs, "connect", lambda *a, **k: pytest.fail("opened a database"))
    calls = tmp_path / "c.jsonl"
    calls.write_text(json.dumps(row(5, "a")) + "\n")
    assert _total(gu.report(NOW, calls_path=calls, budget_path=tmp_path / "b", cache_path=tmp_path / "x.json")) == 1


# ── reading only a log's recent end (O(k), not O(file)) ─────────────────────

def test_tail_since_reads_backwards_only_as_far_as_it_needs(tmp_path, monkeypatch):
    log = tmp_path / "big.jsonl"
    log.write_text("".join(json.dumps(row(60 * 24 * 3 - i * 0.0719, "x")) + "\n" for i in range(60_000)))
    reads = []
    real_open = open
    class Spy:
        def __init__(self, f): self.f = f
        def __enter__(self): return self
        def __exit__(self, *a): self.f.close()
        def seek(self, *a): return self.f.seek(*a)
        def tell(self): return self.f.tell()
        def read(self, n=-1):
            b = self.f.read(n); reads.append(len(b)); return b
    monkeypatch.setattr("builtins.open", lambda p, m="r", *a, **k: Spy(real_open(p, m, *a, **k)) if str(p) == str(log) else real_open(p, m, *a, **k))
    recent = hs.tail_since(log, T - 3600)
    assert recent and all(hs._ts(r) > T - 3600 for r in recent)
    assert sum(reads) < log.stat().st_size / 10


def test_tail_since_ignores_a_half_written_last_line_and_handles_empty_and_missing(tmp_path):
    log = tmp_path / "l.jsonl"
    assert hs.tail_since(log, 0) == []
    log.write_text("")
    assert hs.tail_since(log, 0) == []
    log.write_text(json.dumps(row(1, "a")) + "\n" + '{"t": 1')
    assert len(hs.tail_since(log, 0)) == 1


def test_update_cache_db_ignores_the_launches_stream(tmp_path):
    """update_cache_db hardcodes streams IN ('gh-calls', 'gh-budget') and ignores launches."""
    db_path = tmp_path / "history.db"
    cache_path = tmp_path / "usage-cache.json"

    conn = hs.connect(db_path)

    # Load some gh-calls and gh-budget events
    hs.load(conn, "gh-calls", "mac-mini-1", [json.dumps(row(5, "ticket_pipeline.py")), json.dumps(row(10, "zsh", rc=1, refused="burst"))])
    hs.load(conn, "gh-budget", "mac-mini-1", [json.dumps({"at": T - 300, "graphql": 4700})])

    # Load launches stream (for PR cost metrics) — should be ignored by update_cache_db
    hs.load(conn, "launches", "mac-mini-1", [
        json.dumps({"t": T - 200, "ticket": "G-Eskayo/marvin#123", "cost_usd": 0.045, "model": "claude-opus-5-5"}),
    ])

    # Update cache from the history store; launches should not affect it
    cache = gu.update_cache_db(NOW, conn, "mac-mini-1", cache_path)

    # Verify it aggregates only gh-calls and gh-budget, ignoring launches
    assert cache["hours"]
    hour_key = gu._hour_key(T - 300)
    assert hour_key in cache["hours"]
    assert cache["hours"][hour_key]["total"] == 2
    assert cache["hours"][hour_key]["refused"] == 1

    conn.close()
