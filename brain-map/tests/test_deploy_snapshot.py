#!/usr/bin/env python3
"""
test_deploy_snapshot.py — Unit tests for deploy_snapshot.py orchestration.

Tests the key functions without requiring Docker, the portfolio dev site, or
a full git repo. Run: python -m pytest brain-map/tests/test_deploy_snapshot.py -v
"""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import deploy_snapshot as ds


def test_scan_for_private_content_finds_home_paths():
    """Ensure home paths are detected as privacy leaks."""
    html = '<div>Data stored in /Users/gileskayo/secret</div>'
    leaks = ds.scan_for_private_content(html)
    assert any("Users" in leak for leak in leaks), f"Expected home path leak, got {leaks}"


def test_scan_for_private_content_finds_tokens():
    """Ensure token patterns are detected."""
    html = '<div>API key: sk-ant-abc123xyz</div>'
    leaks = ds.scan_for_private_content(html)
    assert any("Anthropic" in leak for leak in leaks), f"Expected token leak, got {leaks}"


def test_scan_for_private_content_finds_emails():
    """Ensure email addresses are detected."""
    html = '<div>Contact: user@example.com</div>'
    leaks = ds.scan_for_private_content(html)
    assert any("email" in leak.lower() for leak in leaks), f"Expected email leak, got {leaks}"


def test_scan_for_private_content_allows_public_content():
    """Ensure public content passes without leaks."""
    html = '<div>MARVIN is an autonomous agent system.</div>'
    leaks = ds.scan_for_private_content(html)
    assert not leaks, f"Public content flagged as leak: {leaks}"


def test_validate_snapshot_files_requires_html():
    """Snapshot validation should fail if index.html is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)

        # Create only tree-data.json
        (snapshot_dir / "tree-data.json").write_text('{"tree": {}, "synapses": []}')

        # Mock the SNAPSHOT_DIR
        with mock.patch.object(ds, "SNAPSHOT_DIR", snapshot_dir):
            ok, detail = ds.validate_snapshot_files()
            assert not ok, "Should fail if index.html is missing"
            assert "index.html" in detail


def test_validate_snapshot_files_requires_json():
    """Snapshot validation should fail if tree-data.json is missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)

        # Create only index.html
        (snapshot_dir / "index.html").write_text('<html>SNAPSHOT = true</html>')

        # Mock the SNAPSHOT_DIR
        with mock.patch.object(ds, "SNAPSHOT_DIR", snapshot_dir):
            ok, detail = ds.validate_snapshot_files()
            assert not ok, "Should fail if tree-data.json is missing"
            assert "tree-data.json" in detail


def test_validate_snapshot_files_checks_snapshot_flag():
    """Snapshot validation should check SNAPSHOT = true."""
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)

        # Create HTML without SNAPSHOT flag
        (snapshot_dir / "index.html").write_text('<html>SNAPSHOT = false</html>')
        (snapshot_dir / "tree-data.json").write_text('{"tree": {}, "synapses": []}')

        # Mock the SNAPSHOT_DIR
        with mock.patch.object(ds, "SNAPSHOT_DIR", snapshot_dir):
            ok, detail = ds.validate_snapshot_files()
            assert not ok, "Should fail if SNAPSHOT flag is not true"
            assert "SNAPSHOT" in detail


def test_validate_snapshot_files_accepts_valid_files():
    """Snapshot validation should pass for well-formed files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_dir = Path(tmpdir)

        # Create valid files
        (snapshot_dir / "index.html").write_text('<html>SNAPSHOT = true<script></script></html>')
        (snapshot_dir / "tree-data.json").write_text('{"tree": {"id": "root"}, "synapses": []}')

        # Mock the SNAPSHOT_DIR
        with mock.patch.object(ds, "SNAPSHOT_DIR", snapshot_dir):
            ok, detail = ds.validate_snapshot_files()
            assert ok, f"Valid files should pass: {detail}"


def test_log_step_creates_log_directory():
    """Log function should create the log directory if missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = Path(tmpdir) / "nested" / "dir" / "test.log"

        # Mock the SNAPSHOT_LOG
        with mock.patch.object(ds, "SNAPSHOT_LOG", log_file):
            ds.log_step("test-step", True, "test detail")
            assert log_file.exists(), "Log file should be created"
            content = log_file.read_text()
            assert "test-step" in content, "Log should contain step name"
            assert "test detail" in content, "Log should contain detail"


