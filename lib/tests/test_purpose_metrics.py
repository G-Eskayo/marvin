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
