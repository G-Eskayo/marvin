"""The job catalog: every background job declares its goal, machine, reporter and what healthy means (Gil, 2026-10-26).
The waste sweep lists anything that serves no goal, has no consumer, or runs without being catalogued."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import job_catalog as jc  # noqa: E402
import health_checks as hc  # noqa: E402

FIELDS = ("machine", "goal", "reporter", "healthy", "consumer")


def test_every_job_declares_all_five_fields():
    for name, job in jc.JOBS.items():
        for f in FIELDS:
            assert f in job, f"{name} is missing {f}"
        assert job["machine"] in jc.MACHINES, f"{name}: unknown machine {job['machine']!r}"


def test_goals_name_a_north_star_or_a_real_project():
    for name, job in jc.JOBS.items():
        if job["goal"] is None:
            continue
        assert job["goal"] in jc.GOALS, f"{name}: goal {job['goal']!r} is not a north star or project"


def test_health_placement_is_derived_from_the_catalog_not_kept_twice():
    marvin = {n for n, j in jc.JOBS.items() if j.get("label", f"com.marvin.{n}").startswith("com.marvin.")
              and j["machine"] != "none"}
    assert set(hc.JOB_PLACEMENT) == marvin
    for n in marvin:
        assert hc.JOB_PLACEMENT[n] == jc.JOBS[n]["machine"]


def test_jobs_that_were_unplaced_are_now_placed():
    for n in ("history-load", "seal-beta-ingest", "portfolio-dev-tunnel"):
        assert n in hc.JOB_PLACEMENT


def test_a_switched_off_job_is_never_reported_missing():
    # open-loops stays off until goals exist (Gil, 2026-10-26)
    assert jc.JOBS["open-loops"]["machine"] == "none"
    sev, detail = hc.evaluate_job_placement([j for j, w in hc.JOB_PLACEMENT.items() if w in ("both", "mini")], "mini")
    assert sev == "green", detail


def test_waste_lists_jobs_with_no_goal_or_no_consumer():
    jobs = {
        "useful": {"machine": "mini", "goal": "ns1", "reporter": "x", "healthy": "y", "consumer": "Vitals"},
        "aimless": {"machine": "mini", "goal": None, "reporter": "x", "healthy": "y", "consumer": "Vitals"},
        "unread": {"machine": "both", "goal": "ns1", "reporter": "x", "healthy": "y", "consumer": None},
    }
    rows = jc.waste(jobs=jobs, loaded={})
    names = {r["job"]: r["why"] for r in rows}
    assert set(names) == {"aimless", "unread"}
    assert "no goal" in names["aimless"] and "nobody reads" in names["unread"]


def test_waste_lists_a_loaded_job_nobody_catalogued():
    rows = jc.waste(jobs={}, loaded={"mac-mini-1": ["mystery-job"]})
    assert rows == [{"job": "mystery-job", "why": "runs on mac-mini-1 but isn't in the job catalog", "review": None}]


def test_waste_carries_the_review_note():
    jobs = {"old": {"machine": "mini", "goal": "ns1", "reporter": "x", "healthy": "y", "consumer": "Vitals",
                    "review": "ADR 0033 folded it into Health"}}
    assert jc.waste(jobs=jobs, loaded={}) == [{"job": "old", "why": "flagged for review", "review": "ADR 0033 folded it into Health"}]


@pytest.mark.parametrize("bad", [None, "", "   ", 42, ["a"], {"x": 1}])
def test_waste_survives_junk_loaded_lists(bad):
    assert jc.waste(jobs={}, loaded={"m": bad}) == [] or all("job" in r for r in jc.waste(jobs={}, loaded={"m": bad}))


def test_report_is_plain_text_and_names_every_waste_row():
    text = jc.report(jc.waste(jobs={"a": {"machine": "mini", "goal": None, "reporter": "x", "healthy": "y",
                                          "consumer": "z"}}, loaded={}))
    assert "a" in text and "no goal" in text


def test_report_when_nothing_is_wasted():
    assert "nothing" in jc.report([]).lower()
