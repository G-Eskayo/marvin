"""Tests for retrieve.py model-scope filtering. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_retrieve_model_scope.py -v
"""
import sys
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

RETRIEVE_SCRIPTS = Path(__file__).resolve().parents[2] / "skills" / "self-improve" / "scripts"
sys.path.insert(0, str(RETRIEVE_SCRIPTS))

import retrieve  # noqa: E402


class TestFilterByModelScope:
    def test_filter_by_model_scope_with_no_model_returns_all_results(self):
        """When model is None, no filtering occurs."""
        results = [
            {"path": "~/skill1", "model_scope": "sonnet+"},
            {"path": "~/skill2", "model_scope": ""},
        ]
        filtered = retrieve._filter_by_model_scope(results, None)
        assert filtered == results

    def test_filter_by_model_scope_with_empty_scope_allows_all_models(self):
        """Results with empty model_scope are always allowed."""
        results = [
            {"path": "~/skill1", "model_scope": ""},
            {"path": "~/skill2", "model_scope": ""},
        ]
        filtered = retrieve._filter_by_model_scope(results, "haiku")
        assert len(filtered) == 2

    def test_filter_by_model_scope_excludes_restricted_skills_on_haiku(self):
        """Haiku model excludes sonnet+ and opus-only skills."""
        results = [
            {"path": "~/skill1", "model_scope": "haiku,sonnet,opus"},
            {"path": "~/skill2", "model_scope": "sonnet+"},
            {"path": "~/skill3", "model_scope": "opus"},
            {"path": "~/skill4", "model_scope": ""},
        ]
        filtered = retrieve._filter_by_model_scope(results, "haiku")
        assert len(filtered) == 2
        assert filtered[0]["path"] == "~/skill1"
        assert filtered[1]["path"] == "~/skill4"

    def test_filter_by_model_scope_allows_correct_tier_and_above(self):
        """Sonnet model allows sonnet+ but excludes opus-only."""
        results = [
            {"path": "~/skill1", "model_scope": "haiku+"},
            {"path": "~/skill2", "model_scope": "sonnet+"},
            {"path": "~/skill3", "model_scope": "opus"},
            {"path": "~/skill4", "model_scope": ""},
        ]
        filtered = retrieve._filter_by_model_scope(results, "sonnet")
        assert len(filtered) == 3
        paths = [r["path"] for r in filtered]
        assert "~/skill1" in paths
        assert "~/skill2" in paths
        assert "~/skill4" in paths
        assert "~/skill3" not in paths

    def test_filter_by_model_scope_opus_allows_tier_and_above(self):
        """Opus model allows opus-only, opus+, and unrestricted skills."""
        results = [
            {"path": "~/skill1", "model_scope": "haiku"},  # excluded: haiku-only
            {"path": "~/skill2", "model_scope": "sonnet"},  # excluded: sonnet-only
            {"path": "~/skill3", "model_scope": "opus"},  # included: opus-only
            {"path": "~/skill4", "model_scope": "haiku+"},  # included: haiku+ (includes opus)
            {"path": "~/skill5", "model_scope": "opus+"},  # included: opus+
            {"path": "~/skill6", "model_scope": ""},  # included: unrestricted
        ]
        filtered = retrieve._filter_by_model_scope(results, "opus")
        assert len(filtered) == 4
        paths = [r["path"] for r in filtered]
        assert "~/skill3" in paths
        assert "~/skill4" in paths
        assert "~/skill5" in paths
        assert "~/skill6" in paths


class TestTagFallback:
    def test_tag_fallback_without_model_returns_unfiltered(self, tmp_path):
        """tag_fallback without model parameter should return all matching results."""
        manifest = {
            "index": [
                {
                    "name": "skill1",
                    "path": "~/skill1",
                    "tags": ["type:skill", "intent:test"],
                    "model-scope": "sonnet+"
                },
                {
                    "name": "skill2",
                    "path": "~/skill2",
                    "tags": ["type:skill", "intent:debug"],
                }
            ]
        }

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        with patch.object(retrieve, "MANIFEST_PATH", manifest_path):
            results = retrieve.tag_fallback("skill", model=None)
            assert len(results) == 2

    def test_tag_fallback_with_model_filters_results(self, tmp_path):
        """tag_fallback with model parameter should filter by model-scope."""
        manifest = {
            "index": [
                {
                    "name": "skill1",
                    "path": "~/skill1",
                    "tags": ["type:skill", "intent:test"],
                    "model-scope": "sonnet+"
                },
                {
                    "name": "skill2",
                    "path": "~/skill2",
                    "tags": ["type:skill", "intent:test"],
                }
            ]
        }

        manifest_path = tmp_path / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))

        with patch.object(retrieve, "MANIFEST_PATH", manifest_path):
            results = retrieve.tag_fallback("skill", model="haiku")
            assert len(results) == 1
            assert results[0]["path"] == "~/skill2"
