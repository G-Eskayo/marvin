"""Tests for github_hub.py hub election logic.
Run via: ~/.agents/venv/bin/python -m pytest lib/tests/test_github_hub.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import github_hub as gh  # noqa: E402


def test_tier_assignment():
    """Machines are assigned to tiers based on device_id prefix.
    mac-mini-2012 (box with no credentials) is explicitly tier 3 (ineligible for hub)."""
    assert gh._tier_for_device("mac-mini-1") == 0  # Tier 0: Mac mini
    assert gh._tier_for_device("mac-mini-2012") == 3  # Tier 3: ineligible (no credentials)
    assert gh._tier_for_device("macbook-pro-1") == 1  # Tier 1: MacBook Pro
    assert gh._tier_for_device("some-linux-box") == 2  # Tier 2: fallback (other machines)


def test_hub_election_primary_fresh():
    """Tier 1 machine with fresh heartbeat is elected hub."""
    heartbeats = {"mac-mini-1": 100}  # 100 seconds old (fresh)
    is_hub, reason = gh.decide(tier=0, heartbeats=heartbeats)
    assert is_hub is True
    assert "tier 0" in reason or "elected" in reason


def test_hub_election_primary_stale():
    """When Tier 0 is stale, Tier 1 (macbook) becomes the hub."""
    heartbeats = {"mac-mini-1": 4000, "macbook-pro-1": 100}  # Mini stale, MBP fresh
    is_hub, reason = gh.decide(tier=1, heartbeats=heartbeats)
    assert is_hub is True  # macbook-pro is at the best available tier
    assert "elected" in reason


def test_hub_election_all_stale():
    """When all higher tiers are stale/unreadable, any tier becomes hub."""
    heartbeats = {"mac-mini-1": 4000, "macbook-pro-1": None}  # Mini stale, MBP unreadable
    is_hub, reason = gh.decide(tier=2, heartbeats=heartbeats)
    assert is_hub is True


def test_hub_election_unreadable_heartbeat():
    """None (unreadable) is treated as stale."""
    heartbeats = {"mac-mini-1": None}  # Could not read
    is_hub, reason = gh.decide(tier=1, heartbeats=heartbeats)
    assert is_hub is True  # Tier 1 steps in


def test_hub_election_multiple_machines():
    """With multiple Tier 0 machines and device_id specified, only the one with fresh heartbeat is hub."""
    # When device_id is specified: only that machine's heartbeat matters
    heartbeats = {"mac-mini-1": 100, "mac-mini-2": 50}  # Both fresh

    # mac-mini-1 is hub (device_id="mac-mini-1" and its heartbeat is fresh)
    is_hub, reason = gh.decide(tier=0, heartbeats=heartbeats, device_id="mac-mini-1")
    assert is_hub is True  # mac-mini-1's hb is fresh
    assert "elected" in reason or "fresh" in reason

    # mac-mini-2 is also hub (device_id="mac-mini-2" and its heartbeat is fresh)
    is_hub, reason = gh.decide(tier=0, heartbeats=heartbeats, device_id="mac-mini-2")
    assert is_hub is True  # mac-mini-2's hb is fresh

    # If one machine's heartbeat is stale, it's not hub
    heartbeats = {"mac-mini-1": 100, "mac-mini-2": 4000}  # mac-mini-2 stale
    is_hub, reason = gh.decide(tier=0, heartbeats=heartbeats, device_id="mac-mini-2")
    assert is_hub is False  # mac-mini-2's hb is stale
    assert "standby" in reason or "stale" in reason


def test_hub_election_negative_age():
    """Negative age (future time) is treated as age 0 (fresh)."""
    heartbeats = {"mac-mini-1": -100}  # Future time, fresh
    is_hub, reason = gh.decide(tier=0, heartbeats=heartbeats)
    assert is_hub is True


def test_hub_election_tier3_standby():
    """When Tier 0 has fresh heartbeat, Tier 2 (other machine) should not be hub."""
    heartbeats = {"mac-mini-1": 100, "some-linux-box": 50}
    is_hub, reason = gh.decide(tier=2, heartbeats=heartbeats)  # Tier 2 machine
    assert is_hub is False
    assert "standby" in reason


def test_hub_election_returning_higher_priority():
    """A returning higher-priority machine (lower tier) takes over from lower-priority one.
    When Mini returns and sees laptop's fresh heartbeat (tier 1), Mini (tier 0) should claim hub."""
    heartbeats = {"mac-mini-1": 100, "macbook-pro-1": 100}  # Mini returning, sees laptop's hb
    is_hub, reason = gh.decide(tier=0, heartbeats=heartbeats, device_id="mac-mini-1")
    assert is_hub is True  # Mini takes over because it's higher priority
    assert "higher priority" in reason or "elected" in reason


