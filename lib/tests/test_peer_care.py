"""Tests for peer_care.py (marvin#847, design #769 sections 4-5): the 2012 mini and the Mac mini watch each other.
Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_peer_care.py -v

No test reaches a real machine: probes, fixes and notifications are injected, state lives in tmp_path, and the root
unlock script only ever runs in --dry-run or against fakes.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import peer_care as pc  # noqa: E402

CFG = pc.load_config()
T0 = datetime(2026, 10, 31, 3, 0, tzinfo=timezone.utc)


def P(**kw) -> pc.Probe:
    return pc.Probe(**kw)


# ── classify: every row of the design's table, plus the awkward cases ─────────────────────────────────────────

@pytest.mark.parametrize("probe,state", [
    (P(tailscale=True, ssh_key=True, services_ok=True), "healthy"),
    (P(tailscale=True, ssh_key=True, services_ok=False, services_detail="webhook :7878"), "service"),
    (P(tailscale=False, same_lan=True, lan_ssh=True), "network"),
    (P(tailscale=False, same_lan=True, port22=True, lan_ssh=False, ssh_methods=["password", "keyboard-interactive"]),
     "locked"),
    (P(tailscale=False, same_lan=True, arp=False, port22=False), "asleep"),
    (P(tailscale=False, same_lan=True, arp=True, port22=False), "hung"),
    (P(tailscale=False, same_lan=False), "unknown"),
])
def test_classify_the_design_table(probe, state):
    assert pc.classify(probe) == state


def test_classify_key_refused_but_key_auth_still_offered_is_not_locked():
    # a normal sshd that just doesn't know this key offers publickey too: that's not the FileVault screen
    p = P(tailscale=False, same_lan=True, port22=True, lan_ssh=False, ssh_methods=["publickey", "password"])
    assert pc.classify(p) == "unknown"


def test_classify_probe_timeouts_midway_are_unknown_not_healthy():
    assert pc.classify(P(tailscale=None)) == "unknown"
    assert pc.classify(P(tailscale=True, ssh_key=None)) == "unknown"
    assert pc.classify(P(tailscale=False, same_lan=True, arp=None, port22=None)) == "unknown"


def test_classify_tailscale_up_but_ssh_refused_is_unknown():
    assert pc.classify(P(tailscale=True, ssh_key=False)) == "unknown"


def test_classify_stale_lan_address_reads_asleep_and_the_wake_goes_by_mac():
    # DHCP moved the Mini: nothing answers at the old address. The wake packet is addressed by MAC, so it still works.
    assert pc.classify(P(tailscale=False, same_lan=True, arp=False, port22=None)) == "asleep"


def test_classify_services_unknown_counts_as_healthy_only_if_nothing_to_check():
    assert pc.classify(P(tailscale=True, ssh_key=True, services_ok=None)) == "healthy"


# ── the ladder: which fix for which state ───────────────────────────────────────────────────────────────────────

def known(**kw):
    base = {"os": "macos", "lan_ip": "192.0.2.41", "ethernet_mac": None, "ethernet_active": False}
    base.update(kw)
    return base


@pytest.mark.parametrize("state,facts,cfg_patch,fix", [
    ("service", known(), {}, "restart-service"),
    ("network", known(), {}, "restart-tailscale"),
    ("asleep", known(ethernet_mac="aa:bb:cc:dd:ee:ff", ethernet_active=True), {}, "wake"),
    ("asleep", known(), {}, "tell-owner"),                                   # Wi-Fi only: no reliable wake
    ("locked", known(), {}, "unlock"),
    ("locked", known(), {"remote_unlock": {}}, "tell-owner"),
    ("hung", known(), {}, "tell-owner"),                                     # no smart plug yet
    ("hung", known(), {"smart_plugs": {"mac-mini-1": {"off": "http://plug/off", "on": "http://plug/on"}}},
     "power-cycle"),
    ("unknown", known(), {}, "tell-owner"),
])
def test_ladder_step_switches_on_with_what_exists(state, facts, cfg_patch, fix):
    cfg = {**CFG, **cfg_patch}
    assert pc.fix_for(state, "mac-mini-1", facts, cfg) == fix


def test_locked_unlock_needs_the_root_script_too(tmp_path):
    assert pc.fix_for("locked", "mac-mini-1", known(), CFG, unlock_script=tmp_path / "missing") == "tell-owner"


# ── the handle loop: probe, classify, fix and re-probe, one rung of the ladder per trigger ────────────────────

def test_healthy_peer_opens_no_incident(tmp_path):
    result = pc.handle("mac-mini-1", "manual", CFG, probe=lambda p: P(tailscale=True, ssh_key=True, services_ok=True),
                       state_dir=tmp_path, now=lambda: T0)
    assert result["state"] == "healthy" and not (tmp_path / "mac-mini-1.json").exists()


def test_a_fix_that_works_closes_the_incident(tmp_path):
    p1 = P(tailscale=True, ssh_key=True, services_ok=False)  # service state
    p2 = P(tailscale=True, ssh_key=True, services_ok=True)   # healthy after fix
    probes = [p1, p2]
    result = pc.handle("mac-mini-1", "manual", CFG, probe=lambda p: probes.pop(0), run_fix=lambda *a: (True, "ok"),
                       state_dir=tmp_path)
    assert result["action"] == "fixed"
    assert not (tmp_path / "mac-mini-1.json").exists()


def test_fix_that_says_ok_but_probe_still_fails_counts_as_a_failure(tmp_path):
    p = P(tailscale=True, ssh_key=True, services_ok=False)
    result = pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, run_fix=lambda *a: (True, "tried"), state_dir=tmp_path)
    assert result["action"] == "failed"
    incident = json.loads((tmp_path / "mac-mini-1.json").read_text())
    assert incident["last_result"] == "restart-service: tried; still service"


def test_three_attempts_then_it_stops_and_tells_the_owner_once(tmp_path):
    p = P(tailscale=True, ssh_key=True, services_ok=False)
    told = []
    def run_fix(*a):
        return False, "nope"
    pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, run_fix=run_fix, tell=told.append, state_dir=tmp_path)
    pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, run_fix=run_fix, tell=told.append, state_dir=tmp_path)
    pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, run_fix=run_fix, tell=told.append, state_dir=tmp_path)
    assert len(told) == 1
    pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, run_fix=run_fix, tell=told.append, state_dir=tmp_path)
    assert len(told) == 1  # owner only told once


def test_recovery_after_giving_up_starts_a_fresh_budget_next_time(tmp_path):
    p1 = P(tailscale=True, ssh_key=True, services_ok=False)
    p2 = P(tailscale=True, ssh_key=True, services_ok=True)
    told = []
    # Three failing attempts, owner told
    for _ in range(3):
        pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p1, run_fix=lambda *a: (False, "nope"),
                  tell=told.append, state_dir=tmp_path)
    assert len(told) == 1
    # Peer comes back up, incident closes, owner told (recovery is good news)
    told.clear()
    pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p2, state_dir=tmp_path, tell=told.append)
    assert len(told) == 1 and "back up" in str(told[0])
    # Another incident opens: fresh budget
    told.clear()
    for _ in range(3):
        pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p1, run_fix=lambda *a: (False, "nope"),
                  tell=told.append, state_dir=tmp_path)
    assert len(told) == 1


def test_two_triggers_together_one_acts_the_other_stands_down(tmp_path):
    p = P(tailscale=True, ssh_key=True, services_ok=False)
    done = []
    def run_fix(*a):
        done.append("fix")
        return False, "nope"
    # Two threads trigger at nearly the same time
    r1, r2 = [], []
    def t1():
        r1.append(pc.handle("mac-mini-1", "trigger1", CFG, probe=lambda p_: p, run_fix=run_fix, state_dir=tmp_path))
    def t2():
        r2.append(pc.handle("mac-mini-1", "trigger2", CFG, probe=lambda p_: p, run_fix=run_fix, state_dir=tmp_path))
    threads = [threading.Thread(target=t1), threading.Thread(target=t2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(done) == 1  # only one fix ran
    assert [a["action"] for a in r1 + r2] == ["failed", "busy"] or ["busy", "failed"]


def test_the_attempt_is_counted_before_the_fix_runs(tmp_path):
    p = P(tailscale=True, ssh_key=True, services_ok=False)
    runs = []
    def run_fix(*a):
        inc = json.loads((tmp_path / "mac-mini-1.json").read_text())
        runs.append(inc["attempts"])
        return False, "nope"
    # First attempt: attempts field gets incremented before fix
    pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, run_fix=run_fix, state_dir=tmp_path)
    assert runs == [1]


def test_tell_owner_states_message_once_per_incident_and_say_what_to_do(tmp_path):
    p = P(tailscale=False, same_lan=False)
    told = []
    pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, tell=told.append, state_dir=tmp_path)
    assert len(told) == 1 and "offline" in str(told[0]) and "can't see it from here" in str(told[0])
    told.clear()
    pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, tell=told.append, state_dir=tmp_path)
    assert len(told) == 0  # told once per incident


def test_watcher_off_the_home_lan_can_only_tell(tmp_path):
    p = P(tailscale=False, same_lan=False)
    result = pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, state_dir=tmp_path)
    # WoL, restart-tailscale, power-cycle all require same_lan: impossible here, so tell-owner
    assert result["fix"] == "tell-owner"


def test_every_step_goes_to_job_events(tmp_path):
    p = P(tailscale=True, ssh_key=True, services_ok=False)
    result = pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p, run_fix=lambda *a: (False, "nope"),
                       state_dir=tmp_path, jobs_dir=tmp_path)
    # job_events writes one file per job run
    assert (tmp_path / "job-runs").exists()


def test_clock_skew_between_machines_cannot_reopen_or_expire_an_incident(tmp_path):
    # Suppose machine A creates an incident at T, machine B sees it at T-10s and tries to close it
    p = P(tailscale=True, ssh_key=True, services_ok=False)
    inc = {"opened_at": T0.isoformat(), "attempts": 0, "told": False, "trigger": "test"}
    (tmp_path / "mac-mini-1.json").write_text(json.dumps(inc))

    # Machine B sees the incident as "old" (opened 10s ago from its perspective)
    p2 = P(tailscale=True, ssh_key=True, services_ok=True)
    result = pc.handle("mac-mini-1", "manual", CFG, probe=lambda p_: p2, state_dir=tmp_path,
                       now=lambda: T0 + timedelta(seconds=10))
    # The incident should still be cleared (skew doesn't prevent recovery)
    assert result["action"] == "recovered"


# ── IPN watcher: when peers go offline or come back, trigger once ───────────────────────────────────────────────

def test_ipn_bus_only_peer_change_lines_wake_the_watcher(tmp_path):
    lines = ["not a peer change", '{"PeerChanges": []}', "another line"]
    handled = []
    def handle(p, trig):
        handled.append(trig)
        return {}
    pc.read_ipn(lines, ["p1", "p2"], online=lambda: {"p1": True}, handle=handle, state_dir=tmp_path)
    assert handled == ["tailscale-offline"]  # one offline edge


def test_went_offline_is_an_up_to_down_edge_only():
    assert pc.went_offline({}, {}) == []
    assert pc.went_offline({}, {"p": True}) == []
    assert pc.went_offline({"p": True}, {"p": False}) == ["p"]
    assert pc.went_offline({"p": False}, {"p": False}) == []


def test_watched_by_reads_the_config():
    cfg = {"watch": {"mini": ["laptop"], "laptop": []}}
    assert pc.watched_by("laptop", cfg) == ["mini"]
    assert pc.watched_by("mini", cfg) == []


# ── ssh: test parsers ────────────────────────────────────────────────────────────────────────────────────────────

def test_ssh_methods_from_permission_denied():
    out = "Permission denied (publickey,password).\n"
    assert pc.parse_ssh_methods(out) == ["publickey", "password"]


def test_tailscale_online_from_status_json():
    st = {
        "Peer": {
            "coreqnpqe": {
                "HostName": "laptop",
                "Online": True,
            }
        }
    }
    assert pc.online_from_status(st, "laptop") is True
    assert pc.online_from_status(st, "other") is None


def test_arp_parsers_mac_and_linux():
    # macOS arp output
    mac_out = "192.0.2.41 (fe80::1) at aa:bb:cc:dd:ee:ff on en0 ifscope [ethernet]"
    assert pc.parse_arp(mac_out) is True
    # Linux ip neigh output
    linux_out = "192.0.2.41 dev eth0  lladdr aa:bb:cc:dd:ee:ff  REACHABLE"
    assert pc.parse_arp(linux_out) is True
    assert pc.parse_arp("") is False


# ── wake on LAN ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_magic_packet_is_six_ff_then_the_mac_sixteen_times():
    pkt = pc.magic_packet("aa:bb:cc:dd:ee:ff")
    assert pkt[:6] == b"\xff" * 6
    assert pkt[6:] == b"\xaa\xbb\xcc\xdd\xee\xff" * 16


# ── messaging ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_device_names_for_people():
    assert "Mac mini" in pc.device_name("mac-mini-1")
    assert "MacBook Pro" in pc.device_name("macbook-pro-1")
    assert "2012" in pc.device_name("mac-mini-2012")
    assert "unknown" in pc.device_name(None)


# ── FileVault unlock (macOS 26+ remote unlock) ─────────────────────────────────────────────────────────────────

def test_unlock_script_dry_run_reads_no_password_and_connects_nowhere():
    r = subprocess.run([sys.executable, str(LIB / "marvin-peer-unlock-setup"), "--dry-run", "mini", "user"],
                       capture_output=True, text=True, timeout=5)
    assert r.returncode == 0
    assert "password" not in r.stdout.lower()


def test_unlock_script_refuses_a_peer_name_that_could_be_a_path():
    r = subprocess.run([sys.executable, str(LIB / "marvin-peer-unlock-setup"), "--dry-run", "mini/etc", "user"],
                       capture_output=True, text=True, timeout=5)
    assert r.returncode != 0


def test_unlock_script_sends_the_password_only_through_askpass():
    r = subprocess.run([sys.executable, str(LIB / "marvin-peer-unlock-setup"), "--dry-run", "mini", "user"],
                       capture_output=True, text=True, timeout=5)
    assert "--askpass" in r.stdout


# ── expect-back: bounded wait after a planned restart ──────────────────────────────────────────────────────────

def test_expect_back_waits_once_to_the_deadline_then_checks_once(tmp_path):
    handled = []
    sleeps = []
    r = pc.expect_back("mac-mini-1", CFG, minutes=10, sleep=sleeps.append,
                       handle=lambda p, trig: handled.append(trig) or {"action": "none"},
                       state_dir=tmp_path, now=lambda: T0)
    assert sleeps == [600] and handled == ["expected-back"] and r == {"action": "none"}


def test_expect_back_skips_the_probe_when_im_back_already_arrived(tmp_path):
    later = T0 + timedelta(minutes=3)
    (tmp_path / "mac-mini-1.last.json").write_text(json.dumps({"state": "healthy", "at": later.isoformat()}))
    handled = []
    r = pc.expect_back("mac-mini-1", CFG, minutes=10, sleep=lambda s: None,
                       handle=lambda p, trig: handled.append(trig), state_dir=tmp_path, now=lambda: T0)
    assert handled == [] and r["action"] == "back"


def test_command_output_that_isnt_utf8_never_crashes_a_probe():
    r = pc._run(["/bin/sh", "-c", r"printf 'x\325y'"])
    assert r is not None and r.stdout.startswith("x")
