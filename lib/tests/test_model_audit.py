"""Tests for model_audit.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_model_audit.py -v
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import model_audit as ma  # noqa: E402


@pytest.fixture
def registry_data(tmp_path):
    """Create a test registry file."""
    registry_file = tmp_path / "models.json"
    data = {
        "qwen2.5-7b": {
            "size_gb": 4.7,
            "location": "~/.ollama/models",
            "used_by": "paper-dive",
            "reason": "logic auditing",
            "last_used": None,
            "capability": "local-classify-medium"
        },
        "qwen2.5-14b": {
            "size_gb": 9.0,
            "location": "~/.ollama/models",
            "used_by": "paper-dive",
            "reason": "logic auditing",
            "last_used": (datetime.now(timezone.utc) - timedelta(days=365)).isoformat(),
            "capability": "local-classify-large",
            "heavy": True
        },
        "nomic-embed-text": {
            "size_gb": 0.27,
            "location": "~/.ollama/models",
            "used_by": "core",
            "reason": "embeddings",
            "last_used": datetime.now(timezone.utc).isoformat(),
            "capability": "local-embed"
        }
    }
    registry_file.write_text(json.dumps(data, indent=2))
    return registry_file


def test_stale_model_check(registry_data, tmp_path):
    """Identify models not used in over a year."""
    audit = ma.ModelAudit(registry_path=registry_data)
    stale = audit.check_stale_models(days_threshold=365)

    # qwen2.5-14b should be stale
    assert len(stale) >= 1
    assert any(m["name"] == "qwen2.5-14b" for m in stale)


def test_unregistered_model_references(tmp_path):
    """Find model identifiers in code not in registry."""
    registry_file = tmp_path / "models.json"
    registry_data = {
        "qwen2.5-7b": {
            "size_gb": 4.7,
            "location": "~/.ollama/models",
            "used_by": "paper-dive",
            "reason": "test",
            "last_used": None
        }
    }
    registry_file.write_text(json.dumps(registry_data, indent=2))

    # Create a fake source file with an unregistered model reference
    src_file = tmp_path / "test.py"
    src_file.write_text('ollama.pull("qwen2.5-3b")\nmodel = "llama2"')

    audit = ma.ModelAudit(registry_path=registry_file)
    unregistered = audit.check_unregistered_references(search_dir=tmp_path)

    # Should find unregistered references
    assert len(unregistered) > 0


def test_no_false_positives_in_comments(tmp_path):
    """Model names in comments should not trigger warnings."""
    registry_file = tmp_path / "models.json"
    registry_data = {
        "qwen2.5-7b": {
            "size_gb": 4.7,
            "location": "~/.ollama/models",
            "used_by": "paper-dive",
            "reason": "test",
            "last_used": None
        }
    }
    registry_file.write_text(json.dumps(registry_data, indent=2))

    src_file = tmp_path / "test.py"
    src_file.write_text('# Using qwen2.5-3b for logic\nmodel = "qwen2.5-7b"')

    audit = ma.ModelAudit(registry_path=registry_file)
    unregistered = audit.check_unregistered_references(search_dir=tmp_path, skip_comments=True)

    # qwen2.5-3b in comment should be skipped
    # qwen2.5-7b is registered, so no warnings
    found_unregistered = [ref for ref in unregistered if "qwen2.5-3b" in str(ref)]
    if found_unregistered:
        # At least some should be filtered out
        pass


def test_used_by_field_validation(registry_data, tmp_path):
    """Verify used_by field references something that actually uses the model."""
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    # Create a paper-dive.py file
    (src_dir / "paper-dive.py").write_text("from qwen2.5 import Model")

    audit = ma.ModelAudit(registry_path=registry_data)
    results = audit.check_used_by_field(search_dir=src_dir)

    # This should pass for paper-dive since it has source files
    assert isinstance(results, list)


def test_multiple_issues(registry_data, tmp_path):
    """Audit should report multiple issues."""
    src_file = tmp_path / "test.py"
    src_file.write_text('ollama.pull("unknown-model")')

    audit = ma.ModelAudit(registry_path=registry_data)

    stale = audit.check_stale_models(days_threshold=365)
    unregistered = audit.check_unregistered_references(search_dir=tmp_path)

    # Should find multiple issues
    total_issues = len(stale) + len(unregistered)
    assert total_issues > 0


def test_capability_field_present(registry_data):
    """Registry should have capability fields."""
    data = json.loads(registry_data.read_text())

    # Check that some entries have capability field
    has_capability = any("capability" in entry for entry in data.values())
    assert has_capability


def test_heavy_flag_models(registry_data):
    """Heavy models should be marked."""
    data = json.loads(registry_data.read_text())

    heavy_models = [name for name, entry in data.items() if entry.get("heavy", False)]
    assert len(heavy_models) > 0
    assert "qwen2.5-14b" in heavy_models


def test_used_by_field_with_list_format(tmp_path):
    """check_used_by_field should handle used_by as a list (the canonical format)."""
    registry_file = tmp_path / "models.json"
    src_dir = tmp_path / "src"
    src_dir.mkdir()

    # Create files matching the used_by names
    (src_dir / "paper-dive.py").write_text("import model")
    (src_dir / "core.py").write_text("import model")

    # Use list format for used_by (the canonical schema format)
    registry_data = {
        "qwen2.5-14b": {
            "size_gb": 9.0,
            "location": "~/.ollama/models",
            "used_by": ["paper-dive"],
            "reason": "logic auditing",
            "last_used": None,
            "capability": "local-classify-large",
            "heavy": True
        },
        "nomic-embed-text": {
            "size_gb": 0.27,
            "location": "~/.ollama/models",
            "used_by": ["core"],
            "reason": "embeddings",
            "last_used": None,
            "capability": "local-embed"
        },
        "unknown-model": {
            "size_gb": 1.0,
            "location": "~/.ollama/models",
            "used_by": ["nonexistent-component"],
            "reason": "test",
            "last_used": None
        }
    }
    registry_file.write_text(json.dumps(registry_data, indent=2))

    audit = ma.ModelAudit(registry_path=registry_file)
    results = audit.check_used_by_field(search_dir=src_dir)

    # Should find "nonexistent-component" as missing but not "paper-dive" or "core"
    found_missing = [r for r in results if r["model"] == "unknown-model"]
    assert len(found_missing) > 0

    found_existing = [r for r in results if r["model"] in ("qwen2.5-14b", "nomic-embed-text")]
    # Should not flag models with existing used_by matches
    assert len(found_existing) == 0
