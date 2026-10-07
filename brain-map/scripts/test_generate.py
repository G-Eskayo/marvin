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


# ── ownership paths and openable (#184) ──────────────────────────────────

def test_skill_nodes_have_ownership_path_and_are_openable():
    manifest = {"index": [{"name": "diagnose", "calls": []}]}
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())

    tree = generate.build_tree(manifest, enrichment)
    diagnose_node = [n for n in tree["children"] if n["id"] == "Skills"][0]["children"][0]["children"][0]
    while diagnose_node.get("id") != "diagnose":
        for c in diagnose_node.get("children", []):
            if c.get("id") == "diagnose":
                diagnose_node = c
                break
            else:
                diagnose_node = c

    # Find diagnose more reliably by walking the tree
    def find_node(n, id_):
        if n["id"] == id_:
            return n
        for c in n.get("children", []):
            result = find_node(c, id_)
            if result:
                return result
        return None

    diagnose_node = find_node(tree, "diagnose")
    assert diagnose_node is not None
    assert diagnose_node.get("path") == "skills/diagnose"
    assert diagnose_node.get("openable") is True


def test_recurring_agent_nodes_have_ownership_path_when_script_is_resolvable(tmp_path, monkeypatch):
    # Create a temporary agent script in a mock .agents directory
    agents_dir = tmp_path / ".agents"
    agents_dir.mkdir()
    (agents_dir / "test-agent.py").write_text("#!/usr/bin/env python3\nprint('test')")

    launchd_dir = tmp_path / "LaunchAgents"
    launchd_dir.mkdir()

    # Mock Path.home() for discover_recurring_agents
    monkeypatch.setattr(generate, "LAUNCHD_DIR", launchd_dir)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(generate, "SKILLS_DIR", agents_dir / "skills")  # avoid reading real skills

    write_plist(launchd_dir, "com.marvin.test-agent",
                StartInterval=3600,
                ProgramArguments=["/usr/bin/env", "python3", str(agents_dir / "test-agent.py")])

    agents = generate.discover_recurring_agents()
    assert len(agents) > 0
    test_agent = [a for a in agents if a["id"] == "test-agent"][0]
    assert test_agent.get("script_path") == "test-agent.py"


def test_grouping_nodes_and_machines_do_not_have_path_or_openable():
    manifest = {"index": [{"name": "tdd", "calls": []}]}
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())

    tree = generate.build_tree(manifest, enrichment)

    # MARVIN root should have no path/openable
    assert tree.get("path") is None
    assert tree.get("openable") is None

    # Skills trunk should have no path/openable (it's a grouping node)
    skills_trunk = [n for n in tree["children"] if n["id"] == "Skills"][0]
    assert skills_trunk.get("path") is None
    assert skills_trunk.get("openable") is None

    # Quality category should have no path/openable
    quality_cat = skills_trunk["children"][0]
    assert quality_cat.get("path") is None
    assert quality_cat.get("openable") is None


def test_openable_nodes_all_have_path():
    manifest = json.loads(generate.MANIFEST_PATH.read_text())
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())

    tree = generate.build_tree(manifest, enrichment)

    def walk(node):
        if node.get("openable") is True:
            assert node.get("path") is not None, f"Node {node['id']} is openable but has no path"
        for c in node.get("children", []):
            walk(c)

    walk(tree)


def test_code_layers_are_attached_to_openable_nodes():
    manifest = json.loads(generate.MANIFEST_PATH.read_text())
    enrichment = json.loads(generate.ENRICHMENT_PATH.read_text())

    tree = generate.build_tree(manifest, enrichment)
    generate.attach_code_layers(tree)

    def find_openable(node):
        if node.get("openable"):
            assert "code" in node, f"Openable node {node['id']} has no code field"
            assert isinstance(node["code"], dict)
            assert "files" in node["code"]
            assert "functions" in node["code"]
        for c in node.get("children", []):
            find_openable(c)

    find_openable(tree)


def test_graphify_graph_gracefully_missing_doesnt_crash():
    # This should not raise even if graphify-out/graph.json doesn't exist
    graph = generate.load_graphify_graph()
    # graph can be None or a dict, either is fine
    assert graph is None or isinstance(graph, dict)


