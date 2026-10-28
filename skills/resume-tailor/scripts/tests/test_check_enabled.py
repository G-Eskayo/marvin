"""Tests for check_enabled.py (item 7 of #647).

Run via: ~/.agents/venv/bin/python -m pytest skills/resume-tailor/scripts/tests/test_check_enabled.py -v
"""
from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / "skills" / "resume-tailor" / "scripts" / "check_enabled.py"
LIB = ROOT / "lib"


@pytest.fixture
def at(tmp_path, monkeypatch):
    """Point the script at a temp instance dir."""
    inst_dir = tmp_path / "inst"
    inst_dir.mkdir()
    monkeypatch.setenv("MARVIN_INSTANCE_DIR", str(inst_dir))
    return inst_dir


def run_check(inst_dir: Path) -> int:
    """Run check_enabled.py and return its exit code."""
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        env={**dict(subprocess.os.environ), "MARVIN_INSTANCE_DIR": str(inst_dir)},
        capture_output=True,
        text=True
    )
    return result.returncode


class TestCheckEnabled:
    def test_exits_0_when_feature_enabled(self, at):
        """Exits 0 when resume_tailor is explicitly true."""
        (at / "instance.json").write_text(json.dumps({"features": {"resume_tailor": True}}))
        assert run_check(at) == 0

    def test_exits_1_when_feature_disabled(self, at):
        """Exits 1 when resume_tailor is explicitly false."""
        (at / "instance.json").write_text(json.dumps({"features": {"resume_tailor": False}}))
        assert run_check(at) == 1

    def test_exits_1_when_missing_features_key(self, at):
        """Exits 1 when features key is missing."""
        (at / "instance.json").write_text(json.dumps({}))
        assert run_check(at) == 1

    def test_exits_1_when_feature_missing_from_features_dict(self, at):
        """Exits 1 when resume_tailor key is not in features dict."""
        (at / "instance.json").write_text(json.dumps({"features": {}}))
        assert run_check(at) == 1

    def test_exits_1_when_corrupt_instance_json(self, at):
        """Exits 1 when instance.json is malformed JSON (treated as off)."""
        (at / "instance.json").write_text("{ not valid json }")
        assert run_check(at) == 1

    def test_exits_1_when_instance_json_missing(self, at):
        """Exits 1 when instance.json does not exist (treated as off)."""
        assert not (at / "instance.json").exists()
        assert run_check(at) == 1

    def test_never_writes_to_resume_dir(self, at):
        """Never creates or modifies any files (read-only check)."""
        resume_dir = at.parent / ".claude" / "resume"
        (at / "instance.json").write_text(json.dumps({"features": {"resume_tailor": False}}))

        assert run_check(at) == 1
        assert not resume_dir.exists()

    def test_malformed_features_value_reads_as_off(self, at):
        """If features is not a dict (e.g., string), feature is off."""
        (at / "instance.json").write_text(json.dumps({"features": "yes"}))
        assert run_check(at) == 1

    def test_feature_value_must_be_true_not_truthy(self, at):
        """Feature must be exactly True, not just truthy (1, "true", etc.)."""
        (at / "instance.json").write_text(json.dumps({"features": {"resume_tailor": 1}}))
        assert run_check(at) == 1

        (at / "instance.json").write_text(json.dumps({"features": {"resume_tailor": "true"}}))
        assert run_check(at) == 1
