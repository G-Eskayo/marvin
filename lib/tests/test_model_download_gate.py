"""Tests for model_download_gate.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_model_download_gate.py -v
"""
from __future__ import annotations
import sys
import json
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import model_download_gate as mdg  # noqa: E402


@pytest.fixture
def registry_file(tmp_path):
    """Create a test registry file."""
    registry = tmp_path / "models.json"
    data = {
        "qwen2.5-7b": {
            "size_gb": 4.7,
            "location": "~/.ollama/models",
            "used_by": "paper-dive",
            "reason": "logic auditing",
            "last_used": None
        },
        "FLUX.1-schnell-4bit": {
            "size_gb": 6.5,
            "location": "~/.cache/huggingface",
            "used_by": "portfolio-flux",
            "reason": "high-quality image generation",
            "last_used": None
        }
    }
    registry.write_text(json.dumps(data, indent=2))
    return registry


def test_registered_model_allowed(registry_file):
    """A registered model with a reason should be allowed to download."""
    gate = mdg.ModelDownloadGate(registry_path=registry_file)

    # Registered models should be allowed
    assert gate.can_download("qwen2.5-7b") is True
    assert gate.can_download("FLUX.1-schnell-4bit") is True


def test_unregistered_model_blocked(registry_file):
    """An unregistered model should be blocked."""
    gate = mdg.ModelDownloadGate(registry_path=registry_file)

    with pytest.raises(mdg.UnregisteredModelError):
        gate.can_download("unknown-model-xyz")


def test_model_without_reason_blocked(registry_file, tmp_path):
    """A model in registry but without a reason should be blocked."""
    registry = registry_file
    data = json.loads(registry.read_text())
    data["orphaned-model"] = {
        "size_gb": 1.0,
        "location": "~/.ollama/models",
        "used_by": "unknown",
        "reason": "",
        "last_used": None
    }
    registry.write_text(json.dumps(data, indent=2))

    gate = mdg.ModelDownloadGate(registry_path=registry)

    with pytest.raises(mdg.NoDownloadReasonError):
        gate.can_download("orphaned-model")


def test_gate_context_manager(registry_file):
    """ModelDownloadGate should work as context manager."""
    with mdg.ModelDownloadGate(registry_path=registry_file) as gate:
        assert gate.can_download("qwen2.5-7b") is True


def test_multiple_registry_updates(registry_file):
    """Gate should see updated registry on reload."""
    gate = mdg.ModelDownloadGate(registry_path=registry_file)

    # Initially, unregistered model is blocked
    with pytest.raises(mdg.UnregisteredModelError):
        gate.can_download("new-model")

    # Add to registry
    data = json.loads(registry_file.read_text())
    data["new-model"] = {
        "size_gb": 2.0,
        "location": "~/.ollama/models",
        "used_by": "test",
        "reason": "testing",
        "last_used": None
    }
    registry_file.write_text(json.dumps(data, indent=2))

    # Create a new gate instance to reload
    gate2 = mdg.ModelDownloadGate(registry_path=registry_file)
    assert gate2.can_download("new-model") is True


def test_download_tracking(registry_file, monkeypatch):
    """Gate should track download attempts."""
    gate = mdg.ModelDownloadGate(registry_path=registry_file)

    # Mock the actual download
    download_calls = []
    def mock_download(*args, **kwargs):
        download_calls.append((args, kwargs))
        return True

    # Attempt to download
    result = gate.download("qwen2.5-7b", download_fn=mock_download)

    assert result is True
    assert len(download_calls) > 0
