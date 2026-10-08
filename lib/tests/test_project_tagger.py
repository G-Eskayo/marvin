"""Tests for project_tagger.py (ADR 0060, #298). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_project_tagger.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import project_tagger as pt  # noqa: E402

REPO = "G-Eskayo/marvin"
RULES = {"projects": {
    "portfolio-website-updater": {"repo": "G-Eskayo/portfolio-website-updater",
                                  "signals": ["gileskayo.me", "/wp-content/", "dev site", "MARVIN page", "lib/portfolio_"]},
    "marvin-mobile": {"repo": "G-Eskayo/marvin-mobile", "signals": ["MARVIN Mobile", "mobile backend", "APNs"]},
    "marvin": {"repo": "G-Eskayo/marvin", "signals": ["dashboard"]},
}}


def issue(n, title="Ticket", body="", labels=()):
    return {"number": n, "title": title, "body": body, "labels": [{"name": l} for l in labels]}


def test_a_signal_in_the_title_is_clear():
    v = pt.classify(issue(1, title="MARVIN page: shorter story"), RULES, REPO)
    assert v["verdict"] == "clear" and v["project"] == "portfolio-website-updater"
    assert "MARVIN page" in v["why"]


def test_two_different_signals_in_the_body_are_clear_a_passing_mention_is_ignored():
    two = pt.classify(issue(1, body="push it to the dev site, files under /wp-content/"), RULES, REPO)
    assert two["verdict"] == "clear"
    assert pt.classify(issue(2, body="like the dev site did"), RULES, REPO)["verdict"] is None


def test_spelling_variants_are_one_signal():
    rules = {"projects": {"m": {"repo": "o/m", "signals": ["mobile backend", "mobile-backend"]}}}
    assert pt.classify(issue(1, body="the mobile backend (mobile-backend/) also"), rules, REPO)["verdict"] is None


def test_a_project_that_dominates_is_clear_despite_another_passing_mention():
    v = pt.classify(issue(1, title="MARVIN Mobile PRD", body="APNs; mobile backend; a link to the dev site"), RULES, REPO)
    assert v["verdict"] == "clear" and v["project"] == "marvin-mobile"


def test_matching_is_case_insensitive_and_whole_word():
    assert pt.classify(issue(1, title="apns token rotation"), RULES, REPO)["verdict"] == "clear"
    assert pt.classify(issue(2, title="SNAPNSHOT"), RULES, REPO)["verdict"] is None


def test_two_projects_both_clear_is_unclear_never_guessed():
    v = pt.classify(issue(1, title="MARVIN Mobile shows the MARVIN page"), RULES, REPO)
    assert v["verdict"] == "unclear"
    assert set(v["candidates"]) == {"portfolio-website-updater", "marvin-mobile"}


def test_the_repos_own_project_never_counts():
    assert pt.classify(issue(1, title="dashboard is slow"), RULES, REPO)["verdict"] is None


def test_a_ticket_that_already_has_a_project_label_or_is_pinned_is_left_alone():
    assert pt.classify(issue(1, title="MARVIN page", labels=["project:marvin-mobile"]), RULES, REPO) is None
    assert pt.classify(issue(2, title="MARVIN page", labels=["pinned"]), RULES, REPO) is None


def test_plan_labels_clear_ones_lists_unclear_ones_and_respects_a_removed_label():
    issues = [issue(1, title="MARVIN page rework"), issue(2, title="APNs on the MARVIN page"),
              issue(3, title="APNs key"), issue(4, title="nothing to see")]
    actions, unclear = pt.plan(REPO, issues, RULES, removed={(REPO, 3, "project:marvin-mobile")})
    assert [(a["number"], a["arg"]) for a in actions] == [(1, "project:portfolio-website-updater")]
    assert actions[0]["agent"] == "project_tag" and actions[0]["op"] == "add_label"
    assert [u["number"] for u in unclear] == [2]
    assert unclear[0]["candidates"] == ["marvin-mobile", "portfolio-website-updater"] and unclear[0]["repo"] == REPO


def test_removed_labels_come_from_the_audit_log_a_person_took_it_off():
    audit = [{"agent": "project_tag", "status": "applied", "repo": REPO, "number": 3, "op": "add_label", "arg": "project:marvin-mobile"}]
    current = {(REPO, 3): ["bug"], (REPO, 4): ["project:marvin-mobile"]}
    audit.append({"agent": "project_tag", "status": "applied", "repo": REPO, "number": 4, "op": "add_label", "arg": "project:marvin-mobile"})
    assert pt.removed_by_people(audit, current) == {(REPO, 3, "project:marvin-mobile")}


def test_load_rules_missing_or_corrupt_means_no_rules(tmp_path):
    assert pt.load_rules(tmp_path / "none.json") == {"projects": {}}
    bad = tmp_path / "r.json"
    bad.write_text("{nope")
    assert pt.load_rules(bad) == {"projects": {}}


def test_the_shipped_rules_file_parses_and_every_project_has_a_repo_and_signals():
    rules = pt.load_rules()
    assert rules["projects"], "config/project_tags.json should ship with rules"
    for pid, r in rules["projects"].items():
        assert r.get("repo") and r.get("signals"), pid


def test_state_file_round_trip(tmp_path):
    p = tmp_path / "project-tags.json"
    pt.write_state([{"repo": REPO, "number": 2, "title": "x", "candidates": ["marvin-mobile"]}], pending=1, path=p, now="2026-10-08T00:00:00+00:00")
    d = json.loads(p.read_text())
    assert d["unclear"][0]["number"] == 2 and d["pending"] == 1
