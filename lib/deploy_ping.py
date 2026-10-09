#!/usr/bin/env python3
"""After a marvin-repo merge, ping other Macs to pull the code and rebuild.

Fire-and-forget: errors are logged but never block the merge or undo its success.
Runs from merge.js when a PR merges to main. On each reachable remote device:
  1. code_sync.py pull ~/.agents (immediate)
  2. code_sync.py pull ~/.claude (immediate)
  3. dashboard_rebuild.py (delayed ~2min, after settle window, so decide() doesn't skip)
  4. webhook_restart.py (delayed)

The delay is just past dashboard_rebuild's SETTLE_SECONDS so a fresh merge doesn't
look "too fresh" and skip. A Mac that's already running the merged code makes the
rebuild/restart calls idempotent on the far side (decide's own ATTEMPT_FILE/BACKOFF
gates, webhook_restart's no-op-if-already-current), so concurrency here is safe.

Skips offline/asleep devices without attempting ssh (no 5s timeout hang per device).
"""
from __future__ import annotations
import job_events
import machine_profile
import subprocess
import sys
import task_dispatch
from pathlib import Path

HOME = Path.home()
VENV_PYTHON = HOME / ".agents" / "venv" / "bin" / "python"
DEPLOY_PING_SCRIPT = HOME / ".agents" / "lib" / "deploy_ping.py"

def main() -> None:
    with job_events.job_run("deploy-ping", "Deploy ping to other machines") as run:
        run.step("Checking", "which machines are reachable")
        remote_devices = machine_profile.remote_devices()
        online_hosts = task_dispatch._tailscale_online_hosts()

        if not remote_devices:
            run.summary("no remote devices configured")
            return

        run.step("Pinging", f"{len(remote_devices)} remote device(s)")
        failures = []

        for device_id, info in remote_devices.items():
            hostname = info.get("tailscale_hostname", "")
            if not hostname:
                run.step("Skipping", f"{device_id}: no tailscale hostname")
                continue

            if hostname not in online_hosts:
                run.step("Offline", f"{device_id}: {hostname} not reachable")
                continue

            # Build the command to run on the remote machine: pull code, then rebuild/restart after settle window.
            # The delay (130s) is just past dashboard_rebuild's SETTLE_SECONDS (120s), so the fresh merge
            # doesn't trigger the "too fresh" skip in decide(). All paths must be absolute for ssh/nohup.
            remote_cmd = (
                f"{HOME}/.agents/lib/code_sync.py pull {HOME}/.agents; "
                f"{HOME}/.agents/lib/code_sync.py pull {HOME}/.claude; "
                f"(sleep 130; {VENV_PYTHON} {HOME}/.agents/lib/dashboard_rebuild.py --force-relaunch; "
                f"{VENV_PYTHON} {HOME}/.agents/lib/webhook_restart.py --force-relaunch) &"
            )

            try:
                result = subprocess.run(
                    ["ssh", *task_dispatch.SSH_OPTS, hostname, f"nohup bash -c '{remote_cmd}' > /tmp/deploy-ping-{device_id}.log 2>&1 & disown"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode != 0:
                    msg = f"{device_id} ssh failed: {result.stderr[:200]}"
                    run.step("Failed", msg)
                    failures.append(msg)
                else:
                    run.step("Pinged", f"{device_id}: {hostname}")
            except subprocess.TimeoutExpired:
                msg = f"{device_id}: ssh timed out"
                run.step("Timeout", msg)
                failures.append(msg)
            except Exception as e:
                msg = f"{device_id}: {str(e)[:200]}"
                run.step("Error", msg)
                failures.append(msg)

        if failures:
            run.fail("; ".join(failures))
            run.summary(f"pinged {len(remote_devices) - len(failures)}/{len(remote_devices)} (failures: {', '.join(failures[:3])})")
        else:
            run.summary(f"pinged {len(remote_devices)} device(s)")


if __name__ == "__main__":
    main()
