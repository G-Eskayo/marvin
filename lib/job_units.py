#!/usr/bin/env python3
"""Portable scheduled jobs (marvin#911, Linux-node plan step 2): one definition per job, two thin host adapters.

A job is defined once in config/jobs/<name>.json, with no machine's paths in it ("~" stands for the home folder):

    name          file-safe id; launchd label com.marvin.<name>, systemd units marvin-<name>.{service,timer}
    description   one line, shown by systemctl / in the plist's comment
    command       argv, run directly (no shell)
    schedule      {"every_s": N, "at_load": bool}  every N seconds, and once when loaded if at_load
                  {"calendar": {"hour": H, "minute": M}}  daily at H:M local time, caught up after sleep or power-off
    env           optional environment
    low_priority  optional: yields CPU and disk to real work (launchd Background + LowPriorityIO + Nice 10;
                  systemd Nice=10 + idle IO)
    log           stdout to ~/.claude/logs/<log>.log, stderr to <log>-error.log (untracked logs, ADR 0069)

render_plist() writes launchd's form for the Macs and render_systemd() systemd's for Linux (mac-mini-2012), with the
same command, schedule, environment and logs. host_os's rule: a portable core plus thin host adapters, never a fork.

    job_units.py render <name> [--os macos|linux] [--home DIR]   print what would be installed
    job_units.py install <name>...                               install for this machine's OS (no-op if identical)
    job_units.py check-installed [<name>...]                     compare rendered plists to ~/Library/LaunchAgents
"""
from __future__ import annotations

import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import host_os  # noqa: E402

JOBS_DIR = Path(__file__).resolve().parent.parent / "config" / "jobs"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
KEYS = {"name", "description", "command", "schedule", "env", "low_priority", "log"}
NICE = 10


class JobError(ValueError):
    """A job definition that can't be rendered, or a name that has no definition."""


def unit_name(name: str) -> str:
    return f"marvin-{name}"


def launchd_label(name: str) -> str:
    return f"com.marvin.{name}"


def _str(v, what: str) -> str:
    if not isinstance(v, str) or not v or any(c in v for c in "\n\r\0"):
        raise JobError(f"{what} must be a one-line, non-empty string: {v!r}")
    return v


def validate(job: dict) -> dict:
    """The definition, checked; raises JobError naming what's wrong. Nothing half-valid is ever rendered."""
    if not isinstance(job, dict):
        raise JobError("a job definition is a JSON object")
    extra = set(job) - KEYS
    if extra:
        raise JobError(f"unknown key(s) {sorted(extra)}; allowed: {sorted(KEYS)}")
    name = job.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise JobError(f"name must be lowercase letters, digits and dashes: {name!r}")
    cmd = job.get("command")
    if not isinstance(cmd, list) or not cmd:
        raise JobError(f"{name}: command must be a non-empty list")
    for a in cmd:
        _str(a, f"{name}: command argument")
    sched = job.get("schedule")
    if not isinstance(sched, dict) or not sched:
        raise JobError(f"{name}: schedule is required")
    if set(sched) - {"every_s", "at_load", "calendar"}:
        raise JobError(f"{name}: unknown schedule key(s) {sorted(set(sched) - {'every_s', 'at_load', 'calendar'})}")
    if ("every_s" in sched) == ("calendar" in sched):
        raise JobError(f"{name}: schedule needs exactly one of every_s or calendar")
    if "every_s" in sched:
        n = sched["every_s"]
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise JobError(f"{name}: every_s must be a whole number of seconds, at least 1: {n!r}")
    if "at_load" in sched and not isinstance(sched["at_load"], bool):
        raise JobError(f"{name}: at_load must be true or false")
    if "calendar" in sched:
        cal = sched["calendar"]
        if not isinstance(cal, dict) or set(cal) != {"hour", "minute"}:
            raise JobError(f"{name}: calendar needs exactly hour and minute")
        for k, top in (("hour", 23), ("minute", 59)):
            v = cal[k]
            if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= top:
                raise JobError(f"{name}: calendar {k} must be 0..{top}: {v!r}")
    env = job.get("env", {})
    if not isinstance(env, dict) or not all(isinstance(k, str) and re.match(r"^[A-Z_][A-Z0-9_]*$", k) for k in env):
        raise JobError(f"{name}: env must map VARIABLE names to strings")
    for k, v in env.items():
        _str(v, f"{name}: env {k}")
    if "low_priority" in job and not isinstance(job["low_priority"], bool):
        raise JobError(f"{name}: low_priority must be true or false")
    log = job.get("log", name)
    if not isinstance(log, str) or not NAME_RE.match(log):
        raise JobError(f"{name}: log must be a file-safe name: {log!r}")
    if "description" in job:
        _str(job["description"], f"{name}: description")
    return job


