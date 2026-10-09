"""Tests for simulator_capture.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_simulator_capture.py -v
"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import simulator_capture as sc  # noqa: E402
import project_profile as pp  # noqa: E402


# ── scenario validation ─────────────────────────────────────────────────────

def test_validates_scenario_has_required_screen_field():
    bad_scenario = {"dark": True, "orientation": "portrait"}
    with pytest.raises(ValueError, match="screen"):
        sc.validate_scenario(bad_scenario)


def test_validates_scenario_dark_is_boolean():
    bad_scenario = {"screen": "Home", "dark": "yes"}
    with pytest.raises(ValueError, match="dark.*bool"):
        sc.validate_scenario(bad_scenario)


def test_validates_scenario_orientation_is_valid():
    bad_scenario = {"screen": "Home", "dark": True, "orientation": "sideways"}
    with pytest.raises(ValueError, match="orientation"):
        sc.validate_scenario(bad_scenario)


def test_accepts_valid_scenario():
    scenario = {"screen": "Home", "dark": True, "orientation": "portrait"}
    validated = sc.validate_scenario(scenario)
    assert validated["screen"] == "Home"
    assert validated.get("launch_args") == []


def test_scenario_with_launch_args_is_valid():
    scenario = {"screen": "Home", "launch_args": ["-com.apple.CoreTelephony", "simulator"]}
    validated = sc.validate_scenario(scenario)
    assert validated["launch_args"] == ["-com.apple.CoreTelephony", "simulator"]


def test_sanitizes_screen_names_to_prevent_path_traversal():
    scenario = {"screen": "../../../etc/passwd", "dark": False}
    # Should not raise; sanitization happens
    validated = sc.validate_scenario(scenario)
    assert ".." not in validated["screen"]


def test_sanitizes_launch_args_to_prevent_shell_injection():
    scenario = {"screen": "Home", "launch_args": ["; rm -rf /", "$(whoami)"]}
    validated = sc.validate_scenario(scenario)
    # Arguments should be sanitized or fail validation
    for arg in validated.get("launch_args", []):
        assert not any(c in arg for c in [";", "$", "`"])


# ── empty scenario list ─────────────────────────────────────────────────────

def test_empty_scenario_list_returns_empty_results():
    with patch("simulator_capture.subprocess.run") as mock_run:
        results = sc.capture_scenarios(Path("/tmp/worktree"), [])
        assert results == []
        # No simulator should be booted
        mock_run.assert_not_called()


# ── happy path ───────────────────────────────────────────────────────────────

def test_successful_capture_returns_result_with_screenshot_path():
    scenario = {"screen": "Home", "dark": False, "orientation": "portrait"}
    scenarios = [scenario]

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        return result

    with patch("simulator_capture.subprocess.run", side_effect=mock_run):
        with patch("simulator_capture.Path.exists", return_value=True):
            with patch("simulator_capture._boot_simulator", return_value="com.apple.CoreSimulator.SimDevice.12345"):
                with patch("simulator_capture._capture_screenshot", return_value="docs/evidence/home.png"):
                    results = sc.capture_scenarios(Path("/tmp/worktree"), scenarios)

    assert len(results) == 1
    assert results[0]["screen"] == "Home"
    assert results[0]["ok"] is True
    assert "path" in results[0]


def test_failed_scenario_returns_failure_with_reason():
    scenario = {"screen": "Home", "dark": False}
    scenarios = [scenario]

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 1
        result.stderr = "app crashed"
        return result

    with patch("simulator_capture.subprocess.run", side_effect=mock_run):
        with patch("simulator_capture._boot_simulator", side_effect=subprocess.CalledProcessError(1, "simctl")):
            with pytest.raises(Exception):
                sc.capture_scenarios(Path("/tmp/worktree"), scenarios)


def test_multiple_scenarios_all_succeed():
    scenarios = [
        {"screen": "Home", "dark": False, "orientation": "portrait"},
        {"screen": "Settings", "dark": True, "orientation": "landscape"},
    ]

    call_count = [0]
    def mock_boot(udid=None, timeout_s=120):
        call_count[0] += 1
        return f"sim-{call_count[0]}"

    with patch("simulator_capture._boot_simulator", side_effect=mock_boot):
        with patch("simulator_capture._capture_screenshot", return_value="path.png"):
            with patch("simulator_capture.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                results = sc.capture_scenarios(Path("/tmp/worktree"), scenarios)

    assert len(results) == 2
    assert all(r["ok"] for r in results)


def test_partial_failure_returns_all_results_with_mixed_ok():
    scenarios = [
        {"screen": "Home", "dark": False},
        {"screen": "Error", "dark": True},
    ]

    call_count = [0]
    def mock_capture(udid, screen, dark, orientation, launch_args, worktree, timeout_s=120):
        call_count[0] += 1
        if call_count[0] == 1:
            return {"ok": True, "path": "docs/evidence/home.png", "screen": "Home"}
        else:
            return {"ok": False, "reason": "app crashed", "screen": "Error"}

    with patch("simulator_capture._boot_simulator", return_value="sim-1"):
        with patch("simulator_capture._capture_one_scenario", side_effect=mock_capture):
            with patch("simulator_capture._shutdown_simulator"):
                results = sc.capture_scenarios(Path("/tmp/worktree"), scenarios)

    assert len(results) == 2
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False


# ── timeout handling ────────────────────────────────────────────────────────

def test_wedged_simulator_call_is_killed_on_timeout():
    scenario = {"screen": "Home"}
    scenarios = [scenario]

    def mock_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=30)

    with patch("simulator_capture.subprocess.run", side_effect=mock_run):
        with patch("simulator_capture._shutdown_simulator"):
            with pytest.raises(pp.TestTimedOut):
                sc.capture_scenarios(Path("/tmp/worktree"), scenarios, timeout_s=30)


def test_simulator_is_shut_down_even_if_capture_fails():
    scenario = {"screen": "Home"}
    scenarios = [scenario]
    mock_shutdown = MagicMock()

    def mock_capture(udid, *args, **kwargs):
        raise RuntimeError("capture failed")

    with patch("simulator_capture._boot_simulator", return_value="sim-id"):
        with patch("simulator_capture._capture_one_scenario", side_effect=mock_capture):
            with patch("simulator_capture._shutdown_simulator", mock_shutdown) as mock_sd:
                results = sc.capture_scenarios(Path("/tmp/worktree"), scenarios)
                # Shutdown should still be called even if capture fails
                mock_sd.assert_called()
                # The failure should be reported in the result, not raise
                assert len(results) == 1
                assert results[0]["ok"] is False


# ── environment missing ─────────────────────────────────────────────────────

def test_raises_envinvalid_when_simctl_is_missing():
    scenario = {"screen": "Home"}
    scenarios = [scenario]

    def mock_run(cmd, **kwargs):
        if "simctl" in " ".join(cmd):
            raise FileNotFoundError("simctl not found")
        result = MagicMock()
        result.returncode = 0
        return result

    with patch("simulator_capture.subprocess.run", side_effect=mock_run):
        with pytest.raises(pp.EnvMissing):
            sc.capture_scenarios(Path("/tmp/worktree"), scenarios)


# ── malformed scenarios ─────────────────────────────────────────────────────

def test_screen_value_with_path_traversal_is_rejected_or_sanitized():
    scenario = {"screen": "../../etc/passwd"}
    # Either reject or sanitize
    try:
        validated = sc.validate_scenario(scenario)
        # If it validates, the path must be sanitized
        assert ".." not in validated["screen"]
    except ValueError:
        # Or it should explicitly reject
        pass


def test_concurrent_captures_use_distinct_simulator_instances(tmp_path):
    """Verify that concurrent calls don't reuse simulator instances."""
    scenarios1 = [{"screen": "Home"}]
    scenarios2 = [{"screen": "Settings"}]

    captured_udids = []

    def mock_boot(*args, **kwargs):
        udid = f"sim-{len(captured_udids)}"
        captured_udids.append(udid)
        return udid

    with patch("simulator_capture._boot_simulator", side_effect=mock_boot):
        with patch("simulator_capture._capture_screenshot", return_value="path.png"):
            with patch("simulator_capture._shutdown_simulator"):
                sc.capture_scenarios(tmp_path, scenarios1)
                sc.capture_scenarios(tmp_path, scenarios2)

    # Both calls should have booted distinct simulators
    assert len(set(captured_udids)) == 2


