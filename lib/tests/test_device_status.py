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


def test_slots_present_when_local_slots_reader_returns_records():
    slot_records = [
        {"task_id": "t1", "task": "ticket #5: foo", "started_at": "2026-10-07T10:00:00Z"},
        {"task_id": "t2", "task": "ticket #7: bar", "started_at": "2026-10-07T10:05:00Z"},
    ]

    def mock_load():
        return {"machine_slots": {"mac-mini-1": 2, "macbook-pro-1": 1}}

    # Test that slot data is included when readers return records
    import dispatch_concurrency as dc_module
    original_load = dc_module.load
    try:
        dc_module.load = mock_load
        rows_dict = {r["id"]: r for r in ds.device_statuses(
            DEVICES, self_id="mac-mini-1",
            local=lambda: {"busy": False},
            online=lambda: {"mbp"},
            probe=lambda h: {"busy": False},
            local_slots=lambda m: slot_records if m == "mac-mini-1" else [],
            remote_slots=lambda h, m: None,
        )}
        assert rows_dict["mac-mini-1"]["slotsUsed"] == 2
        assert rows_dict["mac-mini-1"]["slotsTotal"] == 2
        assert len(rows_dict["mac-mini-1"]["tickets"]) == 2
    finally:
        dc_module.load = original_load


def test_slots_absent_when_readers_return_none():
    r = ds.device_statuses(
        DEVICES, self_id="mac-mini-1",
        local=lambda: {"busy": False},
        online=lambda: {"mbp"},
        probe=lambda h: {"busy": False},
        local_slots=lambda m: None,
        remote_slots=lambda h, m: None,
    )
    assert all("slotsUsed" not in row for row in r)


def test_tailscale_that_cannot_be_checked_is_not_reported_as_offline():
    # marvin#889: a missing or failing tailscale CLI made every peer read "not online in Tailscale" for four days.
    r = ds.device_statuses(DEVICES, "mac-mini-1", lambda: {"busy": False}, lambda: None, lambda h: {"busy": False})
    for row in r[1:]:
        assert row["state"] == "unreachable"
        assert "can't check" in row["why"] and "not online" not in row["why"]


def test_severity_field_attached_to_unreachable_devices():
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)

    def peer_lookup(host):
        if host == "mbp":
            return {"online": False, "last_seen": now - timedelta(hours=1)}
        return None

    r = ds.device_statuses(
        DEVICES, self_id="mac-mini-1",
        local=lambda: {"busy": False},
        online=lambda: set(),  # offline in Tailscale
        probe=lambda h: {"busy": False},
        peer_lookup=peer_lookup,
        now=now,
        grace_hours=0.0
    )
    rows_dict = {row["id"]: row for row in r}
    assert "severity" in rows_dict["macbook-pro-1"]
    assert rows_dict["macbook-pro-1"]["severity"] == "asleep"  # laptop offline recently


def test_last_seen_field_attached_when_peer_info_available():
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    last_seen = now - timedelta(hours=2)

    def peer_lookup(host):
        if host == "n3":
            return {"online": False, "last_seen": last_seen}
        return None

    r = ds.device_statuses(
        DEVICES, self_id="mac-mini-1",
        local=lambda: {"busy": False},
        online=lambda: set(),
        probe=lambda h: {"busy": False},
        peer_lookup=peer_lookup,
        now=now,
        grace_hours=0.0
    )
    rows_dict = {row["id"]: row for row in r}
    assert "lastSeen" in rows_dict["node-3"]
    assert rows_dict["node-3"]["lastSeen"] == last_seen.isoformat()


def test_grace_period_yellow_for_always_on_within_grace():
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)

    def peer_lookup(host):
        if host == "n3":
            return {"online": False, "last_seen": now - timedelta(hours=1)}
        return None

    r = ds.device_statuses(
        DEVICES, self_id="mac-mini-1",
        local=lambda: {"busy": False},
        online=lambda: set(),
        probe=lambda h: {"busy": False},
        peer_lookup=peer_lookup,
        now=now,
        grace_hours=2.0  # device offline for 1h, within 2h grace
    )
    rows_dict = {row["id"]: row for row in r}
    assert rows_dict["node-3"]["severity"] == "yellow"


def test_clock_skew_clamping_in_last_seen():
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    future_time = now + timedelta(hours=1)  # clock skew

    def peer_lookup(host):
        if host == "n3":
            return {"online": False, "last_seen": future_time}
        return None

    r = ds.device_statuses(
        DEVICES, self_id="mac-mini-1",
        local=lambda: {"busy": False},
        online=lambda: set(),
        probe=lambda h: {"busy": False},
        peer_lookup=peer_lookup,
        now=now,
        grace_hours=0.0
    )
    rows_dict = {row["id"]: row for row in r}
    # lastSeen should be clamped to now (or earlier)
    assert rows_dict["node-3"]["lastSeen"] <= now.isoformat()
