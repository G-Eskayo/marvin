"""Tests for lib.model_registry: schema validation, capability resolution, usage logging, consistency checking."""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib import model_registry


@pytest.fixture
def tmp_config(tmp_path):
    """Temporary models.json for testing."""
    config = {
        "models": [
            {"name": "qwen2.5:14b", "runtime": "ollama", "used_by": ["task-a"], "heavy": True, "reason": "test"},
            {"name": "qwen2.5:7b", "runtime": "ollama", "used_by": ["task-b"], "heavy": False},
            {"name": "test-unused", "runtime": "ollama", "used_by": [], "heavy": False},
        ],
        "capabilities": {
            "local-classify": "qwen2.5:14b",
            "local-judge": "qwen2.5:7b",
        }
    }
    config_file = tmp_path / "models.json"
    config_file.write_text(json.dumps(config, indent=2))
    return config_file


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Temporary HOME for testing logs."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


class TestLoad:
    def test_load_valid(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        assert cfg["models"][0]["name"] == "qwen2.5:14b"
        assert cfg["capabilities"]["local-classify"] == "qwen2.5:14b"

    def test_load_missing_file(self, tmp_path):
        cfg = model_registry.load(path=tmp_path / "nonexistent.json")
        assert isinstance(cfg, dict)
        assert "models" in cfg
        assert "capabilities" in cfg

    def test_load_invalid_json(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid")
        cfg = model_registry.load(path=bad_file)
        assert isinstance(cfg, dict)
        assert "models" in cfg


class TestResolveCapability:
    def test_resolve_known(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        model = model_registry.resolve_capability("local-classify", config=cfg)
        assert model == "qwen2.5:14b"

    def test_resolve_unknown(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        with pytest.raises(KeyError):
            model_registry.resolve_capability("unknown-capability", config=cfg)


class TestRecordUsage:
    def test_record_usage_appends_to_jsonl(self, tmp_home):
        log_file = tmp_home / ".claude" / "logs" / "model-usage.jsonl"
        model_registry.record_usage("qwen2.5:14b", "test-caller", machine="mac-mini", log_dir=tmp_home / ".claude" / "logs")
        assert log_file.exists()
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        record = json.loads(lines[0])
        assert record["model"] == "qwen2.5:14b"
        assert record["caller"] == "test-caller"

    def test_record_usage_multiple_calls(self, tmp_home):
        log_file = tmp_home / ".claude" / "logs" / "model-usage.jsonl"
        log_dir = tmp_home / ".claude" / "logs"
        model_registry.record_usage("qwen2.5:14b", "caller1", machine="mac-mini", log_dir=log_dir)
        model_registry.record_usage("qwen2.5:7b", "caller2", machine="mac-mini", log_dir=log_dir)
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_record_usage_updates_last_used(self, tmp_home):
        log_dir = tmp_home / ".claude" / "logs"
        model_registry.record_usage("qwen2.5:14b", "test-caller", machine="mac-mini", log_dir=log_dir)
        last_used_file = log_dir / "model-last-used.json"
        assert last_used_file.exists()
        data = json.loads(last_used_file.read_text())
        assert "qwen2.5:14b" in data
        ts = datetime.fromisoformat(data["qwen2.5:14b"])
        assert isinstance(ts, datetime)


class TestCheckConsistency:
    def test_no_problems(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        warnings = model_registry.check_consistency(cfg, code_literals=set())
        # The "test-unused" entry has no reason, so it triggers a soft warning
        assert any("test-unused" in w for w in warnings)

    def test_hard_fail_unlisted_literal(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        with pytest.raises(RuntimeError) as exc:
            model_registry.check_consistency(cfg, code_literals={"qwen2.5:27b"})
        assert "not in models.json" in str(exc.value)

    def test_hard_fail_unresolvable_capability(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        # Simulate a code path that references an unknown capability
        with pytest.raises(RuntimeError) as exc:
            model_registry.check_consistency(cfg, code_capabilities={"unknown-cap"})
        assert "unknown-cap" in str(exc.value)

    def test_soft_warning_unused_no_reason(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        warnings = model_registry.check_consistency(cfg, code_literals=set())
        # "test-unused" has no reason and is unused
        assert any("test-unused" in w and "unused" in w.lower() for w in warnings)


class TestIsHeavy:
    def test_heavy_model(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        assert model_registry.is_heavy("qwen2.5:14b", config=cfg)

    def test_light_model(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        assert not model_registry.is_heavy("qwen2.5:7b", config=cfg)

    def test_unknown_model(self, tmp_config):
        cfg = model_registry.load(path=tmp_config)
        assert not model_registry.is_heavy("unknown-model", config=cfg)
