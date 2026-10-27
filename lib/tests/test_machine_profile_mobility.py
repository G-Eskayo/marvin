"""Machine mobility class and label detection fixes (ADR 0062).

Tests 10-13: Detect mobility via battery presence (reliable signal),
falling back to model name as a secondary label source only.
This fixes the broken "MacBook" substring check that fails for
Apple Silicon's unified MacN,n numbering."""

import pytest
import machine_profile as mp


@pytest.fixture
def fake_mac_commands(monkeypatch):
    """Fixture to mock macOS commands for mobility detection."""
    def run_mock(cmd, **_):
        import subprocess
        result = subprocess.CompletedProcess(cmd, 0, "", "")

        # Handle battery detection: "pmset -g batt" output
        if cmd == ["pmset", "-g", "batt"]:
            # Return battery present (mobile device)
            return subprocess.CompletedProcess(cmd, 0,
                "Currently drawing from 'Battery Power'\n-InternalBattery-0\t100%; charged; 0:00 remaining\n", "")

        # Handle sysctl for model
        if cmd == ["sysctl", "-n", "hw.model"]:
            # This will be set by individual tests
            return subprocess.CompletedProcess(cmd, 0, "MacBookPro19,1\n", "")

        # Default: no battery (stationary device)
        if cmd == ["pmset", "-g", "batt"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")

        return result

    monkeypatch.setattr(mp, "_run", run_mock)
    return run_mock


def test_10_mobile_mac_detected_when_battery_present(monkeypatch):
    """Test that a Mac with a battery is detected as mobile."""
    def run_mock(cmd):
        if cmd == ["pmset", "-g", "batt"]:
            return "Currently drawing from 'Battery Power'\nInternalBattery-0\t100%; charged\n"
        if cmd == ["sysctl", "-n", "hw.model"]:
            return "MacBookAir13,1"
        return ""

    monkeypatch.setattr(mp, "_run", run_mock)
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")

    assert mp._mobility_class("MacBookAir13,1") == "mobile"


def test_11_stationary_mac_when_no_battery(monkeypatch):
    """Test that a Mac without battery is detected as stationary."""
    def run_mock(cmd):
        if cmd == ["pmset", "-g", "batt"]:
            # No battery output means stationary
            return ""
        if cmd == ["sysctl", "-n", "hw.model"]:
            return "Macmini9,1"
        return ""

    monkeypatch.setattr(mp, "_run", run_mock)
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")

    assert mp._mobility_class("Macmini9,1") == "stationary"


def test_12_label_uses_hardware_model_when_available(monkeypatch):
    """Test that _label() uses hw_model for naming instead of substring matching."""
    def run_mock(cmd):
        if cmd == ["pmset", "-g", "batt"]:
            return "Currently drawing from 'Battery Power'\nInternalBattery-0\t100%; charged\n"
        if cmd == ["sysctl", "-n", "hw.model"]:
            return "MacBookPro19,1"
        return ""

    monkeypatch.setattr(mp, "_run", run_mock)
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")

    # The new implementation should detect this as a MacBook Pro
    label = mp._label("MacBookPro19,1")
    assert label == "macbook-pro"


def test_13_mac_mini_labeled_correctly(monkeypatch):
    """Test that stationary Macs like Mac mini are labeled correctly."""
    def run_mock(cmd):
        if cmd == ["pmset", "-g", "batt"]:
            return ""  # No battery
        if cmd == ["sysctl", "-n", "hw.model"]:
            return "Macmini9,1"
        return ""

    monkeypatch.setattr(mp, "_run", run_mock)
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")

    label = mp._label("Macmini9,1")
    assert label == "mac-mini"


def test_mac_studio_labeled_correctly(monkeypatch):
    """Test that Mac Studio (stationary) is labeled correctly."""
    def run_mock(cmd):
        if cmd == ["pmset", "-g", "batt"]:
            return ""  # No battery
        if cmd == ["sysctl", "-n", "hw.model"]:
            return "Mac13,1"
        return ""

    monkeypatch.setattr(mp, "_run", run_mock)
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")

    label = mp._label("Mac13,1")
    assert label == "mac-studio"


def test_imac_labeled_correctly(monkeypatch):
    """Test that iMac (stationary) is labeled correctly."""
    def run_mock(cmd):
        if cmd == ["pmset", "-g", "batt"]:
            return ""  # No battery
        if cmd == ["sysctl", "-n", "hw.model"]:
            return "iMac21,1"
        return ""

    monkeypatch.setattr(mp, "_run", run_mock)
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")

    label = mp._label("iMac21,1")
    assert label == "imac"


def test_unknown_model_falls_back_to_generic(monkeypatch):
    """Test that unknown models get a generic label."""
    def run_mock(cmd):
        return ""

    monkeypatch.setattr(mp, "_run", run_mock)
    monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")

    label = mp._label("Unknown,1")
    assert label == "unknown-mac"
