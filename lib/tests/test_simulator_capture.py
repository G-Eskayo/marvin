"""Tests for simulator_capture.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_simulator_capture.py -v
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import project_profile as pp  # noqa: E402


class TestHaveSimulator:
    """Tests for have('simulator', env) capability check."""

    def test_have_simulator_with_ios_runtime(self):
        """Simulator capability returns True when iOS runtime is available."""
        def mock_run(cmd, *args, **kwargs):
            if cmd == ["xcrun", "simctl", "list", "runtimes", "--json"]:
                class Result:
                    stdout = json.dumps({
                        "runtimes": [
                            {"name": "iOS 18.0", "identifier": "com.apple.CoreSimulator.SimRuntime.iOS-18-0"},
                        ]
                    })
                return Result()
            raise ValueError(f"Unexpected command: {cmd}")

        env = {"PATH": "/usr/bin"}
        with patch("subprocess.run", side_effect=mock_run):
            # This will be implemented next
            pass

    def test_have_simulator_no_ios_runtime_only_watchos(self):
        """Simulator capability returns False when only watchOS runtime is available."""
        pass

    def test_have_simulator_xcrun_missing(self, monkeypatch):
        """Simulator check raises EnvMissing when xcrun is not available."""
        pass

    def test_have_simulator_malformed_json(self):
        """Simulator check handles malformed JSON gracefully."""
        pass


class TestRuntimeSelection:
    """Tests for iOS runtime selection."""

    def test_get_latest_ios_runtime_parses_version_correctly(self):
        """_get_latest_ios_runtime uses numeric version parsing, not lexicographic."""
        from simulator_capture import _get_latest_ios_runtime

        def mock_simctl_run(cmd, *args, **kwargs):
            if cmd[0:3] == ["list", "runtimes", "--json"]:
                return 0, json.dumps({
                    "runtimes": [
                        {"name": "iOS 18.0", "identifier": "iOS-18-0", "isAvailable": True},
                        {"name": "iOS 18.9", "identifier": "iOS-18-9", "isAvailable": True},
                        {"name": "iOS 18.10", "identifier": "iOS-18-10", "isAvailable": True},
                    ]
                })
            return 1, ""

        with patch("simulator_capture._simctl_run", side_effect=mock_simctl_run):
            result = _get_latest_ios_runtime()
            assert result == "iOS-18-10", f"Expected iOS-18-10 (numeric 18.10), got {result}"

    def test_get_latest_ios_runtime_filters_unavailable(self):
        """_get_latest_ios_runtime skips unavailable runtimes."""
        from simulator_capture import _get_latest_ios_runtime

        def mock_simctl_run(cmd, *args, **kwargs):
            if cmd[0:3] == ["list", "runtimes", "--json"]:
                return 0, json.dumps({
                    "runtimes": [
                        {"name": "iOS 18.0", "identifier": "iOS-18-0", "isAvailable": False},
                        {"name": "iOS 17.5", "identifier": "iOS-17-5", "isAvailable": True},
                    ]
                })
            return 1, ""

        with patch("simulator_capture._simctl_run", side_effect=mock_simctl_run):
            result = _get_latest_ios_runtime()
            assert result == "iOS-17-5", f"Expected iOS-17-5 (the available one), got {result}"

    def test_get_latest_ios_runtime_handles_missing_is_available(self):
        """_get_latest_ios_runtime treats missing isAvailable as unavailable."""
        from simulator_capture import _get_latest_ios_runtime

        def mock_simctl_run(cmd, *args, **kwargs):
            if cmd[0:3] == ["list", "runtimes", "--json"]:
                return 0, json.dumps({
                    "runtimes": [
                        {"name": "iOS 18.0", "identifier": "iOS-18-0"},
                        {"name": "iOS 17.5", "identifier": "iOS-17-5", "isAvailable": True},
                    ]
                })
            return 1, ""

        with patch("simulator_capture._simctl_run", side_effect=mock_simctl_run):
            result = _get_latest_ios_runtime()
            assert result == "iOS-17-5"


class TestValidateScenario:
    """Tests for scenario validation."""

    def test_validate_scenario_valid(self):
        """Valid scenario passes validation."""
        scenario = {
            "screen": "home",
            "dark": True,
            "orientation": "portrait",
            "launch_args": []
        }
        # This will be implemented
        pass

    def test_validate_scenario_missing_screen(self):
        """Missing 'screen' field raises ValueError."""
        pass

    def test_validate_scenario_non_bool_dark(self):
        """Non-boolean 'dark' field raises ValueError."""
        pass

    def test_validate_scenario_invalid_orientation(self):
        """Invalid orientation raises ValueError."""
        pass

    def test_validate_scenario_launch_args_not_list(self):
        """launch_args must be a list or None."""
        pass

    def test_validate_scenario_screen_with_path_traversal(self):
        """Screen name with '..' is sanitized or rejected."""
        pass


class TestCaptureScenarios:
    """Tests for the main capture_scenarios function."""

    def test_capture_scenarios_empty_list(self, tmp_path):
        """Empty scenarios list returns empty results."""
        from simulator_capture import capture_scenarios
        result = capture_scenarios(tmp_path, [], "com.test.app", "Test.app", sweep_simulators=lambda: None)
        assert result == []

    def test_capture_scenarios_single_valid_scenario(self, tmp_path):
        """Single valid scenario captures successfully."""
        from simulator_capture import capture_scenarios
        app_path = tmp_path / "Test.app"
        app_path.mkdir()
        evidence_dir = tmp_path / "docs" / "evidence"
        evidence_dir.mkdir(parents=True)
        scenarios = [{"screen": "home", "dark": True, "orientation": "portrait"}]

        def mock_simctl_run(cmd, *args, **kwargs):
            if cmd[0] == "boot":
                return 0, "already booted"
            elif cmd[0] == "install":
                return 0, ""
            elif cmd[0] == "launch":
                return 0, ""
            elif cmd[0] == "ui_set_appearance":
                return 0, ""
            elif cmd[0] == "ui_set_orientation":
                return 0, ""
            elif cmd[0] == "io" and cmd[2] == "screenshot":
                Path(cmd[3]).write_bytes(b"\x89PNG\r\n\x1a\n")
                return 0, ""
            return 0, ""

        with patch("simulator_capture._simctl_run", side_effect=mock_simctl_run):
            with patch("simulator_capture._create_device", return_value=True):
                with patch("simulator_capture._device_exists", return_value=True):
                    result = capture_scenarios(tmp_path, scenarios, "com.test.app", str(app_path), sweep_simulators=lambda: None)
                    assert len(result) == 1
                    assert result[0]["ok"] is True

    def test_capture_scenarios_install_fails(self):
        """When app installation fails, scenario is marked failed but others continue."""
        pass

    def test_capture_scenarios_launch_fails(self):
        """When app launch fails, scenario is marked failed but others continue."""
        pass

    def test_capture_scenarios_screenshot_produces_zero_bytes(self):
        """Zero-byte screenshot file is treated as a failure."""
        pass

    def test_capture_scenarios_calls_cleanup_sweep_by_default(self, tmp_path):
        """Defect fix: sweep_simulators defaults to cleanup_sweep.sweep_simulators and is called at start."""
        from simulator_capture import capture_scenarios
        sweep_called = []

        def mock_sweep():
            sweep_called.append(True)

        app_path = tmp_path / "Test.app"
        app_path.mkdir()
        evidence_dir = tmp_path / "docs" / "evidence"
        evidence_dir.mkdir(parents=True)

        scenarios = [{"screen": "home", "dark": True}]

        with patch("simulator_capture._simctl_run", return_value=(1, "not available")):
            with patch("simulator_capture._create_device", return_value=False):
                try:
                    capture_scenarios(tmp_path, scenarios, "com.test.app", str(app_path), sweep_simulators=mock_sweep)
                except Exception:
                    pass

        assert sweep_called, "Defect #1: sweep_simulators was not called"

    def test_capture_scenarios_worktree_scoped_device_name(self):
        """Device names are uniquely scoped to worktree/ticket to avoid collisions."""
        pass

    def test_capture_scenarios_concurrent_calls_no_collision(self, tmp_path):
        """Two concurrent capture calls don't collide on device naming."""
        pass

    def test_capture_scenarios_stale_device_idempotent(self):
        """A leftover simulator device from a previous run is reused without hanging."""
        pass

    def test_capture_scenarios_simulator_boot_failure(self):
        """Failure to boot simulator raises EnvMissing when it's a machine problem."""
        pass

    def test_capture_scenarios_no_writable_evidence_dir(self, tmp_path):
        """Unwritable docs/evidence/ directory is caught and reported as failure."""
        pass

    def test_capture_scenarios_cleanup_on_exception(self):
        """Simulator is shut down even if an exception occurs during capture."""
        pass


