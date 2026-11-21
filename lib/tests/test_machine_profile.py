"""Tests for machine_profile.is_calibrated() (ADR #835)."""
import json
import pytest
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import machine_profile as mp  # noqa: E402


def test_is_calibrated_defaults_true_when_field_absent(tmp_path, monkeypatch):
    """A device with no 'calibrated' field (today's registry shape) defaults to True."""
    network = tmp_path / "marvin-network.json"
    network.write_text(json.dumps({
        "devices": {
            "mac-mini-1": {"hardware_uuid": "ABC123", "tailscale_hostname": "mini.local"}
        }
    }))
    monkeypatch.setattr(mp, "NETWORK_PATH", network)
    assert mp.is_calibrated("mac-mini-1") is True


def test_is_calibrated_true_when_explicitly_set(tmp_path, monkeypatch):
    """A device with 'calibrated: true' returns True."""
    network = tmp_path / "marvin-network.json"
    network.write_text(json.dumps({
        "devices": {
            "mac-mini-1": {"calibrated": True}
        }
    }))
    monkeypatch.setattr(mp, "NETWORK_PATH", network)
    assert mp.is_calibrated("mac-mini-1") is True


def test_is_calibrated_false_when_explicitly_disabled(tmp_path, monkeypatch):
    """A device with 'calibrated: false' returns False."""
    network = tmp_path / "marvin-network.json"
    network.write_text(json.dumps({
        "devices": {
            "mac-mini-1": {"calibrated": False}
        }
    }))
    monkeypatch.setattr(mp, "NETWORK_PATH", network)
    assert mp.is_calibrated("mac-mini-1") is False


def test_is_calibrated_malformed_value_defaults_true(tmp_path, monkeypatch):
    """A string 'false' (not boolean) is truthy in Python, so it counts as calibrated."""
    network = tmp_path / "marvin-network.json"
    network.write_text(json.dumps({
        "devices": {
            "mac-mini-1": {"calibrated": "false"}  # string, not boolean
        }
    }))
    monkeypatch.setattr(mp, "NETWORK_PATH", network)
    # Only the literal boolean False disables it
    assert mp.is_calibrated("mac-mini-1") is True


def test_is_calibrated_unreadable_registry_defaults_true(tmp_path, monkeypatch):
    """Corrupt or missing marvin-network.json: treat as uncalibrated."""
    network = tmp_path / "marvin-network.json"
    # Don't create the file - _load_registry() returns {}
    monkeypatch.setattr(mp, "NETWORK_PATH", network)
    assert mp.is_calibrated("unknown-device") is True  # fail-open


def test_is_calibrated_unregistered_device_defaults_true(tmp_path, monkeypatch):
    """A device not in the registry at all defaults to True (fail-open)."""
    network = tmp_path / "marvin-network.json"
    network.write_text(json.dumps({
        "devices": {
            "mac-mini-1": {"calibrated": False}
        }
    }))
    monkeypatch.setattr(mp, "NETWORK_PATH", network)
    # unregistered-device is not in devices
    assert mp.is_calibrated("unregistered-device") is True
