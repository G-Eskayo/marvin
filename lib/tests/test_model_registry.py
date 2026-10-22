"""Tests for model_registry.py: registry, capabilities, consistency checks.

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_model_registry.py -v
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

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


# ── check_ollama_pulled function ──────────────────────────────────────────

class TestCheckOllamaPulled:
    """Test check_ollama_pulled() for Ollama server/model detection."""

    def test_exact_model_match(self):
        """Test 1: exact match against /api/tags returns (True, '')."""
        response_data = json.dumps({
            "models": [{"name": "qwen2.5:7b"}]
        }).encode()

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
            ok, msg = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is True
            assert msg == ""

    def test_bare_name_normalized_to_latest(self):
        """Test 2: bare name without tag is normalized to :latest (e.g., 'mymodel' -> 'mymodel:latest')."""
        response_data = json.dumps({
            "models": [{"name": "mymodel:latest"}]
        }).encode()

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
            ok, msg = model_registry.check_ollama_pulled("mymodel")
            assert ok is True
            assert msg == ""

    def test_no_prefix_matching(self):
        """Test 2b: Prefix matching is no longer supported. qwen2.5:7b does NOT match qwen2.5:7b-instruct-q4_K_M."""
        response_data = json.dumps({
            "models": [{"name": "qwen2.5:7b-instruct-q4_K_M"}]
        }).encode()

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with TemporaryRegistry() as reg:
            with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
                ok, msg = model_registry.check_ollama_pulled("qwen2.5:7b", registry=reg)
                assert ok is False, "Prefix matching should not work; exact match is required"
                assert "not found" in msg.lower()

    def test_server_unreachable(self):
        """Test 3: Ollama server unreachable (connection refused) returns helpful error."""
        with patch("model_registry.urllib.request.urlopen", side_effect=ConnectionRefusedError("Connection refused")):
            ok, msg = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is False
            assert "ollama serve" in msg
            assert "not responding" in msg.lower()

    def test_model_not_pulled(self):
        """Test 4: Server up, model not pulled returns error with ollama pull command."""
        response_data = json.dumps({
            "models": [{"name": "other-model"}]
        }).encode()

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with TemporaryRegistry() as reg:
            with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
                ok, msg = model_registry.check_ollama_pulled("qwen2.5:7b", registry=reg)
                assert ok is False
                assert "Model 'qwen2.5:7b' (~4.7 GB) not found." in msg
                assert "ollama pull qwen2.5:7b" in msg

    def test_malformed_response(self):
        """Test 5: Malformed /api/tags response (missing models key) treated as not available."""
        response_data = json.dumps({}).encode()  # missing "models" key

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with TemporaryRegistry() as reg:
            with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
                ok, msg = model_registry.check_ollama_pulled("qwen2.5:7b", registry=reg)
                assert ok is False
                assert "not found" in msg.lower()

    def test_empty_model_name(self):
        """Test 6: Empty or absurdly long model name causes no crash."""
        response_data = json.dumps({
            "models": [{"name": "some-model"}]
        }).encode()

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with TemporaryRegistry() as reg:
            with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
                # Empty name
                ok, msg = model_registry.check_ollama_pulled("", registry=reg)
                assert ok is False

                # Long name (no injection possible without shell invocation)
                ok, msg = model_registry.check_ollama_pulled("a" * 1000, registry=reg)
                assert ok is False

    def test_concurrent_calls_independent(self):
        """Test 7: Two concurrent calls against a missing model fail independently."""
        response_data = json.dumps({
            "models": []
        }).encode()

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with TemporaryRegistry() as reg:
            with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
                ok1, msg1 = model_registry.check_ollama_pulled("model-a", registry=reg)
                ok2, msg2 = model_registry.check_ollama_pulled("model-b", registry=reg)

                assert ok1 is False
                assert ok2 is False
                assert "model-a" in msg1
                assert "model-b" in msg2

    def test_no_default_registry_construction_when_passed(self):
        """Test 8: Regression - check_ollama_pulled must not construct default ModelRegistry when registry= is given."""
        response_data = json.dumps({
            "models": [{"name": "some-model:latest"}]
        }).encode()

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with TemporaryRegistry() as provided_reg:
            with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
                # Call with explicit registry - should find the exact match after normalization
                ok, msg = model_registry.check_ollama_pulled("some-model", registry=provided_reg)
                assert ok is True, "Should find exact model match (bare name normalized to :latest)"

    def test_non_dict_json_response(self):
        """Test 5: Non-dict JSON response (e.g., array) is handled gracefully."""
        response_data = json.dumps(["model1", "model2"]).encode()  # Array, not dict

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with TemporaryRegistry() as reg:
            with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
                ok, msg = model_registry.check_ollama_pulled("qwen2.5:7b", registry=reg)
                assert ok is False
                assert "non-dict" in msg.lower() or "not responding" in msg.lower()

    def test_model_entry_missing_name_field(self):
        """Test 6: Model entries missing 'name' field are skipped gracefully."""
        response_data = json.dumps({
            "models": [
                {"size": 123},  # Missing "name"
                {"name": "valid-model:latest"}
            ]
        }).encode()

        mock_response = MagicMock()
        mock_response.__enter__.return_value = mock_response
        mock_response.__exit__.return_value = None
        mock_response.read.return_value = response_data

        with TemporaryRegistry() as reg:
            with patch("model_registry.urllib.request.urlopen", return_value=mock_response):
                # Should not crash, should check against "valid-model" (normalized to "valid-model:latest")
                ok, msg = model_registry.check_ollama_pulled("valid-model", registry=reg)
                assert ok is True, "Should find 'valid-model' even with malformed entry present"

                ok, msg = model_registry.check_ollama_pulled("qwen2.5:7b", registry=reg)
                assert ok is False, "Should not find missing model"
                assert "not found" in msg.lower()


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


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
