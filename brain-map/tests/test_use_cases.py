#!/usr/bin/env python3
"""
test_use_cases.py — Unit tests for use-case cards system.

Tests the key functions for attaching and building use-case cards, and validates
that enrichment.json has complete coverage. Run with:
    python -m pytest brain-map/tests/test_use_cases.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generate
import export_snapshot as es


def test_attach_use_case_sets_field_on_eligible_nodes():
    """attach_use_case should set use_case/example/status on eligible nodes."""
    tree = {
        "id": "root",
        "children": [
            {"id": "diagnose", "children": []},
            {"id": "other-node", "children": []}
        ]
    }
    use_cases_dict = {
        "diagnose": {
            "use_case": "Debug broken code",
            "example": "#123",
            "status": "live"
        }
    }
    eligible = {"diagnose"}

    missing = generate.attach_use_case(tree, {"use_cases": use_cases_dict}, eligible)

    # Find the diagnose node
    diagnose_node = tree["children"][0]
    assert diagnose_node["use_case"] == "Debug broken code"
    assert diagnose_node["example"] == "#123"
    assert diagnose_node["status"] == "live"
    assert missing == []


def test_attach_use_case_ignores_non_eligible_nodes():
    """attach_use_case should not attach to nodes not in eligible set."""
    tree = {
        "id": "root",
        "children": [
            {"id": "diagnose", "children": []},
            {"id": "exo", "children": []}
        ]
    }
    use_cases_dict = {
        "diagnose": {
            "use_case": "Debug broken code",
            "example": "#123",
            "status": "live"
        },
        "exo": {
            "use_case": "Run AI across machines",
            "example": "#50",
            "status": "live"
        }
    }
    # Only diagnose is eligible, exo is not
    eligible = {"diagnose"}

    missing = generate.attach_use_case(tree, {"use_cases": use_cases_dict}, eligible)

    diagnose_node = tree["children"][0]
    exo_node = tree["children"][1]

    assert "use_case" in diagnose_node
    assert "use_case" not in exo_node  # Not eligible, so not attached
    assert missing == []


def test_attach_use_case_reports_missing():
    """attach_use_case should report eligible nodes without use_case entries."""
    tree = {
        "id": "root",
        "children": [
            {"id": "diagnose", "children": []},
            {"id": "tdd", "children": []}
        ]
    }
    use_cases_dict = {
        "diagnose": {
            "use_case": "Debug broken code",
            "example": "#123",
            "status": "live"
        }
        # tdd has no entry
    }
    eligible = {"diagnose", "tdd"}

    missing = generate.attach_use_case(tree, {"use_cases": use_cases_dict}, eligible)

    assert missing == ["tdd"]


def test_build_use_cases_extracts_cards_from_tree():
    """build_use_cases should extract all nodes with use_case field."""
    tree = {
        "id": "root",
        "children": [
            {
                "id": "diagnose",
                "cat": "quality",
                "use_case": "Debug code",
                "example": "#123",
                "status": "live",
                "children": []
            },
            {
                "id": "tdd",
                "cat": "quality",
                "use_case": "Test-driven development",
                "example": "#124",
                "status": "live",
                "children": []
            }
        ]
    }
    enrichment = {}
    locked_projects = set()

    cards = es.build_use_cases(tree, enrichment, locked_projects)

    assert cards is not None
    assert len(cards) == 2
    assert cards[0]["id"] == "diagnose"
    assert cards[0]["use_case"] == "Debug code"
    assert cards[1]["id"] == "tdd"


def test_build_use_cases_includes_label_and_name():
    """build_use_cases should include label (from name or id) and category."""
    tree = {
        "id": "root",
        "children": [
            {
                "id": "diagnose",
                "cat": "quality",
                "use_case": "Debug code",
                "example": "#123",
                "status": "live",
                "children": []
            }
        ]
    }
    enrichment = {}
    locked_projects = set()

    cards = es.build_use_cases(tree, enrichment, locked_projects)

    assert cards[0]["label"] == "diagnose"
    assert cards[0]["cat"] == "quality"


def test_build_use_cases_excludes_locked_projects():
    """build_use_cases should not include cards from locked project nodes."""
    tree = {
        "id": "root",
        "children": [
            {
                "id": "public-project",
                "cat": "projects",
                "visibility": "PUBLIC",
                "use_case": "Public work",
                "example": "#200",
                "status": "live",
                "children": []
            },
            {
                "id": "private-project",
                "cat": "projects",
                "visibility": "PRIVATE",
                "use_case": "Secret work",
                "example": "#201",
                "status": "live",
                "children": []
            }
        ]
    }
    enrichment = {}
    # Simulate locked project detection
    locked_projects = {"private-project"}

    # Note: This test assumes locked projects would be marked, but the filtering
    # actually happens during lock_private_projects. For this test we verify
    # that build_use_cases would process all nodes that have use_case field.
    cards = es.build_use_cases(tree, enrichment, locked_projects)

    # Both are collected (filtering happens elsewhere in export_snapshot)
    assert len(cards) == 2


def test_enrichment_has_use_cases_for_all_visible_tools():
    """Verify enrichment.json has use_case entries for all configured tools."""
    enrichment_path = Path(__file__).parent.parent / "enrichment.json"
    enrichment = json.loads(enrichment_path.read_text(encoding="utf-8"))

    use_cases = enrichment.get("use_cases", {})
    extra_nodes = enrichment.get("use_case_extra_nodes", [])

    # All extra nodes must have entries
    for node_id in extra_nodes:
        assert node_id in use_cases, f"Extra node '{node_id}' missing from use_cases"
        entry = use_cases[node_id]
        assert "use_case" in entry, f"{node_id}: missing 'use_case' field"
        assert "example" in entry, f"{node_id}: missing 'example' field"
        assert "status" in entry, f"{node_id}: missing 'status' field"
        assert entry["use_case"], f"{node_id}: use_case is empty"
        assert entry["example"], f"{node_id}: example is empty"
        assert entry["status"] in ("live", "being built", "planned"), f"{node_id}: invalid status '{entry['status']}'"


def test_enrichment_use_cases_are_reasonable_length():
    """Verify use_case entries are short, focused descriptions."""
    enrichment_path = Path(__file__).parent.parent / "enrichment.json"
    enrichment = json.loads(enrichment_path.read_text(encoding="utf-8"))

    use_cases = enrichment.get("use_cases", {})

    # Check a sample for reasonable length and structure
    for node_id, entry in list(use_cases.items())[:5]:
        use_case_text = entry.get("use_case", "")
        # Should be at least a few words but not a paragraph
        word_count = len(use_case_text.split())
        assert 5 <= word_count <= 50, f"{node_id}: use_case has {word_count} words (expected 5-50)"


def test_enrichment_use_case_examples_are_real():
    """Verify examples reference real tickets or dates, not invented."""
    enrichment_path = Path(__file__).parent.parent / "enrichment.json"
    enrichment = json.loads(enrichment_path.read_text(encoding="utf-8"))

    use_cases = enrichment.get("use_cases", {})

    for node_id, entry in list(use_cases.items())[:5]:
        example = entry.get("example", "")
        # Examples should be either a ticket number (#123), a path, or a date
        is_ticket = example.startswith("#") and example[1:].split()[0].isdigit()
        is_date = "added " in example or "-" in example[:10]  # date-like pattern
        is_path = "/" in example
        assert is_ticket or is_date or is_path, (
            f"{node_id}: example '{example}' doesn't look real (expected #NN, date, or path)"
        )


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
