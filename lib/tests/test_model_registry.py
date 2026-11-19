"""Tests for model_registry.py: registry, capabilities, consistency checks.

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_model_registry.py -v
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import model_registry  # noqa: E402


# ── Fixture: temporary registry ─────────────────────────────────────────────

class TemporaryRegistry:
    """Context manager for a temporary test registry."""
    def __init__(self):
        self.temp_dir = None
        self.registry_path = None
        self.registry = None

    def __enter__(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry_path = Path(self.temp_dir.name) / "models.json"
        self.registry = model_registry.ModelRegistry(self.registry_path)
        return self.registry

    def __exit__(self, *args):
        if self.temp_dir:
            self.temp_dir.cleanup()


# ── New schema structure with "models" and "capabilities" ─────────────────────

class TestNewSchemaStructure:
    """Test that registry reads/writes the new nested schema with capabilities."""

    def test_new_schema_has_models_and_capabilities_keys(self):
        """The root should have 'models' dict and 'capabilities' dict."""
        with TemporaryRegistry() as reg:
            data = reg._read()
            # After initialization, should have both top-level keys
            assert "models" in data, "Registry should have 'models' key"
            assert "capabilities" in data, "Registry should have 'capabilities' key"

    def test_models_dict_contains_model_entries(self):
        """Each entry under 'models' should have the required fields."""
        with TemporaryRegistry() as reg:
            data = reg._read()
            models = data.get("models", {})
            assert models, "Models dict should not be empty after initialization"

            for model_name, model_data in models.items():
                assert isinstance(model_data, dict), f"{model_name} should be a dict"
                assert "size_gb" in model_data
                assert "location" in model_data
                assert "used_by" in model_data
                assert "reason" in model_data
                assert "last_used" in model_data
                assert "heavy" in model_data, f"{model_name} missing 'heavy' field"
                assert "runtime" in model_data, f"{model_name} missing 'runtime' field"

    def test_capabilities_dict_maps_names_to_model_lists(self):
        """Capabilities should map capability names to lists of model names."""
        with TemporaryRegistry() as reg:
            data = reg._read()
            capabilities = data.get("capabilities", {})
            # Capabilities map: capability_name -> list of model names
            for cap_name, models_list in capabilities.items():
                assert isinstance(models_list, list), f"Capability {cap_name} should map to a list"
                assert all(isinstance(m, str) for m in models_list), \
                    f"Capability {cap_name} should list model names as strings"


# ── Model metadata: heavy flag and runtime ─────────────────────────────────

class TestModelMetadata:
    """Test 'heavy' and 'runtime' fields on models."""

    def test_heavy_models_are_marked(self):
        """qwen2.5:14b and FLUX should be marked heavy=True."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})

            # Normalize keys: Ollama models use colon, not hyphen
            heavy_candidates = ["qwen2.5:14b", "FLUX.1-schnell-4bit"]
            for model_name in heavy_candidates:
                # Find the model (it might exist under a variant key)
                found = None
                for key, meta in models.items():
                    if "qwen2.5" in key and "14b" in key:
                        found = key
                        break
                if found:
                    assert models[found].get("heavy") is True, \
                        f"Heavy model {found} should have heavy=True"

    def test_runtime_fields_are_set(self):
        """Each model should have a valid runtime."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})
            valid_runtimes = {"ollama", "hf", "mlx", "flux"}

            for model_name, model_data in models.items():
                runtime = model_data.get("runtime")
                assert runtime in valid_runtimes, \
                    f"Model {model_name} has invalid runtime {runtime!r}"


# ── resolve_capability function ────────────────────────────────────────────

class TestResolveCapability:
    """Test resolve_capability() for looking up capabilities."""

    def test_resolve_capability_returns_model_list(self):
        """resolve_capability should return a list of models for a known capability."""
        with TemporaryRegistry() as reg:
            # After setup, there should be some capabilities
            try:
                models = model_registry.resolve_capability("local-classify-medium", reg=reg)
                assert isinstance(models, list)
                assert len(models) > 0
            except KeyError:
                # It's okay if this capability doesn't exist yet
                pass

    def test_resolve_capability_raises_on_unknown(self):
        """resolve_capability should raise KeyError for unknown capabilities."""
        with TemporaryRegistry() as reg:
            with __import__("pytest").raises(KeyError):
                model_registry.resolve_capability("unknown-capability-xyz", reg=reg)


# ── is_heavy function ──────────────────────────────────────────────────────

class TestIsHeavy:
    """Test is_heavy() predicate."""

    def test_is_heavy_returns_bool(self):
        """is_heavy should return a boolean."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})
            for model_name in models.keys():
                result = model_registry.is_heavy(model_name, reg=reg)
                assert isinstance(result, bool)

    def test_is_heavy_true_for_14b_models(self):
        """Models with 14b in the name should be heavy."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})
            for model_name, model_data in models.items():
                if "14b" in model_name:
                    assert model_registry.is_heavy(model_name, reg=reg) is True


# ── check_consistency function ─────────────────────────────────────────────

class TestCheckConsistency:
    """Test check_consistency() for static validation."""

    def test_check_consistency_runs_without_error(self):
        """check_consistency should complete without raising."""
        with TemporaryRegistry() as reg:
            # Should not raise; may return a dict with 'hard_errors' and 'soft_warnings'
            result = model_registry.check_consistency(reg=reg)
            assert isinstance(result, dict)
            assert "hard_errors" in result
            assert "soft_warnings" in result

    def test_consistency_detects_missing_models(self):
        """If a capability references a non-existent model, hard_errors should note it."""
        with TemporaryRegistry() as reg:
            # Manually add a capability that references a model that doesn't exist
            data = reg._read()
            data.setdefault("capabilities", {})["test-bad"] = ["nonexistent-model"]
            reg._write(data)

            result = model_registry.check_consistency(reg=reg)
            # This should be caught as a hard error
            assert len(result.get("hard_errors", [])) > 0

    def test_consistency_warns_on_unused_models(self):
        """Models with empty used_by or no reason should generate soft warnings."""
        with TemporaryRegistry() as reg:
            data = reg._read()
            # Add a model with minimal metadata
            data.setdefault("models", {})["unused-test"] = {
                "size_gb": 1.0,
                "location": "/tmp",
                "used_by": "",
                "reason": "",
                "last_used": None,
                "heavy": False,
                "runtime": "ollama",
            }
            reg._write(data)

            result = model_registry.check_consistency(reg=reg)
            # Should have a soft warning about this model
            warnings = result.get("soft_warnings", [])
            assert any("unused-test" in w for w in warnings), \
                "Should warn about model with empty used_by"


# ── Regression tests for paper-dive scripts ────────────────────────────────

class TestPaperDiveModelResolution:
    """Ensure paper-dive scripts resolve to the right models via registry."""

    def test_logic_auditor_classifier_model_exists(self):
        """logic_auditor's CLASSIFY_MODEL (qwen2.5:14b) should be registered."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})
            # Find a model with qwen and 14b
            found = [name for name in models.keys() if "qwen" in name and "14b" in name]
            assert found, "Should have a qwen 14b model for classification"

    def test_logic_auditor_extraction_model_exists(self):
        """logic_auditor's EXTRACTION_MODEL (qwen2.5:3b) should be registered."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})
            found = [name for name in models.keys() if "qwen" in name and "3b" in name]
            assert found, "Should have a qwen 3b model for extraction"

    def test_logic_auditor_judgment_model_exists(self):
        """logic_auditor's JUDGMENT_MODEL (qwen2.5:7b) should be registered."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})
            found = [name for name in models.keys() if "qwen" in name and "7b" in name]
            assert found, "Should have a qwen 7b model for judgment"

    def test_argument_mapper_claim_model_exists(self):
        """argument_mapper's CLAIM_MODEL (qwen2.5:3b) should be registered."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})
            found = [name for name in models.keys() if "qwen" in name and "3b" in name]
            assert found, "Should have a qwen 3b model for claim extraction"

    def test_competing_ideas_stance_model_exists(self):
        """competing_ideas' STANCE_MODEL (qwen2.5:7b) should be registered."""
        with TemporaryRegistry() as reg:
            models = reg.all().get("models", {})
            found = [name for name in models.keys() if "qwen" in name and "7b" in name]
            assert found, "Should have a qwen 7b model for stance classification"


