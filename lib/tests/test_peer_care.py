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


# ── handle(): budget, lock, logging ─────────────────────────────────────────────────────────────────────────────

class World:
    """A watched peer whose probe answers follow a script; fixes and notices only record."""

    def __init__(self, tmp_path, probes, fix_ok=True):
        self.dir = tmp_path / "peer-care"
        self.probes = list(probes)
        self.fixes, self.told = [], []
        self.fix_ok = fix_ok
        self.now = T0

    def probe(self, peer):
        return self.probes.pop(0) if len(self.probes) > 1 else self.probes[0]

    def run_fix(self, name, peer, probe, facts):
        self.fixes.append(name)
        return self.fix_ok, f"{name} ran"

    def tell(self, title, msg):
        self.told.append(msg)

    def handle(self, trigger="tailscale-offline", peer="mac-mini-1"):
        return pc.handle(peer, trigger, CFG, probe=self.probe, run_fix=self.run_fix, tell=self.tell,
                         state_dir=self.dir, now=lambda: self.now, facts=lambda p: known(), unlock_script=None)


DOWN = P(tailscale=False, same_lan=True, lan_ssh=True)          # "network"
UP = P(tailscale=True, ssh_key=True, services_ok=True)


def test_healthy_peer_opens_no_incident(tmp_path):
    w = World(tmp_path, [UP])
    r = w.handle()
    assert r["state"] == "healthy" and r["action"] == "none"
    assert w.fixes == [] and w.told == []


def test_a_fix_that_works_closes_the_incident(tmp_path):
    w = World(tmp_path, [DOWN, UP])
    r = w.handle()
    assert r["action"] == "fixed"
    assert w.fixes == ["restart-tailscale"]
    assert pc.load_incident(w.dir, "mac-mini-1") == {}


def test_fix_that_says_ok_but_probe_still_fails_counts_as_a_failure(tmp_path):
    w = World(tmp_path, [DOWN, DOWN])
    r = w.handle()
    assert r["action"] == "failed"
    assert pc.load_incident(w.dir, "mac-mini-1")["attempts"] == 1


def test_three_attempts_then_it_stops_and_tells_the_owner_once(tmp_path):
    w = World(tmp_path, [DOWN])
    for _ in range(3):
        w.handle()
    assert w.fixes == ["restart-tailscale"] * 3
    assert len(w.told) == 1 and "3 tries" in w.told[0]
    for _ in range(4):                       # more triggers: no more fixes, no more messages
        r = w.handle()
        assert r["action"] == "gave-up"
    assert len(w.fixes) == 3 and len(w.told) == 1


def test_recovery_after_giving_up_starts_a_fresh_budget_next_time(tmp_path):
    w = World(tmp_path, [DOWN])
    for _ in range(3):
        w.handle()
    w.probes = [UP]
    assert w.handle()["action"] == "recovered"
    assert any("back" in t for t in w.told)       # the owner was told it needed them, so also that it's back
    w.probes = [DOWN, DOWN]
    w.handle()
    assert pc.load_incident(w.dir, "mac-mini-1")["attempts"] == 1


def test_two_triggers_together_one_acts_the_other_stands_down(tmp_path):
    gate, release = threading.Event(), threading.Event()
    w = World(tmp_path, [DOWN])

    def slow_fix(name, peer, probe, facts):
        gate.set()
        release.wait(5)
        w.fixes.append(name)
        return False, "slow"
    w.run_fix = slow_fix
    results = []
    t = threading.Thread(target=lambda: results.append(w.handle("tailscale-offline")))
    t.start()
    gate.wait(5)
    second = w.handle("dispatch-failed")
    release.set()
    t.join(5)
    assert second["action"] == "busy"
    assert w.fixes == ["restart-tailscale"]
    assert pc.load_incident(w.dir, "mac-mini-1")["attempts"] == 1


def test_the_attempt_is_counted_before_the_fix_runs(tmp_path):
    """A watcher that crashes mid-fix has still spent the attempt: the budget can't be dodged by dying."""
    w = World(tmp_path, [DOWN])

    def boom(name, peer, probe, facts):
        raise RuntimeError("crashed mid-fix")
    w.run_fix = boom
    with pytest.raises(RuntimeError):
        w.handle()
    assert pc.load_incident(w.dir, "mac-mini-1")["attempts"] == 1


def test_tell_owner_states_message_once_per_incident_and_say_what_to_do(tmp_path):
    hung = P(tailscale=False, same_lan=True, arp=True, port22=False)
    w = World(tmp_path, [hung])
    w.handle()
    w.handle()
    assert len(w.told) == 1
    assert "power button" in w.told[0]


def test_watcher_off_the_home_lan_can_only_tell(tmp_path):
    w = World(tmp_path, [P(tailscale=False, same_lan=False)])
    r = w.handle()
    assert r["fix"] == "tell-owner"
    assert "can't see it from here" in w.told[0]


