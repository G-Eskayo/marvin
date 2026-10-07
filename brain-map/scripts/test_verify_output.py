#!/usr/bin/env python3
"""Verify the generated index.html and tree-data.json contain correct structure."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate  # noqa: E402


def test_tree_data_contains_tests_field():
    """Verify tree-data.json has tests field in code layers."""
    with open(generate.TREE_DATA_PATH) as f:
        data = json.load(f)

    tree = data.get("tree", {})

    # Find openable nodes with code data
    openable_with_code = []

    def walk(node):
        if node.get("openable") and node.get("code"):
            openable_with_code.append(node)
        for child in node.get("children", []):
            walk(child)

    walk(tree)

    # All openable nodes should have tests field
    assert len(openable_with_code) > 0, "No openable nodes with code found"
    for node in openable_with_code:
        code = node["code"]
        assert "tests" in code, f"Node {node['id']} missing 'tests' field"
        assert isinstance(code["tests"], list), f"Node {node['id']} tests should be a list"
        # All required fields should be present
        assert "files" in code
        assert "functions" in code
        assert "borrowed" in code
        assert "edges" in code


def test_no_vendor_code_in_output():
    """Verify generated data contains no vendor/generated code."""
    with open(generate.TREE_DATA_PATH) as f:
        data = json.load(f)

    tree = data.get("tree", {})
    vendor_patterns = ["/vendor/", "/node_modules/", "/__pycache__/", "/dist/", "/build/", ".min.js", ".pyc"]

    def walk(node):
        if node.get("code"):
            code = node["code"]
            all_files = code.get("files", []) + code.get("functions", []) + code.get("borrowed", []) + code.get("tests", [])
            for file_node in all_files:
                source_file = file_node.get("source_file", "")
                for pattern in vendor_patterns:
                    assert pattern not in source_file, f"Found vendor/generated file {source_file} in node {node['id']}"
        for child in node.get("children", []):
            walk(child)

    walk(tree)


def test_html_includes_tests_toggle():
    """Verify index.html includes the tests toggle control and showTests variable."""
    with open(generate.OUTPUT_PATH) as f:
        html = f.read()

    # Check for showTests variable
    assert "var showTests = false" in html, "showTests variable not found in HTML"

    # Check for tests toggle control
    assert "code-layer-tests-toggle" in html, "Tests toggle control not found"
    assert "tests-toggle" in html, "Tests toggle button not found"

    # Check for showTests in window.__map
    assert "showTests: function" in html, "showTests method not in window.__map hook"


if __name__ == "__main__":
    test_tree_data_contains_tests_field()
    test_no_vendor_code_in_output()
    test_html_includes_tests_toggle()
    print("All verification tests passed!")
