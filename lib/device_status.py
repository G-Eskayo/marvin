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


def _row(device_id, device_entry, is_self, state, why=None, slots_used=None, slots_total=None, tickets=None):
    busy = state.get("busy") if state else False
    row = {"id": device_id, "kind": device_entry.get("kind"), "self": is_self,
           "state": "busy" if busy else "idle", "task": (state or {}).get("task") if busy else None,
           "startedAt": (state or {}).get("started_at") if busy else None, "why": why}
    if slots_used is not None:
        row["slotsUsed"] = slots_used
    if slots_total is not None:
        row["slotsTotal"] = slots_total
    if tickets is not None:
        row["tickets"] = tickets
    return row


def device_statuses(devices: dict, self_id: str, local, online, probe,
                   local_slots=None, remote_slots=None) -> list[dict]:
    if local_slots is None:
        local_slots = lambda: None
    if remote_slots is None:
        remote_slots = lambda host, machine: None

    state = local()
    local_records = local_slots()
    slots_used = len(local_records) if local_records is not None else None
    slots_total = None
    if local_records is not None:
        import dispatch_concurrency as dc
        slots_total = dc.machine_slot_ceiling(self_id)
    out = [_row(self_id, devices.get(self_id, {}), True, state,
                slots_used=slots_used, slots_total=slots_total, tickets=local_records)]

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
        remote_records = remote_slots(host, device_id) if state is not None else None
        slots_used = len(remote_records) if remote_records is not None else None
        slots_total = None
        if remote_records is not None:
            import dispatch_concurrency as dc
            slots_total = dc.machine_slot_ceiling(device_id)
        out.append(_row(device_id, info, False, state,
                       slots_used=slots_used, slots_total=slots_total, tickets=remote_records)
                   if state is not None
                   else {**_row(device_id, info, False, None), "state": "unreachable", "why": "online in Tailscale but ssh/read failed"})
    return out


def main() -> None:
    import task_dispatch as td
    from machine_profile import registry_id, _load_registry

    def local():
        s = td._read_local_dispatch_state()
        if not s.get("busy"):
            import ticket_pipeline as tp  # a live run_ticket also means busy
            if tp._ticket_process_alive():
                return {"busy": True, "task": "ticket pipeline run"}
        return s

    def get_local_slots():
        import dispatch_concurrency as dc
        return dc.slots_in_use(machine=registry_id())

    def get_remote_slots(host, machine):
        import dispatch_concurrency as dc
        return dc.slots_in_use_remote(host, machine)

    print(json.dumps(device_statuses(_load_registry(), registry_id(), local, td._tailscale_online_hosts, probe_remote,
                                     local_slots=get_local_slots, remote_slots=get_remote_slots)))


if __name__ == "__main__":
    main()