def test_every_step_goes_to_job_events(tmp_path):
    jobs = tmp_path / "jobs"
    w = World(tmp_path, [DOWN, UP])
    pc.handle("mac-mini-1", "tailscale-offline", CFG, probe=w.probe, run_fix=w.run_fix, tell=w.tell,
              state_dir=w.dir, now=lambda: w.now, facts=lambda p: known(), unlock_script=None, jobs_dir=jobs)
    doc = json.loads((jobs / "peer-care-mac-mini-1.json").read_text())
    steps = [s["step"] for s in doc["runs"][-1]["steps"]]
    assert steps[:2] == ["trigger", "probe"]
    assert "fix" in steps and steps[-1] == "result"


def test_clock_skew_between_machines_cannot_reopen_or_expire_an_incident(tmp_path):
    # the incident is keyed by this watcher's own clock only; a peer's timestamps are never compared to it
    w = World(tmp_path, [DOWN])
    w.handle()
    w.now = T0 - timedelta(hours=5)              # this clock jumped back
    w.handle()
    assert pc.load_incident(w.dir, "mac-mini-1")["attempts"] == 2


# ── triggers ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_ipn_bus_only_peer_change_lines_wake_the_watcher():
    assert pc.peer_changed(json.dumps({"PeerChanges": [{"NodeID": 7, "Online": False}]})) is True
    assert pc.peer_changed(json.dumps({"NetMap": {"Peers": []}})) is True
    assert pc.peer_changed(json.dumps({"State": 6})) is False
    assert pc.peer_changed("Connected.") is False
    assert pc.peer_changed("not json {") is False


def test_went_offline_is_an_up_to_down_edge_only():
    assert pc.went_offline({"a": True, "b": True}, {"a": False, "b": True}) == ["a"]
    assert pc.went_offline({"a": False}, {"a": False}) == []          # still down: no new trigger
    assert pc.went_offline({}, {"a": False}) == ["a"]                 # first sight, already down: check it
    assert pc.went_offline({"a": True}, {"a": None}) == []            # couldn't read: not an edge


def test_watched_by_reads_the_config():
    assert pc.watched_by("mac-mini-2012", CFG) == ["mac-mini-1"]
    assert pc.watched_by("mac-mini-1", CFG) == ["mac-mini-2012"]
    assert pc.watched_by("macbook-pro-1", CFG) == []        # the laptop isn't a watcher


# ── parsers over real command output ────────────────────────────────────────────────────────────────────────────

def test_ssh_methods_from_permission_denied():
    err = "gileskayo@192.0.2.41: Permission denied (password,keyboard-interactive).\r\n"
    assert pc.parse_ssh_methods(err) == ["password", "keyboard-interactive"]
    assert pc.parse_ssh_methods("ssh: connect to host x port 22: Operation timed out") == []


def test_tailscale_online_from_status_json():
    st = {"Peer": {"k1": {"HostName": "mac-mini-2012", "Online": False},
                   "k2": {"HostName": "Gils-Mac-mini", "DNSName": "gils-mac-mini.tail.ts.net.", "Online": True}}}
    assert pc.online_from_status(st, "mac-mini-2012") is False
    assert pc.online_from_status(st, "gils-mac-mini") is True
    assert pc.online_from_status(st, "nobody") is None


def test_arp_parsers_mac_and_linux():
    assert pc.parse_arp("? (192.0.2.41) at b4:c:25:e2:80:19 on en1 ifscope [ethernet]") is True
    assert pc.parse_arp("? (192.0.2.41) at (incomplete) on en1 ifscope [ethernet]") is False
    assert pc.parse_arp("192.0.2.41 dev eth0 lladdr b4:0c:25:e2:80:19 REACHABLE") is True
    assert pc.parse_arp("192.0.2.41 dev eth0  FAILED") is False
    assert pc.parse_arp("") is False


def test_magic_packet_is_six_ff_then_the_mac_sixteen_times():
    pkt = pc.magic_packet("aa:bb:cc:dd:ee:ff")
    assert pkt[:6] == b"\xff" * 6
    assert pkt[6:] == bytes.fromhex("aabbccddeeff") * 16
    with pytest.raises(ValueError):
        pc.magic_packet("not-a-mac")


def test_device_names_for_people():
    assert pc.device_name("mac-mini-1") == "Mac mini"
    assert pc.device_name("macbook-pro-1") == "MacBook Pro"
    assert pc.device_name("mac-mini-2012") == "2012 mini"


# ── the root unlock script: dry-run only, and fakes for the real path ──────────────────────────────────────────

UNLOCK = LIB.parent / "bin" / "marvin-peer-unlock"


