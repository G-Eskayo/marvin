#!/usr/bin/env python3
"""Job start/stop hooks, called by task_dispatch's wrapper on whichever machine runs a dispatched job (marvin #931).

Today it does one thing: on mac-mini-2012 the live brain-map display (Electron with software WebGL, ~2 to 3 of the box's
8 threads all the time) is stopped when the first job starts and started again when the last one ends (Gil's
`box-display` decision on G-Eskayo/marvin-instance PR #6). Triggered by the job's own start and EXIT trap, never by
polling.

- start: if the display is running, remember its X session environment in PAUSE_FILE and stop it.
- stop: when no other dispatched job is still alive and PAUSE_FILE says we stopped it, start it again with that
  environment. If the display wasn't running when the job began (someone closed it), nothing starts it.
On the Macs there is no such process and no pause file, so both are no-ops. A hook never fails a job: the wrapper
ignores its exit code, and this exits 0 whatever happens.

Run: ~/.agents/venv/bin/python ~/.agents/lib/job_hooks.py start|stop
"""
from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
TASKS_DIR = HOME / ".claude" / "dispatch" / "tasks"
PAUSE_FILE = HOME / ".claude" / "desktoplive-paused.json"
LOCK_FILE = HOME / ".claude" / "desktoplive.lock"
LOG = HOME / ".claude" / "logs" / "box-display.jsonl"
DISPLAY_PATTERN = "desktop-live-linux/main.js"
REPO = Path(__file__).resolve().parent.parent
# The X session variables a GUI app needs, read from the running display before it is stopped (a job arrives over ssh,
# with none of them).
SESSION_VARS = ("DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE",
                "XDG_CURRENT_DESKTOP", "HOME", "PATH", "LANG", "USER")


def launcher() -> Path:
    return REPO / "config" / socket.gethostname() / "marvin-desktoplive.sh"


def _log(event: str, **detail) -> None:
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(json.dumps({"t": datetime.now(timezone.utc).isoformat(), "event": event, **detail}) + "\n")
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_jobs() -> int:
    """Dispatched jobs still running here: task records whose process is alive. A stale record (its job was
    SIGKILLed, or the machine rebooted) doesn't keep the display off for ever."""
    n = 0
    for f in TASKS_DIR.glob("*.json") if TASKS_DIR.is_dir() else []:
        try:
            if _pid_alive(int(json.loads(f.read_text()).get("pid", 0))):
                n += 1
        except Exception:
            continue
    return n


def display_pids() -> list[int]:
    try:
        out = subprocess.run(["pgrep", "-f", DISPLAY_PATTERN], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return []
    me = os.getpid()
    return [int(p) for p in out.split() if p.isdigit() and int(p) != me]


def process_env(pid: int) -> dict:
    """The session variables of a running process (Linux /proc). Empty when unreadable."""
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    env = dict(kv.split("=", 1) for kv in raw.decode(errors="replace").split("\0") if "=" in kv)
    return {k: v for k, v in env.items() if k in SESSION_VARS}


def _locked(fn):
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        return fn()


def on_start() -> str:
    def go():
        pids = display_pids()
        if not pids:
            return "not-running"
        env = {}
        for pid in pids:
            env = process_env(pid)
            if env.get("DISPLAY"):
                break
        if PAUSE_FILE.exists():
            # Paused before, yet running again (someone started it by hand, or a reboot's autostart): keep the
            # environment we saved and stop it again.
            try:
                env = json.loads(PAUSE_FILE.read_text()).get("env") or env
            except Exception:
                pass
        PAUSE_FILE.write_text(json.dumps({"paused_at": datetime.now(timezone.utc).isoformat(), "env": env}))
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        _log("stopped", pids=pids, jobs=live_jobs())
        return "stopped"
    return _locked(go)


def on_stop() -> str:
    def go():
        if live_jobs() > 0:
            return "jobs-still-running"
        if not PAUSE_FILE.exists():
            return "not-paused"
        try:
            saved = json.loads(PAUSE_FILE.read_text()).get("env") or {}
        except Exception:
            saved = {}
        PAUSE_FILE.unlink(missing_ok=True)
        if display_pids():
            return "already-running"
        script = launcher()
        if not script.exists():
            _log("not-restarted", why=f"no launcher at {script}")
            return "no-launcher"
        env = {**{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "USER", "LANG")}, **saved}
        subprocess.Popen([str(script)], env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True, cwd=str(HOME))
        _log("started", display=env.get("DISPLAY"))
        return "started"
    return _locked(go)


def main(argv: list[str]) -> int:
    try:
        action = argv[1] if len(argv) > 1 else ""
        if action == "start":
            print(on_start())
        elif action == "stop":
            print(on_stop())
        else:
            print("usage: job_hooks.py start|stop", file=sys.stderr)
    except Exception as exc:   # a hook never fails a job
        _log("error", error=str(exc)[:300])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
