#!/usr/bin/env python3
"""Use-case cards for skills, agents, tabs, and machines (#268, Gil 2026-10-08)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import export_snapshot  # noqa: E402
import generate  # noqa: E402


def tree():
    return {"id": "MARVIN", "children": [
        {"id": "diagnose", "cat": "skills", "children": []},
        {"id": "daily-digest", "cat": "agents", "children": []},
        {"id": "Health tab", "cat": "dashboard", "children": []},
        {"id": "mac-mini-1", "cat": "cross-machine", "desc": "device — added 2026-07-06 — hostname", "children": []},
        {"id": "exo", "cat": "cross-machine", "desc": "Distributed LLM inference", "children": []},
        {"id": "Projects", "cat": "projects", "children": [
            {"id": "secret-app", "cat": "projects", "visibility": "PRIVATE", "children": []},
        ]},
    ]}


def test_attach_use_case_sets_fields_for_eligible_nodes():
    """Eligible nodes (skills, agents, tabs, machines) get use_case fields."""
    t = tree()
    eligible = {"diagnose", "daily-digest", "Health tab", "mac-mini-1"}
    use_cases_dict = {
        "diagnose": {"use_case": "Find why it's broken.", "example": "https://issue", "status": "live"},
        "daily-digest": {"use_case": "Write the morning summary.", "example": "path", "status": "live"},
        "Health tab": {"use_case": "See what's red.", "example": "path", "status": "live"},
        "mac-mini-1": {"use_case": "Run the work.", "example": "path", "status": "live"},
    }
    enrichment = {"use_cases": use_cases_dict}

    missing = generate.attach_use_case(t, enrichment, eligible)

    # Check fields are attached
    assert t["children"][0]["use_case"] == "Find why it's broken."
    assert t["children"][1]["status"] == "live"
    # Non-eligible nodes (exo, Projects) are not touched
    assert "use_case" not in t["children"][3]
    assert missing == []


def test_attach_use_case_names_missing_entries():
    """Nodes without use_case entries are collected and returned."""
    t = tree()
    eligible = {"diagnose", "daily-digest", "Health tab", "mac-mini-1"}
    enrichment = {"use_cases": {"diagnose": {"use_case": "...", "example": "...", "status": "live"}}}

    missing = generate.attach_use_case(t, enrichment, eligible)

    assert sorted(missing) == ["Health tab", "daily-digest", "mac-mini-1"]


def test_enrichment_use_cases_has_entries_for_all_skills():
    """Every skill in skill_categories must have a use_cases entry."""
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())
    skill_categories = enrichment.get("skill_categories", {})
    use_cases = enrichment.get("use_cases", {})

    missing = [s for s in skill_categories if s not in use_cases]
    assert missing == [], f"Skills without use_case entries: {missing}"


def test_use_cases_do_not_leak_locked_project_names():
    """Locked project names don't appear in use-case cards."""
    tree_obj = {
        "id": "root",
        "children": [
            {
                "id": "Projects",
                "children": [
                    {"id": "secret-app", "cat": "projects", "visibility": "PRIVATE"},
                    {"id": "public-app", "cat": "projects", "visibility": "PUBLIC"},
                ]
            }
        ]
    }

    # Simulate collecting locked project names
    locked = {"secret-app"}

    # Build use_cases
    enrichment = {"use_cases": {}, "use_case_extra": []}
    result = export_snapshot.build_use_cases(tree_obj, enrichment, locked)
    assert result is not None  # Should not fail

    # If a card mentions the locked project, it should fail
    enrichment_with_leak = {
        "use_cases": {},
        "use_case_extra": [
            {"id": "tool", "cat": "tools", "label": "Tool", "use_case": "Works with secret-app", "example": "url", "status": "live"}
        ]
    }
    result = export_snapshot.build_use_cases(tree_obj, enrichment_with_leak, locked)
    assert result is None, "Should fail when locked project name appears in use_case"


def test_publish_map_requires_use_cases_json():
    """Refuse to publish when use-cases.json is missing from snapshot."""
    import publish_map
    # The REQUIRED tuple should include use-cases.json
    assert "use-cases.json" in publish_map.REQUIRED
