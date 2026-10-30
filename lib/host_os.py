"""Per-OS lookups in one place, so the rest of MARVIN never hard-codes a Mac path.

MARVIN runs on macOS (the Macs) and Linux (mac-mini-2012, ADR 0069). Anything that differs between them
-- where a binary lives, what the OS is called -- is answered here. Named host_os, not platform, so it
never shadows the standard library's platform module.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

MAC_TAILSCALE = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
LINUX_TAILSCALE = "/usr/bin/tailscale"   # where the Debian/Kali package installs it
# Every place a Tailscale CLI may live, in the order to try: the app (the MacBook), Homebrew on Apple silicon (the Mac
# mini since 2026-10-26, no app) and on Intel, then the Linux package. The ONE list (marvin#889: peer_care had its own
# and host_os was app-only, so the Mini read every peer as offline for four days). peer_care's remote restart uses it too.
TAILSCALE_CANDIDATES = [MAC_TAILSCALE, "/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale", LINUX_TAILSCALE]


def os_name() -> str:
    """"macos", "linux", or "unknown"."""
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    return "unknown"


def tailscale_bin() -> str | None:
    """Absolute path to this machine's Tailscale CLI, or None when there isn't one. Absolute because launchd and
    systemd both run jobs with a bare PATH: the first executable candidate wins, then PATH."""
    return next((t for t in TAILSCALE_CANDIDATES if os.access(t, os.X_OK)), None) or shutil.which("tailscale")


def tailscale_bin_or_default() -> str:
    """tailscale_bin(), or the usual path for this OS when none is installed, so a caller's error names a real place."""
    return tailscale_bin() or (MAC_TAILSCALE if os_name() == "macos" else LINUX_TAILSCALE)


def memory_dir() -> Path:
    """MARVIN's memory folder on this machine.

    The synced ~/.claude/settings.json names it in `autoMemoryDirectory` as the Macs' absolute path. Re-root the part
    after `.claude/` under THIS machine's ~/.claude, so mac-mini-2012 (home /home/marvin) reads the same synced memory
    the Macs write. A missing, malformed or out-of-tree setting falls back to Claude Code's own default for this home."""
    home = Path.home()
    claude = home / ".claude"
    default = claude / "projects" / str(home).replace("/", "-") / "memory"
    try:
        value = json.loads((claude / "settings.json").read_text()).get("autoMemoryDirectory")
    except (OSError, ValueError, AttributeError):
        return default
    if not isinstance(value, str) or "/.claude/" not in value:
        return default
    rel = Path(value.split("/.claude/", 1)[1])
    if rel.is_absolute() or ".." in rel.parts:
        return default
    return claude / rel
