"""Per-OS lookups in one place, so the rest of MARVIN never hard-codes a Mac path.

MARVIN runs on macOS (the Macs) and Linux (mac-mini-2012, ADR 0069). Anything that differs between them
-- where a binary lives, what the OS is called -- is answered here. Named host_os, not platform, so it
never shadows the standard library's platform module.
"""
from __future__ import annotations

import shutil
import sys

MAC_TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
LINUX_TAILSCALE = "/usr/bin/tailscale"   # where the Debian/Kali package installs it


def os_name() -> str:
    """"macos", "linux", or "unknown"."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def tailscale_bin() -> str:
    """Absolute path to the Tailscale CLI. Absolute because launchd and systemd both run jobs with a bare PATH."""
    if os_name() == "macos":
        return MAC_TAILSCALE
    return shutil.which("tailscale") or LINUX_TAILSCALE