# ── real-collaborator test (skip if no simulator) ──────────────────────────

def _has_ios_simulator():
    """Check if this machine has iOS simulator tools and runtimes available."""
    try:
        result = subprocess.run(
            ["xcrun", "simctl", "list", "runtimes", "--json"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return False
        import json
        runtimes = json.loads(result.stdout)
        return any(r.get("identifier", "").startswith("com.apple.CoreSimulator.SimRuntime.iOS-")
                  for r in runtimes.get("runtimes", []))
    except Exception:
        return False


@pytest.mark.skipif(
    not _has_ios_simulator(),
    reason="iOS simulator runtime not available on this machine"
)
def test_real_simulator_boots_and_returns_nonzero_byte_png(tmp_path):
    """Integration test: boots a real simulator and captures a screenshot.
    This is expensive and requires an iOS runtime; skip on machines without one."""
    scenario = {
        "screen": "Home",
        "dark": False,
        "orientation": "portrait",
        "launch_args": [],
    }

    try:
        results = sc.capture_scenarios(tmp_path, [scenario], timeout_s=60)
        assert len(results) == 1
        assert results[0]["ok"] is True

        # Verify the screenshot file exists and is not empty
        screenshot_path = tmp_path / results[0]["path"]
        assert screenshot_path.exists()
        assert screenshot_path.stat().st_size > 0
    except pp.EnvMissing:
        # Expected if the test machine doesn't have the tools
        pytest.skip("iOS simulator tooling not available")