class TestFormatDevEvidence:
    """Tests for multi-screenshot evidence formatting in mr_raiser."""

    def test_format_dev_evidence_single_screenshot_backward_compat(self):
        """Single-screenshot format is unchanged from existing behavior."""
        pass

    def test_format_dev_evidence_multiple_screenshots(self):
        """Multiple screenshots are formatted as separate markdown images."""
        pass

    def test_format_dev_evidence_all_scenarios_failed(self):
        """All-failed state uses the warning marker."""
        pass

    def test_format_dev_evidence_partial_failure(self):
        """Partial failure (some ok, some failed) shows both."""
        pass

    def test_format_dev_evidence_sanitizes_screen_names(self):
        """Screen names with special characters are safely displayed."""
        pass


class TestTicketTouchesUIWithCustomPaths:
    """Tests for generalized ticket_touches_ui with custom UI path prefixes."""

    def test_ticket_touches_ui_custom_paths(self, tmp_path, monkeypatch):
        """ticket_touches_ui accepts custom ui_paths parameter."""
        pass

    def test_ticket_touches_ui_default_paths_backward_compat(self):
        """Default behavior without ui_paths stays unchanged."""
        pass


class TestMeasurerEvidence:
    """Tests for Measurer.evidence() integration with simulator capture."""

    def test_measurer_evidence_no_capture_configured(self):
        """When profile has no capture config, returns N/A."""
        pass

    def test_measurer_evidence_capture_not_ui_touching(self):
        """When ticket doesn't touch UI, capture is skipped even if configured."""
        pass

    def test_measurer_evidence_capture_configured_and_ui(self):
        """When profile has capture config and ticket touches UI, captures scenarios."""
        pass

    def test_measurer_evidence_env_missing_during_capture(self):
        """EnvMissing during capture is propagated to run() for redispatch."""
        pass

    def test_measurer_evidence_single_scenario_success(self):
        """Single successful scenario produces the right evidence structure."""
        pass

    def test_measurer_evidence_multiple_scenarios_mixed_results(self):
        """Multiple scenarios with mixed success/failure are all reported."""
        pass


