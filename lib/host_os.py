"""Per-OS lookups in one place, so the rest of MARVIN never hard-codes a Mac path.

MARVIN runs on macOS (the Macs) and Linux (mac-mini-2012, ADR 0069). Anything that differs between them
-- where a binary lives, what the OS is called -- is answered here. Named host_os, not platform, so it
never shadows the standard library's platform module.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
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


# lsof: /usr/sbin on macOS, /usr/bin on Debian/Kali (mac-mini-2012). Absolute, for the same bare-PATH reason as tailscale.
LSOF_CANDIDATES = ["/usr/sbin/lsof", "/usr/bin/lsof"]


def lsof_bin() -> str | None:
    """Absolute path to lsof, or None. The cleanup sweep asks it what live processes use before removing anything;
    a Mac-only path made every folder on the Linux box read as unused (marvin#911)."""
    return next((p for p in LSOF_CANDIDATES if os.access(p, os.X_OK)), None) or shutil.which("lsof")


def memory_dir(home: Path | None = None) -> Path:
    """MARVIN's memory folder on this machine.

    The synced ~/.claude/settings.json names it in `autoMemoryDirectory` as the Macs' absolute path. Re-root the part
    after `.claude/` under THIS machine's ~/.claude, so mac-mini-2012 (home /home/marvin) reads the same synced memory
    the Macs write. A missing, malformed or out-of-tree setting falls back to Claude Code's own default for this home."""
    home = Path.home() if home is None else Path(home)
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


def boot_time() -> float | None:
    """Boot time in seconds since epoch, or None if unreadable.
    macOS: via sysctl kern.boottime; Linux: via /proc/stat or who -b."""
    try:
        if os_name() == "macos":
            proc = subprocess.run(["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                output = proc.stdout.strip()
                if output.startswith("{ sec = "):
                    sec_str = output.split("sec = ")[1].split(",")[0]
                    return float(sec_str)
        elif os_name() == "linux":
            proc = subprocess.run(["who", "-b"], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                from datetime import datetime
                lines = [l for l in proc.stdout.splitlines() if "system boot" in l]
                if lines:
                    parts = lines[0].split()
                    if len(parts) >= 3:
                        date_str = " ".join(parts[-2:])
                        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
                        return dt.timestamp()
    except Exception:
        pass
    return None


def process_start_time(pid: int) -> float | None:
    """Start time (seconds since epoch) for a process, or None if unreadable or dead.
    macOS: via ps; Linux: via /proc/<pid>/stat."""
    if not isinstance(pid, int) or pid <= 0:
        return None
    try:
        if os_name() == "macos":
            proc = subprocess.run(["ps", "-o", "lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0 and proc.stdout.strip():
                from datetime import datetime
                dt = datetime.strptime(proc.stdout.strip(), "%a %b %d %H:%M:%S %Y")
                return dt.timestamp()
        elif os_name() == "linux":
            with open(f"/proc/{pid}/stat", "r") as f:
                parts = f.read().split()
                if len(parts) > 21:
                    from datetime import datetime
                    uptime_seconds = float(open("/proc/uptime").read().split()[0])
                    jiffies = int(parts[21])
                    tick = os.sysconf("SC_CLK_TCK")
                    process_start_jiffies = jiffies / tick
                    boot_t = boot_time()
                    if boot_t is not None:
                        return boot_t + (uptime_seconds - process_start_jiffies)
    except Exception:
        pass
    return None