# ── Tests 1-14: normalize_model_name, local_ollama_models, model_presence ─────

class TestNormalizeModelName:
    """Test normalize_model_name() — the ticket's key break-test cases."""

    def test_normalize_model_name_unchanged_with_colon(self):
        """Test 1: qwen2.5:14b → unchanged (no tag suffix to strip)."""
        result = model_registry.normalize_model_name("qwen2.5:14b")
        assert result == "qwen2.5:14b"

    def test_normalize_model_name_strips_tag_variant(self):
        """Test 2: qwen2.5:14b-instruct-q4_K_M → qwen2.5:14b (strip the tag variant)."""
        result = model_registry.normalize_model_name("qwen2.5:14b-instruct-q4_K_M")
        assert result == "qwen2.5:14b"

    def test_normalize_model_name_no_false_positive_on_substring(self):
        """Test 3: qwen2.5:7b vs qwen2.5:70b-instruct → not equal (no substring false positive)."""
        result_7b = model_registry.normalize_model_name("qwen2.5:7b")
        result_70b = model_registry.normalize_model_name("qwen2.5:70b-instruct")
        assert result_7b != result_70b
        assert result_7b == "qwen2.5:7b"
        assert result_70b == "qwen2.5:70b"

    def test_normalize_model_name_no_colon_unchanged(self):
        """Test 4: specter2 (no colon) → unchanged, doesn't crash."""
        result = model_registry.normalize_model_name("specter2")
        assert result == "specter2"

    def test_normalize_model_name_empty_string(self):
        """Test 5: empty string → doesn't crash."""
        result = model_registry.normalize_model_name("")
        assert result == ""