def available() -> list[str]:
    return sorted(p.stem for p in JOBS_DIR.glob("*.json"))


def load(name: str) -> dict:
    path = JOBS_DIR / f"{name}.json"
    if not NAME_RE.match(name) or not path.is_file():
        raise JobError(f"no job definition {name!r} in {JOBS_DIR}; defined: {', '.join(available()) or 'none'}")
    try:
        job = json.loads(path.read_text())
    except ValueError as exc:
        raise JobError(f"{path}: not valid JSON: {exc}") from None
    validate(job)
    if job["name"] != name:
        raise JobError(f"{path} defines {job['name']!r}, not {name!r}")
    return job


_TILDE = re.compile(r"(?:(?<=^)|(?<=:))~(?=/|:|$)")


def _expand(s: str, home: str) -> str:
    """"~" at the start of a string or of a PATH-style entry becomes `home`; nowhere else (an argument like "a~b" is
    left alone)."""
    return _TILDE.sub(lambda _m: home, s)


def _logs(job: dict, home: str) -> tuple[str, str]:
    base = f"{home}/.claude/logs/{job.get('log', job['name'])}"
    return f"{base}.log", f"{base}-error.log"


# ── launchd (macOS) ──────────────────────────────────────────────────────

def plist_dict(job: dict, home: str) -> dict:
    out: dict = {"Label": launchd_label(job["name"]),
                 "ProgramArguments": [_expand(a, home) for a in job["command"]]}
    if job.get("env"):
        out["EnvironmentVariables"] = {k: _expand(v, home) for k, v in job["env"].items()}
    if job.get("low_priority"):
        out.update({"ProcessType": "Background", "LowPriorityIO": True, "Nice": NICE})
    sched = job["schedule"]
    if "calendar" in sched:
        out["StartCalendarInterval"] = {"Hour": sched["calendar"]["hour"], "Minute": sched["calendar"]["minute"]}
    else:
        out["StartInterval"] = sched["every_s"]
        if sched.get("at_load"):
            out["RunAtLoad"] = True
    out["StandardOutPath"], out["StandardErrorPath"] = _logs(job, home)
    return out


def render_plist(job: dict, home: str) -> bytes:
    return plistlib.dumps(plist_dict(job, home), sort_keys=False)


# ── systemd user units (Linux) ──────────────────────────────────────────

def _sd_escape(s: str) -> str:
    """systemd expands %specifiers in every unit setting, and $VARS in ExecStart: both are doubled so the value
    reaches the program exactly as written."""
    return s.replace("%", "%%")


def _sd_word(arg: str) -> str:
    """One ExecStart argument: specifiers and variables escaped, quoted when it holds anything systemd splits on."""
    a = _sd_escape(arg).replace("$", "$$")
    if a and not re.search(r"[\s\"'\\;]", a):
        return a
    return '"' + a.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_systemd(job: dict, home: str) -> tuple[str, str]:
    """(service, timer) unit text for a systemd --user manager."""
    name, sched = job["name"], job["schedule"]
    out_log, err_log = _logs(job, home)
    desc = _sd_escape(job.get("description", name))
    svc = ["[Unit]", f"Description=MARVIN {name}: {desc}",
           f"# Rendered by lib/job_units.py from config/jobs/{name}.json (marvin#911); edit that, not this.",
           "", "[Service]", "Type=oneshot"]
    for k, v in job.get("env", {}).items():
        svc.append(f'Environment="{k}={_sd_escape(_expand(v, home))}"')
    svc.append("ExecStart=" + " ".join(_sd_word(_expand(a, home)) for a in job["command"]))
    if job.get("low_priority"):
        svc += [f"Nice={NICE}", "IOSchedulingClass=idle"]
    svc += [f"StandardOutput=append:{_sd_escape(out_log)}", f"StandardError=append:{_sd_escape(err_log)}"]
    tmr = ["[Unit]", f"Description=Schedule for MARVIN {name}", "", "[Timer]", f"Unit={unit_name(name)}.service"]
    if "calendar" in sched:
        c = sched["calendar"]
        tmr += [f"OnCalendar=*-*-* {c['hour']:02d}:{c['minute']:02d}:00", "Persistent=true"]
    else:
        n = sched["every_s"]
        tmr += [f"OnActiveSec={'0' if sched.get('at_load') else f'{n}s'}", f"OnUnitActiveSec={n}s"]
    tmr += ["", "[Install]", "WantedBy=timers.target"]
    return "\n".join(svc) + "\n", "\n".join(tmr) + "\n"


