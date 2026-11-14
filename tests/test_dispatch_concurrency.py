"""Tests for lib/dispatch_concurrency.py, especially can_start_another with cold_local_gb."""
from unittest.mock import MagicMock
import pytest
from pathlib import Path
import tempfile

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import dispatch_concurrency


class TestCanStartAnotherWithCold:
    """Test can_start_another with the cold_local_gb parameter."""

    def test_can_start_another_disk_low_with_cold_hint(self):
        """When disk is low, hint includes cold store size."""
        settings = dispatch_concurrency.load()  # defaults

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: 5,  # 5 GB free, below 15 GB default
            github_budget_pct=lambda: 50,
            breaker_tripped=lambda: [],
            missing_tools=lambda m: [],
            cold_local_gb=lambda: 2.5  # 2.5 GB in cold store locally
        )

        assert not ok
        assert "disk" in why
        assert "cold store" in why
        assert "2.5" in why

    def test_can_start_another_disk_ok_no_cold(self):
        """When disk is OK, no cold hint is added."""
        settings = dispatch_concurrency.load()

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: 20,  # 20 GB free, above 15 GB default
            github_budget_pct=lambda: 50,
            breaker_tripped=lambda: [],
            missing_tools=lambda m: [],
            cold_local_gb=lambda: 0
        )

        assert ok

    def test_can_start_another_no_cold_reader(self):
        """When cold_local_gb is None, no hint is added even if disk is low."""
        settings = dispatch_concurrency.load()

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: 5,  # 5 GB free, below 15 GB default
            github_budget_pct=lambda: 50,
            breaker_tripped=lambda: [],
            missing_tools=lambda m: [],
            cold_local_gb=None
        )

        assert not ok
        assert "cold store" not in why

    def test_can_start_another_cold_reader_raises(self):
        """When cold_local_gb raises an exception, it's caught safely."""
        settings = dispatch_concurrency.load()

        def failing_cold():
            raise Exception("some error")

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: 5,
            github_budget_pct=lambda: 50,
            breaker_tripped=lambda: [],
            missing_tools=lambda m: [],
            cold_local_gb=failing_cold
        )

        assert not ok
        assert "disk" in why
        assert "cold" not in why  # hint not added because it raised

    def test_can_start_another_slots_full(self):
        """Slots-full case is unaffected by cold_local_gb."""
        settings = dispatch_concurrency.load()
        settings["parallel"] = True
        settings["machine_slots"]["mac1"] = 1

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 1,  # 1 slot in use, limit is 1
            disk_free_gb=lambda m: 50,
            github_budget_pct=lambda: 50,
            breaker_tripped=lambda: [],
            missing_tools=lambda m: [],
            cold_local_gb=lambda: 0
        )

        assert not ok
        assert "full" in why
        assert "cold" not in why

    def test_can_start_another_parallel_off(self):
        """With parallel off, guards are skipped including cold checks."""
        settings = dispatch_concurrency.load()
        settings["parallel"] = False

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: 1,  # 1 GB free, would fail with parallel on
            github_budget_pct=lambda: 1,
            breaker_tripped=lambda: [],
            missing_tools=lambda m: [],
            cold_local_gb=lambda: 100  # cold store wouldn't help anyway
        )

        assert ok
        assert why is None


class TestCanStartAnotherRegressions:
    """Test that existing can_start_another behavior is preserved."""

    def test_disk_free_gb_none_no_block(self):
        """A None disk reading doesn't block (guard unreadable)."""
        settings = dispatch_concurrency.load()

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: None,  # unreadable
            github_budget_pct=lambda: 50,
            breaker_tripped=lambda: [],
            missing_tools=lambda m: []
        )

        assert ok
        assert why is None

    def test_github_budget_low(self):
        """Low GitHub budget blocks start."""
        settings = dispatch_concurrency.load()

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: 20,
            github_budget_pct=lambda: 10,  # 10%, below 20% default
            breaker_tripped=lambda: [],
            missing_tools=lambda m: []
        )

        assert not ok
        assert "GitHub" in why

    def test_circuit_breaker_tripped(self):
        """A tripped circuit breaker blocks start."""
        settings = dispatch_concurrency.load()

        tripped = [{"project": "org/repo", "signature": "some-error"}]

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: 20,
            github_budget_pct=lambda: 50,
            breaker_tripped=lambda: tripped,
            missing_tools=lambda m: []
        )

        assert not ok
        assert "circuit breaker" in why

    def test_missing_tools(self):
        """Missing tools block start."""
        settings = dispatch_concurrency.load()

        ok, why = dispatch_concurrency.can_start_another(
            "mac1", settings,
            slots_in_use=lambda m: 0,
            disk_free_gb=lambda m: 20,
            github_budget_pct=lambda: 50,
            breaker_tripped=lambda: [],
            missing_tools=lambda m: ["python3-dev", "libffi-dev"]
        )

        assert not ok
        assert "lacks tools" in why


class TestSafeGuardAccess:
    """Test that _safe wrapper prevents guard exceptions from blocking."""

    def test_safe_reader_exception(self):
        """Exceptions in reader functions don't block."""
        def raising_reader(*args):
            raise ValueError("disk error")

        result = dispatch_concurrency._safe(raising_reader, "arg1")
        assert result is None

    def test_safe_reader_success(self):
        """Successful readers return their value."""
        def good_reader(*args):
            return 42

        result = dispatch_concurrency._safe(good_reader, "arg1")
        assert result == 42


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
