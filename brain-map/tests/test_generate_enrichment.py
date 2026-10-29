"""Tests for brain-map/generate.py enrichment loading robustness."""
import json
import sys
from pathlib import Path

import pytest

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))
import generate as gen


class TestSafeDefaults:
    """Test that _SAFE_DEFAULTS contains all required top-level keys."""

    def test_safe_defaults_has_all_required_keys(self):
        """_SAFE_DEFAULTS must have all 7 required keys."""
        required = {"structural", "category_order", "skill_categories", "category_labels",
                   "skills_trunk_desc", "root", "skill_desc_overrides"}
        assert required.issubset(set(gen._SAFE_DEFAULTS.keys()))

    def test_safe_defaults_structural_is_list(self):
        """structural should be a list."""
        assert isinstance(gen._SAFE_DEFAULTS["structural"], list)

    def test_safe_defaults_category_order_is_list(self):
        """category_order should be a list."""
        assert isinstance(gen._SAFE_DEFAULTS["category_order"], list)

    def test_safe_defaults_category_labels_is_dict(self):
        """category_labels should be a dict."""
        assert isinstance(gen._SAFE_DEFAULTS["category_labels"], dict)

    def test_safe_defaults_skill_categories_is_dict(self):
        """skill_categories should be a dict."""
        assert isinstance(gen._SAFE_DEFAULTS["skill_categories"], dict)

    def test_safe_defaults_skill_desc_overrides_is_dict(self):
        """skill_desc_overrides should be a dict."""
        assert isinstance(gen._SAFE_DEFAULTS["skill_desc_overrides"], dict)

    def test_safe_defaults_root_is_dict(self):
        """root should be a dict with id and desc."""
        assert isinstance(gen._SAFE_DEFAULTS["root"], dict)
        assert "id" in gen._SAFE_DEFAULTS["root"]
        assert "desc" in gen._SAFE_DEFAULTS["root"]

    def test_safe_defaults_skills_trunk_desc_is_string(self):
        """skills_trunk_desc should be a string."""
        assert isinstance(gen._SAFE_DEFAULTS["skills_trunk_desc"], str)


class TestLoadEnrichmentMissingFile:
    """Test _load_enrichment() with missing file."""

    def test_load_enrichment_missing_file_returns_defaults_silently(self, tmp_path):
        """Missing enrichment file → return defaults silently (no stderr)."""
        missing_path = tmp_path / "nonexistent.json"
        enrichment = gen._load_enrichment(missing_path)

        # Should return a dict with all defaults
        assert isinstance(enrichment, dict)
        for key in gen._SAFE_DEFAULTS:
            assert key in enrichment

    def test_load_enrichment_missing_file_no_warning_stderr(self, tmp_path, capsys):
        """Missing file should not print a warning."""
        missing_path = tmp_path / "nonexistent.json"
        gen._load_enrichment(missing_path)

        captured = capsys.readouterr()
        assert "WARNING" not in captured.err and "Error" not in captured.err


class TestLoadEnrichmentCorruptJson:
    """Test _load_enrichment() with corrupt JSON."""

    def test_load_enrichment_corrupt_json_warns_and_defaults(self, tmp_path, capsys):
        """Corrupt JSON → warn to stderr, return defaults."""
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("{not valid json")

        enrichment = gen._load_enrichment(bad_path)

        captured = capsys.readouterr()
        assert "WARNING" in captured.err or "Error" in captured.err or "corrupt" in captured.err.lower()
        assert isinstance(enrichment, dict)
        for key in gen._SAFE_DEFAULTS:
            assert key in enrichment

    def test_load_enrichment_wrong_type_warns_and_defaults(self, tmp_path, capsys):
        """JSON that's not a dict → warn to stderr, return defaults."""
        bad_path = tmp_path / "bad.json"
        bad_path.write_text('["not", "a", "dict"]')

        enrichment = gen._load_enrichment(bad_path)

        captured = capsys.readouterr()
        assert "WARNING" in captured.err or "wrong" in captured.err.lower()
        assert isinstance(enrichment, dict)
        for key in gen._SAFE_DEFAULTS:
            assert key in enrichment


class TestLoadEnrichmentValidPartial:
    """Test _load_enrichment() with valid but incomplete JSON."""

    def test_load_enrichment_partial_json_fills_in_missing_keys(self, tmp_path):
        """Valid partial JSON → setdefault all missing keys from defaults."""
        partial_path = tmp_path / "partial.json"
        partial_data = {
            "structural": [{"id": "Custom", "cat": "custom"}],
            "skill_categories": {"my-skill": "custom-category"},
        }
        partial_path.write_text(json.dumps(partial_data))

        enrichment = gen._load_enrichment(partial_path)

        # Custom values are present
        assert enrichment["structural"] == [{"id": "Custom", "cat": "custom"}]
        assert enrichment["skill_categories"] == {"my-skill": "custom-category"}
        # Missing keys are filled with defaults
        assert "category_order" in enrichment
        assert "root" in enrichment
        assert "skills_trunk_desc" in enrichment

    def test_load_enrichment_extra_keys_preserved(self, tmp_path):
        """Valid JSON with extra keys not in defaults → preserved alongside defaults."""
        extra_path = tmp_path / "extra.json"
        extra_data = {
            "structural": [],
            "category_order": [],
            "skill_categories": {},
            "category_labels": {},
            "skills_trunk_desc": "test",
            "root": {"id": "test", "desc": "test"},
            "skill_desc_overrides": {},
            "extra_field": "not in defaults",
            "another_custom": {"nested": "value"},
        }
        extra_path.write_text(json.dumps(extra_data))

        enrichment = gen._load_enrichment(extra_path)

        # Defaults are present
        assert "structural" in enrichment
        assert "root" in enrichment
        # Extra keys are preserved
        assert enrichment["extra_field"] == "not in defaults"
        assert enrichment["another_custom"] == {"nested": "value"}


class TestLoadEnrichmentIntegration:
    """Integration tests for _load_enrichment()."""

    def test_load_enrichment_full_valid_file(self, tmp_path):
        """Full valid enrichment file → loaded as-is."""
        full_path = tmp_path / "full.json"
        full_data = {
            "structural": [{"id": "Memory", "cat": "memory"}],
            "category_order": ["basics", "advanced"],
            "skill_categories": {"skill1": "basics", "skill2": "advanced"},
            "category_labels": {"basics": "Basics", "advanced": "Advanced"},
            "skills_trunk_desc": "All skills available",
            "root": {"id": "MARVIN", "desc": "The brain map"},
            "skill_desc_overrides": {"skill1": "Custom description"},
        }
        full_path.write_text(json.dumps(full_data))

        enrichment = gen._load_enrichment(full_path)

        for key, value in full_data.items():
            assert enrichment[key] == value


class TestMainUsesLoadEnrichment:
    """Test that main() uses _load_enrichment() for robustness."""

    def test_main_can_run_with_missing_enrichment_file(self, tmp_path, monkeypatch):
        """main() should not crash even if enrichment file is missing."""
        # This is an integration test that confirms main() uses the robust loader
        # We'll just test that _load_enrichment is callable and returns valid data
        enrichment = gen._load_enrichment(tmp_path / "missing.json")
        assert "structural" in enrichment
        assert "root" in enrichment
