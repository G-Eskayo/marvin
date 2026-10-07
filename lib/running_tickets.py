"""Which tickets are being worked on right now, per machine, read from the process table.

A `claimed:<machine>` label is NOT this: it stays on a ticket until its PR merges, so a ticket waiting in review still
carries one. The truth is a live `run_ticket.py` process. (Ticket #193's per-task records will replace this with
something richer; the readers here stay the same shape.) An unreachable machine is skipped, never guessed at.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

_RUN = re.compile(r"run_ticket\.py\s+(?:(\S+)#)?(\d+)\b")


def parse(ps_output: str, marvin: str) -> list[tuple[str, int]]:
    """(repo, number) for each distinct ticket a `run_ticket.py` command line names; a bare number is marvin's."""
    seen: list[tuple[str, int]] = []
    for line in ps_output.splitlines():
        m = _RUN.search(line)
        if m and "grep" not in line.split()[0:1]:
            key = (m.group(1) or marvin, int(m.group(2)))
            if key not in seen:
                seen.append(key)
    return seen


def all_running(machines: dict, local_ps, remote_ps, marvin: str) -> list[dict]:
    """`machines` maps a device id to its ssh host (None for this machine). Each reader returns `ps -axo command` output."""
    out = []
    for machine, host in machines.items():
        try:
            text = local_ps() if host is None else remote_ps(host)
        except Exception as exc:  # noqa: BLE001
            print(f"[running-tickets] {machine} unreadable: {exc}", file=sys.stderr)
            continue
        out += [{"machine": machine, "repo": repo, "number": n} for repo, n in parse(text, marvin)]
    return out


def _local_ps() -> str:
    return subprocess.run(["ps", "-axo", "command"], capture_output=True, text=True, timeout=10).stdout


def _remote_ps(host: str) -> str:
    import task_dispatch as td
    p = subprocess.run(["ssh", *td.SSH_OPTS, host, "ps -axo command"], capture_output=True, text=True, timeout=15)
    if p.returncode != 0:
        raise OSError(p.stderr.strip()[:120] or "ssh failed")
    return p.stdout


def current() -> list[dict]:
    import task_dispatch as td
    import ticket_pipeline as tp
    machines = {td.registry_id(): None, **{d: info["tailscale_hostname"] for d, info in td.remote_devices().items()}}
    return all_running(machines, _local_ps, _remote_ps, tp.REPO)
