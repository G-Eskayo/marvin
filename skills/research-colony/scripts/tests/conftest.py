"""Test isolation for skills/research-colony/scripts/tests/."""
import pytest


@pytest.fixture(autouse=True)
def _isolate_machine_role(monkeypatch):
    # brief_fallback.should_run() resolves this machine's role via machine_profile.registry_id(),
    # which reads the real ~/.claude registry and, off the primary, can SSH a real peer.
    # Default every test to primary (the old, gate-less behavior); a test opts into the
    # standby path by overriding this or by passing device_id explicitly.
    import machine_profile
    monkeypatch.setattr(machine_profile, "registry_id", lambda: "mac-mini-test")
