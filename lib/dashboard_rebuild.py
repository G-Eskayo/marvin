#!/usr/bin/env python3
"""Rebuild the installed MARVIN Metrics dashboard app when it falls behind the code.

The app is a native build in /Applications that was only ever rebuilt by the merge
webhook on the machine where a merge happened (webhook-server/merge.js), so every
other machine silently drifted -- on 2026-10-02 the laptop's app was a month old,
lacked the device-aware webhook host, and routed Approve to the wrong place.
Health (health_checks.py) reports the staleness; this runs from the 30-minute
code-sync cycle and fixes it so nobody has to notice.

Conservative on purpose: waits for a fresh change to settle, doesn't interrupt a
running app for a small gap (but does once it is a day behind), and backs off after
an attempt so a broken build can't loop. `decide` is pure; `main` gathers the facts.
"""
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
APP_ASAR = Path("/Applications/MARVIN Metrics.app/Contents/Resources/app.asar")
SCRIPT = HOME / ".agents" / "dashboard" / "scripts" / "rebuild_and_install.sh"
ATTEMPT_FILE = HOME / ".claude" / "logs" / "dashboard-rebuild-attempt"
LOG_FILE = HOME / ".claude" / "logs" / "dashboard-rebuild.log"

# Only these go into the installed app. webhook-server/ is a separate launchd node
# process and test/ never ships, so changes there must not trigger a rebuild.
APP_SOURCE_PATHS = ("dashboard/src", "dashboard/electron", "dashboard/index.html", "dashboard/package.json",
                    "dashboard/package-lock.json", "dashboard/electron.vite.config.js",
                    "dashboard/tailwind.config.js", "dashboard/postcss.config.js")

SETTLE_SECONDS = 2 * 3600        # let a fresh change finish landing before building
FORCE_AFTER_SECONDS = 24 * 3600  # rebuild even a running app once this far behind
BACKOFF_SECONDS = 6 * 3600       # minimum gap between attempts


def decide(*, app_built_ts, dashboard_commit_ts, app_running, last_attempt_ts, now) -> tuple[str, str]:
    """('rebuild' | 'skip', reason)."""
    if dashboard_commit_ts is None:
        return "skip", "no dashboard commit to compare against"
    if last_attempt_ts is not None and now - last_attempt_ts < BACKOFF_SECONDS:
        return "skip", "backing off after a recent rebuild attempt"
    if app_built_ts is None:
        return "rebuild", "no dashboard app installed"
    if app_built_ts >= dashboard_commit_ts:
        return "skip", "installed app is current"
    if now - dashboard_commit_ts < SETTLE_SECONDS:
        return "skip", "latest dashboard change is too fresh -- letting it settle"
    behind = now - app_built_ts
    if app_running and behind < FORCE_AFTER_SECONDS:
        return "skip", "app is running and only slightly behind -- not interrupting"
    return "rebuild", f"installed app is {behind / 3600:.0f}h behind the latest dashboard change"


def _mtime(path: Path):
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


def _facts(now: int) -> dict:
    newest = subprocess.run(["git", "-C", str(HOME / ".agents"), "log", "-1", "--format=%ct", "--", *APP_SOURCE_PATHS],
                            capture_output=True, text=True).stdout.strip()
    running = subprocess.run(["pgrep", "-f", "MARVIN Metrics.app/Contents/MacOS"], capture_output=True).returncode == 0
    return dict(app_built_ts=_mtime(APP_ASAR), dashboard_commit_ts=int(newest) if newest.isdigit() else None,
                app_running=running, last_attempt_ts=_mtime(ATTEMPT_FILE), now=now)


def main() -> None:
    now = int(time.time())
    action, reason = decide(**_facts(now))
    print(f"[dashboard-rebuild] {action}: {reason}", file=sys.stderr)
    if action != "rebuild":
        return
    ATTEMPT_FILE.parent.mkdir(parents=True, exist_ok=True)
    ATTEMPT_FILE.write_text(str(now))  # recorded BEFORE building so a failure still backs off
    env_path = f"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{HOME}/.local/bin"
    with LOG_FILE.open("a") as log:
        subprocess.Popen(["/bin/bash", str(SCRIPT)], stdout=log, stderr=log, env={"HOME": str(HOME), "PATH": env_path},
                         start_new_session=True)


if __name__ == "__main__":
    main()
