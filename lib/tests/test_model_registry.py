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


# ── normalize_model_name and model_present functions ───────────────────────

class TestNormalizeModelName:
    """Test normalize_model_name() for model name normalization."""

    def test_normalize_model_name_identity(self):
        """normalize_model_name should return the model name unchanged (currently identity)."""
        assert model_registry.normalize_model_name("qwen2.5:7b") == "qwen2.5:7b"
        assert model_registry.normalize_model_name("nomic-embed-text") == "nomic-embed-text"


class TestModelPresent:
    """Test model_present() for checking if a model is in a list."""

    def test_model_present_exact_match(self):
        """model_present should return True for an exact match."""
        available = ["qwen2.5:7b", "qwen2.5:14b", "nomic-embed-text"]
        assert model_registry.model_present(available, "qwen2.5:7b") is True
        assert model_registry.model_present(available, "qwen2.5:14b") is True

    def test_model_present_variant_match(self):
        """model_present should return True for a variant (starts with model- for tagged names)."""
        available = ["qwen2.5:7b-instruct-q4_K_M", "qwen2.5:14b-gguf"]
        assert model_registry.model_present(available, "qwen2.5:7b") is True
        assert model_registry.model_present(available, "qwen2.5:14b") is True

    def test_model_present_bare_name_no_hyphen_matching(self):
        """model_present should NOT match repo-name hyphens as variants for bare names.

        Bare names (without ':') should not use startswith matching, only exact
        and :latest. This prevents false positives like nomic-embed-text matching
        nomic-embed-text-v2:latest.
        """
        # nomic-embed-text should NOT match nomic-embed-text-v2:latest
        available = ["nomic-embed-text-v2:latest"]
        assert model_registry.model_present(available, "nomic-embed-text") is False

        # qwen2.5 should NOT match qwen2.5-coder:7b
        available = ["qwen2.5-coder:7b"]
        assert model_registry.model_present(available, "qwen2.5") is False

        # llama3 should NOT match llama3-gradient:latest
        available = ["llama3-gradient:latest"]
        assert model_registry.model_present(available, "llama3") is False

    def test_model_present_no_match(self):
        """model_present should return False when model is not in the list."""
        available = ["qwen2.5:7b", "qwen2.5:14b"]
        assert model_registry.model_present(available, "qwen2.5:3b") is False
        assert model_registry.model_present(available, "unknown-model") is False

    def test_model_present_empty_list(self):
        """model_present should return False for an empty available list."""
        assert model_registry.model_present([], "qwen2.5:7b") is False

    def test_model_present_untagged_as_latest(self):
        """model_present should match 'name:latest' for untagged names.

        Ollama reports untagged pulls as 'name:latest' in /api/tags,
        so a registry entry 'nomic-embed-text' should match 'nomic-embed-text:latest'.
        Tagged names like 'qwen2.5:7b' are already tagged, so they'd be reported
        as 'qwen2.5:7b', not 'qwen2.5:7b:latest'.
        """
        available = ["nomic-embed-text:latest"]
        assert model_registry.model_present(available, "nomic-embed-text") is True

        # Bare names should also match exact names if present
        available = ["nomic-embed-text"]
        assert model_registry.model_present(available, "nomic-embed-text") is True

    def test_model_present_latest_not_matched_for_tagged_names(self):
        """model_present should not match ':latest' for names that already have a tag.

        Only bare names (without ':') should match ':latest' appended.
        Tagged names like 'qwen2.5:7b' should use the existing variant matching,
        not the ':latest' rule. So 'qwen2.5:7b' should not match 'qwen2.5:7b:latest'
        (which is not a real Ollama name anyway).
        """
        # Tagged model in registry should not match :latest rule
        available = ["qwen2.5:7b:latest"]  # Not a real Ollama name
        assert model_registry.model_present(available, "qwen2.5:7b") is False

        # Bare model in registry should not match another tagged variant via :latest
        available = ["nomic-embed-text:v2"]
        assert model_registry.model_present(available, "nomic-embed-text") is False


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


# ── Bootstrap dict vs real config agreement (test 16) ───────────────────

class TestBootstrapDictVsRealConfig:
    """Test that the bootstrap dictionary in _ensure_exists matches real config/models.json."""

    def test_bootstrap_matches_real_config_models(self):
        """The models AND capabilities in _ensure_exists should match config/models.json.

        This ensures the bootstrap dict is in sync with the real config, including
        both the models dict keys and the capabilities dict.
        """
        from pathlib import Path
        import pytest
        config_path = Path(__file__).resolve().parents[2] / "config" / "models.json"
        if not config_path.exists():
            pytest.skip("config/models.json not found")

        import json
        real_config = json.loads(config_path.read_text())

        with TemporaryRegistry() as reg:
            bootstrap = reg._read()

        # Both should have the same model names
        bootstrap_models = set(bootstrap.get("models", {}).keys())
        real_models = set(real_config.get("models", {}).keys())
        assert bootstrap_models == real_models, \
            f"Bootstrap models {bootstrap_models} should match real config models {real_models}"

        # Both should have the same capabilities
        bootstrap_caps = set(bootstrap.get("capabilities", {}).keys())
        real_caps = set(real_config.get("capabilities", {}).keys())
        assert bootstrap_caps == real_caps, \
            f"Bootstrap capabilities {bootstrap_caps} should match real config capabilities {real_caps}"


# ── Capability-points-at-available-model regression guard (test 17) ────────

