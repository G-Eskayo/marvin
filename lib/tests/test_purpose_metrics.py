"""Purpose metrics and outcome checks (marvin#304): a ticket that promises a measurable effect gets measured."""
from datetime import datetime, timezone

import pytest

import purpose_metrics as pm

NOW = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
BODY = """## What to build
Allow read-only tools.

## Purpose metric
- **Measure:** headless-refusals-per-week
- **Baseline:** 376
- **Target:** -70%
- **Check on:** 2026-10-15

## Acceptance criteria
"""


def test_a_purpose_metric_is_read_from_the_ticket():
    spec = pm.parse(BODY)
    assert spec == {"measure": "headless-refusals-per-week", "baseline": 376.0, "target": "-70%",
                    "check_on": "2026-10-15"}
    assert pm.parse("## What to build\nx") is None


def test_targets_are_relative_or_absolute_and_lower_is_better_unless_stated():
    assert pm.target_value({"baseline": 376.0, "target": "-70%"}) == ("<=", pytest.approx(112.8))
    assert pm.target_value({"baseline": 10.0, "target": "+50%"}) == (">=", 15.0)
    assert pm.target_value({"baseline": 5.0, "target": "<= 2"}) == ("<=", 2.0)
    assert pm.met({"baseline": 376.0, "target": "-70%"}, 100) is True
    assert pm.met({"baseline": 376.0, "target": "-70%"}, 200) is False


def test_only_registered_measures_can_run():
    # Tickets live in a public repo: a ticket names a measure, it never supplies code or a command.
    assert "headless-refusals-per-week" in pm.MEASURES
    with pytest.raises(KeyError):
        pm.measure_here("rm -rf ~")


def _issue(number=277, body=BODY, comments=()):
    return {"number": number, "title": "Allow read-only tools", "body": body, "comments": list(comments)}


