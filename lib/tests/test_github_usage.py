"""Tests for github_usage.py (the Metrics tab's GitHub section). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_github_usage.py -v
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

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


def test_budget_series_and_latest_reading():
    budget = [{"at": T - 7200, "graphql": 0.9, "core": 1.0}, {"at": T - 60, "graphql": 0.4, "core": 0.99, "reset": None},
              {"at": T - 3 * 86400, "graphql": 0.1, "core": 1.0}]
    s = gu.summarize([], budget, NOW)
    assert [b["graphql"] for b in s["budget"]] == [0.9, 0.4]
    assert s["latest_budget"]["graphql"] == 0.4


def test_read_jsonl_skips_bad_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"t": 1}\nnot json\n{"t": 2}\n')
    assert [r["t"] for r in gu.read_jsonl(p)] == [1, 2]
    assert gu.read_jsonl(tmp_path / "none.jsonl") == []


def test_cli_prints_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(gu, "CALLS_PATH", tmp_path / "c.jsonl")
    monkeypatch.setattr(gu, "BUDGET_PATH", tmp_path / "b.jsonl")
    gu.main([])
    out = json.loads(capsys.readouterr().out)
    assert "hours" in out and "top" in out and out["machine"]


def test_the_dashboard_app_is_one_caller_across_launches():
    rows = [row(5, "application.com.gileskayo.marvin-metrics-dashboard.1.2"), row(6, "application.com.gileskayo.marvin-metrics-dashboard.3.4"),
            row(7, "com.marvin.ticket-pipeline")]
    top = {t["caller"]: t for t in gu.summarize(rows, [], NOW)["top"]}
    assert top["MARVIN dashboard app"]["calls"] == 2 and top["MARVIN dashboard app"]["group"] == "dashboard"
    assert top["ticket-pipeline"]["group"] == "pipeline"
