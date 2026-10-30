#!/usr/bin/env python3
"""The guarded nightly reset (marvin#847, design and owner answers on #769, ADR 0081).

Each Mac restarts once a night in its own slot (the Mac mini 00:30, the MacBook 02:30), only when nobody is using it,
nothing is running and a watcher is up, and never past 05:00. launchd's StartCalendarInterval starts `run` at the
slot: one event a night, not a poll. Then:

  owner using the Mac    re-check every 15 minutes (macOS has no "went idle" event), until 05:00, then skip
  helper/build/test      wait for that process to exit (kqueue NOTE_EXIT), never a kill; 05:00 is the only clock
  no watcher up          re-check every 15 minutes, so one machine always stays up
  MacBook                only if it is home and on power; otherwise skip the night
  all clear              a notice with Postpone and Skip tonight, on this Mac and the phone; 5 minutes later, if the
                         guards still pass, the restart

The restart itself is `sudo -n /usr/local/libexec/marvin-authrestart`, a root-owned script (bin/marvin-authrestart)
that reads the FileVault password from a root-only System keychain item and pipes it to `fdesetup authrestart`. This
module never sees the password. Without that script installed it records why and skips: a plain restart would stop
at the unlock screen with nothing running.

Every check is logged to job_events (job `nightly-reset`), and the night's state is one small file per Mac
(~/.claude/logs/nightly-reset/<device>.json) that the Health card and the Postpone/Skip buttons read and write.

Cost: O(1) per check; at most (05:00 - slot) / 15 min checks on a late night, and one blocked wait otherwise.

    nightly_reset.py run [--dry-run]     the launchd entry point
    nightly_reset.py status              tonight's verdict, without acting
    nightly_reset.py postpone | skip     the notice's buttons
"""
from __future__ import annotations

import argparse
import json
import os
import re
import select
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

CONFIG_PATH = HERE.parent / "config" / "peer_care.json"
STATE_DIR = Path.home() / ".claude" / "logs" / "nightly-reset"
ROOT_SCRIPT = Path("/usr/local/libexec/marvin-authrestart")
SETUP_COMMAND = "sudo ~/.agents/bin/marvin-reset-setup"
OWNER_IDLE_S = 15 * 60          # touched in the last 15 minutes = using it
MAX_STEPS = 500                 # a broken waiter can't spin forever
DONE = ("restarted", "skipped", "restart-failed")


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(Path(path).read_text())


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def night_window(device: str, now: datetime, cfg: dict) -> tuple[datetime, datetime] | None:
    """(slot, limit) of the night `now` belongs to: tonight's if the limit hasn't passed, else the next one.
    A device with no slot (the 2012 mini) has none."""
    slot_s = cfg["reset"]["slots"].get(device)
    if not slot_s:
        return None
    slot_t, limit_t = _hhmm(slot_s), _hhmm(cfg["reset"]["limit"])
    day = now.date() + timedelta(days=1) if now.time() >= limit_t else now.date()
    slot = datetime.combine(day, slot_t, now.tzinfo)
    limit = datetime.combine(day, limit_t, now.tzinfo)
    return slot, limit


def slot_conflicts(cfg: dict) -> list[str]:
    """Two Macs whose slots are equal: they could both be down at once. Slots are checked as start times; each
    Mac's guard also waits while its watcher is down, which covers a postponed reset running into the next slot."""
    seen: dict[str, str] = {}
    bad = []
    for dev, s in cfg["reset"]["slots"].items():
        if s in seen:
            bad.append(f"{seen[s]} and {dev} both at {s}")
        seen[s] = dev
    return bad


@dataclass
class Facts:
    idle_s: float | None = None
    watching_video: bool = False
    screen_sharing: bool = False
    ssh_logins: int = 0
    work: list = field(default_factory=list)          # [{"what": str, "pid": int}]
    peer_healthy: bool | None = None
    peer_name: str = "the watcher"
    on_power: bool | None = None
    at_home: bool | None = None
    needs_home_power: bool = False


@dataclass
class Verdict:
    action: str      # notice | wait-notice | restart | skip | done | wait-slot | wait-owner | wait-work | wait-peer | postponed
    reason: str
    until: datetime | None = None
    pids: list = field(default_factory=list)


def _ts(s):
    try:
        return datetime.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def owner_activity(f: Facts) -> str | None:
    if f.idle_s is None:
        return "couldn't tell whether the Mac is in use"
    if f.idle_s < OWNER_IDLE_S:
        return f"the Mac is in use (last input {int(f.idle_s // 60)} min ago)"
    if f.watching_video:
        return "something is playing on screen"
    if f.screen_sharing:
        return "Screen Sharing is connected"
    if f.ssh_logins:
        return f"{f.ssh_logins} terminal session(s) logged in over SSH"
    return None


