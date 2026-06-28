"""Tests for qa-agent scripts. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_qa.py -v
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path

import pytest

# resolve scripts/ on path
SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

from qa_scan import detect_stack, extract_dependencies, extract_imports, extract_markers
from qa_capture import build_entry
from qa_query import filter_results


# ── qa_scan ──────────────────────────────────────────────────────────────────

def make_project(files: dict[str, str]) -> Path:
    tmp = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp


def test_detect_stack_python():
    p = make_project({"requirements.txt": "requests==2.28\nflask>=2.0"})
    stack = detect_stack(p)
    assert "python" in stack


def test_detect_stack_javascript():
    p = make_project({"package.json": json.dumps({"dependencies": {"react": "^18"}})})
    stack = detect_stack(p)
    assert "javascript" in stack


def test_detect_stack_multi():
    p = make_project({
        "requirements.txt": "fastapi",
        "package.json": json.dumps({"dependencies": {}}),
    })
    stack = detect_stack(p)
    assert "python" in stack and "javascript" in stack


def test_extract_dependencies_python():
    p = make_project({"requirements.txt": "requests==2.28\nflask>=2.0\n# comment\nnumpy"})
    deps = extract_dependencies(p)
    libs = [d["name"] for d in deps]
    assert "requests" in libs
    assert "flask" in libs
    assert "numpy" in libs


def test_extract_dependencies_node():
    pkg = {"dependencies": {"react": "^18", "axios": "^1"}, "devDependencies": {"jest": "^29"}}
    p = make_project({"package.json": json.dumps(pkg)})
    deps = extract_dependencies(p)
    libs = [d["name"] for d in deps]
    assert "react" in libs
    assert "axios" in libs
    assert "jest" in libs


def test_extract_imports_python():
    src = "import os\nimport sys\nfrom pathlib import Path\nfrom collections import defaultdict\n"
    p = make_project({"main.py": src})
    imports = extract_imports(p)
    assert "os" in imports
    assert "sys" in imports
    assert "pathlib" in imports
    assert "collections" in imports


def test_extract_markers():
    src = (
        "x = 1  # TODO: fix this later\n"
        "y = 2  # FIXME: broken\n"
        "z = 3  # HACK: workaround for upstream bug\n"
        "w = 4  # normal comment\n"
    )
    p = make_project({"main.py": src})
    markers = extract_markers(p)
    types = [m["marker"] for m in markers]
    assert "TODO" in types
    assert "FIXME" in types
    assert "HACK" in types
    assert len(markers) == 3  # not the normal comment


# ── qa_capture ────────────────────────────────────────────────────────────────

def test_build_entry_required_fields():
    entry = build_entry(
        content="Always use PersistentClient for ChromaDB",
        category="anti-pattern",
    )
    assert entry["document"] == "Always use PersistentClient for ChromaDB"
    assert entry["metadata"]["category"] == "anti-pattern"
    assert "created_at" in entry["metadata"]
    assert entry["id"].startswith("qa-")


def test_build_entry_optional_fields():
    entry = build_entry(
        content="Use venv for Python isolation",
        category="pattern",
        library="python",
        tags="venv,isolation,python",
        confidence="high",
        project="my-project",
    )
    assert entry["metadata"]["library"] == "python"
    assert entry["metadata"]["tags"] == "venv,isolation,python"
    assert entry["metadata"]["confidence"] == "high"
    assert entry["metadata"]["project"] == "my-project"


def test_build_entry_dedup_id_stable():
    e1 = build_entry(content="Use venv", category="pattern")
    e2 = build_entry(content="Use venv", category="pattern")
    assert e1["id"] == e2["id"]  # same content → same id → dedup in ChromaDB


# ── qa_query ─────────────────────────────────────────────────────────────────

def test_filter_results_by_category():
    results = [
        {"metadata": {"category": "pattern"}, "document": "a"},
        {"metadata": {"category": "anti-pattern"}, "document": "b"},
        {"metadata": {"category": "pattern"}, "document": "c"},
    ]
    filtered = filter_results(results, category="pattern")
    assert len(filtered) == 2
    assert all(r["metadata"]["category"] == "pattern" for r in filtered)


def test_filter_results_no_filter():
    results = [
        {"metadata": {"category": "pattern"}, "document": "a"},
        {"metadata": {"category": "failed"}, "document": "b"},
    ]
    filtered = filter_results(results, category=None)
    assert len(filtered) == 2
