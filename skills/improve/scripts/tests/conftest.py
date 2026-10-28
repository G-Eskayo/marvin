"""Isolation fixtures for improve/scripts tests."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_machine_role_primary_default(monkeypatch):
    # Pre-existing tests in test_daily_digest.py expect to take the primary branch
    # deterministically (without mocking brief_fallback), so this fixture provides
    # a primary-shaped registry_id by default. New tests that cover fallback-specific
    # paths (should_run=False logic) override this locally, same as test_brief_fallback.py
    # already does for scanner_role.is_primary.
    import machine_profile
    monkeypatch.setattr(machine_profile, "registry_id", lambda: "mac-mini-1")
