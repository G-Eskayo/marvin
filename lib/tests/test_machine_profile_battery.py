"""Machine profile battery detection and label inference (plan §1).

Tests for _has_battery(), _mobility_class() signature change, and _label() logic
using battery status and model substring matching."""

import pytest

import machine_profile as mp


class TestHasBattery:
    """Tests 1-2: _has_battery() detects battery presence from pmset output."""

    def test_has_battery_when_present(self, monkeypatch):
        """Test 1: _has_battery() returns True when InternalBattery is in pmset output."""
        def fake_run(cmd):
            if cmd == ["pmset", "-g", "batt"]:
                return "InternalBattery-0 (Primary): 75% charged; discharging\n"
            return ""

        monkeypatch.setattr(mp, "_run", fake_run)
        assert mp._has_battery() is True

    def test_has_battery_when_absent(self, monkeypatch):
        """Test 2: _has_battery() returns False when no InternalBattery."""
        def fake_run(cmd):
            if cmd == ["pmset", "-g", "batt"]:
                return "No battery attached.\n"
            return ""

        monkeypatch.setattr(mp, "_run", fake_run)
        assert mp._has_battery() is False


class TestMobilityClass:
    """Test 3: _mobility_class() takes boolean has_battery instead of hw_model."""

    def test_mobility_class_from_battery(self, monkeypatch):
        """Test 3: _mobility_class(True) returns 'mobile', False returns 'stationary'."""
        assert mp._mobility_class(True) == "mobile"
        assert mp._mobility_class(False) == "stationary"


class TestLabel:
    """Tests 4-5: _label() uses mobility class and model substring for precise labeling."""

    def test_label_macbook_pro_when_mobile_with_pro_model(self):
        """Test 4a: MacBookPro + mobile -> 'macbook-pro'."""
        assert mp._label(True, "MacBookPro16,2") == "macbook-pro"

    def test_label_macbook_air_when_mobile_with_air_model(self):
        """Test 4b: MacBookAir + mobile -> 'macbook-air'."""
        assert mp._label(True, "MacBookAir13,1") == "macbook-air"

    def test_label_generic_macbook_when_mobile_with_plain_macbook(self):
        """Test 4c: Plain MacBook + mobile -> 'macbook'."""
        assert mp._label(True, "MacBook10,1") == "macbook"

    def test_label_generic_macbook_when_mobile_but_no_known_model(self, monkeypatch):
        """Test 4d: mobile=True but hw_model unknown, falls back to system_profiler."""
        # hw_model has no recognizable pattern, so _get_model_name() is called
        def fake_run(cmd):
            if cmd == ["system_profiler", "SPHardwareDataType"]:
                return 'Model Name: MacBook (12-inch, 2017)\n'
            return ""

        monkeypatch.setattr(mp, "_run", fake_run)
        assert mp._label(True, "MacBook7,1") == "macbook"

    def test_label_mac_mini_when_stationary(self):
        """Test 5a: stationary + any model -> 'mac-mini'."""
        assert mp._label(False, "Macmini9,1") == "mac-mini"
        assert mp._label(False, "UnknownModel") == "mac-mini"


class TestGetModelName:
    """Tests for _get_model_name() — parsing system_profiler output."""

    def test_get_model_name_extracts_from_system_profiler(self, monkeypatch):
        """_get_model_name() parses system_profiler SPHardwareDataType output."""
        def fake_run(cmd):
            if cmd == ["system_profiler", "SPHardwareDataType"]:
                return """Hardware:
    Model Name: MacBook Pro (14-inch, 2023, M3 Max)
    Model Identifier: MacBookPro18,1"""
            return ""

        monkeypatch.setattr(mp, "_run", fake_run)
        assert mp._get_model_name() == "MacBook Pro (14-inch, 2023, M3 Max)"

    def test_get_model_name_returns_empty_if_not_found(self, monkeypatch):
        """_get_model_name() returns empty string if system_profiler unavailable."""
        def fake_run(cmd):
            return ""

        monkeypatch.setattr(mp, "_run", fake_run)
        assert mp._get_model_name() == ""


class TestLabelWithAppleSilicon:
    """Tests 4e-4f: _label() handles Apple Silicon MacBook models via system_profiler."""

    def test_label_apple_silicon_macbook_pro_via_system_profiler(self, monkeypatch):
        """Test 4e: Apple Silicon MacBook Pro (Mac15,x hw_model) labeled via system_profiler."""
        def fake_run(cmd):
            if cmd == ["system_profiler", "SPHardwareDataType"]:
                return 'Model Name: MacBook Pro (16-inch, 2023, M3 Max)\n'
            return ""

        monkeypatch.setattr(mp, "_run", fake_run)
        # hw_model is Mac15,6 (no MacBookPro substring), so system_profiler kicks in
        assert mp._label(True, "Mac15,6") == "macbook-pro"

    def test_label_apple_silicon_macbook_air_via_system_profiler(self, monkeypatch):
        """Test 4f: Apple Silicon MacBook Air (Mac14,x hw_model) labeled via system_profiler."""
        def fake_run(cmd):
            if cmd == ["system_profiler", "SPHardwareDataType"]:
                return 'Model Name: MacBook Air (13-inch, 2022, M2)\n'
            return ""

        monkeypatch.setattr(mp, "_run", fake_run)
        # hw_model is Mac14,2 (no MacBookAir substring), so system_profiler kicks in
        assert mp._label(True, "Mac14,2") == "macbook-air"


class TestBuildProfileRegression:
    """Test 5 (full): build_profile() integration with new _has_battery and _label."""

    def test_build_profile_calls_has_battery_and_passes_to_label(self, monkeypatch):
        """Integration: build_profile() calls _has_battery(), passes result and hw_model to _label()."""
        calls = {}

        def fake_run(cmd):
            if cmd == ["pmset", "-g", "batt"]:
                calls["has_battery"] = True
                return "InternalBattery-0: 75%\n"
            if cmd == ["/usr/sbin/sysctl", "-n", "hw.model"]:
                return "MacBookPro16,2"
            if cmd == ["/usr/sbin/scutil", "--get", "ComputerName"]:
                return "test-mac"
            if cmd == ["uname", "-m"]:
                return "arm64"
            if cmd == ["sw_vers", "-productVersion"]:
                return "15.1"
            if cmd == ["bash", "-lc", "claude --version"]:
                return "claude 1.0"
            if cmd == ["bash", "-lc", "which brew"]:
                return "/opt/homebrew/bin/brew"
            if cmd == ["bash", "-lc", "readlink -f $(which claude) 2>/dev/null || which claude"]:
                return "/opt/homebrew/bin/claude"
            if cmd == ["/usr/sbin/ioreg", "-d2", "-c", "IOPlatformExpertDevice"]:
                return 'IOPlatformUUID" = "UUID-123"'
            if cmd == ["/usr/sbin/ioreg", "-l"]:
                return '"IOPlatformSerialNumber" = "SN123"'
            return ""

        monkeypatch.setattr(mp, "_run", fake_run)
        monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")

        profile = mp.build_profile()

        assert profile["label"] == "macbook-pro"
        assert profile["mobility_class"] == "mobile"
        assert "has_battery" in calls