def test_a_ticket_is_due_on_its_date_and_only_until_it_has_an_outcome():
    assert pm.is_due(_issue(), NOW)
    assert not pm.is_due(_issue(), datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert not pm.is_due(_issue(comments=[f"{pm.OUTCOME_HEADING}\nmet"]), NOW)


def test_a_met_purpose_is_recorded_on_the_ticket(monkeypatch):
    posted, labels = [], []
    result = pm.check_issue("G-Eskayo/marvin", _issue(), NOW, measure=lambda name: (90.0, {"macbook": 40, "mini": 50}),
                            comment=lambda repo, n, text: posted.append(text), label=lambda *a: labels.append(a),
                            diagnose=lambda *a: pytest.fail("no diagnosis when the purpose is met"))
    assert result["met"] is True and labels == []
    assert posted[0].startswith(pm.OUTCOME_HEADING) and "✅" in posted[0] and "90" in posted[0]


def test_a_missed_purpose_gets_a_diagnosis_and_a_label():
    posted, labels = [], []
    result = pm.check_issue("G-Eskayo/marvin", _issue(), NOW, measure=lambda name: (300.0, {"macbook": 300}),
                            comment=lambda repo, n, text: posted.append(text),
                            label=lambda repo, n, name: labels.append(name),
                            diagnose=lambda issue, spec, value, per: "Likely why: build commands still refused.")
    assert result["met"] is False
    assert "⚠️" in posted[0] and "Likely why: build commands still refused." in posted[0]
    for option in ("Fix", "Accept", "Revert"):
        assert option in posted[0]
    assert labels == [pm.MISSED_LABEL]


def test_a_measurement_failure_is_reported_not_judged():
    posted = []
    result = pm.check_issue("G-Eskayo/marvin", _issue(), NOW, measure=lambda name: (_ for _ in ()).throw(OSError("ssh down")),
                            comment=lambda repo, n, text: posted.append(text), label=lambda *a: None,
                            diagnose=lambda *a: "")
    assert result["met"] is None and posted == []  # retried tomorrow, nothing claimed


def test_health_turns_red_for_each_missed_purpose():
    found = pm.health_findings([{"number": 277, "title": "Allow read-only tools", "labels": [{"name": pm.MISSED_LABEL}]}])
    assert found[0]["severity"] == "red" and "#277 Allow read-only tools" in found[0]["detail"]
    assert pm.health_findings([])[0]["severity"] == "green"


def test_a_rate_across_macs_comes_from_summed_counts(monkeypatch):
    counts = {"headless-refusals-per-week": (10.0, {"a": 1.0, "b": 9.0}),
              "headless-bash-calls-per-week": (200.0, {"a": 100.0, "b": 100.0})}
    real = pm.measure_everywhere
    monkeypatch.setattr(pm, "measure_everywhere", lambda name: counts[name] if name in counts else real(name))
    assert real("headless-refusal-rate") == (5.0, {"a": 1.0, "b": 9.0})


# ── every fix gets an outcome check (2026-10-26): recurrence probes, north-star measures, validation ──────────

import json as _json
import subprocess as _subprocess
from datetime import timedelta

RECUR = """## What was wrong
The gh watch fired on every tick.

## Recurrence check
- **Probe:** gh-watch-change-storm
- **Baseline:** 570
- **Check on:** 2026-10-15: the symptom has not come back

## Acceptance criteria
"""


def test_a_recurrence_check_names_a_registered_probe_and_takes_its_threshold():
    spec = pm.parse(RECUR)
    assert spec["kind"] == "recurrence" and spec["measure"] == "gh-watch-change-storm"
    assert spec["baseline"] == 570.0 and spec["check_on"].startswith("2026-10-15")
    assert pm.target_value(spec) == ("<=", pm.PROBES["gh-watch-change-storm"][1])
    assert pm.is_due(_issue(body=RECUR), NOW)
    # baseline is optional for a recurrence check: the symptom's size at the fix is useful, not required
    spec = pm.parse(RECUR.replace("- **Baseline:** 570\n", ""))
    assert spec["baseline"] is None


def test_every_probe_is_also_a_measure_that_can_run_on_the_other_mac():
    for name in pm.PROBES:
        assert name in pm.MEASURES


def test_an_unknown_or_injected_probe_never_runs_anything(monkeypatch):
    monkeypatch.setattr(_subprocess, "run", lambda *a, **k: pytest.fail("ticket text reached a subprocess"))
    for probe in ("rm -rf ~", "__import__('os').system('id')", "$(id)", "gh-watch-change-storm; rm -rf ~",
                  "`id`", "../../etc/passwd", "headless-refusals-per-week\n- **Probe:** x"):
        body = RECUR.replace("gh-watch-change-storm", probe)
        assert pm.parse(body) is None or pm.parse(body)["measure"] in pm.MEASURES
        assert pm.outcome_gap(body, NOW - timedelta(days=30)) is not None or pm.parse(body)["measure"] in pm.MEASURES
    for measure in ("rm -rf ~", "__import__('os')", "$(id)"):
        body = BODY.replace("headless-refusals-per-week", measure)
        assert "unknown measure" in pm.outcome_gap(body, NOW - timedelta(days=30))
        with pytest.raises(KeyError):
            pm.measure_here(pm.parse(body)["measure"])


def test_the_outcome_gap_says_what_is_missing_or_wrong():
    earlier = NOW - timedelta(days=30)
    assert pm.outcome_gap(BODY, earlier) is None
    assert pm.outcome_gap(RECUR, earlier) is None
    assert "no outcome check" in pm.outcome_gap("## What to build\nx", earlier)
    assert "no outcome check" in pm.outcome_gap(None, earlier)
    assert "no outcome check" in pm.outcome_gap("", earlier)
    assert "malformed" in pm.outcome_gap(BODY.replace("376", "lots"), earlier)
    assert "malformed" in pm.outcome_gap("## Purpose metric\n- **Measure:** headless-refusals-per-week\n", earlier)
    assert "malformed" in pm.outcome_gap("## Recurrence check\n- **Check on:** 2026-11-01\n", earlier)
    assert "unknown probe" in pm.outcome_gap(RECUR.replace("gh-watch-change-storm", "no-such-probe"), earlier)
    assert "target" in pm.outcome_gap(BODY.replace("-70%", "a lot fewer"), earlier)
    assert "date" in pm.outcome_gap(BODY.replace("2026-10-15", "next week"), earlier)
    assert "date" in pm.outcome_gap(BODY.replace("2026-10-15", "2026-13-45"), earlier)
    # a date already passed at PR time would measure before the fix ran
    assert "past" in pm.outcome_gap(BODY, NOW)
    # an unknown name is shown defanged, never echoed raw into a PR comment
    gap = pm.outcome_gap(BODY.replace("headless-refusals-per-week", "<img src=x onerror=alert(1)>"), earlier)
    assert "<" not in gap and ">" not in gap


def test_a_recurrence_check_is_due_only_from_its_date_and_never_twice():
    assert not pm.is_due(_issue(body=RECUR), datetime(2026, 10, 14, tzinfo=timezone.utc))
    assert not pm.is_due(_issue(body=RECUR.replace("2026-10-15", "2027-01-01")), NOW)
    assert not pm.is_due(_issue(body=RECUR.replace("2026-10-15", "soon")), NOW)
    assert pm.is_due(_issue(body=RECUR.replace("2026-10-15", "2020-01-01")), NOW)
    assert not pm.is_due(_issue(body=RECUR, comments=[f"{pm.OUTCOME_HEADING}\n✅"]), NOW)


def test_a_held_fix_is_recorded_and_a_returned_symptom_is_a_missed_purpose():
    posted, labels = [], []
    ok = pm.check_issue("G-Eskayo/marvin", _issue(body=RECUR), NOW, measure=lambda name: (12.0, {"mini": 12.0}),
                        comment=lambda r, n, t: posted.append(t), label=lambda r, n, name: labels.append(name),
                        diagnose=lambda *a: pytest.fail("no diagnosis when the fix held"))
    assert ok["met"] is True and labels == [] and "✅" in posted[0] and "gh-watch-change-storm" in posted[0]
    posted.clear()
    bad = pm.check_issue("G-Eskayo/marvin", _issue(body=RECUR), NOW, measure=lambda name: (600.0, {"mini": 600.0}),
                         comment=lambda r, n, t: posted.append(t), label=lambda r, n, name: labels.append(name),
                         diagnose=lambda issue, spec, value, per: "the ETag check came back")
    assert bad["met"] is False and labels == [pm.MISSED_LABEL]
    assert "⚠️" in posted[0] and "came back" in posted[0] and "the ETag check came back" in posted[0]


def test_a_probe_that_throws_is_not_judged_and_nothing_is_posted():
    posted = []
    out = pm.check_issue("G-Eskayo/marvin", _issue(body=RECUR), NOW,
                         measure=lambda name: (_ for _ in ()).throw(ValueError("log unreadable")),
                         comment=lambda r, n, t: posted.append(t), label=lambda *a: pytest.fail("no label"),
                         diagnose=lambda *a: pytest.fail("no diagnosis"))
    assert out["met"] is None and posted == []


def test_the_daily_run_checks_bug_tickets_too_and_never_posts_twice(monkeypatch):
    issues = {pm.LABEL: [_issue(277, BODY, comments=[1])],
              "bug": [_issue(604, RECUR, comments=[1]), _issue(277, BODY, comments=[1]), _issue(9, "## What\nno check")]}
    thread = {277: [], 604: [], 9: []}
    fetched = []

    def gh_json(path):
        fetched.append(path)
        number = int(path.split("/issues/")[1].split("/")[0])
        return [{"body": b} for b in thread[number]]
    monkeypatch.setattr(pm, "labelled_issues", lambda repo, name: [dict(i) for i in issues.get(name, [])])
    monkeypatch.setattr(pm, "_gh_json", gh_json)
    checked = []

    def check(repo, issue, now):
        checked.append(issue["number"])
        thread[issue["number"]].append(f"{pm.OUTCOME_HEADING}\n✅")
        return {"number": issue["number"], "met": True}
    monkeypatch.setattr(pm, "check_issue", check)
    pm.run(NOW)
    assert sorted(checked) == [277, 604]        # 277 once although it carries both labels; #9 has nothing to check
    assert not any("/9/" in p for p in fetched)  # comments fetched only for a ticket whose check is due
    pm.run(NOW)
    assert sorted(checked) == [277, 604]        # the second run finds the outcome comment: nothing posted twice


# ── the probes and measures read real log shapes ───────────────────────────────────────────────────────────

def test_gh_watch_probe_counts_the_busiest_hour_in_the_window(tmp_path):
    log = tmp_path / "dashboard-webhook.log"
    now = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)
    lines = ["[webhook] listening on 7878", "garbage \x00 line", "[gh-watch] change detected on X at not-a-date"]
    lines += [f"[gh-watch] change detected on G-Eskayo/marvin at 2026-10-26T17:{m:02d}:00.000Z" for m in range(40)]
    lines += [f"[gh-watch] change detected on G-Eskayo/marvin at 2026-10-26T15:{m:02d}:00.000Z" for m in range(5)]
    lines += [f"[gh-watch] change detected on G-Eskayo/marvin at 2026-10-01T10:{m:02d}:00.000Z" for m in range(59)]
    log.write_text("\n".join(lines) + "\n")
    assert pm._gh_watch_busiest_hour(log, now=now) == 40.0     # the 2026-10-01 storm is outside the 7 days
    assert pm._gh_watch_busiest_hour(tmp_path / "missing.log", now=now) == 0.0  # no webhook server, no storm


