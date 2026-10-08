#!/usr/bin/env python3
"""Tests for connections.py — threads derived from files that are already the source of truth (plan:
docs/plans/map-connections-2026-10-08.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from connections import builds, runs_on, skill_projects  # noqa: E402

MACHINES = {"mini": "mac-mini-1", "laptop": "macbook-pro-1"}


def pairs(threads):
    return sorted((t["a"], t["b"], t["type"]) for t in threads)


def test_runs_on_expands_both_and_single_machine_jobs():
    placement = {"ticket-pipeline": "both", "health-check": "mini", "dashboard-launch": "laptop"}
    ids = {"ticket-pipeline", "health-check", "dashboard-launch", "mac-mini-1", "macbook-pro-1"}
    assert pairs(runs_on(placement, ids, MACHINES)) == [
        ("dashboard-launch", "macbook-pro-1", "runs-on"),
        ("health-check", "mac-mini-1", "runs-on"),
        ("ticket-pipeline", "mac-mini-1", "runs-on"),
        ("ticket-pipeline", "macbook-pro-1", "runs-on"),
    ]


def test_runs_on_skips_jobs_and_machines_not_on_the_map():
    placement = {"ticket-pipeline": "both", "verify-digest-fix": "mini"}
    ids = {"ticket-pipeline", "mac-mini-1"}  # no laptop node, no verify-digest-fix node
    assert pairs(runs_on(placement, ids, MACHINES)) == [("ticket-pipeline", "mac-mini-1", "runs-on")]


def test_runs_on_label_names_no_machine():
    # the public snapshot anonymises machines, so the label must not carry a machine id
    t = runs_on({"daily-digest": "mini"}, {"daily-digest", "mac-mini-1"}, MACHINES)[0]
    assert "mac-mini" not in t["label"] and "macbook" not in t["label"]


def test_builds_only_projects_with_dispatch_on():
    profiles = [
        {"repo": "G-Eskayo/clarity-captions", "dispatch": "on"},
        {"repo": "G-Eskayo/killer-sudoku", "dispatch": "off"},
        {"repo": "G-Eskayo/finance-os"},
    ]
    ids = {"ticket-pipeline", "clarity-captions", "killer-sudoku", "finance-os"}
    assert pairs(builds(profiles, ids)) == [("ticket-pipeline", "clarity-captions", "builds")]


def test_builds_skips_projects_not_on_the_map():
    assert builds([{"repo": "G-Eskayo/nope", "dispatch": "on"}], {"ticket-pipeline"}) == []


def test_skill_projects_matches_prefixed_project_ids_and_overrides():
    skills = {"resume-tailor", "paper-dive", "portfolio-page", "audit"}
    projects = {"project:resume-tailor", "project:paper-dive", "portfolio-website-updater", "finance-os"}
    overrides = {"portfolio-page": "portfolio-website-updater"}
    assert pairs(skill_projects(skills, projects, overrides)) == [
        ("paper-dive", "project:paper-dive", "skill-project"),
        ("portfolio-page", "portfolio-website-updater", "skill-project"),
        ("resume-tailor", "project:resume-tailor", "skill-project"),
    ]


def test_skill_projects_ignores_overrides_whose_ends_are_missing():
    assert skill_projects({"a"}, {"p"}, {"a": "missing", "ghost": "p"}) == []


from connections import machine_roles, read_job_placement  # noqa: E402


def test_read_job_placement_parses_the_table_without_importing(tmp_path):
    f = tmp_path / "health_checks.py"
    f.write_text('import does_not_exist\nJOB_PLACEMENT = {\n    "a": "both",  # note\n    "b": "mini",\n}\n')
    assert read_job_placement(f) == {"a": "both", "b": "mini"}


def test_read_job_placement_missing_file_or_table_is_empty(tmp_path):
    assert read_job_placement(tmp_path / "nope.py") == {}
    (tmp_path / "x.py").write_text("OTHER = 1\n")
    assert read_job_placement(tmp_path / "x.py") == {}


def test_machine_roles_from_the_registry_kinds():
    network = {"devices": {"mac-mini-1": {"kind": "desktop"}, "macbook-pro-1": {"kind": "laptop"}}}
    assert machine_roles(network) == {"mini": "mac-mini-1", "laptop": "macbook-pro-1"}
    assert machine_roles({}) == {}
