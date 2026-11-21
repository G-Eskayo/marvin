#!/usr/bin/env python3
"""Wait for an in-progress merge to finish, then restart the merge server.

When the dashboard rebuilds (rebuild_and_install.sh), the merge server process restarts
unconditionally. If a merge is in progress, the gate's scratch worktree and merge state die
with it. This helper waits for the merge to finish (polling /merge-queue), then allows the
restart to proceed. If the merge takes too long (exceeds a bound), we restart anyway and let
the queue's resume() mechanism re-add it.

Conservative: uses a monotonic clock, retries failed probes once, never blocks forever.
Mirrors lib/webhook_restart.py's pure decide() + _facts() + main() pattern.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import health_checks  # noqa: E402

HOST = "localhost"
PORT = health_checks.MERGE_PORT
PROBE_TIMEOUT_S = 6  # Longer than MERGE_PROBE_TIMEOUT_S (3s); busy gate can be slow to answer
RETRY_PROBE = True
POLL_INTERVAL_S = 5
WAIT_BOUND_S = 45 * 60  # maxMergingMs (dashboard/electron/main/merge_ops.js:15)


def _merge_running(host: str = HOST, port: int = PORT, timeout: float = PROBE_TIMEOUT_S, retries: int = 1) -> bool:
    """GET /merge-queue, parse {repos}, True if any repo's 'running' is set.

    Retries once on network/timeout errors before failing open to False.
    Returns False on malformed JSON, unreachable server, or HTTP error.
    """
    for attempt in range(max(1, retries)):
        try:
            url = f"http://{host}:{port}/merge-queue"
            response = urllib.request.urlopen(url, timeout=timeout)
            body = response.read().decode('utf-8')
            response.close()

            data = json.loads(body)
            repos = data.get("repos", {})

            # True if any repo has a running merge
            for repo_data in repos.values():
                if isinstance(repo_data, dict) and repo_data.get("running"):
                    return True
            return False
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, ValueError, json.JSONDecodeError):
            if attempt < retries - 1:
                continue  # retry once
            return False
    return False


def decide(*, running: bool, waited_s: float, bound_s: float = WAIT_BOUND_S) -> tuple[str, str]:
    """('wait' | 'restart', reason).

    Waits while a merge is running and under the bound. Restarts if no merge is
    running or if the bound is reached (never blocks forever).
    """
    if not running:
        return "restart", "no merge is running"
    if waited_s >= bound_s:
        return "restart", f"merge is still running after {waited_s / 60:.0f}m (bound is {bound_s / 60:.0f}m) — restarting anyway"
    return "wait", f"merge is running, waited {waited_s:.0f}s of {bound_s:.0f}s"


def main() -> None:
    """Poll /merge-queue until a merge finishes or the wait bound is hit, then exit 0.

    Uses a monotonic clock so the bound accounts for probe time, not just sleep time.
    """
    import job_events

    with job_events.job_run("merge-server-wait", "Wait for in-progress merge before restarting") as run:
        start_time = time.monotonic()
        poll_count = 0

        while True:
            elapsed = time.monotonic() - start_time
            running = _merge_running(host=HOST, port=PORT, timeout=PROBE_TIMEOUT_S, retries=RETRY_PROBE and 2 or 1)
            poll_count += 1

            action, reason = decide(running=running, waited_s=elapsed, bound_s=WAIT_BOUND_S)
            run.step(f"Poll {poll_count}", f"{reason}")

            if action == "restart":
                print(f"[merge-server-wait] {action}: {reason}", file=sys.stderr)
                run.summary(f"{action}: {reason}")
                return

            time.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    main()
