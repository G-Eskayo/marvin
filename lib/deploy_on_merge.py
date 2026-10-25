#!/usr/bin/env python3
"""Cross-Mac deploy on merge (ticket #329).

When a PR merges, the local machine rebuilds its dashboard app. But the other Mac
silently drifts because it only rebuilds when a merge happens *on that machine*.
This module debounces rapid merges and dispatches a fixed sync+restart command
to remote machines via task_dispatch, making both machines current within 2 minutes
instead of waiting 30 minutes for the cron job.

Entry point: deploy_on_merge(<device_id>) called once per remote device by merge.js.
Logic: file-based debounce lock (per-device), dispatch via task_dispatch (async),
recording via job_events (for dashboard visibility).
"""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task_dispatch  # noqa: E402
import job_events  # noqa: E402

DEBOUNCE_SECONDS = 120  # 2-minute window: rapid bursts of merges batch together


def _acquire_lock(path: Path) -> bool:
    """Atomically create lock file. Return True on success, False if already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        os.close(fd)
        return True
    except FileExistsError:
        return False


def deploy_on_merge(device_id: str) -> bool:
    """Try to dispatch deploy-on-merge to a remote device.

    Returns True if dispatched, False if debounced (already scheduled in window).
    Does not raise; dispatch failures are logged via job_events.fail() instead.
    """
    lock_path = HOME / ".claude" / "dispatch" / f"deploy-pending-{device_id}.lock"

    with job_events.job_run("deploy-on-merge", f"Cross-Mac deploy trigger for {device_id}") as run:
        if not _acquire_lock(lock_path):
            run.step("Debounced", f"deploy already pending for {device_id} within {DEBOUNCE_SECONDS}s window")
            return False

        run.step("Dispatching", f"syncing code + restarting services on {device_id}")

        # Fixed command (no interpolation from any input, closing command-injection risk).
        remote_cmd = "cd ~/.agents && venv/bin/python lib/code_sync.py pull && venv/bin/python lib/webhook_restart.py --settle 120 && venv/bin/python lib/dashboard_rebuild.py --settle 120"

        result = task_dispatch.dispatch(
            remote_cmd,
            target=device_id,
            mode="async",
            task_label=f"deploy-on-merge: {device_id}"
        )

        if result.ok:
            run.step("Dispatched", f"async task sent to {device_id}")
            run.summary(f"dispatched to {device_id}")
            return True
        else:
            run.fail(f"dispatch failed for {device_id}: {result.error}")
            run.summary(f"dispatch failed: {result.error}")
            return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: deploy_on_merge.py <device_id>", file=sys.stderr)
        sys.exit(2)
    device_id = sys.argv[1]
    success = deploy_on_merge(device_id)
    sys.exit(0 if success else 1)
