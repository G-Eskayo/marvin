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