def decide(now: datetime, window: tuple[datetime, datetime], f: Facts, st: dict, cfg: dict) -> Verdict:
    """One verdict for one moment. Pure: the caller gathers the facts and acts on the answer."""
    slot, limit = window
    recheck = timedelta(minutes=cfg["reset"]["recheck_minutes"])
    notice = timedelta(minutes=cfg["reset"]["notice_minutes"])
    if st.get("outcome") in DONE:
        return Verdict("done", f"already {st['outcome']} tonight")
    if st.get("skipped"):
        return Verdict("skip", st.get("skip_reason") or "you chose Skip tonight")
    if now < slot:
        return Verdict("wait-slot", "not time yet", slot)
    if now >= limit:
        held = st.get("last_wait") or "the guards never cleared"
        return Verdict("skip", f"still waiting at {limit:%H:%M}: {held}")
    if f.needs_home_power:
        if f.on_power is not True:
            return Verdict("skip", "on battery (or power unknown); the MacBook resets only on power")
        if f.at_home is not True:
            return Verdict("skip", "not at home (or couldn't tell); the MacBook resets only at home")
    postponed = _ts(st.get("postponed_until"))
    if postponed and now < postponed:
        return Verdict("postponed", f"postponed until {postponed:%H:%M}", postponed)
    if f.peer_healthy is not True:
        return Verdict("wait-peer", f"{f.peer_name} isn't up, so this Mac stays up too", min(now + recheck, limit))
    who = owner_activity(f)
    if who:
        return Verdict("wait-owner", who, min(now + recheck, limit))
    if f.work:
        names = ", ".join(w["what"] for w in f.work[:3]) + (f" and {len(f.work) - 3} more" if len(f.work) > 3 else "")
        return Verdict("wait-work", f"{names} running", limit, [w["pid"] for w in f.work if w.get("pid")])
    noticed = _ts(st.get("notice_at"))
    if not noticed:
        return Verdict("notice", "all clear", now + notice)
    if now < noticed + notice:
        return Verdict("wait-notice", f"restarting at {noticed + notice:%H:%M}", noticed + notice)
    return Verdict("restart", "all clear after the notice")


def postpone(st: dict, now: datetime, cfg: dict, window: tuple[datetime, datetime]) -> dict:
    """The notice's Postpone: later by postpone_minutes, with a fresh notice then; past the limit it is a skip."""
    st = dict(st)
    until = now + timedelta(minutes=cfg["reset"]["postpone_minutes"])
    st["postpones"] = int(st.get("postpones") or 0) + 1
    st["notice_at"] = None
    if until >= window[1]:
        st["skipped"] = True
        st["skip_reason"] = f"postponed past {window[1]:%H:%M}"
    else:
        st["postponed_until"] = until.isoformat()
    return st


def skip_tonight(st: dict) -> dict:
    return {**st, "skipped": True, "skip_reason": "you chose Skip tonight"}


def run_night(window, cfg, *, now: Callable, gather: Callable, send_notice: Callable, restart: Callable,
              wait: Callable, load: Callable, save: Callable, log: Callable = lambda *_: None) -> str:
    """Decide, act, repeat, until the night has an outcome. Each wait is bounded by the verdict's `until`."""
    for _ in range(MAX_STEPS):
        t = now()
        st = load()
        v = decide(t, window, gather(), st, cfg)
        log(v.action, v.reason)
        if v.action == "done":
            return st["outcome"]
        if v.action == "skip":
            save({**st, "outcome": "skipped", "reason": v.reason, "finished_at": t.isoformat()})
            return "skipped"
        if v.action == "restart":
            st = {**st, "go_at": t.isoformat()}
            save(st)
            ok, why = restart()
            save({**st, "outcome": "restarted" if ok else "restart-failed", "reason": why,
                  "finished_at": now().isoformat()})
            return "restarted" if ok else "restart-failed"
        if v.action == "notice":
            send_notice(v.until, v.reason)
            save({**st, "notice_at": t.isoformat()})
            continue
        if v.action in ("wait-owner", "wait-work", "wait-peer"):
            st = {**st, "notice_at": None, "last_wait": v.reason}   # the notice is void; a fresh one follows
            save(st)
        wait(v.until, v.pids, wake_on_state=v.action in ("wait-notice", "postponed", "wait-owner", "wait-peer"))
    return "gave-up"


# ── reading the facts ────────────────────────────────────────────────────────────────────────────────────────────

