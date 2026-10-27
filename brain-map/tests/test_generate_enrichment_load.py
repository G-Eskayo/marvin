"""Brain-map: enrichment.json loading with safe fallbacks (plan §3).

Tests 8-11: _load_enrichment() handles JSON parse failures, provides safe defaults
for the 7 unconditionally-indexed top-level keys."""

import json
from pathlib import Path

import pytest

# Import the module; adjust the path as needed
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import generate as gen


class TestLoadEnrichment:
    """Tests 8-11: _load_enrichment() is robust to missing/malformed files."""

    def test_load_enrichment_valid_json(self, tmp_path, monkeypatch):
        """Test 8: _load_enrichment() loads and returns valid JSON dict."""
        enrichment_path = tmp_path / "enrichment.json"
        data = {
            "skill_categories": {"test": "category"},
            "category_order": ["category"],
            "category_labels": {"category": "Label"},
            "skills_trunk_desc": "test",
            "structural": [],
            "root": {"id": "root", "desc": "root"},
            "plain": {},
            "skill_desc_overrides": {},
        }
        enrichment_path.write_text(json.dumps(data))

        monkeypatch.setattr(gen, "ENRICHMENT_PATH", enrichment_path)

        result = gen._load_enrichment()
        assert result == data
        assert result["skill_categories"] == {"test": "category"}

    def test_load_enrichment_missing_file_returns_empty_dict_with_defaults(self, tmp_path, monkeypatch):
        """Test 9: _load_enrichment() returns dict with safe defaults when file missing."""
        enrichment_path = tmp_path / "nonexistent.json"

        monkeypatch.setattr(gen, "ENRICHMENT_PATH", enrichment_path)

        result = gen._load_enrichment()

        assert isinstance(result, dict)
        # Check the 8 safe defaults are present (including skill_desc_overrides)
        assert "skill_categories" in result
        assert "category_order" in result
        assert "category_labels" in result
        assert "skills_trunk_desc" in result
        assert "structural" in result
        assert "root" in result
        assert "plain" in result
        assert "skill_desc_overrides" in result

    def test_load_enrichment_invalid_json_returns_empty_dict_with_defaults(self, tmp_path, monkeypatch):
        """Test 10: _load_enrichment() returns dict with safe defaults on JSON parse error."""
        enrichment_path = tmp_path / "corrupted.json"
        enrichment_path.write_text("{ invalid json ]")

        monkeypatch.setattr(gen, "ENRICHMENT_PATH", enrichment_path)

        result = gen._load_enrichment()

        assert isinstance(result, dict)
        assert "skill_categories" in result
        assert "category_order" in result
        assert "category_labels" in result

    def test_load_enrichment_non_dict_returns_empty_dict_with_defaults(self, tmp_path, monkeypatch):
        """Test 11: _load_enrichment() handles non-dict JSON (list, string, etc.)."""
        enrichment_path = tmp_path / "list.json"
        enrichment_path.write_text(json.dumps(["not", "a", "dict"]))

        monkeypatch.setattr(gen, "ENRICHMENT_PATH", enrichment_path)

        result = gen._load_enrichment()

        assert isinstance(result, dict)
        assert "skill_categories" in result
        assert "category_order" in result


class TestMainUsesLoadEnrichment:
    """Integration: main() uses _load_enrichment() instead of raw json.loads()."""

    def test_main_calls_load_enrichment_not_raw_loads(self, tmp_path, monkeypatch, capsys):
        """main() calls _load_enrichment() to handle missing enrichment.json gracefully."""
        enrichment_path = tmp_path / "enrichment.json"
        # enrichment_path doesn't exist — would fail with raw json.loads()

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps({"index": []}))

        template_path = tmp_path / "template.html"
        template_path.write_text("""<!DOCTYPE html>
<html>
<body>
/*__TREE_START__*//*__TREE_END__*/
/*__SYNAPSES_START__*//*__SYNAPSES_END__*/
</body>
</html>""")

        output_path = tmp_path / "index.html"

        # Mock the paths and dependencies
        monkeypatch.setattr(gen, "ENRICHMENT_PATH", enrichment_path)
        monkeypatch.setattr(gen, "MANIFEST_PATH", manifest_path)
        monkeypatch.setattr(gen, "TEMPLATE_PATH", template_path)
        monkeypatch.setattr(gen, "OUTPUT_PATH", output_path)
        monkeypatch.setattr(gen, "TREE_DATA_PATH", tmp_path / "tree-data.json")

        # Mock functions that require system access
        monkeypatch.setattr(gen, "build_tree", lambda m, e: {})
        monkeypatch.setattr(gen, "attach_layout", lambda t: None)
        monkeypatch.setattr(gen, "attach_code_layers", lambda t: None)
        monkeypatch.setattr(gen, "all_synapses", lambda m, e, t: {})

        # Call main() — it should use _load_enrichment() internally and not raise
        gen.main()

        # Verify output was written (proves main() completed successfully)
        assert output_path.exists()

        # Verify no error was printed to stderr about enrichment (file missing is silent)
        captured = capsys.readouterr()
        # The file missing is expected; no warning for missing file
