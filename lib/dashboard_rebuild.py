#!/usr/bin/env python3
"""Rebuild the installed MARVIN dashboard app when it falls behind the code.

The app is a native build in /Applications that was only ever rebuilt by the merge
webhook on the machine where a merge happened (webhook-server/merge.js), so every
other machine silently drifted -- on 2026-10-02 the laptop's app was a month old,
lacked the device-aware webhook host, and routed Approve to the wrong place.
Health (health_checks.py) reports the staleness; this runs from the 30-minute
code-sync cycle and fixes it so nobody has to notice.

#443 (2026-10-14): merges made on GitHub never reached the app -- this ran every 30 minutes with a 15-minute
settle, wouldn't interrupt an open app, and backed off 6 hours after ANY attempt. Now it also runs the moment the
webhook server's change watch sees G-Eskayo/marvin change (any merge path), compares against origin/main, settles for
2 minutes, rebuilds even an open app (the install relaunches it), never runs two builds at once, and backs off only
after a FAILED build -- until newer code lands, so the next merge (usually the fix) retries at once.
`decide` is pure; `main` gathers the facts.
"""
from __future__ import annotations
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
APP_ASAR = Path("/Applications/MARVIN.app/Contents/Resources/app.asar")  # renamed from "MARVIN Metrics.app" (#442)
SCRIPT = HOME / ".agents" / "dashboard" / "scripts" / "rebuild_and_install.sh"
FAILED_FILE = HOME / ".claude" / "logs" / "dashboard-rebuild-failed"  # written by the script on failure, cleared on success
LOG_FILE = HOME / ".claude" / "logs" / "dashboard-rebuild.log"

# Only these go into the installed app. webhook-server/ is a separate launchd node
# process and test/ never ships, so changes there must not trigger a rebuild.
APP_SOURCE_PATHS = ("dashboard/src", "dashboard/electron", "dashboard/index.html", "dashboard/package.json",
                    "dashboard/package-lock.json", "dashboard/electron.vite.config.js",
                    "dashboard/tailwind.config.js", "dashboard/postcss.config.js", "dashboard/resources")

SETTLE_SECONDS = 2 * 60          # let a merge (and any follow-up push) finish landing before building
RETRY_FAILED_AFTER = 6 * 3600    # a failure on the same code is retried after this, in case it was transient


def decide(*, app_built_ts, dashboard_commit_ts, rebuild_running, last_failure_ts, now) -> tuple[str, str]:
    """('rebuild' | 'skip', reason)."""
    if dashboard_commit_ts is None:
        return "skip", "no dashboard commit to compare against"
    if rebuild_running:
        return "skip", "a rebuild is already running"
    if app_built_ts is not None and app_built_ts >= dashboard_commit_ts:
        return "skip", "installed app is current"
    if now - dashboard_commit_ts < SETTLE_SECONDS:
        return "skip", "latest dashboard change is too fresh -- letting it settle"
    if last_failure_ts is not None and last_failure_ts >= dashboard_commit_ts and now - last_failure_ts < RETRY_FAILED_AFTER:
        return "skip", "the last build of this code failed -- waiting for newer code (or a retry later)"
    if app_built_ts is None:
        return "rebuild", "no dashboard app installed"
    return "rebuild", f"installed app is {(now - app_built_ts) / 3600:.1f}h behind the latest dashboard change"


def _mtime(path: Path):
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


def _facts(now: int) -> dict:
    agents = str(HOME / ".agents")
    # A GitHub-side merge isn't in the local checkout until code-sync pulls, so judge against origin/main.
    subprocess.run(["git", "-C", agents, "fetch", "-q", "origin", "main"], capture_output=True)
    newest = subprocess.run(["git", "-C", agents, "log", "-1", "--format=%ct", "origin/main", "--", *APP_SOURCE_PATHS],
                            capture_output=True, text=True).stdout.strip()
    running = subprocess.run(["pgrep", "-f", "rebuild_and_install.sh"], capture_output=True).returncode == 0
    return dict(app_built_ts=_mtime(APP_ASAR), dashboard_commit_ts=int(newest) if newest.isdigit() else None,
                rebuild_running=running, last_failure_ts=_mtime(FAILED_FILE), now=now)


def main() -> None:
    import job_events
    with job_events.job_run("dashboard-rebuild", "Dashboard app rebuild check") as run:
        now = int(time.time())
        run.step("Checking", "is the installed app behind the code?")
        action, reason = decide(**_facts(now))
        print(f"[dashboard-rebuild] {action}: {reason}", file=sys.stderr)
        run.step("Decision", f"{action}: {reason}")
        run.summary(f"{action}: {reason}")
        if action != "rebuild":
            return
        env_path = f"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{HOME}/.local/bin"
        run.step("Rebuilding", "build + install running in the background (log: ~/.claude/logs/dashboard-rebuild.log)")
        with LOG_FILE.open("a") as log:
            subprocess.Popen(["/bin/bash", str(SCRIPT)], stdout=log, stderr=log, env={"HOME": str(HOME), "PATH": env_path},
                             start_new_session=True)


if __name__ == "__main__":
    main()
