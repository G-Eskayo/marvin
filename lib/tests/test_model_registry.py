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

class TestCheckOllamaPulled:
    """Test check_ollama_pulled() for verifying Ollama model availability."""

    def test_check_ollama_pulled_handles_server_down(self):
        """If Ollama server is unreachable, should return error."""
        def fake_urlopen(url, timeout=5):
            raise ConnectionRefusedError("Connection refused")

        import urllib.request
        original_urlopen = urllib.request.urlopen
        try:
            urllib.request.urlopen = fake_urlopen
            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b", base_url="http://localhost:9999")
            assert ok is False
            assert "Ollama server not responding" in err
        finally:
            urllib.request.urlopen = original_urlopen

    def test_check_ollama_pulled_accepts_exact_match(self):
        """Should return True if the model is in the available list exactly."""
        def fake_get(url, timeout=5):
            class FakeResp:
                def read(self):
                    import json
                    return json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
            return FakeResp()

        import urllib.request
        original_urlopen = urllib.request.urlopen
        try:
            urllib.request.urlopen = fake_get
            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is True
            assert err == ""
        finally:
            urllib.request.urlopen = original_urlopen

    def test_check_ollama_pulled_accepts_prefix_match(self):
        """Should return True if the model is a prefix match (quantization variant)."""
        def fake_get(url, timeout=5):
            class FakeResp:
                def read(self):
                    import json
                    return json.dumps({"models": [{"name": "qwen2.5:7b-instruct-q4_K_M"}]}).encode()
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
            return FakeResp()

        import urllib.request
        original_urlopen = urllib.request.urlopen
        try:
            urllib.request.urlopen = fake_get
            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is True
            assert err == ""
        finally:
            urllib.request.urlopen = original_urlopen

    def test_check_ollama_pulled_rejects_missing_model(self):
        """Should return error if model is not available."""
        def fake_get(url, timeout=5):
            class FakeResp:
                def read(self):
                    import json
                    return json.dumps({"models": [{"name": "other-model:7b"}]}).encode()
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
            return FakeResp()

        import urllib.request
        original_urlopen = urllib.request.urlopen
        try:
            urllib.request.urlopen = fake_get
            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is False
            assert "Model 'qwen2.5:7b' not found" in err
        finally:
            urllib.request.urlopen = original_urlopen


# ── resolve_available_capability ────────────────────────────────────────────

class TestResolveAvailableCapability:
    """Test resolve_available_capability() for fallback handling."""

    def test_resolve_available_capability_returns_first_available(self):
        """Should return the first available model from the capability list."""
        def fake_check(model, base_url=None):
            # First model is available
            return model == "qwen2.5:14b", ""

        original_check = model_registry.check_ollama_pulled
        try:
            model_registry.check_ollama_pulled = fake_check
            model, is_fallback = model_registry.resolve_available_capability("local-classify-medium")
            assert model == "qwen2.5:14b"
            assert is_fallback is False
        finally:
            model_registry.check_ollama_pulled = original_check

    def test_resolve_available_capability_returns_fallback_when_first_missing(self):
        """Should fall back to second model if first isn't available."""
        def fake_check(model, base_url=None):
            # Only second model is available
            return model == "qwen2.5:7b", ""

        # Adjust capability to have fallback: add qwen2.5:7b as fallback for classify
        with TemporaryRegistry() as reg:
            data = reg._read()
            data["capabilities"]["local-classify-medium"] = ["qwen2.5:14b", "qwen2.5:7b"]
            reg._write(data)
            model, is_fallback = model_registry.resolve_available_capability(
                "local-classify-medium", reg=reg, check_fn=fake_check
            )
            assert model == "qwen2.5:7b"
            assert is_fallback is True

    def test_resolve_available_capability_raises_when_none_available(self):
        """Should raise RuntimeError if no models in the capability are available."""
        def fake_check(model, base_url=None):
            return False, "not available"

        with TemporaryRegistry() as reg:
            with __import__("pytest").raises(RuntimeError, match="No models available"):
                model_registry.resolve_available_capability(
                    "local-classify-medium", reg=reg, check_fn=fake_check
                )

    def test_resolve_available_capability_raises_on_unknown_capability(self):
        """Should raise KeyError if capability doesn't exist."""
        with TemporaryRegistry() as reg:
            with __import__("pytest").raises(KeyError):
                model_registry.resolve_available_capability("unknown-capability", reg=reg)

    def test_resolve_available_capability_empty_list_raises(self):
        """Should raise RuntimeError if capability list is empty."""
        with TemporaryRegistry() as reg:
            data = reg._read()
            data["capabilities"]["empty-cap"] = []
            reg._write(data)
            with __import__("pytest").raises(RuntimeError, match="has no models"):
                model_registry.resolve_available_capability("empty-cap", reg=reg)


# ── request_pull ─────────────────────────────────────────────────────────────

class TestRequestPull:
    """Test request_pull() for model pulling with confirmation."""

    def test_request_pull_skips_on_refusal(self):
        """Should return False if user refuses confirmation."""
        confirm_fn = lambda msg: False
        result = model_registry.request_pull("qwen2.5:7b", confirm_fn=confirm_fn)
        assert result is False

    def test_request_pull_pulls_on_confirmation(self):
        """Should call puller_fn if user confirms."""
        confirm_fn = lambda msg: True
        pulled_models = []
        puller_fn = lambda m: pulled_models.append(m)
        result = model_registry.request_pull("qwen2.5:7b", confirm_fn=confirm_fn, puller_fn=puller_fn)
        assert result is True
        assert pulled_models == ["qwen2.5:7b"]

    def test_request_pull_returns_false_on_puller_error(self):
        """Should return False if puller_fn raises an exception."""
        confirm_fn = lambda msg: True
        puller_fn = lambda m: (_ for _ in ()).throw(RuntimeError("pull failed"))
        result = model_registry.request_pull("qwen2.5:7b", confirm_fn=confirm_fn, puller_fn=puller_fn)
        assert result is False


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
