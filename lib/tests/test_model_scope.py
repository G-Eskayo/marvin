"""Tests for model_scope.py parsing and matching. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_model_scope.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import model_scope  # noqa: E402


# ── parse_scope ────────────────────────────────────────────────────────────

class TestParseScope:
    def test_all_string_returns_empty_set(self):
        assert model_scope.parse_scope("all") == set()

    def test_empty_string_returns_empty_set(self):
        assert model_scope.parse_scope("") == set()

    def test_whitespace_only_returns_empty_set(self):
        assert model_scope.parse_scope("  ") == set()

    def test_single_tier_returns_set_with_that_tier(self):
        assert model_scope.parse_scope("haiku") == {"haiku"}
        assert model_scope.parse_scope("sonnet") == {"sonnet"}
        assert model_scope.parse_scope("opus") == {"opus"}

    def test_comma_separated_tiers_returns_all_valid_tiers(self):
        assert model_scope.parse_scope("haiku,sonnet") == {"haiku", "sonnet"}
        assert model_scope.parse_scope("sonnet,opus") == {"sonnet", "opus"}
        assert model_scope.parse_scope("haiku,sonnet,opus") == {"haiku", "sonnet", "opus"}

    def test_comma_separated_with_whitespace(self):
        assert model_scope.parse_scope("haiku, sonnet") == {"haiku", "sonnet"}
        assert model_scope.parse_scope(" haiku , sonnet ") == {"haiku", "sonnet"}

    def test_plus_suffix_returns_tier_and_above(self):
        assert model_scope.parse_scope("haiku+") == {"haiku", "sonnet", "opus"}
        assert model_scope.parse_scope("sonnet+") == {"sonnet", "opus"}
        assert model_scope.parse_scope("opus+") == {"opus"}

    def test_plus_suffix_with_whitespace(self):
        assert model_scope.parse_scope(" haiku+") == {"haiku", "sonnet", "opus"}
        assert model_scope.parse_scope("sonnet+ ") == {"sonnet", "opus"}

    def test_case_insensitive(self):
        assert model_scope.parse_scope("HAIKU") == {"haiku"}
        assert model_scope.parse_scope("Sonnet,OPUS") == {"sonnet", "opus"}
        assert model_scope.parse_scope("OPUS+") == {"opus"}

    def test_unknown_tier_returns_empty_set(self):
        assert model_scope.parse_scope("unknown") == set()

    def test_mixed_known_and_unknown_returns_only_known(self):
        assert model_scope.parse_scope("haiku,unknown") == {"haiku"}
        assert model_scope.parse_scope("unknown,sonnet") == {"sonnet"}

    def test_malformed_plus_returns_empty_set(self):
        assert model_scope.parse_scope("haiku++") == set()
        assert model_scope.parse_scope("+haiku") == set()
        assert model_scope.parse_scope("haiku+sonnet") == set()


# ── is_allowed ─────────────────────────────────────────────────────────────

class TestIsAllowed:
    def test_empty_scope_allows_all_tiers(self):
        assert model_scope.is_allowed("", "haiku") is True
        assert model_scope.is_allowed("", "sonnet") is True
        assert model_scope.is_allowed("", "opus") is True

    def test_all_scope_allows_all_tiers(self):
        assert model_scope.is_allowed("all", "haiku") is True
        assert model_scope.is_allowed("all", "sonnet") is True
        assert model_scope.is_allowed("all", "opus") is True

    def test_single_tier_only_allows_that_tier(self):
        assert model_scope.is_allowed("haiku", "haiku") is True
        assert model_scope.is_allowed("haiku", "sonnet") is False
        assert model_scope.is_allowed("sonnet", "haiku") is False
        assert model_scope.is_allowed("sonnet", "sonnet") is True

    def test_comma_list_allows_listed_tiers(self):
        assert model_scope.is_allowed("haiku,sonnet", "haiku") is True
        assert model_scope.is_allowed("haiku,sonnet", "sonnet") is True
        assert model_scope.is_allowed("haiku,sonnet", "opus") is False

    def test_plus_suffix_allows_tier_and_above(self):
        assert model_scope.is_allowed("haiku+", "haiku") is True
        assert model_scope.is_allowed("haiku+", "sonnet") is True
        assert model_scope.is_allowed("haiku+", "opus") is True

        assert model_scope.is_allowed("sonnet+", "haiku") is False
        assert model_scope.is_allowed("sonnet+", "sonnet") is True
        assert model_scope.is_allowed("sonnet+", "opus") is True

        assert model_scope.is_allowed("opus+", "haiku") is False
        assert model_scope.is_allowed("opus+", "sonnet") is False
        assert model_scope.is_allowed("opus+", "opus") is True

    def test_unknown_tier_returns_true_fail_open(self):
        assert model_scope.is_allowed("haiku", "unknown") is True
        assert model_scope.is_allowed("sonnet", "fable") is True

    def test_malformed_scope_fails_open(self):
        assert model_scope.is_allowed("invalid", "haiku") is True
        assert model_scope.is_allowed("haiku++", "sonnet") is True
