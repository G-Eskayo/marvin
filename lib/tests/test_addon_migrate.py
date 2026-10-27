"""Tests for addon_migrate.py (marvin#647). Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_addon_migrate.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import addon_migrate as am  # noqa: E402


class TestApplyLegacyGrant:
    """Items 13–15 from marvin#647's test list."""

    def test_grants_all_known_addons_when_empty(self):
        """Item 13: apply_legacy_grant({"features": {}}) returns all three known add-ons True."""
        config = {"features": {}}
        result = am.apply_legacy_grant(config)

        assert result["features"]["portfolio"] is True
        assert result["features"]["resume_tailor"] is True
        assert result["features"]["seal_ingest"] is True

    def test_respects_explicit_prior_choice(self):
        """Item 14: apply_legacy_grant leaves explicit False values alone."""
        config = {"features": {"portfolio": False}}
        result = am.apply_legacy_grant(config)

        assert result["features"]["portfolio"] is False  # unchanged
        assert result["features"]["resume_tailor"] is True  # granted
        assert result["features"]["seal_ingest"] is True  # granted

    def test_grants_only_missing_keys(self):
        """Variation: partially filled features dict is completed."""
        config = {"features": {"portfolio": True}}
        result = am.apply_legacy_grant(config)

        assert result["features"]["portfolio"] is True  # unchanged
        assert result["features"]["resume_tailor"] is True  # added
        assert result["features"]["seal_ingest"] is True  # added

    def test_idempotent(self):
        """Item 15: running twice is a no-op the second time."""
        config = {"features": {}}
        result1 = am.apply_legacy_grant(config)
        result2 = am.apply_legacy_grant(result1)

        assert json.dumps(result1, sort_keys=True) == json.dumps(result2, sort_keys=True)

    def test_preserves_unrelated_keys(self):
        """Item 15: unrelated top-level keys are untouched."""
        config = {
            "owner": "G-Eskayo",
            "tickets_repo": "G-Eskayo/marvin",
            "features": {}
        }
        result = am.apply_legacy_grant(config)

        assert result["owner"] == "G-Eskayo"
        assert result["tickets_repo"] == "G-Eskayo/marvin"
        assert result["features"]["portfolio"] is True

    def test_handles_missing_features_key(self):
        """Missing 'features' key is created."""
        config = {"owner": "G-Eskayo"}
        result = am.apply_legacy_grant(config)

        assert result["features"]["portfolio"] is True
        assert result["features"]["resume_tailor"] is True
        assert result["features"]["seal_ingest"] is True

    def test_handles_wrong_shaped_features(self):
        """Item 15: non-dict features is replaced."""
        config = {"features": "yes"}
        result = am.apply_legacy_grant(config)

        assert isinstance(result["features"], dict)
        assert result["features"]["portfolio"] is True

    def test_handles_empty_config(self):
        """Empty/blank config is filled in."""
        config = {}
        result = am.apply_legacy_grant(config)

        assert result["features"]["portfolio"] is True
        assert result["features"]["resume_tailor"] is True
        assert result["features"]["seal_ingest"] is True


class TestCli:
    """Item 16: ratchet test — no hard-coded home paths."""

    def test_cli_with_custom_instance_dir(self, tmp_path):
        """CLI accepts --instance-dir, never hard-codes /Users/gileskayo."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"
        instance_json.write_text(json.dumps({"features": {}}))

        result = am.main(["--instance-dir", str(instance_dir)])

        assert result == 0
        data = json.loads(instance_json.read_text())
        assert data["features"]["portfolio"] is True

    def test_cli_instance_missing(self, tmp_path):
        """CLI exits 1 and reports when instance.json doesn't exist."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()

        result = am.main(["--instance-dir", str(instance_dir)])

        assert result == 1

    def test_cli_invalid_json(self, tmp_path):
        """CLI exits 1 and reports when instance.json is corrupt."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"
        instance_json.write_text("not json {")

        result = am.main(["--instance-dir", str(instance_dir)])

        assert result == 1

    def test_cli_idempotent(self, tmp_path):
        """Running CLI twice is a no-op the second time."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"
        instance_json.write_text(json.dumps({"features": {}}))

        result1 = am.main(["--instance-dir", str(instance_dir)])
        mtime1 = instance_json.stat().st_mtime
        content1 = instance_json.read_text()

        # Run again
        result2 = am.main(["--instance-dir", str(instance_dir)])
        mtime2 = instance_json.stat().st_mtime
        content2 = instance_json.read_text()

        assert result1 == 0
        assert result2 == 0
        assert content1 == content2
        assert mtime1 == mtime2  # file unchanged second time

    def test_cli_writes_only_on_change(self, tmp_path):
        """File is rewritten only if content changed."""
        instance_dir = tmp_path / "instance"
        instance_dir.mkdir()
        instance_json = instance_dir / "instance.json"

        # Start with already-migrated config
        initial = {"features": {"portfolio": True, "resume_tailor": True, "seal_ingest": True}}
        instance_json.write_text(json.dumps(initial, indent=2, sort_keys=True) + "\n")
        mtime_before = instance_json.stat().st_mtime

        am.main(["--instance-dir", str(instance_dir)])

        mtime_after = instance_json.stat().st_mtime
        assert mtime_before == mtime_after  # unchanged
