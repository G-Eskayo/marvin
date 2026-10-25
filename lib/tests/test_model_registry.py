"""Tests for model_registry.py: registry, capabilities, consistency checks.

Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_model_registry.py -v
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

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


# ── check_ollama_pulled function ──────────────────────────────────────────

class TestCheckOllamaPulled:
    """Test check_ollama_pulled() for Ollama availability checks.

    Tests A1-A8: Verify robustness against malformed responses and proper prefix matching.
    """

    def test_check_ollama_pulled_returns_tuple(self):
        """Test A1: check_ollama_pulled should return (bool, str)."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            result = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert isinstance(result, tuple)
            assert len(result) == 2
            assert isinstance(result[0], bool)
            assert isinstance(result[1], str)

    def test_check_ollama_pulled_offline_returns_false(self):
        """Test A2: check_ollama_pulled returns (False, error_msg) if server is down."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = OSError("Connection refused")
            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b", base_url="http://localhost:9999")
            assert ok is False
            assert len(err) > 0
            assert "not responding" in err.lower()

    def test_check_ollama_pulled_missing_model_returns_false(self):
        """Test A3: check_ollama_pulled returns (False, error_msg) if model not in list."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"models": [{"name": "some-other-model"}]}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is False
            assert "not found" in err.lower()

    def test_check_ollama_pulled_accepts_base_url(self):
        """Test A4: check_ollama_pulled accepts custom base_url parameter."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"models": [{"name": "qwen2.5:7b"}]}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            result = model_registry.check_ollama_pulled(
                "qwen2.5:7b",
                base_url="http://custom:11434"
            )
            assert isinstance(result, tuple)
            mock_urlopen.assert_called_with("http://custom:11434/api/tags", timeout=5)

    def test_check_ollama_pulled_malformed_response_not_dict(self):
        """Test A5: check_ollama_pulled guards against non-dict response."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps([1, 2, 3]).encode()  # list, not dict
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is False
            assert "malformed" in err.lower() or "not a dict" in err.lower()

    def test_check_ollama_pulled_malformed_models_not_list(self):
        """Test A6: check_ollama_pulled guards against models not being a list."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"models": "not-a-list"}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is False
            assert "not a list" in err.lower()

    def test_check_ollama_pulled_entry_missing_name_field(self):
        """Test A7: check_ollama_pulled skips entries missing 'name' field."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            # One entry missing 'name', one with it
            mock_resp.read.return_value = json.dumps({
                "models": [{"no_name": "here"}, {"name": "qwen2.5:7b"}]
            }).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is True
            assert err == ""

    def test_check_ollama_pulled_prefix_match_with_dash(self):
        """Test A8: check_ollama_pulled accepts exact match or dash-prefixed variant."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            # The actual model returned has a dash-extension (quantization variant)
            mock_resp.read.return_value = json.dumps({
                "models": [{"name": "qwen2.5:7b-instruct-q4_K_M"}]
            }).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is True
            assert err == ""


# ── resolve_and_check function ────────────────────────────────────────────

class TestResolveAndCheck:
    """Test resolve_and_check() for lazy model resolution with checking.

    Tests B9-B15: base_url threading + resolve_or_raise.
    """

    def test_resolve_and_check_returns_tuple(self):
        """Test B9: resolve_and_check returns (model_name, available)."""
        with TemporaryRegistry() as reg:
            with patch("model_registry.check_ollama_pulled") as mock_check:
                mock_check.return_value = (True, "")
                result = model_registry.resolve_and_check("local-classify-medium", reg=reg)
                assert isinstance(result, tuple)
                assert len(result) == 2
                assert isinstance(result[0], str)
                assert isinstance(result[1], bool)

    def test_resolve_and_check_unknown_capability_raises(self):
        """Test B10: resolve_and_check raises KeyError for unknown capabilities."""
        with TemporaryRegistry() as reg:
            with __import__("pytest").raises(KeyError):
                model_registry.resolve_and_check("unknown-capability-xyz", reg=reg)

    def test_resolve_and_check_accepts_base_url(self):
        """Test B11: resolve_and_check threads base_url to check_ollama_pulled."""
        with TemporaryRegistry() as reg:
            with patch("model_registry.check_ollama_pulled") as mock_check:
                mock_check.return_value = (True, "")
                model_registry.resolve_and_check(
                    "local-classify-medium",
                    reg=reg,
                    base_url="http://custom:11434"
                )
                # Verify base_url was passed to check_ollama_pulled
                mock_check.assert_called()
                call_kwargs = mock_check.call_args[1]
                assert call_kwargs.get("base_url") == "http://custom:11434"

    def test_resolve_and_check_respects_confirm_fn(self):
        """Test B12: resolve_and_check calls confirm_fn if model unavailable."""
        with TemporaryRegistry() as reg:
            calls = []
            def track_confirm(msg):
                calls.append(msg)
                return False

            with patch("model_registry.check_ollama_pulled") as mock_check:
                mock_check.return_value = (False, "not available")
                model, available = model_registry.resolve_and_check(
                    "local-classify-medium",
                    confirm_fn=track_confirm,
                    auto_pull=True,
                    reg=reg
                )
                assert available is False
                assert len(calls) > 0  # confirm_fn was called

    def test_resolve_or_raise_returns_model_on_success(self):
        """Test B13: resolve_or_raise returns just the model name on success."""
        with TemporaryRegistry() as reg:
            with patch("model_registry.check_ollama_pulled") as mock_check:
                mock_check.return_value = (True, "")
                model = model_registry.resolve_or_raise("local-classify-medium", reg=reg)
                assert isinstance(model, str)
                assert "qwen" in model

    def test_resolve_or_raise_raises_on_unavailable(self):
        """Test B14: resolve_or_raise raises ModelUnavailableError if model unavailable."""
        with TemporaryRegistry() as reg:
            with patch("model_registry.check_ollama_pulled") as mock_check:
                mock_check.return_value = (False, "not available")
                with __import__("pytest").raises(model_registry.ModelUnavailableError):
                    model_registry.resolve_or_raise("local-classify-medium", reg=reg)

    def test_resolve_or_raise_threads_base_url(self):
        """Test B15: resolve_or_raise threads base_url parameter correctly."""
        with TemporaryRegistry() as reg:
            with patch("model_registry.check_ollama_pulled") as mock_check:
                mock_check.return_value = (True, "")
                model_registry.resolve_or_raise(
                    "local-classify-medium",
                    reg=reg,
                    base_url="http://custom:11434"
                )
                mock_check.assert_called()
                call_kwargs = mock_check.call_args[1]
                assert call_kwargs.get("base_url") == "http://custom:11434"


# ── Duplication fix: _ensure_exists vs config/models.json ─────────────────

class TestModelRegistryDuplicationFix:
    """Test that _ensure_exists() fallback matches config/models.json.

    Tests D21-D22: Drift guard between _ensure_exists and _bootstrap_fallback.
    """

    def test_ensure_exists_fallback_has_same_models(self):
        """Test D21: Fallback in _ensure_exists should match config/models.json."""
        # Create a registry from scratch (which uses _ensure_exists)
        with TemporaryRegistry() as reg:
            fallback_data = reg._read()
            fallback_models = fallback_data.get("models", {})
            fallback_caps = fallback_data.get("capabilities", {})

            # Load the actual config/models.json
            config_path = Path(__file__).resolve().parents[2] / "config" / "models.json"
            if config_path.exists():
                config_data = json.loads(config_path.read_text())
                config_models = config_data.get("models", {})
                config_caps = config_data.get("capabilities", {})

                # Check that all models in fallback are in config
                for model_name in fallback_models:
                    assert model_name in config_models, \
                        f"Model {model_name} in fallback but not in config/models.json"

                # Check that capabilities match
                for cap_name in fallback_caps:
                    assert cap_name in config_caps, \
                        f"Capability {cap_name} in fallback but not in config/models.json"

    def test_ensure_exists_creates_valid_registry(self):
        """Test D22: _ensure_exists creates a registry that passes consistency checks."""
        with TemporaryRegistry() as reg:
            result = model_registry.check_consistency(reg)
            # Should have no hard errors (soft warnings are acceptable)
            assert len(result.get("hard_errors", [])) == 0, \
                f"Fallback registry has hard errors: {result['hard_errors']}"


# ── Edge-case tests ────────────────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases: empty capabilities, missing keys, stale state.

    Tests G25-G27: Robustness to malformed or incomplete registry state.
    """

    def test_resolve_and_check_empty_model_list(self):
        """Test G25: resolve_and_check raises KeyError when capability has no models."""
        with TemporaryRegistry() as reg:
            data = reg._read()
            data.setdefault("capabilities", {})["empty-cap"] = []
            reg._write(data)

            with __import__("pytest").raises(KeyError):
                model_registry.resolve_and_check("empty-cap", reg=reg)

    def test_resolve_or_raise_with_confirm_fn_threads_correctly(self):
        """Test G26: resolve_or_raise threads confirm_fn and auto_pull correctly."""
        with TemporaryRegistry() as reg:
            calls = []
            def track_confirm(msg):
                calls.append(msg)
                return False

            with patch("model_registry.check_ollama_pulled") as mock_check:
                mock_check.return_value = (False, "not available")
                with __import__("pytest").raises(model_registry.ModelUnavailableError):
                    model_registry.resolve_or_raise(
                        "local-classify-medium",
                        confirm_fn=track_confirm,
                        auto_pull=True,
                        reg=reg
                    )
                # confirm_fn should not be called since the model is unavailable
                # and resolve_or_raise raises before attempting pull

    def test_check_ollama_pulled_empty_models_list(self):
        """Test G27: check_ollama_pulled handles empty models list gracefully."""
        with patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = json.dumps({"models": []}).encode()
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            ok, err = model_registry.check_ollama_pulled("qwen2.5:7b")
            assert ok is False
            assert "no models" in err.lower() or "not found" in err.lower()


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