def test_hub_election_standby_with_stale_own_hb():
    """At same tier, only be hub if own heartbeat is fresh."""
    heartbeats = {"mac-mini-1": 100, "mac-mini-2": 4000}  # mac-mini-1 fresh, mac-mini-2 stale
    # If this machine is mac-mini-2 (tier=0), it should be standby because its hb is stale
    is_hub, reason = gh.decide(tier=0, heartbeats=heartbeats, device_id="mac-mini-2")
    # We're at tier 0, there's a fresh hb at tier 0, but ours is stale
    assert is_hub is False
    assert "standby" in reason or "stale" in reason


def test_no_heartbeat_in_dict_all_stale():
    """When no machine has a fresh heartbeat at all, any machine becomes hub."""
    heartbeats = {"mac-mini-1": 4000}  # Stale
    is_hub, reason = gh.decide(tier=1, heartbeats=heartbeats)
    assert is_hub is True  # No fresh heartbeats, so tier 1 becomes hub
    assert "stale" in reason or "unreadable" in reason


def test_tier3_ineligible_for_hub():
    """The box (mac-mini-2012, tier 3) cannot be elected hub, even if only machine available."""
    heartbeats = {"mac-mini-2012": 100}  # Tier 3: ineligible
    is_hub, reason = gh.decide(tier=3, heartbeats=heartbeats)
    assert is_hub is False  # Tier 3 is never hub (no GitHub credentials)
    assert "ineligible" in reason


def test_write_heartbeat_creates_file(tmp_path):
    """write_heartbeat() creates/updates the heartbeat file with device and timestamp."""
    heartbeat_path = tmp_path / "heartbeat.json"

    gh.write_heartbeat("mac-mini-1", now=1000.0, path=heartbeat_path)

    assert heartbeat_path.exists()
    import json
    doc = json.loads(heartbeat_path.read_text())
    assert doc["device"] == "mac-mini-1"
    assert doc["ts"] == 1000.0


def test_decide_includes_device_id_check():
    """When device_id is provided, only that device's heartbeat matters at same tier."""
    heartbeats = {"mac-mini-1": 100, "mac-mini-2": 4000}

    # mac-mini-1 is hub (fresh heartbeat)
    is_hub, _ = gh.decide(tier=0, heartbeats=heartbeats, device_id="mac-mini-1")
    assert is_hub is True

    # mac-mini-2 is standby (stale heartbeat)
    is_hub, _ = gh.decide(tier=0, heartbeats=heartbeats, device_id="mac-mini-2")
    assert is_hub is False


def test_am_hub_only_writes_heartbeat_when_elected(tmp_path, monkeypatch):
    """am_hub() should only write a heartbeat if elected, not always."""
    heartbeat_path = tmp_path / "heartbeat.json"
    monkeypatch.setattr(gh, "HEARTBEAT_PATH", heartbeat_path)

    # Mock machine_profile
    mock_mp = __import__('unittest.mock', fromlist=['Mock']).Mock()
    mock_mp.registry_id.return_value = "macbook-pro-1"
    mock_mp.remote_devices.return_value = {"mac-mini-1": {}}
    monkeypatch.setitem(__import__('sys').modules, "machine_profile", mock_mp)

    # Mock SSH reads: mac-mini-1 has a fresh heartbeat (is hub at tier 0)
    def mock_ssh_read(device_id, now=None):
        if device_id == "mac-mini-1":
            return 100  # Fresh heartbeat from mac-mini
        return None

    monkeypatch.setattr(gh, "_read_local_heartbeat_age", lambda now=None: 4000)  # Stale
    monkeypatch.setattr(gh, "_read_heartbeat_age", mock_ssh_read)

    # Call am_hub - this machine (macbook-pro) is standby, not hub
    is_hub, reason = gh.am_hub()

    # Verify this machine is NOT hub
    assert is_hub is False

    # Verify heartbeat file was NOT written (machine is standby)
    assert not heartbeat_path.exists()
