"""Brain-map enrichment.json robustness (tests 20-22).

ENRICHMENT_PATH read should degrade to {}-shaped safe defaults on
missing/corrupt/wrong-shaped input, matching lib/instance.py:_config()'s
existing discipline. This prevents the entire brain-map generation from
failing when enrichment.json is unavailable or malformed."""

import json
import pytest
import sys
from pathlib import Path

# Add paths for imports
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "lib"))

import generate


def test_20_missing_enrichment_json_returns_empty_dict(tmp_path, monkeypatch):
    """When enrichment.json doesn't exist, should return empty dict not crash."""
    # Point to a non-existent file
    enrichment_path = tmp_path / "nonexistent.json"
    monkeypatch.setattr(generate, "ENRICHMENT_PATH", enrichment_path)

    # Should not raise, should return empty dict
    result = generate.load_enrichment()
    assert result == {}


def test_21_corrupt_json_returns_empty_dict(tmp_path, monkeypatch):
    """When enrichment.json has invalid JSON, should return empty dict."""
    enrichment_path = tmp_path / "enrichment.json"
    enrichment_path.write_text("{not valid json}")
    monkeypatch.setattr(generate, "ENRICHMENT_PATH", enrichment_path)

    # Should not raise, should return empty dict
    result = generate.load_enrichment()
    assert result == {}


def test_22_wrong_shaped_enrichment_returns_empty_dict(tmp_path, monkeypatch):
    """When enrichment.json is valid JSON but not a dict, should return empty dict."""
    enrichment_path = tmp_path / "enrichment.json"
    # Write valid JSON but not a dict (e.g., a list or string)
    enrichment_path.write_text('["not", "a", "dict"]')
    monkeypatch.setattr(generate, "ENRICHMENT_PATH", enrichment_path)

    # Should not raise, should return empty dict
    result = generate.load_enrichment()
    assert result == {}


def test_valid_enrichment_loads_correctly(tmp_path, monkeypatch):
    """Valid enrichment.json should load and be returned as-is."""
    enrichment_path = tmp_path / "enrichment.json"
    valid_enrichment = {
        "skill_desc_overrides": {"test-skill": "Test description"},
        "categories": {"test-cat": "Test category"}
    }
    enrichment_path.write_text(json.dumps(valid_enrichment))
    monkeypatch.setattr(generate, "ENRICHMENT_PATH", enrichment_path)

    result = generate.load_enrichment()
    assert result == valid_enrichment


def test_empty_json_dict_is_valid(tmp_path, monkeypatch):
    """An empty JSON dict {} should be accepted and returned as-is."""
    enrichment_path = tmp_path / "enrichment.json"
    enrichment_path.write_text("{}")
    monkeypatch.setattr(generate, "ENRICHMENT_PATH", enrichment_path)

    result = generate.load_enrichment()
    assert result == {}