def test_code_layer_filters_by_ownership_path():
    # Create a fixture graph with owned and out-of-path nodes
    graph = {
        "nodes": [
            {
                "id": "skills_diagnose_main",
                "label": "main()",
                "file_type": "code",
                "source_file": "skills/diagnose/main.py",
                "source_location": "L1",
                "community": 1,
                "community_name": "diagnose"
            },
            {
                "id": "skills_diagnose_helper",
                "label": "helper()",
                "file_type": "code",
                "source_file": "skills/diagnose/helper.py",
                "source_location": "L5",
                "community": 1,
                "community_name": "diagnose",
                "_callable": True
            },
            {
                "id": "skills_other_func",
                "label": "other()",
                "file_type": "code",
                "source_file": "skills/other/func.py",
                "source_location": "L1",
                "community": 2,
                "community_name": "other",
                "_callable": True
            }
        ],
        "links": [
            {"source": "skills_diagnose_main", "target": "skills_diagnose_helper"},
            {"source": "skills_diagnose_helper", "target": "skills_other_func"}
        ]
    }

    code_layer = generate._compute_code_layer(graph, "skills/diagnose")

    # Should include diagnose nodes
    owned_ids = {n["id"] for nodes in [code_layer["files"], code_layer["functions"]] for n in nodes}
    assert "skills_diagnose_main" in owned_ids
    assert "skills_diagnose_helper" in owned_ids

    # Should NOT include out-of-path nodes in owned
    assert "skills_other_func" not in owned_ids

    # But should identify it as borrowed
    borrowed_ids = {n["id"] for n in code_layer["borrowed"]}
    assert "skills_other_func" in borrowed_ids


def test_code_layer_excludes_test_files():
    graph = {
        "nodes": [
            {
                "id": "skills_diagnose_main",
                "label": "main()",
                "file_type": "code",
                "source_file": "skills/diagnose/main.py",
                "community": 1
            },
            {
                "id": "skills_diagnose_test",
                "label": "_test_helper()",
                "file_type": "code",
                "source_file": "skills/diagnose/tests/test_main.py",
                "community": 1,
                "_callable": True
            }
        ],
        "links": []
    }

    code_layer = generate._compute_code_layer(graph, "skills/diagnose")

    owned_ids = {n["id"] for nodes in [code_layer["files"], code_layer["functions"]] for n in nodes}
    assert "skills_diagnose_main" in owned_ids
    assert "skills_diagnose_test" not in owned_ids


def test_code_layer_groups_by_community():
    graph = {
        "nodes": [
            {
                "id": "node1",
                "label": "File1",
                "file_type": "code",
                "source_file": "skills/tdd/file1.py",
                "community": 1,
                "community_name": "TDD Core"
            },
            {
                "id": "node2",
                "label": "func()",
                "file_type": "code",
                "source_file": "skills/tdd/func.py",
                "source_location": "L10",
                "community": 1,
                "community_name": "TDD Core",
                "_callable": True
            },
            {
                "id": "node3",
                "label": "other()",
                "file_type": "code",
                "source_file": "skills/tdd/other.py",
                "source_location": "L20",
                "community": 2,
                "community_name": "Helpers",
                "_callable": True
            }
        ],
        "links": []
    }

    code_layer = generate._compute_code_layer(graph, "skills/tdd")

    # Verify community grouping is preserved
    for node in code_layer["files"] + code_layer["functions"]:
        assert node["community"] >= 1
        assert node["community_name"] != ""


def test_code_layer_filters_vendor_paths():
    """Vendor and generated files should not appear in owned or borrowed."""
    graph = {
        "nodes": [
            {
                "id": "skills_diagnose_main",
                "label": "main()",
                "file_type": "code",
                "source_file": "skills/diagnose/main.py",
                "community": 1
            },
            {
                "id": "skills_diagnose_vendor",
                "label": "motion.min.js",
                "file_type": "code",
                "source_file": "skills/diagnose/vendor/motion.12.42.2.js",
                "community": 1,
                "_callable": True
            },
            {
                "id": "skills_diagnose_pyc",
                "label": "compiled",
                "file_type": "code",
                "source_file": "skills/diagnose/__pycache__/main.cpython-39.pyc",
                "community": 1
            },
            {
                "id": "skills_diagnose_dist",
                "label": "built",
                "file_type": "code",
                "source_file": "skills/diagnose/dist/bundle.min.js",
                "community": 1,
                "_callable": True
            }
        ],
        "links": [
            {"source": "skills_diagnose_main", "target": "skills_diagnose_vendor"},
            {"source": "skills_diagnose_main", "target": "skills_diagnose_pyc"}
        ]
    }

    code_layer = generate._compute_code_layer(graph, "skills/diagnose")

    owned_ids = {n["id"] for nodes in [code_layer["files"], code_layer["functions"]] for n in nodes}
    borrowed_ids = {n["id"] for n in code_layer["borrowed"]}

    # Vendor/generated should be completely absent
    assert "skills_diagnose_vendor" not in owned_ids
    assert "skills_diagnose_vendor" not in borrowed_ids
    assert "skills_diagnose_pyc" not in owned_ids
    assert "skills_diagnose_pyc" not in borrowed_ids
    assert "skills_diagnose_dist" not in owned_ids
    assert "skills_diagnose_dist" not in borrowed_ids

    # Only the main file should be owned
    assert "skills_diagnose_main" in owned_ids


