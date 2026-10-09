#!/usr/bin/env python3
"""iOS Simulator screenshot capture for dev-environment evidence (G-Eskayo/marvin#?, ADR 0063).

Captures screenshots of iOS apps running in the simulator, driven by profile-declared scenarios
(screen name, light/dark appearance, portrait/landscape orientation). Handles device lifecycle,
app installation/launch, and error recovery. Integrates with project_profile.Measurer.evidence()
for automated evidence capture on UI-touching tickets.

Exported: validate_scenario, capture_scenarios.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path
from typing import Callable

import project_profile as pp  # noqa: E402


class SimulatorUnavailable(pp.EnvMissing):
    """Simulator runtime is not available on THIS machine."""
    def __init__(self):
        super().__init__("simulator-capture", ["iOS simulator runtime"])


def validate_scenario(scenario: dict) -> dict:
    """Validate and sanitize a scenario dict. Returns a validated copy.

    Raises ValueError if validation fails. Sanitizes:
    - screen: alphanumeric + underscore, no paths or special chars
    - dark: boolean (if present, defaults to True)
    - orientation: "portrait" or "landscape" (case-insensitive)
    - launch_args: list of strings (if present, defaults to [])
    """
    if not isinstance(scenario, dict):
        raise ValueError(f"scenario must be a dict, got {type(scenario)}")

    # Validate and sanitize 'screen' field
    if "screen" not in scenario:
        raise ValueError("scenario missing required 'screen' field")
    screen = scenario.get("screen")
    if not isinstance(screen, str) or not screen:
        raise ValueError(f"'screen' must be a non-empty string, got {screen!r}")
    # Sanitize: remove any path separators, null bytes, keep only alphanumeric + underscore + dash
    screen_sanitized = re.sub(r"[^a-zA-Z0-9_\-]", "", screen)
    if not screen_sanitized:
        raise ValueError(f"'screen' becomes empty after sanitization: {screen!r}")
    if len(screen_sanitized) > 200:
        raise ValueError(f"'screen' name too long (max 200 chars): {len(screen_sanitized)}")

    # Validate and default 'dark' field
    dark = scenario.get("dark", True)
    if not isinstance(dark, bool):
        raise ValueError(f"'dark' must be boolean, got {dark!r}")

    # Validate and default 'orientation' field
    orientation = scenario.get("orientation", "portrait").lower()
    if orientation not in ("portrait", "landscape"):
        raise ValueError(f"'orientation' must be 'portrait' or 'landscape', got {orientation!r}")

    # Validate and default 'launch_args' field
    launch_args = scenario.get("launch_args", [])
    if not isinstance(launch_args, (list, type(None))):
        raise ValueError(f"'launch_args' must be a list or None, got {type(launch_args)}")
    if launch_args is None:
        launch_args = []
    for i, arg in enumerate(launch_args):
        if not isinstance(arg, str):
            raise ValueError(f"'launch_args[{i}]' must be string, got {type(arg)}")
        if len(arg) > 4000:
            raise ValueError(f"'launch_args[{i}]' too long (max 4000 chars): {len(arg)}")

    return {
        "screen": screen_sanitized,
        "dark": dark,
        "orientation": orientation,
        "launch_args": launch_args,
    }


def _device_name(worktree_path: Path, ticket_id: str | None = None) -> str:
    """Unique simulator device name scoped to worktree/ticket to avoid collisions under parallel dispatch.
    Uses a hash of the worktree path + optional ticket ID to ensure determinism."""
    scope = f"{worktree_path.name}:{ticket_id or 'notask'}"
    digest = hashlib.sha256(scope.encode()).hexdigest()[:8]
    return f"marvin-{digest}"


def _appearance_arg(dark: bool) -> str:
    """Xcode appearance override argument (-com.apple.CoreSimulator.IndigoAppearance)."""
    return "dark" if dark else "light"


def _simctl_run(cmd: list[str], env: dict | None = None, timeout: int = 60) -> tuple[int, str]:
    """Run xcrun simctl command, return (returncode, stdout+stderr)."""
    full_cmd = ["xcrun", "simctl"] + cmd
    try:
        result = subprocess.run(
            full_cmd, capture_output=True, text=True, timeout=timeout, env=env or os.environ
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, (e.stdout or "") + (e.stderr or "") + f"\n(timeout after {timeout}s)"
    except OSError as e:
        return 127, str(e)


def capture_scenarios(
    worktree_path: Path,
    scenarios: list[dict],
    app_bundle_id: str,
    app_path: str,
    ticket_id: str | None = None,
    timeout_s: int = 300,
) -> list[dict]:
    """Capture screenshots for a list of scenarios. Returns one result dict per scenario,
    with 'ok', 'screen', 'path'/'reason', 'appearance', 'orientation' fields.

    Boots a simulator, installs the app, captures each scenario, and cleans up.
    Device name is unique per worktree/ticket to avoid collisions (ADR 0052).
    Failures in one scenario don't block others; simulator is always cleaned up.

    Args:
        worktree_path: path to the worktree
        scenarios: list of validated scenario dicts (screen, dark, orientation, launch_args)
        app_bundle_id: iOS app bundle ID (e.g., "com.example.MyApp")
        app_path: path to built .app bundle, relative to worktree or absolute
        ticket_id: optional ticket identifier for device name uniqueness
        timeout_s: per-scenario timeout (not total)

    Returns:
        List of scenario result dicts. Each has:
        - ok (bool): True if screenshot was captured
        - screen (str): scenario screen name
        - path (str): relative path to screenshot (if ok=True)
        - reason (str): failure reason (if ok=False)
        - appearance (str): "light" or "dark"
        - orientation (str): "portrait" or "landscape"

    Raises EnvMissing if simulator is unavailable or app is missing.
    """
    if not scenarios:
        return []

    # Validate all scenarios first
    scenarios = [validate_scenario(s) for s in scenarios]

    # Build absolute app path if relative
    app_abs = Path(app_path)
    if not app_abs.is_absolute():
        app_abs = worktree_path / app_path
    if not app_abs.exists():
        raise pp.EnvMissing("simulator-capture", [f"app path not found: {app_abs}"])

    # Ensure evidence dir exists and is writable
    evidence_dir = worktree_path / "docs" / "evidence"
    try:
        evidence_dir.mkdir(parents=True, exist_ok=True)
        # Test write permission
        test_file = evidence_dir / ".writetest"
        test_file.write_text("")
        test_file.unlink()
    except (OSError, PermissionError) as e:
        raise pp.EnvMissing("simulator-capture", [f"docs/evidence/ not writable: {e}"])

    device_name = _device_name(worktree_path, ticket_id)
    results = []

    try:
        # Boot the simulator (idempotent: reuses if already running)
        rc, out = _simctl_run(["boot", device_name])
        if rc != 0 and "already booted" not in out and "Unable to boot" in out:
            raise SimulatorUnavailable()

        # Install the app
        rc, out = _simctl_run(["install", device_name, str(app_abs)])
        if rc != 0:
            # Install failed for all scenarios
            reason = (out.splitlines()[-1:][0] if out.splitlines() else out[:200]).strip()
            return [
                {
                    "ok": False,
                    "screen": s["screen"],
                    "reason": f"install failed: {reason[:100]}",
                    "appearance": _appearance_arg(s["dark"]),
                    "orientation": s["orientation"],
                }
                for s in scenarios
            ]

        # Capture each scenario
        for scenario in scenarios:
            result: dict = {
                "ok": False,
                "screen": scenario["screen"],
                "appearance": _appearance_arg(scenario["dark"]),
                "orientation": scenario["orientation"],
            }

            # Set appearance and orientation
            for arg in ["appearance", "orientation"]:
                val = scenario["dark"] if arg == "appearance" else scenario["orientation"]
                if arg == "appearance":
                    val = "dark" if scenario["dark"] else "light"
                    cmd = ["ui_set_appearance", device_name, val]
                else:
                    cmd = ["ui_set_orientation", device_name, "FaceUp" if scenario["orientation"] == "portrait" else "LandscapeRight"]
                rc, out = _simctl_run(cmd)
                # Appearance/orientation failures don't block the whole scenario

            # Launch the app with scenario's launch args
            launch_args = scenario.get("launch_args", [])
            launch_cmd = ["launch", device_name, app_bundle_id] + launch_args
            rc, out = _simctl_run(launch_cmd, timeout=20)
            if rc != 0:
                result["reason"] = f"launch failed: {(out.splitlines()[-1:][0] if out.splitlines() else out[:100]).strip()[:100]}"
                results.append(result)
                continue

            # Wait briefly for UI to settle
            try:
                subprocess.run(["sleep", "1"], timeout=2, capture_output=True)
            except Exception:
                pass

            # Capture screenshot
            screenshot_name = f"{scenario['screen']}-{_appearance_arg(scenario['dark'])}-{scenario['orientation']}.png"
            screenshot_path = evidence_dir / screenshot_name

            rc, out = _simctl_run(["io", device_name, "screenshot", str(screenshot_path)])
            if rc != 0 or not screenshot_path.exists() or screenshot_path.stat().st_size == 0:
                if screenshot_path.exists():
                    screenshot_path.unlink()
                result["reason"] = f"screenshot failed: {(out.splitlines()[-1:][0] if out.splitlines() else 'empty file')[:100]}"
                results.append(result)
                continue

            # Success
            result["ok"] = True
            result["path"] = f"docs/evidence/{screenshot_name}"
            results.append(result)

    finally:
        # Always shut down the simulator
        try:
            subprocess.run(["xcrun", "simctl", "shutdown", device_name], timeout=10, capture_output=True)
        except Exception:
            pass

    return results