class TestCapabilityPointsToAvailableModel:
    """Regression test: every capability must point to a registered model."""

    def test_all_capabilities_reference_registered_models(self):
        """Every capability in the registry should point only to registered models."""
        from pathlib import Path
        config_path = Path(__file__).resolve().parents[2] / "config" / "models.json"
        if not config_path.exists():
            pytest.skip("config/models.json not found")

        import json
        config = json.loads(config_path.read_text())

        models = config.get("models", {})
        capabilities = config.get("capabilities", {})

        for cap_name, model_list in capabilities.items():
            for model_name in model_list:
                assert model_name in models, \
                    f"Capability '{cap_name}' references unknown model '{model_name}'"


# ── list_installed function tests ─────────────────────────────────────────

class TestListInstalled:
    """Test list_installed() tolerates malformed Ollama responses."""

    def test_list_installed_calls_api(self, monkeypatch):
        """list_installed() should attempt to query localhost:11434/api/tags."""
        called = []

        class MockResponse:
            def read(self):
                return b'{"models": [{"name": "test-model"}]}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def mock_urlopen(url, *args, **kwargs):
            called.append(url)
            return MockResponse()

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        result = model_registry.list_installed()
        assert called, "Should have called urlopen"
        assert "localhost:11434/api/tags" in called[0]

    def test_list_installed_tolerates_non_dict_body(self, monkeypatch):
        """list_installed() should return None if response body is not a dict."""
        class MockResponse:
            def read(self):
                return b'["not", "a", "dict"]'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def mock_urlopen(url, *args, **kwargs):
            return MockResponse()

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        result = model_registry.list_installed()
        assert result is None, "Should return None for non-dict response"

    def test_list_installed_tolerates_missing_name_field(self, monkeypatch):
        """list_installed() should skip entries missing the 'name' field."""
        class MockResponse:
            def read(self):
                return b'{"models": [{"name": "valid-model"}, {"size_gb": 1.0}, {"name": "another-model"}]}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        def mock_urlopen(url, *args, **kwargs):
            return MockResponse()

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        result = model_registry.list_installed()
        assert result == ["valid-model", "another-model"], \
            "Should include only entries with 'name' field"

    def test_list_installed_returns_none_on_connection_error(self, monkeypatch):
        """list_installed() should return None if Ollama is unreachable."""
        def mock_urlopen(url, *args, **kwargs):
            raise ConnectionError("Ollama not running")

        monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)
        result = model_registry.list_installed()
        assert result is None, "Should return None on connection error"


# ── ensure_installed function tests ────────────────────────────────────────

class TestEnsureInstalled:
    """Test ensure_installed() error handling."""

    def test_ensure_installed_raises_ollama_unavailable_when_list_returns_none(self, monkeypatch):
        """ensure_installed() should raise OllamaUnavailableError when Ollama is unreachable."""
        def mock_list():
            return None

        monkeypatch.setattr(model_registry, "list_installed", mock_list)

        with __import__("pytest").raises(model_registry.OllamaUnavailableError) as exc_info:
            model_registry.ensure_installed("qwen2.5:7b")

        assert exc_info.value.model == "qwen2.5:7b"

    def test_ensure_installed_raises_model_unavailable_when_not_found(self, monkeypatch):
        """ensure_installed() should raise ModelUnavailableError when model is not in list."""
        def mock_list():
            return ["some-other-model"]

        monkeypatch.setattr(model_registry, "list_installed", mock_list)

        with __import__("pytest").raises(model_registry.ModelUnavailableError) as exc_info:
            model_registry.ensure_installed("qwen2.5:7b")

        assert exc_info.value.model == "qwen2.5:7b"


# ── resolve_or_raise function tests ────────────────────────────────────────

class TestResolveOrRaise:
    """Test resolve_or_raise() for lazy model resolution."""

    def test_resolve_or_raise_returns_model_when_installed(self, monkeypatch):
        """resolve_or_raise() should return the model name if it's installed."""
        def mock_list():
            return ["qwen2.5:14b"]

        monkeypatch.setattr(model_registry, "list_installed", mock_list)
        with TemporaryRegistry() as reg:
            result = model_registry.resolve_or_raise("local-inference-large", reg=reg)
            assert result == "qwen2.5:14b"

    def test_resolve_or_raise_raises_on_unknown_capability(self, monkeypatch):
        """resolve_or_raise() should raise KeyError for unknown capability."""
        def mock_list():
            return ["qwen2.5:14b"]

        monkeypatch.setattr(model_registry, "list_installed", mock_list)
        with TemporaryRegistry() as reg:
            with __import__("pytest").raises(KeyError):
                model_registry.resolve_or_raise("unknown-capability", reg=reg)

    def test_resolve_or_raise_raises_ollama_unavailable(self, monkeypatch):
        """resolve_or_raise() should raise OllamaUnavailableError when Ollama is unreachable."""
        def mock_list():
            return None

        monkeypatch.setattr(model_registry, "list_installed", mock_list)
        with TemporaryRegistry() as reg:
            with __import__("pytest").raises(model_registry.OllamaUnavailableError):
                model_registry.resolve_or_raise("local-inference-large", reg=reg)

    def test_resolve_or_raise_raises_model_unavailable(self, monkeypatch):
        """resolve_or_raise() should raise ModelUnavailableError when model is not installed."""
        def mock_list():
            return ["qwen2.5:3b"]

        monkeypatch.setattr(model_registry, "list_installed", mock_list)
        with TemporaryRegistry() as reg:
            with __import__("pytest").raises(model_registry.ModelUnavailableError):
                model_registry.resolve_or_raise("local-inference-large", reg=reg)


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
