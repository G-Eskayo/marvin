"""device_status: one row per registered device -- idle / busy (task) / unreachable -- for the Activity tab."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import device_status as ds  # noqa: E402

DEVICES = {
    "mac-mini-1": {"kind": "desktop", "tailscale_hostname": "gils-mac-mini"},
    "macbook-pro-1": {"kind": "laptop", "tailscale_hostname": "mbp"},
    "node-3": {"kind": "desktop", "tailscale_hostname": "n3"},
}


def rows(local=None, online=("mbp",), remote=None):
    remote = remote or {}
    return {r["id"]: r for r in ds.device_statuses(
        DEVICES, self_id="mac-mini-1",
        local=lambda: local or {"busy": False},
        online=lambda: set(online),
        probe=lambda host: remote.get(host, {"busy": False}))}


def test_one_row_per_device_self_first_and_labelled():
    r = ds.device_statuses(DEVICES, "mac-mini-1", lambda: {"busy": False}, lambda: {"mbp", "n3"}, lambda h: {"busy": False})
    assert [x["id"] for x in r] == ["mac-mini-1", "macbook-pro-1", "node-3"]
    assert r[0]["self"] is True and r[0]["kind"] == "desktop" and r[1]["self"] is False


def test_self_idle_and_busy_with_task_name():
    assert rows()["mac-mini-1"]["state"] == "idle"
    b = rows(local={"busy": True, "task": "ticket #5: x", "started_at": "2026-10-05T10:00:00Z"})["mac-mini-1"]
    assert (b["state"], b["task"], b["startedAt"]) == ("busy", "ticket #5: x", "2026-10-05T10:00:00Z")


def test_remote_offline_in_tailscale_is_unreachable():
    assert rows(online=())["macbook-pro-1"]["state"] == "unreachable"


def test_remote_online_idle_or_busy():
    assert rows()["macbook-pro-1"]["state"] == "idle"
    b = rows(remote={"mbp": {"busy": True, "task": "t"}})["macbook-pro-1"]
    assert b["state"] == "busy" and b["task"] == "t"


def test_remote_ssh_failure_is_unreachable_not_idle():
    r = rows(remote={"mbp": None})["macbook-pro-1"]  # probe returns None when ssh/read fails
    assert r["state"] == "unreachable" and "ssh" in r["why"].lower()


def test_slots_used_and_total_when_provided():
    """Device rows include slotsUsed/slotsTotal when slot info is available."""
    def mock_local_slots():
        return [
            {"pid": 100, "task_id": "t1", "machine": "mac-mini-1"},
            {"pid": 101, "task_id": "t2", "machine": "mac-mini-1"},
        ]

    def mock_remote_slots(host, machine):
        if host == "mbp" and machine == "macbook-pro-1":
            return [{"pid": 200, "task_id": "t3", "machine": "macbook-pro-1"}]
        return None

    r = ds.device_statuses(DEVICES, self_id="mac-mini-1",
                          local=lambda: {"busy": False},
                          online=lambda: set(["mbp"]),
                          probe=lambda h: {"busy": False},
                          local_slots=mock_local_slots,
                          remote_slots=mock_remote_slots)

    rows_by_id = {row["id"]: row for row in r}
    assert rows_by_id["mac-mini-1"]["slotsUsed"] == 2
    assert rows_by_id["mac-mini-1"]["slotsTotal"] == 2
    assert rows_by_id["macbook-pro-1"]["slotsUsed"] == 1
    assert rows_by_id["macbook-pro-1"]["slotsTotal"] == 1


def test_slots_absent_when_no_slots_info():
    """Device rows omit slotsUsed/slotsTotal when slot info is not available."""
    r = ds.device_statuses(DEVICES, self_id="mac-mini-1",
                          local=lambda: {"busy": False},
                          online=lambda: set(["mbp"]),
                          probe=lambda h: {"busy": False})

    rows_by_id = {row["id"]: row for row in r}
    assert "slotsUsed" not in rows_by_id["mac-mini-1"]
    assert "slotsTotal" not in rows_by_id["mac-mini-1"]
    assert "slotsUsed" not in rows_by_id["macbook-pro-1"]
    assert "slotsTotal" not in rows_by_id["macbook-pro-1"]


def test_tickets_list_included_when_provided():
    """Device rows include tickets list when slot info is available."""
    tickets = [
        {"pid": 100, "task_id": "t1", "task": "ticket #5", "started_at": "2026-10-06T10:00:00Z"},
        {"pid": 101, "task_id": "t2", "task": "ticket #6", "started_at": "2026-10-06T10:05:00Z"},
    ]

    def mock_local_slots():
        return tickets

    r = ds.device_statuses(DEVICES, self_id="mac-mini-1",
                          local=lambda: {"busy": False},
                          online=lambda: set(["mbp"]),
                          probe=lambda h: {"busy": False},
                          local_slots=mock_local_slots,
                          remote_slots=lambda h, m: None)

    rows_by_id = {row["id"]: row for row in r}
    assert rows_by_id["mac-mini-1"]["tickets"] == tickets
    assert "tickets" not in rows_by_id.get("macbook-pro-1", {})
