"""Tests for check_enabled.py (marvin#647, item 7). Run via:
    ~/.agents/venv/bin/python -m pytest skills/resume-tailor/scripts/tests/test_check_enabled.py -v
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "check_enabled.py"


class TestCheckEnabledScript:
    """Item 7: check_enabled.py exits 0/1 based on instance configuration."""

    def test_exits_zero_when_enabled(self, tmp_path, monkeypatch):
        """Feature on → exit 0."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"
        instance_json.write_text(json.dumps({"features": {"resume_tailor": True}}))

        monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(instance_dir))
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True)
        assert result.returncode == 0

    def test_exits_one_when_disabled(self, tmp_path, monkeypatch):
        """Feature off → exit 1."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"
        instance_json.write_text(json.dumps({"features": {"resume_tailor": False}}))

        monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(instance_dir))
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True)
        assert result.returncode == 1

    def test_exits_one_when_missing(self, tmp_path, monkeypatch):
        """Instance missing → exit 1."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        # No instance.json file

        monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(instance_dir))
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True)
        assert result.returncode == 1

    def test_exits_one_when_corrupt(self, tmp_path, monkeypatch):
        """Corrupt instance.json → exit 1 (feature reads as off)."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"
        instance_json.write_text("{not json")

        monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(instance_dir))
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True)
        assert result.returncode == 1

    def test_exits_zero_when_empty_config_and_all_enabled(self, tmp_path, monkeypatch):
        """Even though we're applying a gate, a feature missing is False, not True.
        This test confirms the expected behavior."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"
        instance_json.write_text(json.dumps({"features": {}}))

        monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(instance_dir))
        result = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True)
        # Feature not present → False → exit 1
        assert result.returncode == 1

    def test_never_writes_anything(self, tmp_path, monkeypatch):
        """Script never touches the filesystem except for reading."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"
        initial = json.dumps({"features": {"resume_tailor": True}})
        instance_json.write_text(initial)
        mtime_before = instance_json.stat().st_mtime

        monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(instance_dir))
        subprocess.run([sys.executable, str(SCRIPT)], capture_output=True)

        assert instance_json.read_text() == initial
        assert instance_json.stat().st_mtime == mtime_before
