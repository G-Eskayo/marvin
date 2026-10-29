"""Test _has_battery(), _mobility_class(), _label() refactoring in machine_profile.py"""
import pytest
import machine_profile as mp


class TestHasBattery:
    """Tests for the new _has_battery() function."""

    def test_has_battery_detects_internal_battery(self, monkeypatch):
        """_has_battery() returns True when pmset output contains "InternalBattery"."""
        pmset_output = """Now drawing from 'Battery Power'
 -InternalBattery 0	(current charge:  87%; health: Normal)"""
        monkeypatch.setattr(mp, "_run", lambda cmd: pmset_output if cmd == ["/usr/sbin/pmset", "-g", "batt"] else "")
        assert mp._has_battery() is True

    def test_has_battery_detects_no_battery(self, monkeypatch):
        """_has_battery() returns False when pmset output has no "InternalBattery"."""
        pmset_output = "Now drawing from 'AC Power'\n"
        monkeypatch.setattr(mp, "_run", lambda cmd: pmset_output if cmd == ["/usr/sbin/pmset", "-g", "batt"] else "")
        assert mp._has_battery() is False

    def test_has_battery_returns_false_on_exception(self, monkeypatch):
        """_has_battery() returns False if pmset command fails."""
        monkeypatch.setattr(mp, "_run", lambda cmd: "")
        assert mp._has_battery() is False

    def test_has_battery_uses_absolute_pmset_path(self, monkeypatch):
        """_has_battery() calls pmset with absolute path /usr/sbin/pmset."""
        calls = []
        monkeypatch.setattr(mp, "_run", lambda cmd: (calls.append(cmd), "")[1])
        mp._has_battery()
        assert ["/usr/sbin/pmset", "-g", "batt"] in calls


class TestMobilityClass:
    """Tests for _mobility_class() with boolean has_battery parameter."""

    def test_mobility_class_mobile_when_has_battery(self):
        """_mobility_class(True) returns 'mobile' for devices with batteries."""
        assert mp._mobility_class(True) == "mobile"

    def test_mobility_class_stationary_when_no_battery(self):
        """_mobility_class(False) returns 'stationary' for devices without batteries."""
        assert mp._mobility_class(False) == "stationary"


class TestLabel:
    """Tests for _label() with boolean has_battery parameter."""

    def test_label_macbook_when_has_battery(self):
        """_label(True) returns 'macbook-pro' for devices with batteries."""
        assert mp._label(True) == "macbook-pro"

    def test_label_mac_mini_when_no_battery(self):
        """_label(False) returns 'mac-mini' for devices without batteries."""
        assert mp._label(False) == "mac-mini"


class TestBuildProfileUsesHasBattery:
    """Test that build_profile() calls _has_battery() and uses its result."""

    def test_build_profile_calls_has_battery_on_macos(self, monkeypatch):
        """macOS build_profile() calls _has_battery() and uses it for mobility_class/label."""
        calls = []

        def fake_has_battery():
            calls.append("has_battery")
            return True

        def fake_run(cmd):
            if cmd == ["/usr/sbin/sysctl", "-n", "hw.model"]:
                return "MacBook"
            return ""

        monkeypatch.setattr(mp.host_os, "os_name", lambda: "macos")
        monkeypatch.setattr(mp, "_has_battery", fake_has_battery)
        monkeypatch.setattr(mp, "_run", fake_run)

        profile = mp.build_profile()
        assert "has_battery" in calls
        assert profile["mobility_class"] == "mobile"
        assert profile["label"] == "macbook-pro"

    def test_build_profile_linux_no_battery_check(self, monkeypatch, tmp_path):
        """Linux profile doesn't call _has_battery() — just uses stationary/hostname label."""
        dmi = tmp_path / "dmi"
        dmi.mkdir()
        (dmi / "product_name").write_text("Macmini6,2\n")
        (dmi / "product_uuid").write_text("b080693d-2b90-405f-bf62-603682494206\n")
        (dmi / "product_serial").write_text("C07ABC123DWYL\n")

        calls = []
        def fake_has_battery():
            calls.append("has_battery")
            return False

        def fake_run(cmd):
            if cmd == ["hostname"]:
                return "mac-mini-2012"
            if cmd == ["uname", "-m"]:
                return "x86_64"
            return ""

        monkeypatch.setattr(mp.host_os, "os_name", lambda: "linux")
        monkeypatch.setattr(mp, "DMI_DIR", dmi)
        monkeypatch.setattr(mp, "_has_battery", fake_has_battery)
        monkeypatch.setattr(mp, "_run", fake_run)

        profile = mp.build_profile()
        # Linux doesn't call _has_battery at all
        assert "has_battery" not in calls
        assert profile["mobility_class"] == "stationary"
        assert profile["label"] == "mac-mini-2012"