def parse_hid_idle(out: str) -> float | None:
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    return int(m.group(1)) / 1e9 if m else None


def parse_display_assertion(out: str) -> bool:
    m = re.search(r"^\s*PreventUserIdleDisplaySleep\s+(\d+)", out, re.M)
    return bool(m and int(m.group(1)))


def parse_on_power(out: str) -> bool | None:
    if "AC Power" in out:
        return True
    if "Battery Power" in out:
        return False
    return None


def parse_ssh_logins(out: str) -> int:
    return sum(1 for line in out.splitlines() if re.search(r"\sttys\d+\s.*\(\S+\)\s*$", line))


def parse_screen_sharing(out: str) -> bool:
    return any(re.search(r"\.5900\s", line) and "ESTABLISHED" in line for line in out.splitlines())


_WORK = [
    (re.compile(r"helper_tab\.py run .*--group (\S+) --title (.+?) --"), lambda m: f"helper {m.group(1)}: {m.group(2)}"),
    (re.compile(r"/Xcode\.app/Contents/MacOS/Xcode\b"), lambda m: "Xcode"),
    (re.compile(r"/Simulator\.app/Contents/MacOS/Simulator\b"), lambda m: "a simulator"),
    (re.compile(r"\bxcodebuild\b"), lambda m: "an Xcode build"),
    (re.compile(r"-m pytest\b|\bvitest\b"), lambda m: "a test run"),
    (re.compile(r"\bclaude (-p|--print)\b"), lambda m: "a Claude helper"),
    (re.compile(r"\bmerge_gate|run_ticket\.py\b"), lambda m: "a merge or ticket run"),
]


def parse_work(ps_out: str, own_pid: int) -> list[dict]:
    """Work that must finish before a reset, from `ps -axo pid=,command=`. Never this process."""
    work = []
    for line in ps_out.splitlines():
        m0 = re.match(r"\s*(\d+)\s+(.*)$", line)
        if not m0:
            continue
        pid, cmd = int(m0.group(1)), m0.group(2)
        if pid == own_pid or "nightly_reset.py" in cmd:
            continue
        for rx, name in _WORK:
            m = rx.search(cmd)
            if m:
                work.append({"what": name(m), "pid": pid})
                break
    return work


def _out(cmd: list[str], timeout: float = 10) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def watcher_up(states: list) -> bool | None:
    """Any watcher up is enough. None when none is known up and at least one couldn't be read."""
    if not states or True in states:
        return True
    return None if None in states else False


def gather_facts(device: str, cfg: dict) -> Facts:
    import peer_care
    watchers = cfg["reset"]["needs_up"].get(device, [])
    up = [peer_care.peer_online(w) for w in watchers]
    return Facts(
        idle_s=parse_hid_idle(_out(["/usr/sbin/ioreg", "-c", "IOHIDSystem", "-d", "4"])),
        watching_video=parse_display_assertion(_out(["/usr/bin/pmset", "-g", "assertions"])),
        screen_sharing=parse_screen_sharing(_out(["/usr/sbin/netstat", "-an", "-p", "tcp"])),
        ssh_logins=parse_ssh_logins(_out(["/usr/bin/who"])),
        work=parse_work(_out(["/bin/ps", "-axo", "pid=,command="]), os.getpid()),
        peer_healthy=watcher_up(up),
        peer_name=" or ".join(peer_care.device_name(w) for w in watchers) or "the watcher",
        on_power=parse_on_power(_out(["/usr/bin/pmset", "-g", "batt"])),
        at_home=peer_care.same_lan_as(cfg["home_anchor"]) if device != cfg["home_anchor"] else True,
        needs_home_power=device in cfg["reset"].get("home_and_power_only", []),
    )


# ── acting ───────────────────────────────────────────────────────────────────────────────────────────────────────

def restart_command(dry_run: bool = False, script: Path = ROOT_SCRIPT) -> list[str]:
    return ["/usr/bin/sudo", "-n", str(script)] + (["--dry-run"] if dry_run else [])


def go_token() -> Path:
    """The root script reads exactly this path (bin/marvin-authrestart) and accepts it for 60 s."""
    return STATE_DIR / "go"


