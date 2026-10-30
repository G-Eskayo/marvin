"""Parallel ticket dispatch: the settings and the guard rails (ADR 0052, ticket #194).

`config/dispatch.json` is one synced file. With `parallel` off every other field is ignored and each machine
runs one ticket at a time, as before. `can_start_another` answers "may this machine start another ticket right
now?" with a plain-language reason when not; every reader is injected, so the rules are tested without a
network or disk. A guard that cannot be read never blocks (an unreadable budget must not stall dispatch).

Also tracks running tasks via per-task JSON records in TASKS_DIR, reaping dead processes, and maintains a
dispatch-state summary for the UI (AC 0193).
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).resolve().parents[1] / "config" / "dispatch.json"
TASKS_DIR = Path.home() / ".claude" / "dispatch" / "tasks"
DISPATCH_STATE_PATH = Path.home() / ".claude" / "dispatch-state.json"
MAX_LIMIT = 8

DEFAULTS = {
    "parallel": False,
    "max_total": 2,
    "max_per_project": 1,
    "machine_slots": {"mac-mini-1": 2, "macbook-pro-1": 1},
    # Extra slots that open only while that machine's API credit is ready (#849): the plan's slots come first.
    "credit_slots": {},
    "guards": {"min_disk_gb": 15, "min_github_budget_pct": 20},
}


def _whole(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_LIMIT


def validate(raw: dict) -> tuple[dict, list[str]]:
    """The settings with every invalid field replaced by its default, and one sentence per field that was invalid."""
    raw = raw if isinstance(raw, dict) else {}
    out = json.loads(json.dumps(DEFAULTS))
    problems: list[str] = []
    if "parallel" in raw:
        if isinstance(raw["parallel"], bool):
            out["parallel"] = raw["parallel"]
        else:
            problems.append("parallel must be true or false")
    for key in ("max_total", "max_per_project"):
        if key in raw:
            if _whole(raw[key]):
                out[key] = raw[key]
            else:
                problems.append(f"{key} must be a whole number from 1 to {MAX_LIMIT}")
    if isinstance(raw.get("machine_slots"), dict):
        for machine, n in raw["machine_slots"].items():
            if _whole(n):
                out["machine_slots"][machine] = n
            else:
                problems.append(f"machine_slots.{machine} must be a whole number from 1 to {MAX_LIMIT}")
    if isinstance(raw.get("credit_slots"), dict):
        for machine, n in raw["credit_slots"].items():
            if isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= MAX_LIMIT:
                out["credit_slots"][machine] = n
            else:
                problems.append(f"credit_slots.{machine} must be a whole number from 0 to {MAX_LIMIT}")
    guards = raw.get("guards")
    if isinstance(guards, dict):
        for key, hi in (("min_disk_gb", 10_000), ("min_github_budget_pct", 100)):
            if key in guards:
                v = guards[key]
                if isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= hi:
                    out["guards"][key] = v
                else:
                    problems.append(f"guards.{key} must be a number from 0 to {hi}")
    return out, problems


def load(path: Path | None = None) -> dict:
    """Missing, unreadable or invalid settings fall back to the safe defaults, field by field, never to an error."""
    try:
        raw = json.loads(Path(path or PATH).read_text())
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULTS))
    return validate(raw)[0]


def save(settings: dict, path: Path | None = None) -> dict:
    """Write validated settings atomically; invalid ones are refused (ValueError) and nothing is written."""
    clean, problems = validate(settings)
    if problems:
        raise ValueError("; ".join(problems))
    target = Path(path or PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(clean, f, indent=2)
        f.write("\n")
    os.replace(tmp, target)
    return clean


def effective_limit(settings: dict, machine: str, credit_ready: bool = False) -> int:
    """Tickets this machine may run at once: one when parallel is off, else the smaller of its slots and max_total
    (the plan's slots), plus its credit_slots on top while its API credit is ready (#849)."""
    if not settings.get("parallel"):
        return 1
    plan = max(1, min(settings["machine_slots"].get(machine, 1), settings["max_total"]))
    return plan + (settings.get("credit_slots", {}).get(machine, 0) if credit_ready else 0)


def _safe(reader, *args):
    try:
        return reader(*args)
    except Exception:  # noqa: BLE001 -- an unreadable guard must not stall dispatch
        return None


def can_start_another(machine: str, settings: dict, *, slots_in_use, disk_free_gb, github_budget_pct,
                      breaker_tripped, missing_tools, credit_ready=None) -> tuple[bool, str | None]:
    # An unreadable credit state means the plan's slots only: never a block, never extra builds on a guess.
    limit = effective_limit(settings, machine, credit_ready=bool(credit_ready and _safe(credit_ready, machine)))
    used = slots_in_use(machine)
    if used >= limit:
        return False, f"{machine} is full: {used} of {limit} slots in use"
    if not settings.get("parallel"):
        return True, None  # off: exactly today's behaviour, no extra guards
    g = settings["guards"]
    disk = _safe(disk_free_gb, machine)
    if disk is not None and disk < g["min_disk_gb"]:
        return False, f"disk {disk:g} GB free on {machine}, minimum {g['min_disk_gb']:g}"
    pct = _safe(github_budget_pct)
    if pct is not None and pct < g["min_github_budget_pct"]:
        return False, f"GitHub request budget {pct:g}% left, minimum {g['min_github_budget_pct']:g}%"
    trips = _safe(breaker_tripped) or []
    if trips:
        t = trips[0]
        return False, f"circuit breaker tripped for {str(t.get('project', '?')).split('/')[-1]}: {t.get('signature', '?')}"
    missing = _safe(missing_tools, machine) or []
    if missing:
        return False, f"{machine} lacks tools the project needs: {', '.join(missing)}"
    return True, None


CREDIT_RETRY_S = 6 * 3600   # a failed credit check keeps the extra slots shut this long, then the next build retries


def credit_ready_local(home: Path | None = None, now: datetime | None = None) -> bool:
    """This machine's API credit can take a build: its key file holds a key, and the last check (written by
    lib/builder_auth.sh to ~/.claude/dispatch/credit-state.json) didn't fail in the last CREDIT_RETRY_S. A state that
    can't be read leaves it to the key; the next real check rewrites it."""
    home = home or Path.home()
    try:
        if not (home / ".claude" / ".anthropic-api-key").read_text().strip():
            return False
    except OSError:
        return False
    try:
        state = json.loads((home / ".claude" / "dispatch" / "credit-state.json").read_text())
        if state.get("ok") is False:
            at = datetime.strptime(state["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            return ((now or datetime.now(timezone.utc)) - at).total_seconds() >= CREDIT_RETRY_S
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return True


PLAN_RETRY_S = 3600   # after the plan's usage limit, builds use the credit this long, then the plan is tried again


def _plan_state_path(home: Path | None) -> Path:
    return (home or Path.home()) / ".claude" / "dispatch" / "plan-state.json"


def mark_plan_limited(home: Path | None = None, now: datetime | None = None) -> None:
    """A run on this Mac just hit the plan's usage limit (Gil, 2026-10-30: plan first, the credit only once it runs out)."""
    path = _plan_state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps({"limited_at": at}) + "\n")


def plan_limited(home: Path | None = None, now: datetime | None = None) -> bool:
    """This Mac hit the plan's usage limit in the last PLAN_RETRY_S. Anything unreadable, or dated in the future, reads
    as False: the wrong way to fail here spends the credit while the plan has room."""
    try:
        at = datetime.strptime(json.loads(_plan_state_path(home).read_text())["limited_at"],
                               "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return False
    age = ((now or datetime.now(timezone.utc)) - at).total_seconds()
    return 0 <= age < PLAN_RETRY_S


def credit_env(home: Path | None = None, base: dict | None = None, now: datetime | None = None) -> dict | None:
    """`base` switched to the monthly API credit (the key in, the plan's token out), or None when the credit isn't
    ready. The key is read at the moment of use and never written anywhere."""
    if not credit_ready_local(home, now):
        return None
    try:
        key = ((home or Path.home()) / ".claude" / ".anthropic-api-key").read_text().strip()
    except OSError:
        return None
    env = {k: v for k, v in (base if base is not None else os.environ).items() if k != "CLAUDE_CODE_OAUTH_TOKEN"}
    env["ANTHROPIC_API_KEY"] = key
    return env


def record_credit_check(ok: bool, why: str, home: Path | None = None, now: datetime | None = None) -> None:
    """The same credit-state.json lib/builder_auth.sh writes, so a spent credit closes the extra slots."""
    path = (home or Path.home()) / ".claude" / "dispatch" / "credit-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    at = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps({"ok": ok, "why": why, "at": at}) + "\n")


def log_billing(task: str, mode: str, why: str, home: Path | None = None) -> None:
    """One line in the log builder_auth.sh writes, ~/.claude/logs/builder-billing.jsonl."""
    log = (home or Path.home()) / ".claude" / "logs" / "builder-billing.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log.open("a") as f:
        f.write(json.dumps({"at": at, "task": task, "mode": mode, "why": why}) + "\n")


def credit_ready_remote(host: str, run=None) -> bool | None:
    """credit_ready_local on another machine over ssh; None when it can't be asked."""
    run = run or subprocess.run
    try:
        proc = run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
                    host, 'cd "$HOME/.agents" && "$HOME/.agents/venv/bin/python" -m lib.dispatch_concurrency credit-ready'],
                   capture_output=True, text=True, timeout=10)
        if proc.returncode != 0:
            return None
        return proc.stdout.strip() == "true"
    except Exception:
        return None


def others_running(task_id: str, reader=None) -> int:
    """Live builds on this machine other than `task_id`: how builder_auth.sh tells a plan slot from an overflow one."""
    records = (reader or slots_in_use)()
    return sum(1 for r in records if r.get("task_id") != task_id)


def partition_alive(records: list[dict], is_alive) -> tuple[list[dict], list[dict]]:
    """Split records into (alive processes, dead processes). is_alive is an injected liveness checker
    (e.g., _pid_alive or a fake for testing)."""
    alive = []
    dead = []
    for rec in records:
        pid = rec.get("pid")
        if pid and is_alive(pid):
            alive.append(rec)
        else:
            dead.append(rec)
    return alive, dead


def _pid_alive(pid: int) -> bool:
    """Check if a PID is alive via os.kill(pid, 0)."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, TypeError):
        return False


def _read_task_records(tasks_dir: Path | None = None) -> list[dict]:
    """Glob *.json files in tasks_dir, skip unreadable/malformed files. Returns list of task records."""
    tasks_dir = tasks_dir or TASKS_DIR
    records = []
    if not tasks_dir.exists():
        return records
    for f in tasks_dir.glob("*.json"):
        try:
            records.append(json.loads(f.read_text()))
        except (OSError, ValueError):
            pass
    return records


def _reap(dead: list[dict], tasks_dir: Path | None = None) -> None:
    """Unlink dead task record files."""
    tasks_dir = tasks_dir or TASKS_DIR
    for rec in dead:
        task_id = rec.get("task_id")
        if task_id:
            (tasks_dir / f"{task_id}.json").unlink(missing_ok=True)


def slots_in_use(machine: str | None = None, *, reader=None, is_alive=None, tasks_dir: Path | None = None) -> list[dict]:
    """Read alive task records, reap the dead ones as a side effect. Filter to machine if provided.
    Returns the list of alive records (which can be counted for available slot logic).
    reader and is_alive are injected for testing; defaults are _read_task_records and _pid_alive."""
    reader = reader or _read_task_records
    is_alive_fn = is_alive or _pid_alive
    records = reader(tasks_dir)
    alive, dead = partition_alive(records, is_alive_fn)
    if dead:
        _reap(dead, tasks_dir)
    if machine:
        alive = [r for r in alive if r.get("machine") == machine]
    return alive


def slots_in_use_remote(host: str, machine: str, run=None) -> list[dict] | None:
    """SSH to host and invoke this script's CLI (slots-in-use --machine <machine>); None on failure."""
    run = run or subprocess.run
    try:
        proc = run(
            ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new",
             # From ~/.agents with MARVIN's python (a bare `-m lib...` ran relative to the remote home and failed);
             # exact form is on mac-mini-2012's observer-key list (ADR 0069).
             host, 'cd "$HOME/.agents" && "$HOME/.agents/venv/bin/python" -m lib.dispatch_concurrency slots-in-use '
                   '--machine ' + machine],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def refresh_dispatch_state_summary(tasks_dir: Path | None = None) -> None:
    """Recompute dispatch-state.json from alive task records: {"busy": False} if none, else
    {"busy": True, "task": ..., "task_id": ..., "started_at": ...} from the earliest-started record."""
    tasks_dir = tasks_dir or TASKS_DIR
    alive = slots_in_use(tasks_dir=tasks_dir)
    if not alive:
        state = {"busy": False}
    else:
        earliest = min(alive, key=lambda r: r.get("started_at", ""))
        state = {
            "busy": True,
            "task": earliest.get("task", ""),
            "task_id": earliest.get("task_id", ""),
            "started_at": earliest.get("started_at", ""),
        }
    DISPATCH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DISPATCH_STATE_PATH.parent, suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(state, f)
        f.write("\n")
    os.replace(tmp, DISPATCH_STATE_PATH)


def _cli(argv: list[str]) -> int:
    """`dispatch_concurrency.py get` prints the settings; `set '<json>'` validates and saves them (the dashboard's
    control), exiting 1 with the reasons on stderr if any field is invalid. `slots-in-use [--machine ID]` prints
    alive task records as JSON. `refresh-summary` updates dispatch-state.json."""
    import sys
    if argv[:1] == ["get"]:
        print(json.dumps(load()))
        return 0
    if argv[:1] == ["set"] and len(argv) == 2:
        try:
            print(json.dumps(save(json.loads(argv[1]))))
            return 0
        except (ValueError, TypeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
    if argv[:1] == ["slots-in-use"]:
        machine = None
        if len(argv) >= 3 and argv[1] == "--machine":
            machine = argv[2]
        print(json.dumps(slots_in_use(machine)))
        return 0
    if argv[:1] == ["credit-ready"]:
        print("true" if credit_ready_local() else "false")
        return 0
    if argv[:1] == ["plan-limited"]:
        print("true" if plan_limited() else "false")
        return 0
    if argv[:1] == ["others-running"] and len(argv) == 3 and argv[1] == "--exclude":
        print(others_running(argv[2]))
        return 0
    if argv[:1] == ["refresh-summary"]:
        refresh_dispatch_state_summary()
        return 0
    print("usage: dispatch_concurrency.py get | set '<json>' | slots-in-use [--machine ID] | refresh-summary", file=sys.stderr)
    return 2


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
