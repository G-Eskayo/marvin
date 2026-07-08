#!/usr/bin/env python3
"""Snapshot of the properties that actually predict cross-machine behavior
differences — not just a friendly hostname. Written to
~/.claude/machine-profile.json, refreshed by cross_machine_merge.py and
readable by any script that wants to tag its output with machine provenance.

Run standalone to refresh: ~/.agents/venv/bin/python machine_profile.py
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROFILE_PATH = Path.home() / ".claude" / "machine-profile.json"
NETWORK_PATH = Path.home() / ".claude" / "marvin-network.json"


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        return ""


def _hardware_uuid() -> str:
    out = _run(["ioreg", "-d2", "-c", "IOPlatformExpertDevice"])
    for line in out.splitlines():
        if "IOPlatformUUID" in line:
            return line.split('"')[3]
    return ""


def _serial() -> str:
    out = _run(["ioreg", "-l"])
    for line in out.splitlines():
        if "IOPlatformSerialNumber" in line:
            return line.split('"')[3]
    return ""


def _claude_install_method(claude_path: str) -> str:
    if "/.local/share/claude/" in claude_path:
        return "native-installer"
    if "node_modules" in claude_path or "/opt/homebrew" in claude_path or "/usr/local" in claude_path:
        return "homebrew-npm"
    return "unknown"


def _mobility_class(hw_model: str) -> str:
    # Apple's model-identifier scheme doesn't reliably distinguish desktop
    # families by number (Mac16,x spans mini/Studio/iMac), but every mobile
    # Mac has always been named MacBook* — that substring is the stable signal.
    return "mobile" if "MacBook" in hw_model else "stationary"


def _label(hw_model: str) -> str:
    return "macbook-pro" if "MacBook" in hw_model else "mac-mini"


def build_profile() -> dict:
    hw_model = _run(["sysctl", "-n", "hw.model"])
    claude_path = _run(["bash", "-lc", "readlink -f $(which claude) 2>/dev/null || which claude"])
    venv_python = str(Path.home() / ".agents" / "venv" / "bin" / "python")

    chromadb_version = ""
    try:
        out = subprocess.run(
            [venv_python, "-c", "import chromadb; print(chromadb.__version__)"],
            capture_output=True, text=True, timeout=15,
        )
        chromadb_version = out.stdout.strip()
    except Exception:
        pass

    return {
        "label": _label(hw_model),
        "hostname": _run(["scutil", "--get", "ComputerName"]),
        "hardware_uuid": _hardware_uuid(),
        "serial": _serial(),
        "hw_model": hw_model,
        "mobility_class": _mobility_class(hw_model),
        "chip_arch": _run(["uname", "-m"]),
        "macos_version": _run(["sw_vers", "-productVersion"]),
        "claude_version": _run(["bash", "-lc", "claude --version"]),
        "claude_path": claude_path,
        "claude_install_method": _claude_install_method(claude_path),
        "python_venv_version": _run([venv_python, "--version"]),
        "chromadb_version": chromadb_version,
        "homebrew_present": bool(_run(["bash", "-lc", "which brew"])),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_or_build(max_age_hours: int = 24) -> dict:
    """Read the cached profile if fresh enough, else regenerate."""
    if PROFILE_PATH.exists():
        try:
            cached = json.loads(PROFILE_PATH.read_text())
            gen = datetime.fromisoformat(cached["generated_at"])
            age_hours = (datetime.now(timezone.utc) - gen).total_seconds() / 3600
            if age_hours < max_age_hours:
                return cached
        except Exception:
            pass
    profile = build_profile()
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))
    return profile


def machine_label() -> str:
    """Fast path for tagging — just the label, cached aggressively."""
    return load_or_build(max_age_hours=24 * 7).get("label", "unknown-machine")


def _load_registry() -> dict:
    if not NETWORK_PATH.exists():
        return {}
    try:
        return json.loads(NETWORK_PATH.read_text()).get("devices", {})
    except Exception:
        return {}


def registry_id() -> str:
    """This machine's stable id in marvin-network.json, resolved by matching
    hardware UUID — not by label — so it can't misidentify itself even if
    renamed or if a second machine of the same kind is added later."""
    my_uuid = load_or_build().get("hardware_uuid", "")
    for device_id, info in _load_registry().items():
        if info.get("hardware_uuid") == my_uuid and my_uuid:
            return device_id
    return machine_label()  # not registered yet — fall back to the plain label


def remote_devices() -> dict:
    """All registered devices that aren't this one, keyed by device id."""
    my_id = registry_id()
    return {k: v for k, v in _load_registry().items() if k != my_id}


if __name__ == "__main__":
    profile = build_profile()
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))
    print(json.dumps(profile, indent=2))
    print(f"\nWritten to {PROFILE_PATH}", file=sys.stderr)
