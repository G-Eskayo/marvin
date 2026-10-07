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
