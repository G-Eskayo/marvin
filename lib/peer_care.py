#!/usr/bin/env python3
"""Peer care: the two always-home machines watch each other (marvin#847, design #769 sections 3-5, ADR 0081).

The watchers are the Mac mini and the 2012 Linux mini (owner, #769: not the laptop, which isn't reliably on). They
act only on a trigger, never a timer:

  tailscale    `watch-ipn`: one blocked reader on tailscaled's IPN bus; a watched peer going offline wakes it
  code-sync    the end of each existing code-sync run probes the watched peers (no new clock)
  back         the restarted machine's boot says "I'm back"; `expect-back` waits once, bounded, for it
  manual       `check <peer>`

On a trigger: one probe, a pure `classify` naming the state, and one rung of that state's fix ladder. Each incident
gets at most `attempts_per_incident` (3) fixes, then the owner is told once. A lock per peer stops two triggers (or
two watchers) acting at once, and the attempt is counted before the fix runs, so a crash can't dodge the budget.
Every step goes to job_events as `peer-care-<peer>` (the Activity tab shows it with no new UI).

Fixes switch on as the owner's pieces arrive, with no code change: Wake-on-LAN once the peer's Ethernet is seen in
use, the FileVault unlock once `marvin-peer-unlock` is installed (owner's one-line setup), a power cycle once a smart
plug is listed in config/peer_care.json `smart_plugs`.

    peer_care.py check <peer> [--trigger NAME]     probe and maybe fix one peer
    peer_care.py check-all --trigger code-sync      every peer this machine watches
    peer_care.py watch-ipn                          the long-running IPN reader (launchd KeepAlive / systemd)
    peer_care.py im-back                            at boot: tell the watchers this machine is up
    peer_care.py expect-back <peer> [--minutes N]   after a planned restart: wait once for "I'm back"
    peer_care.py status [--json]                    incidents and last probes, for the Health card
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

CONFIG_PATH = HERE.parent / "config" / "peer_care.json"
STATE_DIR = HERE.parent / "var" / "peer-care"            # gitignored; per machine, never synced
UNLOCK_SCRIPT = Path("/usr/local/libexec/marvin-peer-unlock")
UNLOCK_SETUP = "sudo ~/.agents/bin/marvin-peer-unlock-setup"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=accept-new"]
TAILSCALE_CANDIDATES = ["/opt/homebrew/bin/tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
                        "/usr/local/bin/tailscale", "/usr/bin/tailscale"]
WEBHOOK_LABEL = "com.marvin.dashboard-webhook"
WEBHOOK_PORT = 7878


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def device_name(device: str) -> str:
    """For people: "mac-mini-1" -> "Mac mini", "macbook-pro-1" -> "MacBook Pro", "mac-mini-2012" -> "2012 mini"."""
    m = re.fullmatch(r"mac-mini-(\d{4})", device or "")
    if m:
        return f"{m.group(1)} mini"
    words = {"mac": "Mac", "mini": "mini", "macbook": "MacBook", "pro": "Pro", "air": "Air"}
    parts = re.sub(r"-\d$", "", device or "").split("-")
    return " ".join(words.get(w, w) for w in parts) if all(w in words for w in parts) else (device or "the peer")


def watched_by(device: str, cfg: dict) -> list[str]:
    """Who watches `device`."""
    return [w for w, peers in cfg["watch"].items() if device in peers]


# ── probing ─────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Probe:
    tailscale: bool | None = None      # peer online on the tailnet
    ssh_key: bool | None = None        # ssh with our key over Tailscale works
    services_ok: bool | None = None    # the peer's MARVIN services answer (None: nothing to check)
    services_detail: str = ""
    same_lan: bool | None = None       # this watcher is on the peer's home LAN
    arp: bool | None = None            # the peer's LAN address answers ARP
    port22: bool | None = None         # TCP 22 open on the LAN address
    lan_ssh: bool | None = None        # ssh with our key over the LAN works
    ssh_methods: list = field(default_factory=list)   # what sshd offered when the key was refused

    def summary(self) -> str:
        return ", ".join(f"{k}={v}" for k, v in asdict(self).items() if v not in (None, [], ""))


def classify(p: Probe) -> str:
    """healthy | service | network | locked | asleep | hung | unknown (design #769 section 4). Anything a probe
    couldn't read is `unknown`, never healthy."""
    if p.tailscale is True:
        if p.ssh_key is not True:
            return "unknown"
        return "service" if p.services_ok is False else "healthy"
    if p.tailscale is None or p.same_lan is not True:
        return "unknown"
    if p.lan_ssh is True:
        return "network"
    if p.port22 is True and "password" in p.ssh_methods and "publickey" not in p.ssh_methods:
        return "locked"          # macOS 26's pre-boot sshd: password only (man fdesetup, REMOTE UNLOCKING VIA SSH)
    if p.port22 is not True and p.arp is False:
        return "asleep"
    if p.port22 is False and p.arp is True:
        return "hung"            # the NIC answers, the OS doesn't
    return "unknown"


def tailscale_bin() -> str | None:
    return next((t for t in TAILSCALE_CANDIDATES if os.access(t, os.X_OK)), None) or shutil.which("tailscale")


def online_from_status(status: dict, hostname: str) -> bool | None:
    want = (hostname or "").lower()
    for peer in (status.get("Peer") or {}).values():
        names = {(peer.get("HostName") or "").lower(), (peer.get("DNSName") or "").split(".")[0].lower()}
        if want in names:
            return bool(peer.get("Online"))
    return None


def _registry() -> dict:
    import machine_profile
    return machine_profile._load_registry()


def ts_host(device: str) -> str:
    return (_registry().get(device) or {}).get("tailscale_hostname") or device


def tailscale_status() -> dict | None:
    ts = tailscale_bin()
    if not ts:
        return None
    try:
        out = subprocess.run([ts, "status", "--json"], capture_output=True, text=True, timeout=10).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def peer_online(device: str) -> bool | None:
    st = tailscale_status()
    return None if st is None else online_from_status(st, ts_host(device))


def parse_ssh_methods(stderr: str) -> list[str]:
    m = re.search(r"Permission denied \(([^)]*)\)", stderr or "")
    return [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []


def parse_arp(out: str) -> bool:
    if re.search(r"\bat [0-9a-fA-F]{1,2}(:[0-9a-fA-F]{1,2}){5}\b", out or ""):
        return True
    return bool(re.search(r"lladdr [0-9a-fA-F:]{11,17}\b.*\b(REACHABLE|STALE|DELAY|PROBE|PERMANENT)", out or ""))


def _run(cmd: list[str], timeout: float = 15) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None


def _ssh(target: str, command: str, timeout: float = 20) -> subprocess.CompletedProcess | None:
    return _run(["ssh", *SSH_OPTS, target, command], timeout)


def _port_open(ip: str, port: int = 22, timeout: float = 3) -> bool | None:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except (ConnectionRefusedError, socket.timeout, TimeoutError):
        return False
    except OSError:
        return False


def _arp(ip: str) -> bool | None:
    r = _run(["ip", "neigh", "show", ip]) if sys.platform.startswith("linux") else _run(["/usr/sbin/arp", "-n", ip])
    return None if r is None else parse_arp(r.stdout)


def local_network_id() -> str | None:
    """The gateway's MAC: two machines with the same one are on the same LAN (as network_reachability, on Linux too)."""
    if sys.platform.startswith("linux"):
        r = _run(["ip", "route", "show", "default"])
        m = re.search(r"default via (\S+)", r.stdout if r else "")
        if not m:
            return None
        n = _run(["ip", "neigh", "show", m.group(1)])
        mm = re.search(r"lladdr (\S+)", n.stdout if n else "")
        return mm.group(1).lower() if mm else m.group(1)
    import network_reachability
    nid = network_reachability.current_network_id()
    return None if nid == "unknown" else nid.lower()


# What a healthy peer says about itself, cached for when it's down. KEY=VALUE lines, on macOS and Linux.
FACTS_CMD = r"""
echo OS=$(uname -s); echo USER=$(whoami)
if [ "$(uname -s)" = Darwin ]; then
  gw=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}'); echo GW_MAC=$(arp -n "$gw" 2>/dev/null | awk '{print $4}')
  dev=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}'); echo LAN_IP=$(ipconfig getifaddr "$dev")
  echo ETH_MAC=$(ifconfig en0 2>/dev/null | awk '/ether/{print $2}'); echo ETH_ACTIVE=$(ifconfig en0 2>/dev/null | grep -c 'status: active')
else
  gw=$(ip route show default | awk '{print $3; exit}'); echo GW_MAC=$(ip neigh show "$gw" | awk '{print $5; exit}')
  dev=$(ip route show default | awk '{print $5; exit}'); echo LAN_IP=$(ip -4 -o addr show "$dev" | awk '{print $4}' | cut -d/ -f1)
  eth=$(ls /sys/class/net | grep -E '^(en|eth)' | head -1); echo ETH_MAC=$(cat /sys/class/net/$eth/address 2>/dev/null)
  echo ETH_ACTIVE=$([ "$dev" = "$eth" ] && echo 1 || echo 0)
fi
"""


def parse_facts(out: str) -> dict:
    kv = dict(line.split("=", 1) for line in (out or "").splitlines() if "=" in line)
    return {"os": "macos" if kv.get("OS") == "Darwin" else (kv.get("OS") or "").lower() or None,
            "user": kv.get("USER") or None, "network_id": (kv.get("GW_MAC") or "").lower() or None,
            "lan_ip": kv.get("LAN_IP") or None, "ethernet_mac": (kv.get("ETH_MAC") or "").lower() or None,
            "ethernet_active": kv.get("ETH_ACTIVE") == "1"}


def facts_path(state_dir: Path, peer: str) -> Path:
    return state_dir / f"{peer}.facts.json"


def load_facts(peer: str, state_dir: Path = STATE_DIR) -> dict:
    try:
        return json.loads(facts_path(state_dir, peer).read_text())
    except (OSError, ValueError):
        return {}


def refresh_facts(peer: str, state_dir: Path = STATE_DIR) -> dict:
    r = _ssh(ts_host(peer), FACTS_CMD)
    if not r or r.returncode != 0:
        return load_facts(peer, state_dir)
    f = {**parse_facts(r.stdout), "seen_at": _now().isoformat()}
    state_dir.mkdir(parents=True, exist_ok=True)
    tmp = facts_path(state_dir, peer).with_suffix(".tmp")
    tmp.write_text(json.dumps(f))
    os.replace(tmp, facts_path(state_dir, peer))
    return f


def same_lan_as(peer: str) -> bool | None:
    mine, theirs = local_network_id(), load_facts(peer).get("network_id")
    if not mine or not theirs:
        return None
    return mine == theirs


def _services(peer: str, facts: dict) -> tuple[bool | None, str]:
    """The MARVIN services a peer runs. The Mac mini's merge webhook; the 2012 has none beyond sshd."""
    if (facts.get("os") or (_registry().get(peer) or {}).get("os", "macos")) != "macos":
        return None, ""
    import urllib.error
    import urllib.request
    try:
        urllib.request.urlopen(f"http://{ts_host(peer)}:{WEBHOOK_PORT}/merge-history", timeout=3).close()
        return True, ""
    except urllib.error.HTTPError:
        return True, ""
    except Exception:  # noqa: BLE001
        return False, f"merge webhook :{WEBHOOK_PORT} not answering"


def probe(peer: str, state_dir: Path = STATE_DIR) -> Probe:
    """One bounded probe (~15 s worst case)."""
    p = Probe(tailscale=peer_online(peer))
    if p.tailscale:
        r = _ssh(ts_host(peer), "true", timeout=10)
        p.ssh_key = None if r is None else r.returncode == 0
        if p.ssh_key:
            facts = refresh_facts(peer, state_dir)
            p.services_ok, p.services_detail = _services(peer, facts)
        return p
    facts = load_facts(peer, state_dir)
    p.same_lan = same_lan_as(peer)
    ip = facts.get("lan_ip")
    if not p.same_lan or not ip:
        return p
    p.port22 = _port_open(ip)              # also makes the ARP entry fresh
    p.arp = _arp(ip)
    if p.port22:
        r = _run(["ssh", *SSH_OPTS, "-o", "PreferredAuthentications=publickey", f"{facts.get('user')}@{ip}", "true"], 10)
        p.lan_ssh = None if r is None else r.returncode == 0
        if r is not None and r.returncode != 0:
            r2 = _run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "PubkeyAuthentication=no",
                       "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                       f"{facts.get('user')}@{ip}", "true"], 10)
            p.ssh_methods = parse_ssh_methods(r2.stderr if r2 else "") or parse_ssh_methods(r.stderr)
    return p


# ── fixing ──────────────────────────────────────────────────────────────────────────────────────────────────────

def fix_for(state: str, peer: str, facts: dict, cfg: dict, unlock_script: Path | None = None) -> str:
    """The one rung for this state, given what exists today. `unlock_script` None skips the installed check."""
    if state == "service":
        return "restart-service"
    if state == "network":
        return "restart-tailscale"
    if state == "asleep":
        return "wake" if facts.get("ethernet_active") and facts.get("ethernet_mac") else "tell-owner"
    if state == "locked":
        allowed = bool((cfg.get("remote_unlock") or {}).get(peer))
        installed = unlock_script is None or Path(unlock_script).exists()
        return "unlock" if allowed and installed else "tell-owner"
    if state == "hung":
        plug = (cfg.get("smart_plugs") or {}).get(peer) or {}
        return "power-cycle" if plug.get("off") and plug.get("on") else "tell-owner"
    return "tell-owner"


def magic_packet(mac: str) -> bytes:
    hexs = re.sub(r"[:\-]", "", mac or "")
    if not re.fullmatch(r"[0-9a-fA-F]{12}", hexs):
        raise ValueError(f"not a MAC address: {mac!r}")
    return b"\xff" * 6 + bytes.fromhex(hexs) * 16


def run_fix(name: str, peer: str, p: Probe, facts: dict, cfg: dict | None = None) -> tuple[bool, str]:
    """The real fixes. Each is bounded; none loops."""
    cfg = cfg or load_config()
    lan = f"{facts.get('user')}@{facts.get('lan_ip')}"
    if name == "restart-service":
        r = _ssh(ts_host(peer), f"launchctl kickstart -k gui/$(id -u)/{WEBHOOK_LABEL}")
        return bool(r and r.returncode == 0), (r.stderr.strip() if r else "ssh failed")[:200] or "kickstarted"
    if name == "restart-tailscale":
        cmd = ("for t in " + " ".join(TAILSCALE_CANDIDATES) + "; do [ -x \"$t\" ] && { \"$t\" down; \"$t\" up; exit $?; }; done; exit 127")
        r = _ssh(lan, cmd, timeout=40)
        return bool(r and r.returncode == 0), (r.stderr.strip() if r else "ssh over the LAN failed")[:200] or "tailscale up"
    if name == "wake":
        pkt = magic_packet(facts["ethernet_mac"])
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            s.sendto(pkt, ("255.255.255.255", 9))
        time.sleep(int(cfg.get("wake_wait_seconds", 120)))
        return True, "magic packet sent"
    if name == "unlock":
        r = _run(["/usr/bin/sudo", "-n", str(UNLOCK_SCRIPT), peer], timeout=60)
        return bool(r and r.returncode == 0), ((r.stdout + r.stderr).strip() if r else "couldn't run the unlock")[-200:]
    if name == "power-cycle":
        import urllib.request
        plug = cfg["smart_plugs"][peer]
        urllib.request.urlopen(plug["off"], timeout=10).close()
        time.sleep(10)
        urllib.request.urlopen(plug["on"], timeout=10).close()
        return True, "power cycled; it will come back at the unlock screen"
    return False, f"no such fix {name}"


def tell_message(state: str, peer: str, p: Probe | None = None) -> str:
    name = device_name(peer)
    return {
        "hung": f"The {name} isn't responding: its network card answers, nothing else does. It needs the power button "
                f"held, then the FileVault password.",
        "asleep": f"The {name} isn't answering on the network, and it can't be woken over Wi-Fi. It needs you to wake "
                  f"it (or plug it into Ethernet so it can be woken remotely).",
        "locked": f"The {name} is at the FileVault unlock screen and needs you to unlock it. "
                  f"(Remote unlock switches on after the one-line setup: {UNLOCK_SETUP} {peer} user@address)",
        "unknown": f"The {name} is offline and I can't see it from here: this watcher isn't on its home network, or a "
                   f"probe couldn't finish.",
    }.get(state, f"The {name} has a problem ({state}) that I can't fix.")


def notify_owner(title: str, message: str, actions: bool = False, device: str | None = None) -> None:
    """This machine's desktop notification (with Postpone / Skip tonight when `actions`) plus the phone push."""
    if actions and sys.platform == "darwin" and shutil.which("terminal-notifier"):
        py = sys.executable
        script = str(HERE / "nightly_reset.py")
        # terminal-notifier blocks until clicked or timed out and prints the chosen action; run it detached
        subprocess.Popen(["/bin/sh", "-c",
                          'a=$(terminal-notifier -title "$1" -message "$2" -actions "Postpone,Skip tonight" '
                          '-timeout 300 -group marvin-nightly-reset); '
                          'case "$a" in Postpone) "$3" "$4" postpone;; "Skip tonight") "$3" "$4" skip;; esac',
                          "_", title, message, py, script], start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            import mr_notification
            mr_notification.push_notify(message)
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        import mr_notification
        mr_notification._fire(title, message, None)
    except Exception:  # noqa: BLE001 -- telling must never break the watcher
        pass


def _incident_path(state_dir: Path, peer: str) -> Path:
    return state_dir / f"{peer}.json"


def load_incident(state_dir: Path, peer: str) -> dict:
    try:
        return json.loads(_incident_path(state_dir, peer).read_text())
    except (OSError, ValueError):
        return {}


def _save_incident(state_dir: Path, peer: str, inc: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    p = _incident_path(state_dir, peer)
    if not inc:
        p.unlink(missing_ok=True)
        return
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(inc))
    os.replace(tmp, p)


def _record_probe(state_dir: Path, peer: str, state: str, p: Probe, at: datetime) -> None:
    last = state_dir / f"{peer}.last.json"
    tmp = last.with_suffix(".tmp")
    tmp.write_text(json.dumps({"state": state, "at": at.isoformat(), "probe": asdict(p)}))
    os.replace(tmp, last)


def handle(peer: str, trigger: str, cfg: dict, *, probe: Callable = probe, run_fix: Callable | None = None,
           tell: Callable | None = None, state_dir: Path = STATE_DIR, now: Callable = _now,
           facts: Callable | None = None, unlock_script: Path | None = UNLOCK_SCRIPT, jobs_dir: Path | None = None) -> dict:
    """One trigger for one peer: probe, classify, at most one fix, re-probe. Returns what happened."""
    import job_events
    run_fix = run_fix or (lambda name, pr, p, f: globals()["run_fix"](name, pr, p, f, cfg))
    tell = tell or notify_owner
    facts = facts or (lambda pr: load_facts(pr, state_dir))
    budget = int(cfg.get("attempts_per_incident", 3))
    name = device_name(peer)
    state_dir.mkdir(parents=True, exist_ok=True)
    with open(state_dir / f"{peer}.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"peer": peer, "action": "busy", "state": None, "fix": None}
        with job_events.job_run(f"peer-care-{peer}", f"Peer care: {name}", jobs_dir) as run:
            run.step("trigger", trigger)
            p = probe(peer)
            state = classify(p)
            run.step("probe", f"{state}: {p.summary()}")
            _record_probe(state_dir, peer, state, p, now())
            inc = load_incident(state_dir, peer)
            if state == "healthy":
                if not inc:
                    run.step("result", "healthy")
                    return {"peer": peer, "action": "none", "state": state, "fix": None}
                _save_incident(state_dir, peer, {})
                if inc.get("told"):
                    tell("MARVIN: back up", f"The {name} is back up.")
                run.step("result", f"recovered after {inc.get('attempts', 0)} attempt(s)")
                return {"peer": peer, "action": "recovered", "state": state, "fix": None}
            if not inc:
                inc = {"opened_at": now().isoformat(), "attempts": 0, "told": False, "trigger": trigger}
            if inc["attempts"] >= budget:
                run.step("result", f"gave up after {budget} attempts; waiting for you")
                return {"peer": peer, "action": "gave-up", "state": state, "fix": None}
            fix = fix_for(state, peer, facts(peer), cfg, unlock_script)
            inc.update(attempts=inc["attempts"] + 1, state=state, last_fix=fix, last_at=now().isoformat())
            _save_incident(state_dir, peer, inc)               # counted before acting
            run.step("fix", f"{fix} (attempt {inc['attempts']} of {budget})")
            if fix == "tell-owner":
                if not inc["told"]:
                    tell(f"MARVIN: the {name} needs you", tell_message(state, peer, p))
                    inc["told"] = True
                    _save_incident(state_dir, peer, inc)
                run.step("result", "told the owner")
                return {"peer": peer, "action": "told", "state": state, "fix": fix}
            ok, detail = run_fix(fix, peer, p, facts(peer))
            p2 = probe(peer)
            s2 = classify(p2)
            _record_probe(state_dir, peer, s2, p2, now())
            if s2 == "healthy":
                _save_incident(state_dir, peer, {})
                run.step("result", f"fixed by {fix}: {detail}")
                return {"peer": peer, "action": "fixed", "state": state, "fix": fix}
            inc["last_result"] = f"{fix}: {detail}; still {s2}"
            if inc["attempts"] >= budget and not inc["told"]:
                tell(f"MARVIN: the {name} needs you",
                     f"The {name} is still {s2} after {budget} tries (last: {fix}). It needs you. "
                     + tell_message(s2, peer, p2))
                inc["told"] = True
            _save_incident(state_dir, peer, inc)
            run.step("result", inc["last_result"])
            run.fail(inc["last_result"])
            return {"peer": peer, "action": "failed", "state": state, "fix": fix}


# ── triggers ────────────────────────────────────────────────────────────────────────────────────────────────────

def peer_changed(line: str) -> bool:
    try:
        msg = json.loads(line)
    except ValueError:
        return False
    return isinstance(msg, dict) and ("PeerChanges" in msg or "NetMap" in msg)


def went_offline(before: dict, now_: dict) -> list[str]:
    return [p for p, up in now_.items() if up is False and before.get(p) is not False]


def watch_ipn(me: str, cfg: dict) -> int:
    """Block on tailscaled's IPN bus; on each peer change re-read the watched peers and handle any that went down."""
    ts = tailscale_bin()
    if not ts:
        print("no tailscale CLI", file=sys.stderr)
        return 1
    peers = cfg["watch"].get(me, [])
    seen: dict = {}
    proc = subprocess.Popen([ts, "debug", "watch-ipn", "--peer-changes"], stdout=subprocess.PIPE, text=True)
    for line in proc.stdout:
        if not peer_changed(line):
            continue
        st = tailscale_status() or {}
        cur = {p: online_from_status(st, ts_host(p)) for p in peers}
        for p in went_offline(seen, cur):
            handle(p, "tailscale-offline", cfg)
        seen.update({k: v for k, v in cur.items() if v is not None})
    return proc.wait()


def im_back(me: str, cfg: dict) -> None:
    """At boot: tell each watcher. It closes any open incident by probing (a healthy probe closes it)."""
    for w in watched_by(me, cfg):
        _ssh(ts_host(w), f"~/.agents/venv/bin/python ~/.agents/lib/peer_care.py check {me} --trigger back", 60)


def expect_back(peer: str, cfg: dict, minutes: float | None = None) -> dict:
    """After a planned restart: one bounded wait, then one check. A healthy probe is the "I'm back" seen from here."""
    deadline = time.monotonic() + 60 * (minutes or cfg.get("back_within_minutes", 10))
    while time.monotonic() < deadline:
        time.sleep(min(60, max(0, deadline - time.monotonic())))
        if peer_online(peer):
            break
    return handle(peer, "expected-back", cfg)


def status(cfg: dict, state_dir: Path = STATE_DIR) -> dict:
    import machine_profile
    me = machine_profile.registry_id()
    out = {}
    for p in cfg["watch"].get(me, []):
        try:
            last = json.loads((state_dir / f"{p}.last.json").read_text())
        except (OSError, ValueError):
            last = None
        out[p] = {"name": device_name(p), "last": last, "incident": load_incident(state_dir, p),
                  "unlock_installed": UNLOCK_SCRIPT.exists()}
    return {"watcher": me, "peers": out}


def main(argv: list[str] | None = None) -> int:
    import machine_profile
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("peer")
    c.add_argument("--trigger", default="manual")
    a_ = sub.add_parser("check-all")
    a_.add_argument("--trigger", default="manual")
    sub.add_parser("watch-ipn")
    sub.add_parser("im-back")
    e = sub.add_parser("expect-back")
    e.add_argument("peer")
    e.add_argument("--minutes", type=float, default=None)
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = load_config()
    me = machine_profile.registry_id()
    if a.cmd == "check":
        print(json.dumps(handle(a.peer, a.trigger, cfg)))
    elif a.cmd == "check-all":
        for p in cfg["watch"].get(me, []):
            print(json.dumps(handle(p, a.trigger, cfg)))
    elif a.cmd == "watch-ipn":
        return watch_ipn(me, cfg)
    elif a.cmd == "im-back":
        im_back(me, cfg)
    elif a.cmd == "expect-back":
        print(json.dumps(expect_back(a.peer, cfg, a.minutes)))
    elif a.cmd == "status":
        print(json.dumps(status(cfg), indent=None if a.json else 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
