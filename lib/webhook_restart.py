#!/usr/bin/env python3
"""Restart the webhook-server node process when its code changes.

The webhook-server (launchd job com.marvin.dashboard-webhook) is a long-running
node process that directly imports from ../electron/main. When #258 moved
portfolio.js, the webhook-server's already-loaded module graph kept the stale
path until a manual launchctl kickstart -k force-restart. Health (health_checks.py)
reports the staleness; this runs from the 30-minute code-sync cycle and fixes it
so nobody has to notice.

Conservative on purpose: waits for a fresh change to settle, backs off after an
attempt so a failed restart can't loop. `decide` is pure; `main` gathers facts.
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
LAUNCHD_LABEL = "com.marvin.dashboard-webhook"
ATTEMPT_FILE = HOME / ".claude" / "logs" / "webhook-restart-attempt"
LOG_FILE = HOME / ".claude" / "logs" / "webhook-restart.log"

# Only these go into the webhook server's concerns. dashboard/src and
# dashboard/electron/preload are for the Electron app only.
WEBHOOK_SOURCE_PATHS = ("dashboard/webhook-server", "dashboard/electron/main")

SETTLE_SECONDS = 60              # let a fresh change settle before restarting
BACKOFF_SECONDS = 6 * 3600       # minimum gap between attempts


def decide(*, server_start_ts, webhook_commit_ts, last_attempt_ts, now, force_relaunch=False) -> tuple[str, str]:
    """('restart' | 'skip', reason)."""
    if webhook_commit_ts is None:
        return "skip", "no webhook commit to compare against"
    if server_start_ts is None:
        return "restart", "webhook server is not running"
    if server_start_ts >= webhook_commit_ts:
        return "skip", "server is current"
    if now - webhook_commit_ts < SETTLE_SECONDS:
        return "skip", "latest webhook change is too fresh -- letting it settle"
    # Check backoff AFTER settle, so a failed restart still backs off even with a fresh commit
    if last_attempt_ts is not None and now - last_attempt_ts < BACKOFF_SECONDS:
        return "skip", "backing off after a recent restart attempt"
    behind = now - server_start_ts
    return "restart", f"server started {behind / 3600:.0f}h ago, {(webhook_commit_ts - server_start_ts) / 3600:.0f}h behind the latest code change"


def _mtime(path: Path):
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


def _facts(now: int) -> dict:
    # Get newest commit touching webhook paths
    newest = subprocess.run(["git", "-C", str(HOME / ".agents"), "log", "-1", "--format=%ct", "--", *WEBHOOK_SOURCE_PATHS],
                            capture_output=True, text=True).stdout.strip()

    # Get webhook server start time via launchctl list and ps
    server_start_ts = None
    try:
        launchctl_output = subprocess.run(["launchctl", "list"], capture_output=True, text=True).stdout
        for line in launchctl_output.splitlines():
            parts = line.split()
            if len(parts) >= 3 and LAUNCHD_LABEL in parts[2]:
                pid_str = parts[0]
                if pid_str.isdigit():
                    pid = int(pid_str)
                    ps_output = subprocess.run(["ps", "-o", "etimes=", "-p", str(pid)],
                                              capture_output=True, text=True).stdout.strip()
                    if ps_output and ps_output.isdigit():
                        elapsed_secs = int(ps_output)
                        server_start_ts = now - elapsed_secs
                break
    except (subprocess.SubprocessError, ValueError, OSError):
        pass

    return dict(server_start_ts=server_start_ts, webhook_commit_ts=int(newest) if newest.isdigit() else None,
                last_attempt_ts=_mtime(ATTEMPT_FILE), now=now)


def main(force_relaunch: bool = False) -> None:
    import argparse
    import job_events

    # Parse --force-relaunch flag if running as __main__
    if force_relaunch is False:  # Default value, check for CLI args
        parser = argparse.ArgumentParser()
        parser.add_argument("--force-relaunch", action="store_true", help="skip 'too fresh' guard (debounce and backoff still apply)")
        args = parser.parse_args()
        force_relaunch = args.force_relaunch

    with job_events.job_run("webhook-restart", "Webhook server restart check") as run:
        now = int(time.time())
        action, reason = decide(**_facts(now), force_relaunch=force_relaunch)
        print(f"[webhook-restart] {action}: {reason}", file=sys.stderr)
        run.step("Decision", f"{action}: {reason}")
        run.summary(f"{action}: {reason}")
        if action != "restart":
            return
        ATTEMPT_FILE.parent.mkdir(parents=True, exist_ok=True)
        ATTEMPT_FILE.write_text(str(now))  # recorded BEFORE restarting so a failure still backs off
        uid = os.getuid()
        run.step("Restarting", f"launchctl kickstart -k gui/{uid}/{LAUNCHD_LABEL}")
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a") as log:
            subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LAUNCHD_LABEL}"],
                          stdout=log, stderr=log)


if __name__ == "__main__":
    main()
