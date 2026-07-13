#!/usr/bin/env python3
"""Task-dispatch: location-transparent work execution across MARVIN's known
devices — submit a shell command without specifying which physical machine
runs it; the system picks one based on liveness + current dispatch load.

Design/scope decisions are in ~/.agents/docs/adr/0013-task-dispatch-general-
primitive-v1-scope.md and ~/.agents/CONTEXT.md's "Task-dispatch" section —
read those before extending this. Short version: v1 is single-target
dispatch only (fan-out+merge and exo-scheduled dispatch are deliberately
deferred), unit of work is an arbitrary shell command, machine selection
uses an explicit dispatch-state file (not raw OS load), and failures are
reported loud with no automatic retry-elsewhere.

Run standalone: ~/.agents/venv/bin/python task_dispatch.py "command" [--target ID] [--async] [--timeout N]
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from machine_profile import registry_id, remote_devices, _load_registry  # noqa: E402

DISPATCH_STATE_PATH = Path.home() / ".claude" / "dispatch-state.json"
TAILSCALE_BIN = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


@dataclass
class DispatchResult:
    ok: bool
    device_id: str | None = None
    output: str | None = None
    stderr: str | None = None
    error: str | None = None


def _tailscale_online_hosts() -> set[str]:
    """Hostnames Tailscale currently reports as online (not 'offline')."""
    try:
        proc = subprocess.run([TAILSCALE_BIN, "status"], capture_output=True, text=True, timeout=10)
        online = set()
        for line in proc.stdout.splitlines():
            parts = line.split()
            if len(parts) < 2:
                continue
            hostname = parts[1]
            if "offline" not in line:
                online.add(hostname)
        return online
    except Exception:
        return set()


def _read_local_dispatch_state() -> dict:
    if not DISPATCH_STATE_PATH.exists():
        return {"busy": False}
    try:
        return json.loads(DISPATCH_STATE_PATH.read_text())
    except Exception:
        return {"busy": False}


def _read_remote_dispatch_state(host: str) -> dict:
    try:
        proc = subprocess.run(
            ["ssh", *SSH_OPTS, host, f"cat {DISPATCH_STATE_PATH}"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {"busy": False}
        return json.loads(proc.stdout)
    except Exception:
        return {"busy": False}


def _candidates() -> dict:
    """All known devices (self + registered remotes) keyed by device_id,
    each tagged with whether it's self."""
    self_id = registry_id()
    devices = _load_registry()
    result = {self_id: {"is_self": True, "tailscale_hostname": None}}
    for device_id, info in remote_devices().items():
        result[device_id] = {**info, "is_self": False}
    return result


def select_machine(explicit_target: str | None = None) -> tuple[str, dict] | None:
    """Pick a device to run on. Explicit target skips liveness/load checks
    on OTHER machines but still validates the target itself is usable."""
    devices = _candidates()

    if explicit_target:
        if explicit_target not in devices:
            return None
        info = devices[explicit_target]
        if info["is_self"]:
            return explicit_target, info
        online = _tailscale_online_hosts()
        if info["tailscale_hostname"] not in online:
            return None
        state = _read_remote_dispatch_state(info["tailscale_hostname"])
        if state.get("busy"):
            return None
        return explicit_target, info

    online = _tailscale_online_hosts()
    # Prefer self first (no SSH round-trip needed), then remotes in registry order.
    self_id = registry_id()
    ordered_ids = [self_id] + [d for d in devices if d != self_id]
    for device_id in ordered_ids:
        info = devices[device_id]
        if info["is_self"]:
            state = _read_local_dispatch_state()
            if not state.get("busy"):
                return device_id, info
            continue
        if info["tailscale_hostname"] not in online:
            continue
        state = _read_remote_dispatch_state(info["tailscale_hostname"])
        if not state.get("busy"):
            return device_id, info

    return None


def _build_wrapper_script(command: str, task_id: str, task_label: str) -> str:
    """A script that marks the dispatch-state file busy, runs the real
    command, and on exit (via trap — fires even if the command fails or
    crashes, not just on clean exit) clears the state file and deletes its
    own /tmp script file. Self-deleting a running script is safe on
    Unix/macOS: rm just unlinks the directory entry, the already-open file
    stays readable to the running interpreter until it exits.

    Also exports CLAUDE_CODE_OAUTH_TOKEN from ~/.claude/.oauth-token on
    whichever machine actually runs this (local or remote — $HOME expands at
    runtime there, not where this string is built), if that file exists.
    Dispatched commands run in a non-interactive shell (no .zshrc/.zprofile
    sourced), so the normal keychain-backed login can't render its
    interactive confirmation dialog and fails with "Not logged in" — found
    2026-07-12/13 testing cross-machine claude -p dispatch for real, same
    root cause as the DarkWake auth bug. The token file is deliberately
    outside code_sync's ~/.claude scope (its .gitignore never allow-lists
    it) — this file never leaves the machine it's created on."""
    started_at = datetime.now(timezone.utc).isoformat()
    busy_json = json.dumps({"busy": True, "task": task_label, "task_id": task_id, "started_at": started_at})
    idle_json = json.dumps({"busy": False})
    return f"""#!/bin/bash
mkdir -p {DISPATCH_STATE_PATH.parent}
cat > {DISPATCH_STATE_PATH} << 'DISPATCH_STATE_EOF'
{busy_json}
DISPATCH_STATE_EOF
trap 'rm -f "$0"; cat > {DISPATCH_STATE_PATH} << 'DISPATCH_IDLE_EOF'
{idle_json}
DISPATCH_IDLE_EOF' EXIT
if [ -f "$HOME/.claude/.oauth-token" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude/.oauth-token")"
fi
{command}
"""


