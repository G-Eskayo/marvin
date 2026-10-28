"""Tests for addon_migrate.py (items 17–19 of #647).

Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_addon_migrate.py -v
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lib"))

import addon_migrate  # noqa: E402


class TestApplyLegacyGrant:
    def test_grants_all_addons_when_none_configured(self):
        """Item 17: apply_legacy_grant({"features": {}}) returns all three known add-ons True."""
        result = addon_migrate.apply_legacy_grant({"features": {}})
        assert result["features"] == {
            "portfolio": True,
            "resume_tailor": True,
            "seal_ingest": True,
        }

    def test_respects_explicit_prior_choice(self):
        """Item 18: apply_legacy_grant(...) leaves an explicit False, still grants the others."""
        result = addon_migrate.apply_legacy_grant({
            "features": {"portfolio": False}
        })
        assert result["features"]["portfolio"] is False
        assert result["features"]["resume_tailor"] is True
        assert result["features"]["seal_ingest"] is True

    def test_idempotent_and_handles_malformed_input(self):
        """Item 19: running twice is a no-op; non-dict features and missing keys handled gracefully."""
        # Test idempotency
        config = {"features": {}}
        first = addon_migrate.apply_legacy_grant(config)
        second = addon_migrate.apply_legacy_grant(first)
        assert first == second

        # Test malformed features (non-dict)
        malformed1 = addon_migrate.apply_legacy_grant({"features": "yes"})
        assert isinstance(malformed1["features"], dict)
        assert all(malformed1["features"][k] is True for k in addon_migrate.KNOWN_ADDONS)

        # Test missing features key
        no_features = addon_migrate.apply_legacy_grant({})
        assert isinstance(no_features["features"], dict)
        assert all(no_features["features"][k] is True for k in addon_migrate.KNOWN_ADDONS)

        # Test unrelated top-level keys preserved
        with_other = addon_migrate.apply_legacy_grant({
            "owner": "pat-example",
            "features": {}
        })
        assert with_other["owner"] == "pat-example"
        assert all(with_other["features"][k] is True for k in addon_migrate.KNOWN_ADDONS)


class TestMigrationCLI:
    def test_migration_writes_only_on_change(self, tmp_path, monkeypatch):
        """Migration writes back only when changes are made."""
        inst_dir = tmp_path / "inst"
        inst_dir.mkdir()
        config_path = inst_dir / "instance.json"

        # First run: empty features
        config_path.write_text(json.dumps({"features": {}}))
        original_mtime = config_path.stat().st_mtime

        result = addon_migrate.main(["--instance-dir", str(inst_dir)])
        assert result == 0
        assert config_path.stat().st_mtime > original_mtime  # File was written

        # Second run: features already configured
        import time
        time.sleep(0.01)  # ensure different mtime if file were rewritten
        original_mtime = config_path.stat().st_mtime
        result = addon_migrate.main(["--instance-dir", str(inst_dir)])
        assert result == 0
        assert config_path.stat().st_mtime == original_mtime  # File was not rewritten

    def test_migration_creates_missing_instance_json(self, tmp_path):
        """Migration creates instance.json if missing."""
        inst_dir = tmp_path / "inst"
        inst_dir.mkdir()
        config_path = inst_dir / "instance.json"

        assert not config_path.exists()
        result = addon_migrate.main(["--instance-dir", str(inst_dir)])
        assert result == 0
        assert config_path.exists()

        data = json.loads(config_path.read_text())
        assert all(data["features"].get(k) is True for k in addon_migrate.KNOWN_ADDONS)

    def test_migration_preserves_unrelated_keys(self, tmp_path):
        """Migration preserves other instance.json keys like owner and tickets_repo."""
        inst_dir = tmp_path / "inst"
        inst_dir.mkdir()
        config_path = inst_dir / "instance.json"

        original = {
            "owner": "pat-example",
            "tickets_repo": "org/tickets",
            "features": {}
        }
        config_path.write_text(json.dumps(original))

        addon_migrate.main(["--instance-dir", str(inst_dir)])

        data = json.loads(config_path.read_text())
        assert data["owner"] == "pat-example"
        assert data["tickets_repo"] == "org/tickets"
        assert all(data["features"].get(k) is True for k in addon_migrate.KNOWN_ADDONS)
