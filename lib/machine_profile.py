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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_os  # noqa: E402

PROFILE_PATH = Path.home() / ".claude" / "machine-profile.json"
NETWORK_PATH = Path.home() / ".claude" / "marvin-network.json"
DMI_DIR = Path("/sys/class/dmi/id")   # Linux firmware tables: the same hardware identity ioreg gives on macOS


def _run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=10).stdout
        return out.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def _dmi(name: str) -> str:
    """A Linux DMI field. product_uuid and product_serial are root-only, so fall back to non-interactive sudo
    (on mac-mini-2012's sudo list); empty, never a guess, if neither works."""
    path = DMI_DIR / name
    try:
        return path.read_text().strip()
    except OSError:
        return _run(["sudo", "-n", "cat", str(path)]).strip()


def _hardware_uuid() -> str:
    if host_os.os_name() == "linux":
        return _dmi("product_uuid").upper()   # uppercase, matching how ioreg reports it on the Macs
    out = _run(["/usr/sbin/ioreg", "-d2", "-c", "IOPlatformExpertDevice"])
    for line in out.splitlines():
        if "IOPlatformUUID" in line:
            return line.split('"')[3]
    return ""


def _serial() -> str:
    if host_os.os_name() == "linux":
        return _dmi("product_serial")
    out = _run(["/usr/sbin/ioreg", "-l"])
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


def _has_battery() -> bool:
    """Check if this machine has an internal battery via pmset.
    Returns False on any error."""
    try:
        out = _run(["/usr/sbin/pmset", "-g", "batt"])
        return "InternalBattery" in out
    except Exception:
        return False


def _mobility_class(has_battery: bool) -> str:
    """Determine mobility class from battery presence (more reliable than hw_model)."""
    return "mobile" if has_battery else "stationary"


def _label(has_battery: bool) -> str:
    """Determine machine label from battery presence."""
    return "macbook-pro" if has_battery else "mac-mini"


def build_profile() -> dict:
    if host_os.os_name() == "linux":
        return _build_linux_profile()
    hw_model = _run(["/usr/sbin/sysctl", "-n", "hw.model"])
    claude_path = _run(["bash", "-lc", "readlink -f $(which claude) 2>/dev/null || which claude"])
    venv_python = str(Path.home() / ".agents" / "venv" / "bin" / "python")
    has_battery = _has_battery()

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
        "label": _label(has_battery),
        "hostname": _run(["/usr/sbin/scutil", "--get", "ComputerName"]),
        "hardware_uuid": _hardware_uuid(),
        "serial": _serial(),
        "hw_model": hw_model,
        "mobility_class": _mobility_class(has_battery),
        "chip_arch": _run(["uname", "-m"]),
        "macos_version": _run(["sw_vers", "-productVersion"]),
        "claude_version": _run(["bash", "-lc", "claude --version"]),
        "claude_path": claude_path,
        "claude_install_method": _claude_install_method(claude_path),
        "python_venv_version": _run([venv_python, "--version"]),
        "chromadb_version": chromadb_version,
        "homebrew_present": bool(_run(["bash", "-lc", "which brew"])),
        "os": "macos",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _build_linux_profile() -> dict:
    """Same fields as the Macs where they mean something on Linux. The label is the hostname: a Mac Mini running
    Kali must not label its output "mac-mini", which is the M4 Mini's label."""
    hostname = _run(["hostname"])
    claude_path = _run(["bash", "-lc", "readlink -f $(which claude) 2>/dev/null || which claude"])
    venv_python = str(Path.home() / ".agents" / "venv" / "bin" / "python")
    return {
        "label": hostname or "linux",
        "hostname": hostname,
        "hardware_uuid": _hardware_uuid(),
        "serial": _serial(),
        "hw_model": _dmi("product_name"),
        "mobility_class": "stationary",
        "chip_arch": _run(["uname", "-m"]),
        "macos_version": "",
        "os": "linux",
        "os_version": _run(["uname", "-r"]),
        "claude_version": _run(["bash", "-lc", "claude --version"]),
        "claude_path": claude_path,
        "claude_install_method": _claude_install_method(claude_path),
        "python_venv_version": _run([venv_python, "--version"]),
        "homebrew_present": False,
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
    my_uuid = (load_or_build().get("hardware_uuid") or "").upper()
    for device_id, info in _load_registry().items():
        if my_uuid and (info.get("hardware_uuid") or "").upper() == my_uuid:
            return device_id
    return machine_label()  # not registered yet — fall back to the plain label


def remote_devices() -> dict:
    """All registered devices that aren't this one, keyed by device id."""
    my_id = registry_id()
    return {k: v for k, v in _load_registry().items() if k != my_id}


def remote_macs() -> dict:
    """Remote devices running macOS. For Mac-only checks (launchd, dashboard) and for anything that copies MARVIN's
    data out: mac-mini-2012 runs Linux and holds untrusted code (ADR 0069). An entry with no `os` predates the
    field and is a Mac; any other value is not."""
    return {k: v for k, v in remote_devices().items() if v.get("os", "macos") == "macos"}


if __name__ == "__main__":
    profile = build_profile()
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_PATH.write_text(json.dumps(profile, indent=2))
    print(json.dumps(profile, indent=2))
    print(f"\nWritten to {PROFILE_PATH}", file=sys.stderr)
