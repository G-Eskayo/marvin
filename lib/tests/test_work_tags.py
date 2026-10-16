"""Work tags (ADR 0069): devices list the tags they accept, a job names the tag it needs, untagged work is
`general`, and when no accepting device is free the job fails loudly -- it never falls back to a Mac."""
import pytest

import task_dispatch as td

MACS = {"general", "macos"}
KALI = ["security", "quarantine", "test", "bench"]


@pytest.fixture
def network(monkeypatch):
    """Self is mac-mini-1. Mutate the returned dict to change the world before calling select_machine."""
    world = {
        "registry": {
            "mac-mini-1": {"tailscale_hostname": "gils-mac-mini", "accepts": sorted(MACS)},
            "macbook-pro-1": {"tailscale_hostname": "laptop", "accepts": sorted(MACS)},
            "mac-mini-2012": {"tailscale_hostname": "mac-mini-2012", "accepts": KALI, "os": "linux"},
        },
        "online": {"gils-mac-mini", "laptop", "mac-mini-2012"},
        "busy": set(),
    }
    monkeypatch.setattr(td, "registry_id", lambda: "mac-mini-1")
    monkeypatch.setattr(td, "_load_registry", lambda: world["registry"])
    monkeypatch.setattr(td, "remote_devices", lambda: {k: v for k, v in world["registry"].items() if k != "mac-mini-1"})
    monkeypatch.setattr(td, "_tailscale_online_hosts", lambda: set(world["online"]))
    monkeypatch.setattr(td, "_read_local_dispatch_state", lambda: {"busy": "mac-mini-1" in world["busy"]})
    host_to_id = {"laptop": "macbook-pro-1", "mac-mini-2012": "mac-mini-2012", "gils-mac-mini": "mac-mini-1"}
    monkeypatch.setattr(td, "_read_remote_dispatch_state", lambda host: {"busy": host_to_id[host] in world["busy"]})
    return world


def picked(**kw):
    sel = td.select_machine(**kw)
    return sel[0] if sel else None


def test_untagged_work_stays_on_the_macs(network):
    assert picked() == "mac-mini-1"


def test_untagged_work_never_spills_onto_the_kali_box_when_both_macs_are_busy(network):
    network["busy"] |= {"mac-mini-1", "macbook-pro-1"}
    assert picked() is None


def test_quarantine_work_skips_the_idle_mac_it_was_submitted_from(network):
    assert picked(need="quarantine") == "mac-mini-2012"


def test_quarantine_work_fails_rather_than_falling_back_to_a_mac_when_the_box_is_offline(network):
    network["online"].discard("mac-mini-2012")
    assert picked(need="quarantine") is None


def test_quarantine_work_fails_when_the_box_is_busy(network):
    network["busy"].add("mac-mini-2012")
    assert picked(need="quarantine") is None


def test_naming_the_kali_box_for_untagged_work_is_refused(network):
    # The ticket pipeline names machines explicitly; tags must hold there too.
    assert picked(explicit_target="mac-mini-2012") is None


def test_naming_a_mac_for_quarantine_work_is_refused_even_for_self(network):
    assert picked(explicit_target="mac-mini-1", need="quarantine") is None


def test_naming_the_box_for_work_it_accepts_works(network):
    assert picked(explicit_target="mac-mini-2012", need="test") == "mac-mini-2012"


def test_a_registry_entry_without_accepts_still_takes_general_work(network):
    # Backward compatible: the Macs' entries predate tags.
    for dev in ("mac-mini-1", "macbook-pro-1"):
        del network["registry"][dev]["accepts"]
    assert picked() == "mac-mini-1"
    assert picked(need="quarantine") == "mac-mini-2012"


@pytest.mark.parametrize("bad", ["quarantine", None, 7, {"quarantine": True}])
def test_a_malformed_accepts_takes_nothing(network, bad):
    # Fail closed: a typo in the registry must not open a device to work it wasn't meant for.
    network["registry"]["mac-mini-2012"]["accepts"] = bad
    assert picked(need="quarantine") is None


def test_need_is_normalised_and_an_unknown_tag_matches_nothing(network):
    assert picked(need="  Quarantine ") == "mac-mini-2012"
    assert picked(need="no-such-tag") is None
    assert picked(need="") == "mac-mini-1"   # empty means untagged, i.e. general


def test_dispatch_names_the_tag_when_nothing_accepts_it(network):
    network["online"].discard("mac-mini-2012")
    result = td.dispatch("echo hi", need="quarantine")
    assert not result.ok
    assert "quarantine" in result.error