# ── install (the thin host adapters) ────────────────────────────────────

def _default_run(cmd: list[str]) -> int:
    return subprocess.run(cmd, capture_output=True, text=True).returncode


def _write_if_changed(path: Path, data: bytes) -> bool:
    if path.exists() and path.read_bytes() == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return True


def _install_linux(job: dict, home: Path, run: Callable[[list[str]], int]) -> dict:
    d = home / ".config" / "systemd" / "user"
    service, timer = render_systemd(job, str(home))
    u = unit_name(job["name"])
    changed = _write_if_changed(d / f"{u}.service", service.encode())
    changed = _write_if_changed(d / f"{u}.timer", timer.encode()) or changed
    ok = True
    if changed:
        ok = run(["systemctl", "--user", "daemon-reload"]) == 0
    ok = run(["systemctl", "--user", "enable", "--now", f"{u}.timer"]) == 0 and ok
    return {"job": job["name"], "changed": changed, "ok": ok}


def _install_macos(job: dict, home: Path, run: Callable[[list[str]], int], uid: int) -> dict:
    label = launchd_label(job["name"])
    path = home / "Library" / "LaunchAgents" / f"{label}.plist"
    want = render_plist(job, str(home))
    if path.exists():
        try:
            if plistlib.loads(path.read_bytes()) == plistlib.loads(want):
                return {"job": job["name"], "changed": False, "ok": True}   # identical to launchd: leave it be
        except Exception:  # noqa: BLE001 -- an unreadable installed plist is replaced
            pass
    _write_if_changed(path, want)
    run(["launchctl", "bootout", f"gui/{uid}/{label}"])   # fails harmlessly when it wasn't loaded
    ok = run(["launchctl", "bootstrap", f"gui/{uid}", str(path)]) == 0
    return {"job": job["name"], "changed": True, "ok": ok}


def install(names: list[str], os_name: str | None = None, home: Path | None = None,
            run: Callable[[list[str]], int] | None = None, uid: int | None = None) -> list[dict]:
    """Install each job for this OS. Every definition is loaded first, so one bad name installs nothing."""
    os_name = os_name or host_os.os_name()
    if os_name not in ("linux", "macos"):
        raise JobError(f"no scheduler adapter for {os_name!r} (have: linux, macos)")
    jobs = [load(n) for n in names]
    home = Path(home or Path.home())
    run = run or _default_run
    (home / ".claude" / "logs").mkdir(parents=True, exist_ok=True)
    if os_name == "linux":
        return [_install_linux(j, home, run) for j in jobs]
    uid = os.getuid() if uid is None else uid
    return [_install_macos(j, home, run, uid) for j in jobs]


def check_installed(names: list[str], home: Path | None = None) -> list[dict]:
    """For each job, whether ~/Library/LaunchAgents holds exactly (parsed) what render_plist makes."""
    home = Path(home or Path.home())
    out = []
    for n in names:
        path = home / "Library" / "LaunchAgents" / f"{launchd_label(n)}.plist"
        if not path.exists():
            out.append({"job": n, "installed": False})
            continue
        want, have = plist_dict(load(n), str(home)), plistlib.loads(path.read_bytes())
        diff = sorted(k for k in set(want) | set(have) if want.get(k) != have.get(k))
        out.append({"job": n, "installed": True, "identical": not diff, "differs": diff})
    return out


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("render", "install", "check-installed"):
        print(__doc__.split("\n\n")[-1], file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "render":
        os_name = rest[rest.index("--os") + 1] if "--os" in rest else host_os.os_name()
        home = rest[rest.index("--home") + 1] if "--home" in rest else str(Path.home())
        job = load(rest[0])
        if os_name == "linux":
            service, timer = render_systemd(job, home)
            print(f"# {unit_name(job['name'])}.service\n{service}\n# {unit_name(job['name'])}.timer\n{timer}", end="")
        else:
            sys.stdout.write(render_plist(job, home).decode())
        return 0
    if cmd == "install":
        res = install(rest)
        print(json.dumps(res))
        return 0 if all(r["ok"] for r in res) else 1
    res = check_installed(rest or available())
    print(json.dumps(res))
    return 0 if all(r.get("identical", True) for r in res) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