def _stages(path, n, times):
    path.mkdir(exist_ok=True)
    (path / f"g-eskayo__marvin-{n}.json").write_text(_json.dumps(
        [{"stage": "executing", "status": "started", "detail": "planning call", "timestamp": t} for t in times]
        + [{"stage": "executing", "status": "started", "detail": "planning reused from round 1", "timestamp": times[0]}]))


def test_replan_probe_counts_tickets_planned_three_times_inside_24_hours(tmp_path):
    d = tmp_path / "ticket-stages"
    now = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)
    _stages(d, 1, ["2026-10-25T01:00:00+00:00", "2026-10-25T09:00:00+00:00", "2026-10-25T23:00:00+00:00"])  # loop
    _stages(d, 2, ["2026-10-22T01:00:00+00:00", "2026-10-23T09:00:00+00:00", "2026-10-24T23:00:00+00:00"])  # spread
    _stages(d, 3, ["2026-10-10T01:00:00+00:00", "2026-10-10T02:00:00+00:00", "2026-10-10T03:00:00+00:00"])  # old
    (d / "corrupt.json").write_text("{not json")
    (d / "odd.json").write_text(_json.dumps({"not": "a list"}))
    (d / "mixed.json").write_text(_json.dumps([None, 3, {"stage": "executing", "timestamp": "bad"}]))
    assert pm._replanned_tickets(d, now=now) == 1.0
    assert pm._replanned_tickets(tmp_path / "none", now=now) == 0.0


