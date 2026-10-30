#!/usr/bin/env python3
"""Task-dispatch: location-transparent work execution across MARVIN's known
devices — submit a shell command without specifying which physical machine
runs it; the system picks one based on liveness + current dispatch load.

Design/scope decisions are in ~/.agents/docs/adr/0013-task-dispatch-general-
primitive-v1-scope.md and ~/.agents/CONTEXT.md's "Task-dispatch" section —
read those before extending this. Short version: v1 is single-target
dispatch only (fan-out+merge and exo-scheduled dispatch are deliberately
deferred), unit of work is an arbitrary shell command, machine selection
uses an explicit dispatch-state file (not raw OS load), and failures are
reported loud with no automatic retry-elsewhere -- except the one exception ADR 0069's amendment allows (marvin #930):
`test` and `bench` work that stalls on the box, or can't reach it, reruns once on the less busy Mac.

Run standalone: ~/.agents/venv/bin/python task_dispatch.py "command" [--target ID] [--async] [--timeout N]
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent))
from machine_profile import registry_id, remote_devices, _load_registry  # noqa: E402
import host_os  # noqa: E402

DISPATCH_STATE_PATH = Path.home() / ".claude" / "dispatch-state.json"
# The same files as a shell sees them on whichever machine runs the command. Homes differ between machines
# (/home/marvin on mac-mini-2012), so anything sent over ssh names $HOME, never this machine's path (ADR 0069).
SHELL_STATE_PATH = '"$HOME/.claude/dispatch-state.json"'
SHELL_TASKS_DIR = '"$HOME/.claude/dispatch/tasks"'
TAILSCALE_BIN = host_os.tailscale_bin_or_default()
# The GUI app's CLI refuses to run without a TERM ("The Tailscale GUI failed to start"), which is exactly what launchd
# provides. Found 2026-10-05: under launchd it printed that error, and the parse below read it as one online host
# called "Tailscale", so no peer ever looked reachable.
TAILSCALE_ENV = {**os.environ, "TERM": "dumb"}
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]


@dataclass
class DispatchResult:
    ok: bool
    device_id: str | None = None
    output: str | None = None
    stderr: str | None = None
    error: str | None = None
    waiting: bool = False   # refused under memory pressure and queued to run when it drops (marvin#845)
    timed_out: bool = False      # the run hit its time limit (a stall, not a result)
    unreachable: bool = False    # the machine could not be reached, or the link dropped mid-run
    fell_back_from: str | None = None   # set when this is a Mac's rerun of work the box couldn't finish (#930)


# ADR 0069 amendment (marvin #930, Gil 2026-10-30): only these tags may rerun on a Mac when the box stalls. quarantine
# and security never do: a Mac must never run untrusted code. Any tag not listed here keeps "fail loudly".
FALLBACK_NEEDS = frozenset({"test", "bench"})
FALLBACK_LOG = Path.home() / ".claude" / "logs" / "dispatch-fallback.jsonl"
# One record per fallback run in progress, started from this machine; a dead pid's record doesn't count.
FALLBACK_RUNS_DIR = Path.home() / ".claude" / "dispatch" / "fallback"
# At most this many fallback runs at once from one dispatcher, so a box that stalls on every job can't pile them all
# onto the Macs (a fallback storm). Over the cap the job fails loudly and the log says "capped".
FALLBACK_CAP = 2
TIE_MARGIN = 0.1     # two Macs whose load scores differ by less than this are tied, and a tie goes to the Mini
ASYNC_LOG_DIR = Path.home() / ".claude" / "logs" / "dispatch-async"
KILL_GRACE_S = 15    # GNU timeout's -k: seconds after SIGTERM before SIGKILL on the box


def tailscale_online_hosts_or_none() -> set[str] | None:
    """Hostnames Tailscale currently reports as online (not 'offline'), or None when it can't be asked: the CLI is
    missing, exits non-zero or hangs. A view must say "can't check", never "every peer is offline" (marvin#889)."""
    try:
        proc = subprocess.run([TAILSCALE_BIN, "status"], capture_output=True, text=True, timeout=10, env=TAILSCALE_ENV)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    online = set()
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[0].count(".") != 3:   # a peer row starts with its IP; anything else is not one
            continue
        hostname = parts[1]
        if "offline" not in line:
            online.add(hostname)
    return online


def _tailscale_online_hosts() -> set[str]:
    """For dispatch: an unanswerable Tailscale means no remote machine to send work to (stay local)."""
    return tailscale_online_hosts_or_none() or set()


def _read_local_dispatch_state() -> dict:
    if not DISPATCH_STATE_PATH.exists():
        return {"busy": False}
    try:
        return json.loads(DISPATCH_STATE_PATH.read_text())
    except Exception:
        return {"busy": False}


def _read_remote_dispatch_state(host: str) -> dict:
    try:
        proc = subprocess.run(
            ["ssh", *SSH_OPTS, host, f"cat {SHELL_STATE_PATH}"],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return {"busy": False}
        return json.loads(proc.stdout)
    except Exception:
        return {"busy": False}


def _candidates() -> dict:
    """All known devices (self + registered remotes) keyed by device_id,
    each tagged with whether it's self."""
    self_id = registry_id()
    devices = _load_registry()
    result = {self_id: {**devices.get(self_id, {}), "is_self": True, "tailscale_hostname": None}}
    for device_id, info in remote_devices().items():
        result[device_id] = {**info, "is_self": False}
    return result


GENERAL = "general"


def _normalise_need(need: str | None) -> str:
    return (need or "").strip().lower() or GENERAL


def accepts(info: dict, need: str) -> bool:
    """Whether a registry entry takes work tagged `need` (ADR 0069). An entry with no `accepts` predates tags
    and takes general work only; a malformed one takes nothing, so a registry typo fails closed."""
    if "accepts" not in info:
        return need == GENERAL
    tags = info["accepts"]
    if not isinstance(tags, list):
        return False
    return need in {str(t).strip().lower() for t in tags}


def select_machine(explicit_target: str | None = None, need: str | None = None) -> tuple[str, dict] | None:
    """Pick a device to run on. Explicit target skips liveness/load checks
    on OTHER machines but still validates the target itself is usable.
    Only devices that accept `need` qualify (untagged work is "general"), named targets included: there is
    no fallback to a device that doesn't accept it, so quarantine work can never land on a Mac."""
    need = _normalise_need(need)
    devices = {d: info for d, info in _candidates().items() if accepts(info, need)}

    if explicit_target:
        if explicit_target not in devices:
            return None
        info = devices[explicit_target]
        if info["is_self"]:
            return explicit_target, info
        online = _tailscale_online_hosts()
        if info["tailscale_hostname"] not in online:
            return None
        state = _read_remote_dispatch_state(info["tailscale_hostname"])
        if state.get("busy"):
            return None
        return explicit_target, info

    online = _tailscale_online_hosts()
    # Prefer self first (no SSH round-trip needed), then remotes in registry order.
    self_id = registry_id()
    ordered_ids = [d for d in [self_id] if d in devices] + [d for d in devices if d != self_id]
    for device_id in ordered_ids:
        info = devices[device_id]
        if info["is_self"]:
            state = _read_local_dispatch_state()
            if not state.get("busy"):
                return device_id, info
            continue
        if info["tailscale_hostname"] not in online:
            continue
        state = _read_remote_dispatch_state(info["tailscale_hostname"])
        if not state.get("busy"):
            return device_id, info

    return None


def machine_load(device_id: str, info: dict) -> tuple[float, int, int] | None:
    """(1-minute load, cores, dispatch runs in progress) for a Mac, or None when it can't be read. Plan section F's
    reading: the run count matters because a run just started hasn't shown up in the load yet."""
    if info.get("is_self"):
        try:
            load1 = os.getloadavg()[0]
        except OSError:
            return None
        return load1, os.cpu_count() or 0, _live_task_count(Path.home() / ".claude" / "dispatch" / "tasks")
    cmd = f"sysctl -n vm.loadavg hw.ncpu; ls {SHELL_TASKS_DIR} 2>/dev/null | grep -c '\\.json$'"
    try:
        proc = subprocess.run(["ssh", *SSH_OPTS, info["tailscale_hostname"], cmd],
                              capture_output=True, text=True, timeout=10)
        lines = proc.stdout.split("\n")
        load1 = float(lines[0].strip("{} ").split()[0])
        return load1, int(lines[1]), int((lines[2] if len(lines) > 2 else "0").strip() or 0)
    except Exception:
        return None


def _live_task_count(tasks_dir: Path) -> int:
    n = 0
    for f in tasks_dir.glob("*.json") if tasks_dir.is_dir() else []:
        try:
            if _pid_alive(int(json.loads(f.read_text()).get("pid", 0))):
                n += 1
        except Exception:
            continue
    return n


def load_score(reading: tuple[float, int, int] | None) -> float | None:
    """Busy-ness of a Mac: 1-minute load per core, plus one per run already taken there. None when unknown."""
    if not reading:
        return None
    load1, cores, runs = reading
    if not cores or cores <= 0:
        return None
    return load1 / cores + runs


def pick_fallback_mac() -> tuple[str, dict, float | None] | None:
    """The less busy online Mac (general work), for a fallback rerun. A busy dispatch-state does not rule a Mac out:
    the fallback must not be dropped because both Macs have builds going; it goes where there's most room. A tie or
    an unreadable load goes to the Mini (more cores, plan section F)."""
    online = _tailscale_online_hosts()
    macs = {d: info for d, info in _candidates().items()
            if accepts(info, GENERAL) and (info["is_self"] or info.get("tailscale_hostname") in online)}
    if not macs:
        return None
    scores = {d: load_score(machine_load(d, info)) for d, info in macs.items()}
    minis = [d for d, info in macs.items() if info.get("kind") == "desktop"]
    if any(v is None for v in scores.values()):
        choice = minis[0] if minis else next(d for d in macs if scores[d] is not None) if any(
            v is not None for v in scores.values()) else next(iter(macs))
        return choice, macs[choice], scores[choice]
    best = min(scores, key=scores.get)
    tied = [d for d in macs if scores[d] - scores[best] < TIE_MARGIN]
    choice = next((d for d in tied if d in minis), best)
    return choice, macs[choice], scores[choice]


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


def _fallback_runs_in_progress() -> int:
    return _live_task_count(FALLBACK_RUNS_DIR)


def _log_fallback(entry: dict) -> None:
    try:
        FALLBACK_LOG.parent.mkdir(parents=True, exist_ok=True)
        with FALLBACK_LOG.open("a") as fh:
            fh.write(json.dumps({"t": datetime.now(timezone.utc).isoformat(), **entry}) + "\n")
    except Exception:
        pass   # logging never changes the run's outcome


def _fall_back(command: str, need: str, reason: str, box: str | None, box_error: str | None, mode: str,
               timeout: int, label: str, ticket: str | None, repo: str | None) -> DispatchResult:
    """Rerun `command` once on the less busy Mac. Only for FALLBACK_NEEDS; the caller has checked."""
    base = {"need": need, "label": label, "from": box, "reason": reason, "box_error": (box_error or "")[:300]}
    if _fallback_runs_in_progress() >= FALLBACK_CAP:
        _log_fallback({**base, "to": None, "outcome": "capped"})
        return DispatchResult(ok=False, device_id=box, error=(
            f"{box or 'the box'} could not finish this {need} work ({reason}), and {FALLBACK_CAP} fallback runs are "
            f"already going on the Macs (the fallback cap), so it was not rerun"), fell_back_from=box)
    picked = pick_fallback_mac()
    if picked is None:
        _log_fallback({**base, "to": None, "outcome": "no-mac"})
        return DispatchResult(ok=False, device_id=box, error=f"{box or 'the box'} could not finish this {need} work "
                              f"({reason}) and no Mac is online to rerun it", fell_back_from=box)
    device_id, info, score = picked
    if info["is_self"]:
        import memory_guard
        held = memory_guard.guard(label, None, str(Path.home()))
        if not held["ok"]:
            _log_fallback({**base, "to": device_id, "score": score, "outcome": "refused", "detail": held["message"]})
            return DispatchResult(ok=False, device_id=device_id, error=held["message"], fell_back_from=box)
    FALLBACK_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    slot = FALLBACK_RUNS_DIR / f"{uuid.uuid4().hex[:12]}.json"
    slot.write_text(json.dumps({"pid": os.getpid(), "need": need, "label": label, "to": device_id}))
    started = time.monotonic()
    try:
        script = _build_wrapper_script(command, str(uuid.uuid4())[:8], label, device_id, ticket=ticket, repo=repo,
                                       need=need)
        result = (_run_local(script, mode, timeout) if info["is_self"]
                  else _run_remote(info["tailscale_hostname"], script, mode, timeout, device_id, info.get("os", "macos")))
    finally:
        slot.unlink(missing_ok=True)
    result.fell_back_from = box
    _log_fallback({**base, "to": device_id, "score": score, "outcome": "ok" if result.ok else "failed",
                   "seconds": round(time.monotonic() - started, 1)})
    return result


def _detach_sync_dispatch(command: str, need: str, timeout: int, target: str | None, label: str) -> DispatchResult:
    """Async test/bench work runs as a detached *sync* dispatch, so this process's timeout and fallback still apply
    to it. The caller gets control back at once, as with any async dispatch."""
    ASYNC_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = ASYNC_LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:6]}.log"
    argv = [sys.executable, str(Path(__file__).resolve()), command, "--needs", need, "--timeout", str(timeout),
            "--label", label]
    if target:
        argv += ["--target", target]
    with open(log, "a") as out:
        subprocess.Popen(argv, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
    return DispatchResult(ok=True, device_id=None, output=None)


def _remote_invocation(remote_path: str, timeout: int, remote_os: str) -> tuple[str, int]:
    """The command ssh runs, and how long ssh is waited for. On Linux the run is wrapped in GNU timeout, so a stall is
    killed on the box itself (SIGTERM, then SIGKILL) and nothing is left running there; ssh is given a little longer so
    the box's own kill wins. A Mac has no GNU timeout: unchanged."""
    if remote_os == "linux":
        return f"timeout -k {KILL_GRACE_S} {timeout} {remote_path}", timeout + KILL_GRACE_S + 15
    return remote_path, timeout


def _classify_remote_exit(code: int) -> str | None:
    """A stall ("timeout", "unreachable") or None for the job's own result."""
    if code in (124, 137):
        return "timeout"
    if code == 255:
        return "unreachable"
    return None


def _build_wrapper_script(command: str, task_id: str, task_label: str, device_id: str,
                          ticket: str | None = None, repo: str | None = None, need: str | None = None) -> str:
    """A script that writes a task record to TASKS_DIR/<task_id>.json (with metadata including the real runtime PID),
    marks the dispatch-state file busy, runs the real command, and on exit (via trap — fires even if the command
    fails or crashes, not just on clean exit) removes the task record and clears the state file and deletes its
    own /tmp script file. Self-deleting a running script is safe on Unix/macOS: rm just unlinks the directory entry,
    the already-open file stays readable to the running interpreter until it exits.

    Also exports CLAUDE_CODE_OAUTH_TOKEN from ~/.claude/.oauth-token, and GH_TOKEN from ~/.claude/.gh-token, on
    whichever machine actually runs this (local or remote — $HOME expands at runtime there, not where this string
    is built), if those files exist. Dispatched commands run in a non-interactive shell (no .zshrc/.zprofile sourced),
    so the normal keychain-backed login can't render its interactive confirmation dialog and fails with "Not logged in" —
    found 2026-07-12/13 testing cross-machine claude -p dispatch for real, same root cause as the DarkWake auth bug.
    Same failure mode hit `gh` itself, one layer later: found 2026-10-01 when a ticket's implementation and tests
    genuinely passed but `mr_raiser.py`'s plain `gh pr create` subprocess call died on a keychain-access error
    (errSecInteractionNotAllowed) raising the credential helper needs — the work succeeded and was discarded anyway
    because nothing could preserve it as a PR. Both token files are deliberately outside code_sync's ~/.claude scope
    (its .gitignore never allow-lists them) — neither ever leaves the machine it's created on."""
    started_at = datetime.now(timezone.utc).isoformat()
    busy_json = json.dumps({"busy": True, "task": task_label, "task_id": task_id, "started_at": started_at})
    idle_json = json.dumps({"busy": False})

    task_record = {
        "task_id": task_id,
        "task": task_label,
        "machine": device_id,
        "started_at": started_at,
    }
    if ticket:
        task_record["ticket"] = ticket
    if repo:
        task_record["repo"] = repo
    record_json = json.dumps(task_record)
    record_prefix = record_json[:-1]

    tasks_dir, state = SHELL_TASKS_DIR, SHELL_STATE_PATH
    # Only general work (builds) chooses plan or API credit. Tagged work (test, bench, quarantine, security) runs no
    # model, and a test job falling back to a busy Mac must not send even builder_auth's 1-token probe (#930).
    builder_auth = (f'''if [ -f "$HOME/.agents/lib/builder_auth.sh" ]; then
  . "$HOME/.agents/lib/builder_auth.sh" && marvin_builder_auth {task_id}
fi
''' if _normalise_need(need) == GENERAL else "")
    return f"""#!/bin/bash
mkdir -p {tasks_dir}
mkdir -p "$HOME/.claude"
# $$, not $BASHPID: macOS's /bin/bash is 3.2, which has no BASHPID, and an empty pid made every record unreadable.
printf '%s, "pid": %s}}' '{record_prefix}' "$$" > {tasks_dir}/{task_id}.json
cat > {state} << 'DISPATCH_STATE_EOF'
{busy_json}
DISPATCH_STATE_EOF
(cd "$HOME/.agents" && "$HOME/.agents/venv/bin/python" -m lib.dispatch_concurrency refresh-summary)
# Job hooks (#931): on mac-mini-2012 the live display stops while jobs run. A hook never changes the job's outcome.
"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/job_hooks.py" start >/dev/null 2>&1 || true
trap 'rm -f "$0" {tasks_dir}/{task_id}.json; cat > {state} << 'DISPATCH_IDLE_EOF'
{idle_json}
DISPATCH_IDLE_EOF
(cd "$HOME/.agents" && "$HOME/.agents/venv/bin/python" -m lib.dispatch_concurrency refresh-summary)
"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/memory_guard.py" kick >/dev/null 2>&1
"$HOME/.agents/venv/bin/python" "$HOME/.agents/lib/job_hooks.py" stop >/dev/null 2>&1' EXIT
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if [ -f "$HOME/.claude/.oauth-token" ]; then
  export CLAUDE_CODE_OAUTH_TOKEN="$(cat "$HOME/.claude/.oauth-token")"
fi
# Plan first; the monthly API credit only while this Mac's plan is at its usage limit (#775, Gil 2026-10-30).
{builder_auth}if [ -f "$HOME/.claude/.gh-token" ]; then
  export GH_TOKEN="$(cat "$HOME/.claude/.gh-token")"
  # git itself asks the macOS keychain for credentials, which is locked in a non-interactive shell (every push from the macbook
  # died with exit 128, 2026-10-07); gh's credential helper reads GH_TOKEN instead. Set through the environment so it reaches
  # every git call in the run and leaves repo and global config alone.
  export GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0= GIT_CONFIG_KEY_1=credential.helper GIT_CONFIG_VALUE_1="!gh auth git-credential"
fi
{command}
"""


def dispatch(command: str, target: str | None = None, mode: str = "sync",
             timeout: int = 300, task_label: str | None = None, ticket: str | None = None,
             repo: str | None = None, need: str | None = None, queue_argv: list[str] | None = None,
             fallback: bool = True) -> DispatchResult:
    """Run `command` on an available device. mode: "sync" (wait, capture
    output) or "async" (fire-and-forget, returns immediately). Fails loud,
    no automatic retry on a different machine -- except `test`/`bench` work (FALLBACK_NEEDS, ADR 0069's amendment,
    marvin #930): when no box can take it, or the box times out or drops off mid-run, it reruns once on the less busy
    Mac and the fallback is logged. A box run that finishes with failures is a result and stands. `fallback=False`
    turns that off (an extra runner whose verdict comes from elsewhere). Optional ticket/repo metadata are stored
    in the task record for tracking and UI display.
    Work for this Mac first passes the memory guard (marvin#845): at warn or critical pressure it is refused with a
    plain message; given `queue_argv` (a command that re-runs this dispatch) that is queued until pressure drops and
    the result says `waiting`. Nothing running is stopped."""
    tag = _normalise_need(need)
    label = task_label or command[:60]
    may_fall_back = fallback and tag in FALLBACK_NEEDS
    if may_fall_back and mode == "async":
        return _detach_sync_dispatch(command, tag, timeout, target, label)

    selected = select_machine(target, need=need)
    if selected is None:
        if may_fall_back:
            return _fall_back(command, tag, "unavailable", target, "no box that accepts it is online and idle",
                              mode, timeout, label, ticket, repo)
        reason = (f"target '{target}' unavailable or doesn't accept '{tag}' work" if target
                  else f"no machine that accepts '{tag}' work is currently available")
        return DispatchResult(ok=False, error=reason)

    device_id, info = selected
    if info["is_self"]:
        import memory_guard
        held = memory_guard.guard(label, queue_argv, str(Path.home()))
        if not held["ok"]:
            return DispatchResult(ok=False, device_id=device_id, error=held["message"], waiting=bool(held["queued"]))
    task_id = str(uuid.uuid4())[:8]
    script = _build_wrapper_script(command, task_id, label, device_id, ticket=ticket, repo=repo, need=tag)

    if info["is_self"]:
        return _run_local(script, mode, timeout)
    result = _run_remote(info["tailscale_hostname"], script, mode, timeout, device_id, info.get("os", "macos"))
    if may_fall_back and (result.timed_out or result.unreachable):
        return _fall_back(command, tag, "timeout" if result.timed_out else "unreachable", device_id, result.error,
                          mode, timeout, label, ticket, repo)
    return result


def _run_local(script: str, mode: str, timeout: int) -> DispatchResult:
    tmp = Path(f"/tmp/dispatch-{uuid.uuid4().hex[:8]}.sh")
    tmp.write_text(script)
    tmp.chmod(0o755)
    self_id = registry_id()
    try:
        if mode == "async":
            subprocess.Popen(
                ["/bin/bash", str(tmp)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            return DispatchResult(ok=True, device_id=self_id, output=None)
        proc = subprocess.run(["/bin/bash", str(tmp)], capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return DispatchResult(ok=False, device_id=self_id, error=f"exit {proc.returncode}: {proc.stderr[:500]}")
        return DispatchResult(ok=True, device_id=self_id, output=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired:
        return DispatchResult(ok=False, device_id=self_id, error=f"timed out after {timeout}s")
    except Exception as exc:
        return DispatchResult(ok=False, device_id=self_id, error=str(exc))


def _run_remote(host: str, script: str, mode: str, timeout: int, device_id: str,
                remote_os: str = "macos") -> DispatchResult:
    remote_path = f"/tmp/dispatch-{uuid.uuid4().hex[:8]}.sh"
    try:
        write_proc = subprocess.run(
            ["ssh", *SSH_OPTS, host, f"cat > {remote_path} && chmod +x {remote_path}"],
            input=script, capture_output=True, text=True, timeout=10,
        )
        if write_proc.returncode != 0:
            return DispatchResult(ok=False, device_id=device_id, unreachable=write_proc.returncode == 255,
                                  error=f"failed to write script to {host}: {write_proc.stderr[:300]}")

        if mode == "async":
            subprocess.run(
                ["ssh", *SSH_OPTS, host, f"nohup {remote_path} > /tmp/dispatch-{device_id}.log 2>&1 & disown"],
                capture_output=True, text=True, timeout=10,
            )
            return DispatchResult(ok=True, device_id=device_id, output=None)

        remote_cmd, ssh_wait = _remote_invocation(remote_path, timeout, remote_os)
        proc = subprocess.run(
            ["ssh", *SSH_OPTS, host, remote_cmd],
            capture_output=True, text=True, timeout=ssh_wait,
        )
        if proc.returncode != 0:
            stall = _classify_remote_exit(proc.returncode) if remote_os == "linux" else (
                "unreachable" if proc.returncode == 255 else None)
            if stall == "timeout":
                return DispatchResult(ok=False, device_id=device_id, timed_out=True, output=proc.stdout,
                                      error=f"timed out after {timeout}s on {device_id} (stopped there)")
            return DispatchResult(ok=False, device_id=device_id, unreachable=stall == "unreachable", output=proc.stdout,
                                  error=f"exit {proc.returncode}: {proc.stderr[:500]}")
        return DispatchResult(ok=True, device_id=device_id, output=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired:
        return DispatchResult(ok=False, device_id=device_id, timed_out=True, error=f"timed out after {timeout}s")
    except Exception as exc:
        return DispatchResult(ok=False, device_id=device_id, unreachable=True, error=str(exc))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", help="shell command to dispatch")
    ap.add_argument("--target", default=None, help="explicit device id (e.g. mac-mini-1) instead of auto-select")
    ap.add_argument("--async", dest="async_mode", action="store_true", help="fire-and-forget, don't wait for completion")
    ap.add_argument("--timeout", type=int, default=300, help="seconds to wait in sync mode (default 300)")
    ap.add_argument("--needs", default=None, help="work tag the job needs, e.g. quarantine or test (default: general)")
    ap.add_argument("--no-fallback", action="store_true",
                    help="test/bench work: never rerun on a Mac when the box stalls (an extra runner, not the verdict)")
    ap.add_argument("--label", default=None, help="task label shown in the task record (default: the command)")
    args = ap.parse_args()

    # Async work under memory pressure waits for it to drop; the same command line runs again then (marvin#845).
    rerun = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]] if args.async_mode else None
    result = dispatch(args.command, target=args.target, mode="async" if args.async_mode else "sync", timeout=args.timeout,
                      need=args.needs, queue_argv=rerun, fallback=not args.no_fallback, task_label=args.label)
    if result.fell_back_from:
        print(f"[dispatch] FELL BACK: {result.fell_back_from} could not finish it; rerun on {result.device_id}",
              file=sys.stderr)
    if result.ok:
        print(f"[dispatch] ran on {result.device_id or 'a detached dispatch (see ~/.claude/logs/dispatch-async)'}",
              file=sys.stderr)
        if result.output is not None:
            print(result.output, end="")
        if result.stderr is not None:
            print(result.stderr, end="", file=sys.stderr)
        sys.exit(0)
    elif result.waiting:
        print(f"[dispatch] WAITING: {result.error}", file=sys.stderr)
        sys.exit(3)
    else:
        print(f"[dispatch] FAILED: {result.error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
