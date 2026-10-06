#!/usr/bin/env python3
"""This machine's tool and token usage plus the other machine's, in one JSON for the dashboard's Metrics tab.

Each machine scans its own Claude session transcripts (lib/tool_usage.py, lib/session_usage.py) and keeps the result in
~/.claude/logs/. Those files are NOT synced (they can quote commands and error output), so the other machine's are read over ssh
when the report is built. A scan older than STALE_PEER_MIN on a reachable peer is refreshed there first.

    usage_report.py            print the merged report as JSON
    usage_report.py scan       refresh this machine's two files (what the hourly job and the peer's ssh call run)
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

HOME = Path.home()
TOOL_PATH = HOME / ".claude" / "logs" / "tool-usage.json"
TOKEN_PATH = HOME / ".claude" / "logs" / "token-usage.json"
STALE_LOCAL_MIN = 10
STALE_PEER_MIN = 90
AGENTS_PYTHON = "~/.agents/venv/bin/python"
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


def this_machine() -> str:
    import machine_profile
    return machine_profile.registry_id()


def peer_machines() -> dict[str, str]:
    """{device id: tailscale hostname} for every other registered machine."""
    import machine_profile
    return {dev: info.get("tailscale_hostname") for dev, info in machine_profile.remote_devices().items() if info.get("tailscale_hostname")}


def _age_min(doc, now) -> float | None:
    try:
        return (now - datetime.fromisoformat(doc["generated_at"])).total_seconds() / 60
    except (KeyError, TypeError, ValueError):
        return None


def _read(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def refresh_local() -> None:
    import session_usage
    import tool_usage
    tool_usage.refresh()
    session_usage.refresh()


def default_ssh(host: str, command: str, timeout: int = 20) -> str:
    proc = subprocess.run(["ssh", *SSH_OPTS, host, command], capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        err = proc.stderr.strip()[:200]
        if "No such file" in err:
            raise FileNotFoundError(err)   # the machine answered; it just has no scan yet
        raise OSError(err or f"ssh exit {proc.returncode}")
    return proc.stdout


def _peer_docs(host: str, ssh) -> tuple[dict | None, dict | None, bool]:
    """(tool scan, token scan, did the machine answer at all). A missing file is an answer; a failed connection is not."""
    answered = False
    out = []
    for name in ("tool-usage.json", "token-usage.json"):
        try:
            out.append(json.loads(ssh(host, f"cat ~/.claude/logs/{name}")))
            answered = True
        except FileNotFoundError:
            out.append(None)
            answered = True
        except (OSError, ValueError, subprocess.SubprocessError):
            out.append(None)
    return out[0], out[1], answered


def report(now: datetime | None = None, ssh=default_ssh) -> dict:
    now = now or datetime.now(timezone.utc)
    tools, tokens = _read(TOOL_PATH), _read(TOKEN_PATH)
    stale = [d for d in (tools, tokens) if d is None or (_age_min(d, now) or 1e9) > STALE_LOCAL_MIN]
    if stale:
        try:
            refresh_local()
            tools, tokens = _read(TOOL_PATH), _read(TOKEN_PATH)
        except Exception:  # noqa: BLE001  a failed scan must not hide what was already there
            pass
    machines = [{"machine": this_machine(), "this": True, "reachable": True, "tools": tools, "tokens": tokens}]
    for dev, host in peer_machines().items():
        ptools, ptokens, reachable = _peer_docs(host, ssh)
        old = any(d is None or (_age_min(d, now) or 1e9) > STALE_PEER_MIN for d in (ptools, ptokens))
        if reachable and old:
            try:
                ssh(host, f"{AGENTS_PYTHON} ~/.agents/lib/usage_report.py scan", timeout=120)
                ptools, ptokens, _ = _peer_docs(host, ssh)
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        machines.append({"machine": dev, "this": False, "reachable": reachable, "tools": ptools, "tokens": ptokens})
    return {"generated_at": now.isoformat(), "machines": machines}


def _cli() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        refresh_local()
        return
    print(json.dumps(report()))


if __name__ == "__main__":
    _cli()