def test_health_check_mark_success():
    """Health check should mark deployment as successful."""
    with tempfile.TemporaryDirectory() as tmpdir:
        health_dir = Path(tmpdir)

        # Mock HOME and create health check
        with mock.patch.object(ds, "HOME", health_dir):
            ds.health_check_mark_success()

            health_file = health_dir / ".claude" / "health" / "snapshot-deploy.json"
            assert health_file.exists(), "Health file should be created"

            data = json.loads(health_file.read_text())
            assert data["status"] == "ok", "Health status should be 'ok'"
            assert "timestamp" in data, "Health should contain timestamp"


def test_health_check_mark_failure():
    """Health check should mark deployment as failed."""
    with tempfile.TemporaryDirectory() as tmpdir:
        health_dir = Path(tmpdir)

        # Mock HOME and create health check
        with mock.patch.object(ds, "HOME", health_dir):
            ds.health_check_mark_failure("Test failure reason")

            health_file = health_dir / ".claude" / "health" / "snapshot-deploy.json"
            assert health_file.exists(), "Health file should be created"

            data = json.loads(health_file.read_text())
            assert data["status"] == "error", "Health status should be 'error'"
            assert "Test failure reason" in data["message"], "Health should contain failure reason"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])


# ── ADR 0057: after a passing dev deploy, the map publishes itself to production when MARVIN_SNAPSHOT_PUBLISH=1 ──

def _passing_steps(monkeypatch):
    monkeypatch.setattr(ds, "run_export_snapshot", lambda c: (True, "ok"))
    monkeypatch.setattr(ds, "validate_snapshot_files", lambda: (True, "ok"))
    monkeypatch.setattr(ds, "validate_snapshot_content", lambda: (True, "ok"))
    monkeypatch.setattr(ds, "upload_to_portfolio", lambda *a: (True, "ok"))
    monkeypatch.setattr(ds, "log_step", lambda *a: None)
    marks = []
    monkeypatch.setattr(ds, "health_check_mark_success", lambda: marks.append("ok"))
    monkeypatch.setattr(ds, "health_check_mark_failure", lambda why: marks.append("fail: " + why))
    return marks


def test_publishes_to_production_only_when_switched_on(monkeypatch):
    marks = _passing_steps(monkeypatch)
    calls = []
    monkeypatch.setattr(ds, "publish_to_production", lambda: calls.append(1) or (True, "published abc"))
    monkeypatch.setattr(ds, "PUBLISH_ENABLED", False)
    assert ds.deploy_snapshot(force=True) and calls == []
    monkeypatch.setattr(ds, "PUBLISH_ENABLED", True)
    assert ds.deploy_snapshot(force=True) and calls == [1]
    assert ds.deploy_snapshot(force=True, dry_run=True) and calls == [1]  # a dry run never publishes
    assert marks[-1] == "ok"


def test_a_refused_or_failed_publish_turns_health_red(monkeypatch):
    marks = _passing_steps(monkeypatch)
    monkeypatch.setattr(ds, "PUBLISH_ENABLED", True)
    monkeypatch.setattr(ds, "publish_to_production", lambda: (False, "refused: would change deploy/longform/x"))
    assert ds.deploy_snapshot(force=True) is False
    assert marks[-1].startswith("fail: production publish")


def test_the_publish_never_runs_when_a_check_failed(monkeypatch):
    _passing_steps(monkeypatch)
    monkeypatch.setattr(ds, "validate_snapshot_content", lambda: (False, "leak"))
    monkeypatch.setattr(ds, "PUBLISH_ENABLED", True)
    called = []
    monkeypatch.setattr(ds, "publish_to_production", lambda: called.append(1) or (True, ""))
    assert ds.deploy_snapshot(force=True) is False and called == []


def test_upload_copies_every_snapshot_file_and_folder(tmp_path, monkeypatch):
    """facts.json (2026-10-08) never reached the dev site: only index.html and tree-data.json were copied by name."""
    for name in ("index.html", "tree-data.json", "facts.json"):
        (tmp_path / name).write_text("x")
    (tmp_path / "vendor").mkdir()
    copied = []

    class R:
        returncode = 0

    def run(cmd, **kw):
        if cmd[1] == "cp":
            copied.append(Path(cmd[2]).name)
        return R()
    monkeypatch.setattr(ds.subprocess, "run", run)
    ok, _ = ds.upload_to_portfolio(tmp_path / "index.html", tmp_path / "tree-data.json")
    assert ok and sorted(copied) == ["facts.json", "index.html", "tree-data.json", "vendor"]
