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

# Only these go into the webhook server's concerns. dashboard/src and
# dashboard/electron/preload are for the Electron app only.
WEBHOOK_SOURCE_PATHS = ("dashboard/webhook-server", "dashboard/electron/main")

SETTLE_SECONDS = 60              # let a fresh change settle before restarting
BACKOFF_SECONDS = 6 * 3600       # minimum gap between attempts
MERGE_WAIT_TIMEOUT_S = 15 * 60   # max time to wait for merge to complete before restarting (see GATE_TIMEOUT_MS = 40 min in merge.js:818; awaits decision "wait-bound" in #1106)


def decide(*, server_start_ts, webhook_commit_ts, last_attempt_ts, now) -> tuple[str, str]:
    """('restart' | 'skip', reason)."""
    if webhook_commit_ts is None:
        return "skip", "no webhook commit to compare against"
    if last_attempt_ts is not None and now - last_attempt_ts < BACKOFF_SECONDS:
        return "skip", "backing off after a recent restart attempt"
    if server_start_ts is None:
        return "restart", "webhook server is not running"
    if server_start_ts >= webhook_commit_ts:
        return "skip", "server is current"
    if now - webhook_commit_ts < SETTLE_SECONDS:
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
                last_attempt_ts=_mtime(ATTEMPT_FILE), now=now)


def merge_running(host: str = "localhost", port: int = 7878, timeout_s: float = 5, exec=None) -> bool:
    """Check if a merge is currently running on the webhook server.

    Returns True if any repo in the merge queue has a running merge, False otherwise.
    Handles network errors, timeouts, and malformed JSON gracefully.
    """
    if exec is None:
        exec = lambda cmd, *args, **kw: subprocess.run(
            [cmd] + list(args),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            **{k: v for k, v in kw.items() if k != "timeout"}
        ).stdout

    try:
        url = f"http://{host}:{port}/merge-queue"
        response = exec("curl", "-s", "--max-time", str(int(timeout_s)), url)
        data = json.loads(response)
        repos = data.get("repos", {})
        for repo_info in repos.values():
            if repo_info.get("running") is not None:
                return True
        return False
    except (json.JSONDecodeError, KeyError, ValueError, TimeoutError, Exception):
        return False


def wait_for_merge_idle(timeout_s: float, poll_s: float, check=merge_running, sleep=time.sleep, now=time.monotonic) -> tuple[bool, float]:
    """Wait for merge queue to become idle.

    Polls at intervals until merge is not running, or timeout is exceeded.
    Returns (success, elapsed_seconds).
    """
    start = now()
    while True:
        if not check():
            return (True, now() - start)
        elapsed = now() - start
        if elapsed >= timeout_s:
            return (False, elapsed)
        time_until_timeout = timeout_s - elapsed
        sleep(min(poll_s, time_until_timeout))


def restart_now(reason: str, wait_timeout_s: float = 10, wait_func=None, restart_func=None, log_func=None) -> None:
    """Restart the webhook server, optionally waiting for merge to complete first.

    Logs the outcome to LOG_FILE, then restarts launchctl unconditionally.
    """
    if wait_func is None:
        wait_func = wait_for_merge_idle
    if restart_func is None:
        def _restart():
            uid = os.getuid()
            subprocess.run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LAUNCHD_LABEL}"])
        restart_func = _restart
    if log_func is None:
        def _log(msg):
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with LOG_FILE.open("a") as log:
                log.write(msg + "\n")
        log_func = _log

    success, elapsed = wait_func(timeout_s=wait_timeout_s, poll_s=1, check=merge_running, sleep=time.sleep, now=time.monotonic)
    if success:
        log_func(f"[restart-now] waited {elapsed:.1f}s for merge to complete before restarting: {reason}")
    else:
        log_func(f"[restart-now] gave up waiting for merge after {elapsed:.1f}s (timeout {wait_timeout_s}s), restarting anyway: {reason}")

    restart_func()


def main() -> None:
    import argparse
    import job_events

    parser = argparse.ArgumentParser(description="Restart the webhook-server process")
    parser.add_argument("--force", action="store_true", help="Force restart immediately, bypassing staleness/backoff checks")
    parser.add_argument("--reason", type=str, help="Reason for the restart (used with --force)")
    args = parser.parse_args()

    if args.force:
        if not args.reason:
            print("[webhook-restart] --force requires --reason", file=sys.stderr)
            sys.exit(1)
        restart_now(args.reason, wait_timeout_s=MERGE_WAIT_TIMEOUT_S)
        return

    with job_events.job_run("webhook-restart", "Webhook server restart check") as run:
        now = int(time.time())
        run.step("Checking", "is the webhook server behind the code?")
        action, reason = decide(**_facts(now))
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
