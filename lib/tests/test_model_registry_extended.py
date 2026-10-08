"""Tests for ModelRegistry step 1 extensions (schema + methods).

Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_model_registry_extended.py -v
"""
from __future__ import annotations
import sys
import json
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import model_registry as mr  # noqa: E402


@pytest.fixture
def registry_file(tmp_path):
    """Provide a temporary registry file."""
    return tmp_path / "models.json"


@pytest.fixture
def registry(registry_file):
    """Create a registry with the extended schema."""
    # Initialize with extended schema
    initial = {
        "qwen2.5:14b": {
            "capability": "local-classify-large",
            "heavy": True,
            "last_used": None,
            "location": "~/.ollama/models",
            "reason": "logic auditing, competing ideas, argument mapper",
            "runtime": "ollama",
            "machine": "both",
            "size_gb": 9.0,
            "used_by": ["paper-dive"],
        },
        "qwen2.5:7b": {
            "capability": "local-classify-medium",
            "heavy": False,
            "last_used": None,
            "location": "~/.ollama/models",
            "reason": "logic auditing, competing ideas, argument mapper",
            "runtime": "ollama",
            "machine": "both",
            "size_gb": 4.7,
            "used_by": ["paper-dive"],
        },
        "qwen2.5:3b": {
            "capability": "local-classify-small",
            "heavy": False,
            "last_used": None,
            "location": "~/.ollama/models",
            "reason": "logic auditing, competing ideas, argument mapper",
            "runtime": "ollama",
            "machine": "both",
            "size_gb": 1.9,
            "used_by": ["paper-dive"],
        },
        "FLUX.1-schnell-4bit": {
            "capability": "image-gen",
            "heavy": True,
            "last_used": None,
            "location": "~/.cache/huggingface",
            "reason": "high-quality image generation for portfolio projects",
            "runtime": "mflux",
            "machine": "macbook-pro",
            "size_gb": 6.5,
            "used_by": ["portfolio-flux"],
        },
        "MiniLM": {
            "capability": "local-embed",
            "heavy": False,
            "last_used": None,
            "location": "~/.cache/chroma",
            "reason": "vector search (Chroma default)",
            "runtime": "hf",
            "machine": "both",
            "size_gb": 0.17,
            "used_by": ["core"],
        },
        "nomic-embed-text": {
            "capability": "local-embed",
            "heavy": False,
            "last_used": None,
            "location": "~/.ollama/models",
            "reason": "memory search, routing, embeddings",
            "runtime": "ollama",
            "machine": "both",
            "size_gb": 0.27,
            "used_by": ["core"],
        },
        "specter2": {
            "capability": "citation-embed",
            "heavy": False,
            "last_used": None,
            "location": "~/.cache/huggingface/models",
            "reason": "citation graph analysis",
            "runtime": "hf",
            "machine": "both",
            "size_gb": 0.84,
            "used_by": ["paper-dive"],
        },
    }
    registry_file.write_text(json.dumps(initial, indent=2))
    return mr.ModelRegistry(path=registry_file)


@pytest.fixture
def registry_with_capabilities(registry):
    """Add a capabilities map to the registry (loaded separately)."""
    # Capabilities map is stored separately or as a top-level key
    # For now, we test the methods work with the registry
    return registry


def test_resolve_capability_returns_first_model(registry):
    """resolve_capability should return the first/best model for a capability."""
    # local-classify-large should return qwen2.5:14b (only one)
    result = registry.resolve_capability("local-classify-large")
    assert result == "qwen2.5:14b"


def test_resolve_capability_multiple_models(registry):
    """resolve_capability should prefer larger models when multiple available."""
    # Add qwen2.5:14b to local-classify-medium (same capability as 7b)
    data = registry._read()
    data["qwen2.5:14b"]["capability"] = "local-classify-medium"
    registry._write(data)

    result = registry.resolve_capability("local-classify-medium")
    # Should return qwen2.5:14b (9.0 GB) over qwen2.5:7b (4.7 GB)
    assert result == "qwen2.5:14b"


def test_resolve_capability_not_found(registry):
    """resolve_capability should return None for unknown capability."""
    result = registry.resolve_capability("nonexistent-capability")
    assert result is None


def test_is_heavy_for_heavy_model(registry):
    """is_heavy should return True for heavy models."""
    assert registry.is_heavy("qwen2.5:14b") is True
    assert registry.is_heavy("FLUX.1-schnell-4bit") is True


def test_is_heavy_for_light_model(registry):
    """is_heavy should return False for non-heavy models."""
    assert registry.is_heavy("qwen2.5:7b") is False
    assert registry.is_heavy("nomic-embed-text") is False


def test_is_heavy_unknown_model(registry):
    """is_heavy should return False for unknown models."""
    assert registry.is_heavy("unknown-model") is False


def test_by_machine_returns_matching_models(registry):
    """by_machine should return models for a given machine."""
    # Both macbook-pro and both
    result = registry.by_machine("macbook-pro")
    # Should include FLUX.1-schnell-4bit (macbook-pro) and all "both"
    assert "FLUX.1-schnell-4bit" in result
    assert "qwen2.5:14b" in result
    assert "nomic-embed-text" in result


def test_by_machine_both_filter(registry):
    """by_machine should include models marked as 'both'."""
    mac_mini_result = registry.by_machine("mac-mini")
    # Should only include "both" machines, not "macbook-pro"
    assert "FLUX.1-schnell-4bit" not in mac_mini_result
    assert "qwen2.5:14b" in mac_mini_result


def test_used_by_is_list(registry):
    """used_by field should be a list."""
    qwen_7b = registry.get("qwen2.5:7b")
    assert isinstance(qwen_7b["used_by"], list)
    assert "paper-dive" in qwen_7b["used_by"]


def test_runtime_field_present(registry):
    """All models should have a runtime field."""
    for name, entry in registry.all().items():
        assert "runtime" in entry, f"{name} missing runtime"
        assert entry["runtime"] in ["ollama", "hf", "mlx", "mflux"]


def test_machine_field_present(registry):
    """All models should have a machine field."""
    for name, entry in registry.all().items():
        assert "machine" in entry, f"{name} missing machine"
        assert entry["machine"] in ["mac-mini", "macbook-pro", "both"]


def test_register_creates_with_new_fields(registry_file):
    """register method should create entries with all new fields."""
    reg = mr.ModelRegistry(path=registry_file)
    reg.register(
        name="test-model",
        location="~/.cache/test",
        size_gb=2.5,
        used_by=["test-app"],
        reason="testing",
        runtime="ollama",
        machine="both",
        capability="test-capability",
        heavy=False,
    )

    entry = reg.get("test-model")
    assert entry["runtime"] == "ollama"
    assert entry["machine"] == "both"
    assert entry["used_by"] == ["test-app"]
    assert entry["capability"] == "test-capability"
    assert entry["heavy"] is False
