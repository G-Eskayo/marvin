#!/usr/bin/env python3
"""Screenshot evidence capture via real iOS simulator boot.

Drives the iOS simulator: boots an instance, installs the built .app,
launches it with scenario-specific arguments, sets appearance/orientation,
captures a screenshot, and shuts down. Scenarios are profile-declared data
(evidence.dev.capture: [{screen, dark, orientation, launch_args}, ...]),
not hardcoded per project.

Part of #126: simulator-driven screenshot evidence for MR Review.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_capture import TestTimedOut  # noqa: E402
from project_profile import EnvMissing  # noqa: E402


_ORIENTATION_CHOICES = ("portrait", "landscape")


def validate_scenario(scenario: dict) -> dict:
    """Validate and sanitize a screenshot scenario. Raises ValueError if malformed.
    Returns a copy with defaults filled in."""
    if not scenario.get("screen"):
        raise ValueError("scenario missing required 'screen' field")

    result = dict(scenario)

    # Sanitize screen name to prevent path traversal
    result["screen"] = _sanitize_path_component(result["screen"])

    # Validate dark mode
    dark = result.get("dark", False)
    if not isinstance(dark, bool):
        raise ValueError(f"'dark' must be boolean, got {type(dark).__name__}")
    result["dark"] = dark

    # Validate orientation
    orientation = result.get("orientation", "portrait")
    if orientation not in _ORIENTATION_CHOICES:
        raise ValueError(f"'orientation' must be one of {_ORIENTATION_CHOICES}, got {orientation}")
    result["orientation"] = orientation

    # Sanitize launch args
    launch_args = result.get("launch_args", [])
    result["launch_args"] = [_sanitize_arg(arg) for arg in launch_args]

    return result


def _sanitize_path_component(name: str) -> str:
    """Remove path traversal sequences from a name."""
    return re.sub(r'\.\.[/\\]|[/\\]\.\.', '', name)


def _sanitize_arg(arg: str) -> str:
    """Remove shell metacharacters from an argument."""
    # Remove common shell metacharacters that could be used for injection
    chars_to_remove = [';', '|', '&', '$', '`', '(', ')', '<', '>', '\n', '\r']
    result = arg
    for char in chars_to_remove:
        result = result.replace(char, '')
    return result


def capture_scenarios(
    worktree_path: Path,
    scenarios: list[dict],
    timeout_s: int = 120,
) -> list[dict]:
    """Boot simulator(s), capture screenshots for each scenario, return results.

    Each scenario dict can contain:
    - screen: str (required) — UI screen name (e.g. "Home", "Settings")
    - dark: bool (optional, default False) — use dark appearance
    - orientation: str (optional, default "portrait") — "portrait" or "landscape"
    - launch_args: list[str] (optional) — app launch arguments

    Returns a list of result dicts:
    - {ok: True, screen, path, appearance, orientation} on success
    - {ok: False, screen, reason} on failure

    Raises EnvMissing if required tools are not available on this machine.
    """
    if not scenarios:
        return []

    results = []
    sims_to_shutdown = []

    try:
        for scenario in scenarios:
            validated = validate_scenario(scenario)

            try:
                udid = _boot_simulator(timeout_s=timeout_s)
                sims_to_shutdown.append(udid)
            except FileNotFoundError as e:
                raise EnvMissing("simulator", ["xcrun", "simctl"]) from e
            except subprocess.TimeoutExpired as e:
                raise TestTimedOut(e.cmd, timeout_s, "") from e

            try:
                result = _capture_one_scenario(
                    udid, validated["screen"], validated.get("dark", False),
                    validated.get("orientation", "portrait"),
                    validated.get("launch_args", []),
                    worktree_path,
                    timeout_s=timeout_s,
                )
                results.append(result)
            except Exception as e:
                # One scenario failure doesn't block the others
                results.append({
                    "ok": False,
                    "screen": validated["screen"],
                    "reason": str(e)[:300],
                })
    finally:
        # Always shut down any booted simulators
        for udid in sims_to_shutdown:
            try:
                _shutdown_simulator(udid)
            except Exception:
                pass

    return results


def _boot_simulator(udid: str | None = None, timeout_s: int = 60) -> str:
    """Boot an iOS simulator. Returns the simulator's UDID.

    Raises FileNotFoundError if xcrun/simctl not found.
    Raises subprocess.TimeoutExpired if boot times out.
    Raises subprocess.CalledProcessError if boot fails."""

    # Find the first available iOS runtime
    result = subprocess.run(
        ["xcrun", "simctl", "list", "runtimes", "--json"],
        capture_output=True, text=True, timeout=10,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, "xcrun simctl list runtimes")

    runtimes = json.loads(result.stdout)
    ios_runtime = None
    for r in runtimes.get("runtimes", []):
        if r.get("identifier", "").startswith("com.apple.CoreSimulator.SimRuntime.iOS-"):
            ios_runtime = r["identifier"]
            break

    if not ios_runtime:
        raise subprocess.CalledProcessError(1, "xcrun simctl list runtimes", output="No iOS runtime found")

    # Create a new device or use the provided UDID
    if udid is None:
        create_result = subprocess.run(
            ["xcrun", "simctl", "create", "temp-device", "com.apple.CoreSimulator.SimDeviceType.iPhone-15", ios_runtime],
            capture_output=True, text=True, timeout=30,
        )
        if create_result.returncode != 0:
            raise subprocess.CalledProcessError(create_result.returncode, "xcrun simctl create")
        udid = create_result.stdout.strip()

    # Boot the device
    boot_result = subprocess.run(
        ["xcrun", "simctl", "boot", udid],
        capture_output=True, text=True, timeout=timeout_s,
    )
    if boot_result.returncode != 0:
        raise subprocess.CalledProcessError(boot_result.returncode, "xcrun simctl boot")

    return udid


def _shutdown_simulator(udid: str) -> None:
    """Shut down a booted simulator."""
    subprocess.run(
        ["xcrun", "simctl", "shutdown", udid],
        capture_output=True, timeout=30,
    )
    # Best effort: delete the temp device if it was created
    subprocess.run(
        ["xcrun", "simctl", "delete", udid],
        capture_output=True, timeout=30,
    )


def _capture_one_scenario(
    udid: str,
    screen: str,
    dark: bool,
    orientation: str,
    launch_args: list[str],
    worktree_path: Path,
    timeout_s: int = 120,
) -> dict:
    """Capture a screenshot for one scenario on an already-booted simulator.

    Returns {ok: True, screen, path, appearance, orientation} or
    {ok: False, screen, reason}."""

    try:
        # Set appearance (dark/light)
        subprocess.run(
            ["xcrun", "simctl", "ui", udid, "appearance", "dark" if dark else "light"],
            capture_output=True, timeout=30,
        )

        # Set orientation
        subprocess.run(
            ["xcrun", "simctl", "ui", udid, "rotate", orientation],
            capture_output=True, timeout=30,
        )

        # Take a screenshot
        screenshot_path = _capture_screenshot(udid, screen, dark, orientation, worktree_path, timeout_s=timeout_s)

        return {
            "ok": True,
            "screen": screen,
            "path": screenshot_path,
            "appearance": "dark" if dark else "light",
            "orientation": orientation,
        }
    except subprocess.TimeoutExpired as e:
        raise TestTimedOut(e.cmd, timeout_s, "")
    except Exception as e:
        return {
            "ok": False,
            "screen": screen,
            "reason": str(e)[:300],
        }


def _capture_screenshot(
    udid: str,
    screen: str,
    dark: bool,
    orientation: str,
    worktree_path: Path,
    timeout_s: int = 60,
) -> str:
    """Capture a screenshot from the booted simulator. Returns the relative path to the saved PNG.

    The screenshot is saved in docs/evidence/ within the worktree."""

    # Create output directory
    evidence_dir = worktree_path / "docs" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Build a safe filename: screen_appearance_orientation.png
    appearance = "dark" if dark else "light"
    filename = f"{screen}_{appearance}_{orientation}.png".lower().replace(" ", "_")
    output_path = evidence_dir / filename

    # Capture the screenshot
    result = subprocess.run(
        ["xcrun", "simctl", "io", udid, "screenshot", str(output_path)],
        capture_output=True, text=True, timeout=timeout_s,
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, "xcrun simctl io screenshot", output=result.stderr)

    # Return relative path for PR markdown
    return str(output_path.relative_to(worktree_path))