def test_github_calls_and_failed_headless_runs_per_day(tmp_path):
    now = datetime(2026, 10, 26, 18, tzinfo=timezone.utc)
    t = now.timestamp()
    calls = tmp_path / "gh-calls.jsonl"
    calls.write_text("\n".join([_json.dumps({"t": t - 60}), _json.dumps({"t": t - 3600}), _json.dumps({"t": t - 90000}),
                                "not json", _json.dumps({"no": "t"}), _json.dumps({"t": "soon"})]) + "\n")
    assert pm._github_calls(calls, now=now) == 2.0
    launches = tmp_path / "launches.jsonl"
    at = lambda h: (now - timedelta(hours=h)).isoformat()
    launches.write_text("\n".join(_json.dumps(r) for r in [
        {"at": at(1), "exit_code": 0, "exit_cause": "ok"}, {"at": at(2), "exit_code": 1, "exit_cause": "error"},
        {"at": at(3), "exit_code": 124, "exit_cause": "timeout"}, {"at": at(30), "exit_code": 1},
        {"at": "garbage", "exit_code": 1}, {"exit_code": 1}]) + "\nnot json\n")
    assert pm._failed_headless_runs(launches, now=now) == 2.0
    assert pm._github_calls(tmp_path / "missing", now=now) == 0.0
    for name in ("github-calls-per-day", "failed-headless-runs-per-day"):
        assert name in pm.MEASURES