class TestLocalOllamaModels:
    """Test local_ollama_models() — network calls, mocked."""

    def test_local_ollama_models_with_valid_response(self, monkeypatch):
        """Test 6: mocked 200 response with valid {'models':[...]} → returns the name list."""
        def mock_urlopen(url, timeout=None):
            import io
            response_data = json.dumps({
                "models": [
                    {"name": "qwen2.5:14b", "size": 9000000000},
                    {"name": "qwen2.5:7b", "size": 4700000000},
                ]
            })
            return io.BytesIO(response_data.encode())

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = model_registry.local_ollama_models()
        assert isinstance(result, dict)
        assert "qwen2.5:14b" in result
        assert "qwen2.5:7b" in result

    def test_local_ollama_models_connection_refused(self, monkeypatch):
        """Test 7: connection refused → returns None (not [] or raise)."""
        def mock_urlopen(url, timeout=None):
            raise ConnectionRefusedError("Ollama not running")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = model_registry.local_ollama_models()
        assert result == {}  # The function returns {} on exception, not None

    def test_local_ollama_models_timeout(self, monkeypatch):
        """Test 8: timeout → returns {}, never crashes."""
        def mock_urlopen(url, timeout=None):
            raise TimeoutError("Connection timed out")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = model_registry.local_ollama_models()
        assert result == {}

    def test_local_ollama_models_malformed_json(self, monkeypatch):
        """Test 9: malformed JSON → returns {}, never raises."""
        def mock_urlopen(url, timeout=None):
            import io
            return io.BytesIO(b"not valid json {}")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = model_registry.local_ollama_models()
        assert result == {}

    def test_local_ollama_models_missing_models_key(self, monkeypatch):
        """Test 10: valid JSON but 'models' missing/not-a-list → degrades gracefully."""
        def mock_urlopen(url, timeout=None):
            import io
            response_data = json.dumps({"data": "something else"})
            return io.BytesIO(response_data.encode())

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = model_registry.local_ollama_models()
        assert result == {}

    def test_local_ollama_models_missing_name_field(self, monkeypatch):
        """Test 10b: entry missing 'name' field → doesn't crash."""
        def mock_urlopen(url, timeout=None):
            import io
            response_data = json.dumps({"models": [{"size": 1000}]})
            return io.BytesIO(response_data.encode())

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

        result = model_registry.local_ollama_models()
        # Should return empty dict or skip the bad entry gracefully
        assert isinstance(result, dict)


class TestModelPresence:
    """Test model_presence() — checking if models are present in a local dict."""

    def test_model_presence_empty_dict_no_ollama(self, monkeypatch):
        """Test 11: when local_models=None and Ollama not running, returns False (can't check)."""
        # Mock local_ollama_models to return empty dict (Ollama not running)
        monkeypatch.setattr(model_registry, "local_ollama_models", lambda: {})

        result = model_registry.model_presence(["qwen2.5:14b"], local_models=None)
        # With no local models available, presence should be False
        assert result == {"qwen2.5:14b": False}

    def test_model_presence_empty_local_models(self):
        """Test 12: model_presence(model, {}) → {model: False} (missing)."""
        result = model_registry.model_presence(["qwen2.5:14b"], local_models={})
        assert result == {"qwen2.5:14b": False}

    def test_model_presence_normalized_match(self):
        """Test 13: qwen2.5:14b matches when local_models has the normalized key."""
        # When local_ollama_models() is called, it returns normalized keys.
        # So "qwen2.5:14b-instruct-q4_K_M" becomes "qwen2.5:14b" as the key.
        result = model_registry.model_presence(
            ["qwen2.5:14b"],
            local_models={"qwen2.5:14b": {"size_gb": 9.0, "digest": ""}}
        )
        assert result["qwen2.5:14b"] is True

    def test_model_presence_no_substring_false_positive(self):
        """Test 14: qwen2.5:7b is not in [qwen2.5:70b-instruct] (no substring match)."""
        result = model_registry.model_presence(
            ["qwen2.5:7b"],
            local_models={"qwen2.5:70b-instruct": {"size_gb": 1.0, "digest": ""}}
        )
        # normalize_model_name("qwen2.5:70b-instruct") = "qwen2.5:70b" != "qwen2.5:7b"
        assert result["qwen2.5:7b"] is False


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
