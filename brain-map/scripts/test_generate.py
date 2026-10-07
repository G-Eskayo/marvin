#!/usr/bin/env python3
"""
Tests for generate.py's system layer (#182): every skill, recurring agent,
machine, dashboard tab and current project appears, and the node list is
derived from the live system, never hand-kept.
"""
import json
import plistlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate  # noqa: E402


def ids(node: dict) -> set:
    out: set = set()
    generate.collect_ids(node, out)
    return out


def write_plist(dir_: Path, label: str, **keys) -> None:
    with (dir_ / f"{label}.plist").open("wb") as f:
        plistlib.dump({"Label": label, "ProgramArguments": ["/bin/true"], **keys}, f)


# ── recurring agents ─────────────────────────────────────────────────────

def test_recurring_agents_include_interval_jobs_and_skip_one_offs_and_services(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "LAUNCHD_DIR", tmp_path)
    write_plist(tmp_path, "com.marvin.daily-digest", StartCalendarInterval={"Hour": 7, "Minute": 0})
    write_plist(tmp_path, "com.marvin.ticket-pipeline", StartInterval=900)
    write_plist(tmp_path, "com.marvin.weekly", StartCalendarInterval=[{"Weekday": 1, "Hour": 9, "Minute": 30}])
    write_plist(tmp_path, "com.marvin.verify-once", StartCalendarInterval={"Day": 7, "Month": 7, "Hour": 9, "Minute": 0})
    write_plist(tmp_path, "com.marvin.desktoplive", RunAtLoad=True, KeepAlive=True)

    agents = {a["id"]: a for a in generate.discover_recurring_agents()}

    assert set(agents) == {"daily-digest", "ticket-pipeline", "weekly"}
    assert agents["daily-digest"]["schedule"] == "07:00"
    assert agents["ticket-pipeline"]["schedule"] == "every 15 min"
    assert agents["weekly"]["schedule"] == "09:30"


# ── skills ───────────────────────────────────────────────────────────────

def test_skill_without_a_category_still_appears_under_other(capsys):
    manifest = {"index": [{"name": "tdd", "calls": []}, {"name": "brand-new-skill", "calls": []}]}
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())
    assert "brand-new-skill" not in enrichment["skill_categories"]

    tree = generate.build_tree(manifest, enrichment)

    assert "brand-new-skill" in ids(tree)
    other = [n for n in tree["children"] if n["id"] == "Skills"][0]["children"]
    assert any(c["cat"] == "other" and any(s["id"] == "brand-new-skill" for s in c["children"]) for c in other)


# ── dashboard tabs ───────────────────────────────────────────────────────

def test_dashboard_tabs_read_from_the_app_source(tmp_path, monkeypatch):
    app = tmp_path / "App.jsx"
    app.write_text("const TABS = [\n  { id: 'metrics', label: 'Metrics' },\n  { id: 'mr-review', label: 'MR Review' }\n]\n")
    monkeypatch.setattr(generate, "DASHBOARD_APP_PATH", app)

    assert [t["id"] for t in generate.discover_dashboard_tabs()] == ["Metrics tab", "MR Review tab"]


# ── projects ─────────────────────────────────────────────────────────────

def test_projects_are_active_and_recent_catalog_entries_except_marvin(tmp_path, monkeypatch):
    (tmp_path / "projects.some-mac.json").write_text(json.dumps({"projects": [
        {"id": "marvin", "name": "marvin", "status": "active", "visibility": "PUBLIC", "kind": "repo", "description": "this system"},
        {"id": "finance-os", "name": "finance-os", "status": "active", "visibility": "PRIVATE", "kind": "repo", "description": "Budgeting app"},
        {"id": "killer-sudoku", "name": "killer-sudoku", "status": "recent", "visibility": "PUBLIC", "kind": "repo", "description": ""},
        {"id": "old", "name": "old", "status": "dormant", "visibility": "PUBLIC", "kind": "repo", "description": ""},
    ]}))
    monkeypatch.setattr(generate, "CATALOG_DIR", tmp_path)

    projects = {p["id"]: p for p in generate.discover_projects()}

    assert set(projects) == {"finance-os", "killer-sudoku"}
    assert projects["finance-os"]["visibility"] == "PRIVATE"


def test_no_catalog_means_no_projects_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(generate, "CATALOG_DIR", tmp_path / "missing")
    assert generate.discover_projects() == []


def test_a_project_named_like_a_skill_gets_its_own_id_and_keeps_its_name(tmp_path, monkeypatch):
    (tmp_path / "projects.some-mac.json").write_text(json.dumps({"projects": [
        {"id": "paper-dive", "name": "paper-dive", "status": "active", "visibility": "PUBLIC", "kind": "repo", "description": ""},
    ]}))
    monkeypatch.setattr(generate, "CATALOG_DIR", tmp_path)
    manifest = json.loads(generate.MANIFEST_PATH.read_text())
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())

    tree = generate.build_tree(manifest, enrichment)

    projects = next(c for c in tree["children"] if c["id"] == "Projects")["children"]
    assert [(p["id"], p.get("name")) for p in projects] == [("project:paper-dive", "paper-dive")]


def test_every_node_id_in_the_live_tree_is_unique():
    manifest = json.loads(generate.MANIFEST_PATH.read_text())
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())
    seen: list = []
    (walk := lambda n: (seen.append(n["id"]), [walk(c) for c in n.get("children", [])]))(generate.build_tree(manifest, enrichment))
    assert sorted(i for i in set(seen) if seen.count(i) > 1) == []


# ── the live system (guards against anything silently dropping out) ─────

def test_live_tree_contains_every_skill_agent_machine_tab_and_project():
    manifest = json.loads(generate.MANIFEST_PATH.read_text())
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())
    tree_ids = ids(generate.build_tree(manifest, enrichment))

    missing_skills = [e["name"] for e in manifest["index"] if e["name"] not in tree_ids]
    # A few skills are deliberately shown as a richer node elsewhere under
    # another id (research-colony is an agent) — those count as present.
    represented = {"research-colony"}
    assert [s for s in missing_skills if s not in represented] == []
    for a in generate.discover_recurring_agents():
        assert a["id"] in tree_ids
    for d in generate.discover_devices():
        assert d["id"] in tree_ids
    for t in generate.discover_dashboard_tabs():
        assert t["id"] in tree_ids
    for p in generate.discover_projects():
        assert p["id"] in tree_ids
    assert {"Dashboard", "Projects"} <= tree_ids


def test_plist_that_only_launchd_tolerates_still_counts(tmp_path, monkeypatch):
    # "--" inside an XML comment: launchd and plutil accept it, Python's parser doesn't.
    (tmp_path / "com.marvin.nightly.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<plist version="1.0"><dict>\n'
        '<key>Label</key><string>com.marvin.nightly</string>\n'
        '<!-- every day at 04:00 -- quiet hour -->\n'
        '<key>StartCalendarInterval</key><dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>0</integer></dict>\n'
        '</dict></plist>\n')
    monkeypatch.setattr(generate, "LAUNCHD_DIR", tmp_path)

    assert [a["id"] for a in generate.discover_recurring_agents()] == ["nightly"]