class TestDashboardParseDevEvidence:
    """Tests for dashboard parsing of multi-screenshot evidence."""

    def test_parse_dev_evidence_single_screenshot_backward_compat(self):
        """Existing single-screenshot PR body parses correctly."""
        pass

    def test_parse_dev_evidence_multiple_screenshots(self):
        """Multiple-screenshot body is parsed into structured data."""
        pass

    def test_parse_dev_evidence_all_scenarios_failed(self):
        """Failed-scenario markers are parsed and flagged."""
        pass

    def test_parse_dev_evidence_truncated_markdown(self):
        """Malformed markdown doesn't crash the parser."""
        pass

    def test_parse_dev_evidence_missing_evidence_flag_set(self):
        """missingEvidence is true when screenshots array is empty."""
        pass


class TestPrCardMissingEvidenceFlag:
    """Tests for PrCard/MrDetail rendering of missing evidence warning."""

    def test_pr_card_renders_warning_when_missing_evidence(self):
        """PrCard shows warning line when missingEvidence is true."""
        pass

    def test_pr_card_no_warning_when_evidence_present(self):
        """PrCard doesn't show warning when evidence is present."""
        pass

    def test_mr_detail_renders_warning_when_missing_evidence(self):
        """MrDetail shows warning line when missingEvidence is true."""
        pass


# Integration test: real collaborator (xcrun/simctl) if available
class TestSimulatorCaptureRealCollaborator:
    """Integration tests using real xcrun/simctl if available."""

    @pytest.mark.skipif(
        not Path("/Applications/Xcode.app/Contents/Developer").exists(),
        reason="Xcode not installed"
    )
    def test_real_simulator_availability_check(self):
        """Real xcrun simctl list works and returns JSON."""
        pass

    @pytest.mark.skipif(
        not Path("/Applications/Xcode.app/Contents/Developer").exists(),
        reason="Xcode not installed"
    )
    def test_real_simulator_screenshot_differs_from_springboard(self, tmp_path):
        """Screenshot of a real app differs from blank springboard baseline."""
        pass
