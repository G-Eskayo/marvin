"""Per-device dispatch status for the dashboard's Activity tab: idle / busy (task) / unreachable.

Reuses task_dispatch's readers (local state file, Tailscale online set, SSH `cat` of the remote state
file). The difference: task_dispatch treats "could not read" as idle because it only wants to find a free
machine; a status view must NOT, so the remote probe here returns None on failure and that becomes
"unreachable". `python device_status.py` prints the rows as JSON.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def probe_remote(host: str):
    import task_dispatch as td
    try:
        p = subprocess.run(["ssh", *td.SSH_OPTS, host, f"cat {td.DISPATCH_STATE_PATH}"],
                           capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout) if p.stdout.strip() else {"busy": False}  # no state file = idle
    except ValueError:
        return None


def _row(device_id, device_entry, is_self, state, why=None, slotsUsed=None, slotsTotal=None, tickets=None):
    busy = state.get("busy") if state else False
    row = {"id": device_id, "kind": device_entry.get("kind"), "self": is_self,
            "state": "busy" if busy else "idle", "task": (state or {}).get("task") if busy else None,
            "startedAt": (state or {}).get("started_at") if busy else None, "why": why}
    if slotsUsed is not None and slotsTotal is not None:
        row["slotsUsed"] = slotsUsed
        row["slotsTotal"] = slotsTotal
    if tickets:
        row["tickets"] = tickets
    return row


def device_statuses(devices: dict, self_id: str, local, online, probe, local_slots=None, remote_slots=None) -> list[dict]:
    local_slots = local_slots or (lambda m: None)
    remote_slots = remote_slots or (lambda h, m: None)

    def add_slot_info(row, device_id, is_self):
        if is_self:
            slots = local_slots(device_id)
        else:
            host = devices[device_id].get("tailscale_hostname")
            slots = remote_slots(host, device_id) if host else None
        if slots is not None:
            from dispatch_concurrency import load as load_dispatch_config
            cfg = load_dispatch_config()
            total = cfg.get("machine_slots", {}).get(device_id, 1)
            row["slotsUsed"] = len(slots)
            row["slotsTotal"] = total
            tickets = [{"id": s.get("task_id"), "label": s.get("task"), "started_at": s.get("started_at")}
                      for s in slots if s.get("task")]
            if tickets:
                row["tickets"] = tickets
        return row

    local_state = local()
    out = [add_slot_info(_row(self_id, devices.get(self_id, {}), True, local_state), self_id, True)]
    online_hosts = None
    for device_id, info in devices.items():
        if device_id == self_id:
            continue
        if online_hosts is None:
            online_hosts = online()
        host = info.get("tailscale_hostname")
        if host not in online_hosts:
            out.append({**_row(device_id, info, False, None), "state": "unreachable", "why": "not online in Tailscale"})
            continue
        state = probe(host)
        if state is not None:
            out.append(add_slot_info(_row(device_id, info, False, state), device_id, False))
        else:
            out.append({**_row(device_id, info, False, None), "state": "unreachable", "why": "online in Tailscale but ssh/read failed"})
    return out


def main() -> None:
    import task_dispatch as td
    from machine_profile import registry_id, _load_registry
    import dispatch_concurrency as dc

    def local():
        s = td._read_local_dispatch_state()
        if not s.get("busy"):
            import ticket_pipeline as tp  # a live run_ticket also means busy
            if tp._ticket_process_alive():
                return {"busy": True, "task": "ticket pipeline run"}
        return s

    def local_slots_reader(machine):
        try:
            return dc.slots_in_use(machine)
        except Exception:
            return None

    def remote_slots_reader(host, machine):
        try:
            result = dc.slots_in_use_remote(host, machine)
            return result if result is not None else None
        except Exception:
            return None

    print(json.dumps(device_statuses(_load_registry(), registry_id(), local, td._tailscale_online_hosts, probe_remote,
                                    local_slots=local_slots_reader, remote_slots=remote_slots_reader)))


if __name__ == "__main__":
    main()