def test_code_layer_bucketing_test_files():
    """Test files should be bucketed separately in code['tests'], not in owned."""
    graph = {
        "nodes": [
            {
                "id": "skills_diagnose_main",
                "label": "main.py",
                "file_type": "code",
                "source_file": "skills/diagnose/main.py",
                "community": 1
            },
            {
                "id": "skills_diagnose_test",
                "label": "test_main.py",
                "file_type": "code",
                "source_file": "skills/diagnose/tests/test_main.py",
                "community": 1
            },
            {
                "id": "skills_diagnose_test_helper",
                "label": "test_helper()",
                "file_type": "code",
                "source_file": "skills/diagnose/test_helpers.py",
                "source_location": "L5",
                "community": 1,
                "_callable": True
            }
        ],
        "links": []
    }

    code_layer = generate._compute_code_layer(graph, "skills/diagnose")

    owned_ids = {n["id"] for nodes in [code_layer["files"], code_layer["functions"]] for n in nodes}
    test_ids = {n["id"] for n in code_layer["tests"]}

    # Main should be owned, tests should be bucketed separately
    assert "skills_diagnose_main" in owned_ids
    assert "skills_diagnose_test" in test_ids
    assert "skills_diagnose_test_helper" in test_ids
    assert "skills_diagnose_test" not in owned_ids
    assert "skills_diagnose_test_helper" not in owned_ids
    # Tests should not leak into owned bucket
    assert len(test_ids) == 2
    assert len(owned_ids) == 1


def test_code_layer_test_structure():
    """Test nodes should have same structure as owned nodes (files vs functions)."""
    graph = {
        "nodes": [
            {
                "id": "skills_tdd_test_file",
                "label": "test_main.py",
                "file_type": "code",
                "source_file": "skills/tdd/tests/test_main.py",
                "community": 1
            },
            {
                "id": "skills_tdd_test_func",
                "label": "test_something()",
                "file_type": "code",
                "source_file": "skills/tdd/tests/test_main.py",
                "source_location": "L10",
                "community": 1,
                "_callable": True
            }
        ],
        "links": []
    }

    code_layer = generate._compute_code_layer(graph, "skills/tdd")

    assert "tests" in code_layer
    assert isinstance(code_layer["tests"], list)
    assert len(code_layer["tests"]) == 2
    # Test file and function should both have community info
    for test_node in code_layer["tests"]:
        assert "id" in test_node
        assert "label" in test_node
        assert "community" in test_node
        assert "source_file" in test_node


def test_code_layer_live_regression_guard_no_vendor_in_borrowing():
    """Live regression: ensure borrowed nodes never include vendor/generated code."""
    graph = {
        "nodes": [
            {
                "id": "skills_diagnose_main",
                "label": "main()",
                "file_type": "code",
                "source_file": "skills/diagnose/main.py",
                "community": 1
            },
            {
                "id": "external_func",
                "label": "external_func()",
                "file_type": "code",
                "source_file": "skills/other/func.py",
                "source_location": "L5",
                "community": 2,
                "_callable": True
            },
            {
                "id": "vendor_motion",
                "label": "motion.js",
                "file_type": "code",
                "source_file": "brain-map/vendor/motion.12.42.2.js",
                "community": 3
            }
        ],
        "links": [
            {"source": "skills_diagnose_main", "target": "external_func"},
            {"source": "skills_diagnose_main", "target": "vendor_motion"}
        ]
    }

    code_layer = generate._compute_code_layer(graph, "skills/diagnose")

    borrowed_ids = {n["id"] for n in code_layer["borrowed"]}

    # external_func should be borrowed
    assert "external_func" in borrowed_ids
    # vendor_motion should NOT be borrowed, despite being called
    assert "vendor_motion" not in borrowed_ids
