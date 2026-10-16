"""Mac-only checks and the history copy go to the Macs only (ADR 0069). mac-mini-2012 runs Linux and holds
untrusted code, so it gets neither launchd/dashboard checks (false alarms) nor a copy of MARVIN's history."""
import pytest

import machine_profile as mp

REGISTRY = {
    "mac-mini-1": {"tailscale_hostname": "gils-mac-mini"},
    "macbook-pro-1": {"tailscale_hostname": "laptop", "os": "macos"},
    "mac-mini-2012": {"tailscale_hostname": "mac-mini-2012", "os": "linux"},
}


@pytest.fixture
def registry(monkeypatch):
    monkeypatch.setattr(mp, "_load_registry", lambda: REGISTRY)
    monkeypatch.setattr(mp, "registry_id", lambda: "mac-mini-1")


def test_remote_macs_leaves_out_linux_and_treats_a_missing_os_as_a_mac(registry):
    assert set(mp.remote_macs()) == {"macbook-pro-1"}
    assert set(mp.remote_devices()) == {"macbook-pro-1", "mac-mini-2012"}


def test_an_unknown_os_is_not_treated_as_a_mac(registry, monkeypatch):
    monkeypatch.setattr(mp, "_load_registry", lambda: {**REGISTRY, "odd": {"tailscale_hostname": "odd", "os": "windows"}})
    assert "odd" not in mp.remote_macs()


def test_machine_state_checks_never_ssh_into_the_linux_box(registry):
    import health_checks as hc
    hosts = []
    up = {"machine:macbook-pro-1": "green", "machine:mac-mini-2012": "green"}
    hc.check_machine_state_everywhere(up, runner=lambda target, *a, **k: hosts.append(target) or "")
    assert "laptop" in hosts   # proves the check really reaches remote Macs
    assert "mac-mini-2012" not in hosts


def test_history_is_never_shipped_to_the_linux_box(registry, monkeypatch, tmp_path):
    import history_store as hs
    shipped = []
    monkeypatch.setattr(hs, "ship_to", lambda conn, host, **k: shipped.append(host) or {"skipped": "test"})
    monkeypatch.setattr(hs, "run", lambda streams=None, db_path=None: {})
    monkeypatch.setattr(hs, "require_home", lambda: None)
    monkeypatch.setattr(hs, "connect", lambda db_path=None: __import__("sqlite3").connect(":memory:"))
    hs.main()
    assert "mac-mini-2012" not in shipped
    assert "laptop" in shipped
