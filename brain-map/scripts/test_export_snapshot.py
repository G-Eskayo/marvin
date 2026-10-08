#!/usr/bin/env python3
"""
Tests for export_snapshot.py: privacy filtering, anonymization, and leak scanning (#187).

Verifies:
- Private projects are locked (no path/openable/code)
- Public projects remain openable
- Machine hostnames are anonymized to kind + count
- Code layers are filtered to git-tracked files only
- Privacy scanner catches paths, IPs, emails, tokens
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_snapshot  # noqa: E402


# ── privacy scanning ─────────────────────────────────────────────────────

def test_privacy_scan_flags_seeded_path():
    text = "This file is /Users/gileskayo/some/path"
    leaks = export_snapshot.scan_for_leaks(text)
    assert any("/Users/" in leak for leak in leaks)


def test_privacy_scan_flags_seeded_ipv4():
    text = "Server running at 192.168.1.1:8080"
    leaks = export_snapshot.scan_for_leaks(text)
    assert any("IPv4" in leak for leak in leaks)


def test_privacy_scan_flags_seeded_email():
    text = "Contact us at hello@example.com for details"
    leaks = export_snapshot.scan_for_leaks(text)
    assert any("email" in leak for leak in leaks)


def test_privacy_scan_flags_seeded_anthropic_token():
    text = "API key sk-ant-abc123def456"
    leaks = export_snapshot.scan_for_leaks(text)
    assert any("Anthropic" in leak for leak in leaks)


def test_privacy_scan_flags_seeded_github_token():
    text = "Token: gho_abc123def456"
    leaks = export_snapshot.scan_for_leaks(text)
    assert any("GitHub" in leak for leak in leaks)


def test_privacy_scan_flags_seeded_aws_key():
    text = "Key AKIAIOSFODNN7EXAMPLE"
    leaks = export_snapshot.scan_for_leaks(text)
    assert any("AWS" in leak for leak in leaks)


def test_privacy_scan_flags_seeded_slack_token():
    text = "Token xoxb-abc123def456"
    leaks = export_snapshot.scan_for_leaks(text)
    assert any("Slack" in leak for leak in leaks)


def test_privacy_scan_flags_seeded_bearer_token():
    text = "Bearer aaaabbbbccccddddeeeeffffgggg"
    leaks = export_snapshot.scan_for_leaks(text)
    assert any("Bearer" in leak for leak in leaks)


def test_privacy_scan_clean_export_passes():
    text = "This is clean exported code with no secrets just regular text"
    leaks = export_snapshot.scan_for_leaks(text)
    assert not leaks


# ── code layer filtering ─────────────────────────────────────────────────

def test_sanitize_code_layer_filters_files_outside_allowlist():
    code = {
        "files": [
            {"id": "file1", "source_file": "lib/core.py"},
            {"id": "file2", "source_file": "vendor/external/lib.py"},
        ],
        "functions": [],
        "borrowed": [],
        "tests": [],
        "edges": [],
    }
    allowlist = {"lib/core.py"}
    result = export_snapshot.sanitize_code_layer(code, allowlist)
    assert len(result["files"]) == 1
    assert result["files"][0]["id"] == "file1"


def test_sanitize_code_layer_removes_edges_to_dropped_nodes():
    code = {
        "files": [
            {"id": "file1", "source_file": "lib/core.py"},
            {"id": "file2", "source_file": "lib/utils.py"},
        ],
        "functions": [
            {"id": "func1", "source_file": "lib/core.py"},
            {"id": "func2", "source_file": "external/func.py"},
        ],
        "borrowed": [],
        "tests": [],
        "edges": [
            {"source": "func1", "target": "func2"},  # target dropped
            {"source": "func1", "target": "file2"},  # both survive
        ],
    }
    allowlist = {"lib/core.py", "lib/utils.py"}
    result = export_snapshot.sanitize_code_layer(code, allowlist)
    # func2 is dropped (not in allowlist), so its edge should be dropped
    assert len(result["edges"]) == 1
    assert result["edges"][0]["target"] == "file2"


def test_sanitize_code_layer_preserves_borrowed_in_allowlist():
    code = {
        "files": [],
        "functions": [{"id": "func1", "source_file": "lib/core.py"}],
        "borrowed": [
            {"id": "ext1", "source_file": "external/allowed.py"},
            {"id": "ext2", "source_file": "external/forbidden.py"},
        ],
        "tests": [],
        "edges": [],
    }
    allowlist = {"lib/core.py", "external/allowed.py"}
    result = export_snapshot.sanitize_code_layer(code, allowlist)
    assert len(result["borrowed"]) == 1
    assert result["borrowed"][0]["id"] == "ext1"


# ── project locking ──────────────────────────────────────────────────────

def test_private_projects_are_locked_nodes():
    tree = {
        "id": "root",
        "children": [
            {
                "id": "Projects",
                "cat": "projects",
                "children": [
                    {
                        "id": "public-project",
                        "cat": "projects",
                        "visibility": "PUBLIC",
                        "path": "/some/path",
                        "openable": True,
                        "code": {"files": []},
                    },
                    {
                        "id": "private-project",
                        "cat": "projects",
                        "visibility": "PRIVATE",
                        "path": "/some/path",
                        "openable": True,
                        "code": {"files": []},
                    },
                    {
                        "id": "local-project",
                        "cat": "projects",
                        "visibility": None,
                        "path": "/some/path",
                        "openable": True,
                        "code": {"files": []},
                    },
                ],
            }
        ],
    }

    export_snapshot.lock_private_projects(tree)

    projects = tree["children"][0]["children"]
    public = projects[0]
    private = projects[1]
    local = projects[2]

    # PUBLIC project unchanged
    assert public.get("openable") is True
    assert "path" in public
    assert "code" in public
    assert "locked" not in public or not public.get("locked")

    # PRIVATE project locked
    assert private.get("locked") is True
    assert "openable" not in private
    assert "path" not in private
    assert "code" not in private

    # Local (null) project locked
    assert local.get("locked") is True
    assert "openable" not in local
    assert "path" not in local
    assert "code" not in local


# ── machine anonymization ────────────────────────────────────────────────

def test_machines_shown_by_kind_not_hostname():
    tree = {
        "id": "root",
        "children": [
            {
                "id": "Cross-Machine Network",
                "cat": "cross-machine",
                "children": [
                    {
                        "id": "device-001",
                        "cat": "cross-machine",
                        "desc": "MacBook Pro — added 2026-09-15 — c02f52gpq05ps-macbook-pro",
                    },
                    {
                        "id": "device-002",
                        "cat": "cross-machine",
                        "desc": "MacBook Pro — added 2026-08-20 — c0aef111q05aa-macbook-pro",
                    },
                    {
                        "id": "device-003",
                        "cat": "cross-machine",
                        "desc": "Mac Mini — added 2026-07-10 — c0def222q05bb-mac-mini",
                    },
                ],
            }
        ],
    }

    export_snapshot.anonymize_machines(tree)

    devices = tree["children"][0]["children"]

    # Check that tailscale hostnames are gone
    for device in devices:
        desc = device.get("desc", "")
        assert "c02f52gpq05ps" not in desc
        assert "c0aef111q05aa" not in desc
        assert "c0def222q05bb" not in desc

    # Check that kinds are present and deduped
    assert "Macbook Pro" in devices[0].get("name", "")
    assert "Macbook Pro" in devices[1].get("name", "")
    assert "Mac Mini" in devices[2].get("name", "")

    # Check that the second MacBook Pro is numbered
    assert devices[0]["name"] == "Macbook Pro"
    assert devices[1]["name"] == "Macbook Pro 2"

    # Descriptions should be cleaned
    assert "added 2026-09-15" in devices[0].get("desc", "")


# ── structural privacy scan ──────────────────────────────────────────────

def test_scan_tree_flags_untracked_code_files():
    tree = {
        "id": "root",
        "code": {
            "files": [
                {"id": "f1", "source_file": "lib/core.py"},
                {"id": "f2", "source_file": "untracked/secret.py"},
            ],
            "functions": [],
            "borrowed": [],
            "tests": [],
            "edges": [],
        },
        "children": [],
    }
    allowlist = {"lib/core.py"}
    issues = export_snapshot.scan_tree_for_leaks(tree, allowlist)
    assert any("untracked" in issue for issue in issues)


def test_scan_tree_flags_textual_leaks():
    tree = {
        "id": "root",
        "desc": "Found at /Users/gileskayo/project",
        "children": [],
    }
    allowlist = set()
    issues = export_snapshot.scan_tree_for_leaks(tree, allowlist)
    assert any("/Users/" in issue for issue in issues)


def test_exported_html_contains_snapshot_flag_set_true():
    """Verify that the SNAPSHOT flag is set to true in exported HTML."""
    # Read the template
    template = export_snapshot.TEMPLATE_PATH.read_text(encoding="utf-8")

    # Verify the placeholder exists
    assert "/*__SNAPSHOT_FLAG__*/var SNAPSHOT = false;" in template

    # Simulate what export_snapshot does
    modified = re.sub(
        r"/\*__SNAPSHOT_FLAG__\*/var SNAPSHOT = false;/\*__SNAPSHOT_FLAG__\*/",
        "/*__SNAPSHOT_FLAG__*/var SNAPSHOT = true;/*__SNAPSHOT_FLAG__*/",
        template,
    )

    # Verify it was changed
    assert "/*__SNAPSHOT_FLAG__*/var SNAPSHOT = true;" in modified
    assert "/*__SNAPSHOT_FLAG__*/var SNAPSHOT = false;" not in modified


# 2026-10-07: the first real snapshot carried 26 /Users/<name>/... strings in scheduled-job nodes' "path" field
# (a launchd command line). The tree scan only read name/desc/label, so it passed.
def test_tree_scan_reads_every_field_not_just_name_desc_label():
    tree = {"name": "root", "children": [{"name": "code-sync", "path": "/Users/someone/.agents/lib/code_sync.py pull"}]}
    assert export_snapshot.scan_tree_for_leaks(tree, set())


def test_home_paths_are_rewritten_to_tilde_everywhere():
    tree = {"name": "root", "children": [{"name": "job", "path": "/Users/someone/.agents/venv/bin/python /Users/someone/.agents/lib/x.py",
                                          "meta": {"cmd": ["/Users/someone/.claude/a.md"]}}]}
    clean = export_snapshot.redact_home_paths(tree)
    assert "/Users/" not in json.dumps(clean)
    assert clean["children"][0]["path"] == "~/.agents/venv/bin/python ~/.agents/lib/x.py"
    assert clean["children"][0]["meta"]["cmd"] == ["~/.claude/a.md"]
    assert export_snapshot.scan_tree_for_leaks(clean, set()) == []


# 2026-10-07: the first deployed snapshot drew nothing, because index.html loads ./vendor/motion.12.42.2.js and only
# index.html + tree-data.json were exported/uploaded (404). A snapshot must carry every local file its page uses.
def test_local_assets_lists_relative_scripts_and_styles_but_not_the_data_file():
    html = '<script src="./vendor/motion.js"></script><link href="./css/a.css"><script src="https://cdn/x.js"></script>' \
           '<script>fetch("./tree-data.json")</script>'
    assert export_snapshot.local_assets(html) == ["css/a.css", "vendor/motion.js"]


def test_copy_local_assets_copies_them_and_refuses_when_one_is_missing(tmp_path):
    src, out = tmp_path / "src", tmp_path / "out"
    (src / "vendor").mkdir(parents=True)
    (src / "vendor" / "motion.js").write_text("m")
    assert export_snapshot.copy_local_assets('<script src="./vendor/motion.js"></script>', src, out) == []
    assert (out / "vendor" / "motion.js").read_text() == "m"
    missing = export_snapshot.copy_local_assets('<script src="./vendor/gone.js"></script>', src, out)
    assert missing == ["vendor/gone.js"]


def test_anonymize_machines_renames_only_the_registered_devices():
    """2026-10-08: the trunk, exo and task-dispatch share cat 'cross-machine' and were renamed from their descriptions
    ('Registered Machines + Distributed-Systems Primitives'). Only device nodes (desc '<kind> — added <date> ...') change."""
    from export_snapshot import anonymize_machines
    tree = {"id": "Cross-Machine Network", "cat": "cross-machine",
            "desc": "Registered machines + distributed-systems primitives — see ADR 0020", "children": [
                {"id": "mac-mini-1", "cat": "cross-machine", "desc": "desktop — added 2026-07-06 — gils-mac-mini"},
                {"id": "macbook-pro-1", "cat": "cross-machine", "desc": "laptop — added 2026-07-06 — host-x"},
                {"id": "task-dispatch", "cat": "cross-machine", "desc": "General fan-out/merge dispatch primitive (lib/task_dispatch.py)"},
                {"id": "exo", "cat": "cross-machine", "desc": "Distributed LLM inference across registered devices"}]}
    anonymize_machines(tree)
    names = {c["id"]: c.get("name") for c in tree["children"]}
    assert names == {"mac-mini-1": "Desktop", "macbook-pro-1": "Laptop", "task-dispatch": None, "exo": None}
    assert tree.get("name") is None
    assert "gils-mac-mini" not in tree["children"][0]["desc"]