def dispatch(command: str, target: str | None = None, mode: str = "sync",
             timeout: int = 300, task_label: str | None = None) -> DispatchResult:
    """Run `command` on an available device. mode: "sync" (wait, capture
    output) or "async" (fire-and-forget, returns immediately). Fails loud,
    no automatic retry on a different machine."""
    selected = select_machine(target)
    if selected is None:
        reason = f"target '{target}' unavailable" if target else "no machine currently available"
        return DispatchResult(ok=False, error=reason)

    device_id, info = selected
    task_id = str(uuid.uuid4())[:8]
    label = task_label or command[:60]
    script = _build_wrapper_script(command, task_id, label)

    if info["is_self"]:
        return _run_local(script, mode, timeout)
    return _run_remote(info["tailscale_hostname"], script, mode, timeout, device_id)


def _run_local(script: str, mode: str, timeout: int) -> DispatchResult:
    tmp = Path(f"/tmp/dispatch-{uuid.uuid4().hex[:8]}.sh")
    tmp.write_text(script)
    tmp.chmod(0o755)
    self_id = registry_id()
    try:
        if mode == "async":
            subprocess.Popen(
                ["/bin/bash", str(tmp)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return DispatchResult(ok=True, device_id=self_id, output=None)
        proc = subprocess.run(["/bin/bash", str(tmp)], capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return DispatchResult(ok=False, device_id=self_id, error=f"exit {proc.returncode}: {proc.stderr[:500]}")
        return DispatchResult(ok=True, device_id=self_id, output=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired:
        return DispatchResult(ok=False, device_id=self_id, error=f"timed out after {timeout}s")
    except Exception as exc:
        return DispatchResult(ok=False, device_id=self_id, error=str(exc))


def _run_remote(host: str, script: str, mode: str, timeout: int, device_id: str) -> DispatchResult:
    remote_path = f"/tmp/dispatch-{uuid.uuid4().hex[:8]}.sh"
    try:
        write_proc = subprocess.run(
            ["ssh", *SSH_OPTS, host, f"cat > {remote_path} && chmod +x {remote_path}"],
            input=script, capture_output=True, text=True, timeout=10,
        )
        if write_proc.returncode != 0:
            return DispatchResult(ok=False, device_id=device_id, error=f"failed to write script to {host}: {write_proc.stderr[:300]}")

        if mode == "async":
            subprocess.run(
                ["ssh", *SSH_OPTS, host, f"nohup {remote_path} > /tmp/dispatch-{device_id}.log 2>&1 & disown"],
                capture_output=True, text=True, timeout=10,
            )
            return DispatchResult(ok=True, device_id=device_id, output=None)

        proc = subprocess.run(
            ["ssh", *SSH_OPTS, host, remote_path],
            capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            return DispatchResult(ok=False, device_id=device_id, error=f"exit {proc.returncode}: {proc.stderr[:500]}")
        return DispatchResult(ok=True, device_id=device_id, output=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired:
        return DispatchResult(ok=False, device_id=device_id, error=f"timed out after {timeout}s")
    except Exception as exc:
        return DispatchResult(ok=False, device_id=device_id, error=str(exc))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", help="shell command to dispatch")
    ap.add_argument("--target", default=None, help="explicit device id (e.g. mac-mini-1) instead of auto-select")
    ap.add_argument("--async", dest="async_mode", action="store_true", help="fire-and-forget, don't wait for completion")
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait in sync mode (default 300)")
    args = ap.parse_args()

    result = dispatch(args.command, target=args.target, mode="async" if args.async_mode else "sync", timeout=args.timeout)
    if result.ok:
        print(f"[dispatch] ran on {result.device_id}", file=sys.stderr)
        if result.output is not None:
            print(result.output, end="")
        if result.stderr is not None:
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(0)
    else:
        print(f"[dispatch] FAILED: {result.error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