def restart(script: Path = ROOT_SCRIPT, dry_run: bool = False, device: str | None = None) -> tuple[bool, str]:
    """Ask the root script to restart. It refuses unless the go token was written in the last minute."""
    if not Path(script).exists():
        return False, f"the restart script isn't installed; run once at the Mac: {SETUP_COMMAND}"
    if device:
        go_token().parent.mkdir(parents=True, exist_ok=True)
        go_token().write_text(datetime.now().astimezone().isoformat())
    try:
        r = subprocess.run(restart_command(dry_run, Path(script)), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"couldn't run the restart script: {e}"
    if r.returncode != 0:
        return False, (r.stderr or r.stdout).strip()[-300:] or f"exit {r.returncode}"
    return True, (r.stdout.strip()[-300:] or "restarting")


def state_path(device: str) -> Path:
    return STATE_DIR / f"{device}.json"


def load_state(device: str, night: str) -> dict:
    try:
        st = json.loads(state_path(device).read_text())
    except (OSError, ValueError):
        return {"night": night}
    return st if st.get("night") == night else {"night": night}


def save_state(device: str, st: dict) -> None:
    p = state_path(device)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1))
    os.replace(tmp, p)


def kqueue_wait(until: datetime, pids=(), watch: Path | None = None, now: Callable = None) -> None:
    """Block until `until`, a watched pid exits, or the state file changes (Postpone/Skip pressed). macOS kqueue:
    no polling. Off macOS (or if kqueue fails) it simply sleeps to the deadline."""
    now = now or (lambda: datetime.now().astimezone())
    secs = max(0.0, (until - now()).total_seconds())
    try:
        kq = select.kqueue()
    except AttributeError:
        import time as _t
        _t.sleep(secs)
        return
    evs = []
    for pid in pids:
        evs.append(select.kevent(pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD | select.KQ_EV_ONESHOT,
                                 fflags=select.KQ_NOTE_EXIT))
    fd = None
    if watch is not None:
        try:
            watch.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(str(watch.parent), os.O_RDONLY)
            evs.append(select.kevent(fd, filter=select.KQ_FILTER_VNODE, flags=select.KQ_EV_ADD | select.KQ_EV_CLEAR,
                                     fflags=select.KQ_NOTE_WRITE))
        except OSError:
            fd = None
    try:
        for ev in evs:      # a pid that already exited can't be registered: that is itself the wake-up
            try:
                kq.control([ev], 0, 0)
            except OSError:
                return
        kq.control(None, 1, secs)
    finally:
        kq.close()
        if fd is not None:
            os.close(fd)


def send_notice(device: str, when: datetime, reason: str = "") -> None:
    """On this Mac: a notification with Postpone and Skip tonight. On the phone: the same words by push."""
    import peer_care
    name = peer_care.device_name(device)
    msg = f"Restarting the {name} at {when:%H:%M} for its nightly reset. Postpone or Skip tonight?"
    peer_care.notify_owner("MARVIN: nightly reset", msg, actions=True, device=device)


def main(argv: list[str] | None = None) -> int:
    import job_events
    import machine_profile
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["run", "status", "postpone", "skip"])
    ap.add_argument("--dry-run", action="store_true", help="decide and log, but the restart script only says what it would do")
    ap.add_argument("--device", default=None)
    a = ap.parse_args(argv)
    cfg = load_config()
    device = a.device or machine_profile.registry_id()
    now = lambda: datetime.now().astimezone()  # noqa: E731
    window = night_window(device, now(), cfg)
    if window is None:
        print(f"{device} has no nightly reset slot")
        return 0
    night = window[0].date().isoformat()
    if a.cmd == "postpone":
        save_state(device, postpone(load_state(device, night), now(), cfg, window))
        print(json.dumps(load_state(device, night)))
        return 0
    if a.cmd == "skip":
        save_state(device, skip_tonight(load_state(device, night)))
        print("skipped tonight")
        return 0
    if a.cmd == "status":
        v = decide(now(), window, gather_facts(device, cfg), load_state(device, night), cfg)
        print(json.dumps({"device": device, "slot": window[0].isoformat(), "limit": window[1].isoformat(),
                          "action": v.action, "reason": v.reason, "until": v.until.isoformat() if v.until else None}))
        return 0
    with job_events.job_run("nightly-reset", "Nightly reset") as run:
        outcome = run_night(
            window, cfg, now=now, gather=lambda: gather_facts(device, cfg),
            send_notice=lambda when, reason="": send_notice(device, when, reason),
            restart=lambda: restart(dry_run=a.dry_run, device=device),
            wait=lambda until, pids=(), wake_on_state=False: kqueue_wait(
                until, pids, state_path(device) if wake_on_state else None, now),
            load=lambda: load_state(device, night), save=lambda st: save_state(device, st),
            log=lambda action, reason: run.step(action, reason))
        run.summary(f"{outcome}: {load_state(device, night).get('reason', '')}")
        if outcome in ("restart-failed", "gave-up"):
            run.fail(load_state(device, night).get("reason", outcome))
    return 0


if __name__ == "__main__":
    sys.exit(main())
