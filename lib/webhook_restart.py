#!/usr/bin/env python3
"""Restart the webhook-server node process when its code changes.

The webhook-server (launchd job com.marvin.dashboard-webhook) is a long-running
node process that directly imports from ../electron/main. When #258 moved
portfolio.js, the webhook-server's already-loaded module graph kept the stale
path until a manual launchctl kickstart -k force-restart. Health (health_checks.py)
reports the staleness; this runs from the 30-minute code-sync cycle and fixes it
so nobody has to notice.

Merge-safe: a deferred restart waits for merge-in-flight to finish, then retries.
Conservative on purpose: waits for a fresh change to settle, backs off only after
a failed restart. `decide` is pure; `main` gathers facts. Mirrors dashboard_rebuild.py.
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
FAILED_FILE = HOME / ".claude" / "logs" / "webhook-restart-failed"
LOG_FILE = HOME / ".claude" / "logs" / "webhook-restart.log"

# Only these go into the webhook server's concerns. dashboard/src and
# dashboard/electron/preload are for the Electron app only.
WEBHOOK_SOURCE_PATHS = ("dashboard/webhook-server", "dashboard/electron/main")

SETTLE_SECONDS = 60              # let a fresh change settle before restarting
RETRY_FAILED_AFTER = 6 * 3600    # a failure on the same code is retried after this
GATE_CLONE_MAX_AGE_MS = 2 * 60 * 60_000 / 1000  # 2h, convert to seconds


def decide(*, server_start_ts, webhook_commit_ts, restart_running, last_failure_ts, merge_inflight, now) -> tuple[str, str]:
    """('restart' | 'skip', reason)."""
    if webhook_commit_ts is None:
        return "skip", "no webhook commit to compare against"
    if restart_running:
        return "skip", "a restart is already running"
    if merge_inflight:
        return "wait", "a merge is in flight; restarting now would cut it off"
    if server_start_ts is not None and server_start_ts >= webhook_commit_ts:
        return "skip", "server is current"
    if now - webhook_commit_ts < SETTLE_SECONDS:
        return "skip", "latest webhook change is too fresh -- letting it settle"
    if last_failure_ts is not None and last_failure_ts >= webhook_commit_ts and now - last_failure_ts < RETRY_FAILED_AFTER:
        return "skip", "the last restart of this code failed -- waiting for newer code (or a retry later)"
    if server_start_ts is None:
        return "restart", "webhook server is not running"
    behind = now - server_start_ts
    return "restart", f"server started {behind / 3600:.0f}h ago, {(webhook_commit_ts - server_start_ts) / 3600:.0f}h behind the latest code change"


def _mtime(path: Path):
    try:
        return int(path.stat().st_mtime)
    except OSError:
        return None


def _merge_inflight(now: int) -> bool:
    inflight_path = HOME / ".claude" / "logs" / "merge-inflight.json"
    try:
        with open(inflight_path) as f:
            data = json.load(f)
            if not isinstance(data, dict):
                return False
            for entry in data.values():
                if not isinstance(entry, dict):
                    continue
                started_at = entry.get("startedAt")
                if isinstance(started_at, (int, float)):
                    age_secs = (now * 1000 - started_at) / 1000
                    if age_secs < GATE_CLONE_MAX_AGE_MS:
                        return True
            return False
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def _restart_running() -> bool:
    try:
        return subprocess.run(["pgrep", "-f", "launchctl kickstart.*dashboard-webhook"],
                            capture_output=True).returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


def _facts(now: int) -> dict:
    agents = str(HOME / ".agents")
    # A GitHub-side merge isn't in the local checkout until code-sync pulls, so judge against origin/main.
    subprocess.run(["git", "-C", agents, "fetch", "-q", "origin", "main"], capture_output=True)
    newest = subprocess.run(["git", "-C", agents, "log", "-1", "--format=%ct", "origin/main", "--", *WEBHOOK_SOURCE_PATHS],
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
                restart_running=_restart_running(), last_failure_ts=_mtime(FAILED_FILE),
                merge_inflight=_merge_inflight(now), now=now)


def main() -> None:
    import job_events
    with job_events.job_run("webhook-restart", "Webhook server restart check") as run:
        now = int(time.time())
        run.step("Checking", "is the webhook server behind the code?")

        facts = _facts(now)
        if not facts["merge_inflight"]:
            run.step("Syncing", "pulling latest code before checking")
            pull_ok = True
            try:
                import code_sync
                code_sync.pull(HOME / ".agents")
            except Exception as e:
                print(f"[webhook-restart] code_sync.pull failed: {e}", file=sys.stderr)
                run.step("Sync failed", f"skipping restart: {e}")
                pull_ok = False
            if not pull_ok:
                return
            facts = _facts(now)
        else:
            run.step("Waiting", "a merge is in flight -- skipping pull, will retry when it finishes")

        action, reason = decide(**facts)
        print(f"[webhook-restart] {action}: {reason}", file=sys.stderr)
        run.step("Decision", f"{action}: {reason}")
        run.summary(f"{action}: {reason}")
        if action != "restart":
            return
        uid = os.getuid()
        run.step("Restarting", f"launchctl kickstart -k gui/{uid}/{LAUNCHD_LABEL}")
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LAUNCHD_LABEL}"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        with LOG_FILE.open("a") as log:
            log.write(result.stdout)
            log.write(result.stderr)
        if result.returncode != 0:
            FAILED_FILE.parent.mkdir(parents=True, exist_ok=True)
            FAILED_FILE.write_text(str(now))
            run.step("Failed", f"exit code {result.returncode} -- recorded failure for backoff")


if __name__ == "__main__":
    main()
