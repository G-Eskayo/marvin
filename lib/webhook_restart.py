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
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
LAUNCHD_LABEL = "com.marvin.dashboard-webhook"
ATTEMPT_FILE = HOME / ".claude" / "logs" / "webhook-restart-attempt"
LOG_FILE = HOME / ".claude" / "logs" / "webhook-restart.log"
MERGE_INFLIGHT_FILE = HOME / ".claude" / "logs" / "merge-inflight.json"

# Only these go into the webhook server's concerns. dashboard/src and
# dashboard/electron/preload are for the Electron app only.
WEBHOOK_SOURCE_PATHS = ("dashboard/webhook-server", "dashboard/electron/main")

SETTLE_SECONDS = 60              # let a fresh change settle before restarting
BACKOFF_SECONDS = 6 * 3600       # minimum gap between attempts


def merge_inflight(path=MERGE_INFLIGHT_FILE, max_age_ms=30*60*1000) -> bool:
    """Read merge-inflight.json and return True if an active merge is in flight, False otherwise.
    Entries older than max_age_ms (default 30 min) are treated as stale and ignored.
    Entries with stage=='done' are treated as completed (removal is pending) and ignored.
    Fails open: missing, malformed, or non-dict → False."""
    try:
        now = int(time.time() * 1000)
        with open(path) as f:
            data = json.load(f)
        if not (isinstance(data, dict) and data):
            return False
        # Only count if a merge is actively running and recent.
        # Skip done/stale entries that might still be in the file.
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            # Ignore if the merge is marked done (in-flight removal is pending)
            if entry.get("stage") == "done":
                continue
            # If startedAt is present, skip if it's older than 30 min.
            # If startedAt is missing, treat as active (fail-open: assume merge is in progress).
            if "startedAt" in entry:
                age_ms = now - entry["startedAt"]
                if age_ms >= max_age_ms:
                    continue
            return True
        return False
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def decide(*, server_start_ts, webhook_commit_ts, last_attempt_ts, now, merge_inflight_flag=False, immediate=False) -> tuple[str, str]:
    """('restart' | 'skip', reason)."""
    if webhook_commit_ts is None:
        return "skip", "no webhook commit to compare against"
    if last_attempt_ts is not None and now - last_attempt_ts < BACKOFF_SECONDS:
        return "skip", "backing off after a recent restart attempt"
    if server_start_ts is None:
        return "restart", "webhook server is not running"
    if merge_inflight_flag:
        return "skip", "a merge is in flight; will retry once it ends"
    if server_start_ts >= webhook_commit_ts:
        return "skip", "server is current"
    if not immediate and now - webhook_commit_ts < SETTLE_SECONDS:
        return "skip", "latest webhook change is too fresh -- letting it settle"
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
                last_attempt_ts=_mtime(ATTEMPT_FILE), merge_inflight_flag=merge_inflight(), now=now)


def main() -> None:
    import job_events
    # Check for --immediate flag: merge-ending trigger bypasses the settle check
    immediate = "--immediate" in sys.argv

    with job_events.job_run("webhook-restart", "Webhook server restart check") as run:
        now = int(time.time())
        run.step("Checking", "is the webhook server behind the code?")

        # Pull fresh code from the agents repo before checking staleness
        run.step("Syncing", f"running code_sync.py pull ~/.agents")
        try:
            result = subprocess.run([sys.executable, str(Path(__file__).parent / "code_sync.py"), "pull", str(HOME / ".agents")],
                                   capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                run.step("Syncing", f"pull completed with exit code {result.returncode}; proceeding")
        except (subprocess.SubprocessError, OSError) as e:
            run.step("Syncing", f"pull failed ({e}); proceeding with existing repo state")

        facts = _facts(now)
        action, reason = decide(**facts, immediate=immediate)
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
