"""Test model_registry extensions: heavy models, machine labels, capabilities."""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import model_registry


def test_model_registry_register_with_heavy_and_machine(tmp_path):
    """Models can be registered with heavy and machine flags."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)

    registry.register(
        "qwen2.5:14b",
        "~/.ollama/models",
        9.0,
        "paper-dive",
        "logic auditing",
        heavy=True,
        machine="macbook-pro"
    )

    data = json.loads(registry_path.read_text())
    assert data["qwen2.5:14b"]["heavy"] is True
    assert data["qwen2.5:14b"]["machine"] == "macbook-pro"


def test_model_registry_register_defaults_heavy_to_false(tmp_path):
    """Models default to heavy=False if not specified."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)

    registry.register("small-model", "path", 0.5, "test", "reason")

    data = json.loads(registry_path.read_text())
    assert data["small-model"]["heavy"] is False
    assert data["small-model"]["machine"] is None


def test_is_heavy_returns_true_for_marked_heavy(tmp_path):
    """is_heavy() returns True for models marked heavy."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)
    registry.register("heavy-model", "path", 10.0, "test", "reason", heavy=True)

    with patch.object(model_registry.ModelRegistry, 'path', registry_path):
        assert model_registry.is_heavy("heavy-model") is True


def test_is_heavy_returns_false_for_light_models(tmp_path):
    """is_heavy() returns False for models not marked heavy."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)
    registry.register("light-model", "path", 1.0, "test", "reason", heavy=False)

    assert model_registry.is_heavy("light-model") is False


def test_is_heavy_returns_false_for_unknown_models():
    """is_heavy() returns False for models not in registry."""
    assert model_registry.is_heavy("unknown-model") is False


def test_resolve_capability_returns_model_name(tmp_path):
    """resolve_capability() maps a capability name to a model."""
    cap_path = tmp_path / "caps.json"
    cap_path.write_text(json.dumps({"local-test": "qwen2.5:7b"}))

    with patch.object(model_registry, 'CAPABILITIES_PATH', cap_path):
        model = model_registry.resolve_capability("local-test")
        assert model == "qwen2.5:7b"


def test_resolve_capability_raises_on_unknown():
    """resolve_capability() raises KeyError for unknown capability."""
    with patch.object(model_registry, 'CAPABILITIES_PATH', Path("/nonexistent")):
        with pytest.raises(KeyError, match="unknown capability"):
            model_registry.resolve_capability("unknown-capability")


def test_ensure_capabilities_creates_default(tmp_path):
    """_ensure_capabilities_exist() creates default file if missing."""
    cap_path = tmp_path / "caps.json"

    with patch.object(model_registry, 'CAPABILITIES_PATH', cap_path):
        model_registry._ensure_capabilities_exist()

        assert cap_path.exists()
        data = json.loads(cap_path.read_text())
        assert "local-classify-medium" in data
        assert data["local-classify-medium"] == "qwen2.5:14b"


def test_check_consistency_passes_with_valid_registry(tmp_path):
    """check_consistency() passes when all code refs are in registry."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)

    # Register the models referenced in patterns
    registry.register("qwen2.5:14b", "path", 9.0, "test", "reason", heavy=True)
    registry.register("qwen2.5:7b", "path", 4.7, "test", "reason")
    registry.register("qwen2.5:3b", "path", 1.9, "test", "reason")
    registry.register("nomic-embed-text", "path", 0.3, "test", "reason")

    # Create a fake capability file
    cap_path = tmp_path / "caps.json"
    cap_path.write_text(json.dumps({
        "local-classify-medium": "qwen2.5:14b",
        "local-extract-small": "qwen2.5:3b",
    }))

    with patch.object(model_registry, 'CAPABILITIES_PATH', cap_path):
        with patch.object(model_registry, 'REGISTRY_PATH', registry_path):
            # Should not raise
            hard, soft = model_registry.check_consistency()
            assert isinstance(hard, list)
            assert isinstance(soft, list)


def test_check_consistency_warns_on_unused_models(tmp_path):
    """check_consistency() warns (soft fail) for models with no used_by/reason."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)

    registry.register("unused-model", "path", 1.0, "", "", heavy=False)

    with patch.object(model_registry, 'REGISTRY_PATH', registry_path):
        hard, soft = model_registry.check_consistency()
        assert any("unused-model" in w for w in soft)


def test_model_registry_schema_backcompat(tmp_path):
    """Existing portfolio_flux usage still works with new schema."""
    registry_path = tmp_path / "models.json"
    registry = model_registry.ModelRegistry(registry_path)

    registry.register("FLUX.1-schnell-4bit", "~/.cache/huggingface", 6.5,
                      "portfolio-flux", "image generation", heavy=True)

    # Old code paths that use get/all should still work
    meta = registry.get("FLUX.1-schnell-4bit")
    assert meta is not None
    assert meta["size_gb"] == 6.5
    assert meta["used_by"] == "portfolio-flux"

    all_models = registry.all()
    assert "FLUX.1-schnell-4bit" in all_models
    assert all_models["FLUX.1-schnell-4bit"]["heavy"] is True