def test_unlock_script_dry_run_reads_no_password_and_connects_nowhere(tmp_path):
    calls = tmp_path / "calls"
    for n in ("ssh", "security", "cat"):
        (tmp_path / n).write_text(f'#!/bin/sh\necho "{n} $*" >> "{calls}"\n')
        (tmp_path / n).chmod(0o755)
    r = subprocess.run([str(UNLOCK), "mac-mini-1", "--dry-run"], capture_output=True, text=True, timeout=30,
                       env={"PATH": f"{tmp_path}:/usr/bin:/bin", "MARVIN_PEER_UNLOCK_DIR": str(tmp_path / "etc")})
    assert r.returncode == 0, r.stderr
    assert "dry run" in r.stdout.lower()
    assert not calls.exists()


def test_unlock_script_refuses_a_peer_name_that_could_be_a_path():
    for bad in ("../etc/passwd", "a b", "", "-oProxyCommand=x"):
        r = subprocess.run([str(UNLOCK), bad, "--dry-run"], capture_output=True, text=True, timeout=30)
        assert r.returncode == 64, bad


def test_unlock_script_sends_the_password_only_through_askpass(tmp_path):
    """The real path with a fake ssh: the password must not be in ssh's argv or environment; ssh gets it only by
    running the askpass program, which reads the root-only secret file itself. Host and user come from the root-owned
    config written at setup, never from the caller."""
    etc = tmp_path / "etc"
    etc.mkdir()
    pw = "s3cr3t pass"
    (etc / "mac-mini-1.secret").write_text(pw)
    (etc / "mac-mini-1.conf").write_text("TARGET=owner@192.0.2.41\n")
    rec = tmp_path / "rec"
    rec.mkdir()
    (tmp_path / "ssh").write_text(
        f'#!/bin/sh\necho "$@" > "{rec}/argv"; env > "{rec}/env"; "$SSH_ASKPASS" "password:" > "{rec}/got"\n')
    (tmp_path / "ssh").chmod(0o755)
    env = {"PATH": f"{tmp_path}:/usr/bin:/bin", "MARVIN_PEER_UNLOCK_DIR": str(etc), "MARVIN_PEER_UNLOCK_TEST": "1",
           "HOME": str(tmp_path)}
    r = subprocess.run([str(UNLOCK), "mac-mini-1"], capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    argv = (rec / "argv").read_text()
    assert "owner@192.0.2.41" in argv and "PubkeyAuthentication=no" in argv
    assert pw not in argv and pw not in (rec / "env").read_text()
    assert (rec / "got").read_text() == pw


def test_came_back_is_a_down_to_up_edge_only():
    assert pc.came_back({"a": False}, {"a": True}) == ["a"]
    assert pc.came_back({"a": True}, {"a": True}) == []
    assert pc.came_back({}, {"a": True}) == []                      # first sight, up: nothing to close
    assert pc.came_back({"a": False}, {"a": None}) == []


def test_ipn_reader_handles_down_edges_and_up_edges_with_an_open_incident(tmp_path):
    """Fed bus lines and tailnet states in order: the reader handles the peer when it goes down, and again when it
    comes back (that probe closes the incident). Unrelated bus lines and a steady state do nothing."""
    states = iter([{"mac-mini-1": True}, {"mac-mini-1": False}, {"mac-mini-1": False}, {"mac-mini-1": True}])
    handled = []
    lines = [json.dumps({"PeerChanges": []}), json.dumps({"State": 6}), json.dumps({"PeerChanges": []}),
             json.dumps({"PeerChanges": []}), json.dumps({"PeerChanges": []})]
    inc_dir = tmp_path / "pc"
    pc._save_incident(inc_dir, "mac-mini-1", {"attempts": 1})
    pc.read_ipn(lines, ["mac-mini-1"], online=lambda: next(states),
                handle=lambda p, trig: handled.append((p, trig)), state_dir=inc_dir)
    assert handled == [("mac-mini-1", "tailscale-offline"), ("mac-mini-1", "tailscale-back")]


def test_up_edge_without_an_incident_does_nothing(tmp_path):
    states = iter([{"mac-mini-1": False}, {"mac-mini-1": True}])
    handled = []
    pc.read_ipn([json.dumps({"PeerChanges": []})] * 2, ["mac-mini-1"], online=lambda: next(states),
                handle=lambda p, trig: handled.append(trig), state_dir=tmp_path / "pc")
    assert handled == ["tailscale-offline"]          # the down edge only; no incident was opened by the fake handle


def test_expect_back_waits_once_to_the_deadline_then_checks_once(tmp_path):
    """No re-check loop: one sleep to the deadline, then one handle(); if the peer's own "I'm back" already closed it
    (a healthy probe recorded after the restart began), it doesn't probe again."""
    sleeps, handled = [], []
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
