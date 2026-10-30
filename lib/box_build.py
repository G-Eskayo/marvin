#!/usr/bin/env python3
"""Ticket builds on mac-mini-2012, each in a disposable marvin-build VM (marvin #951; ADR 0069, amendment 2).

The Mac that runs the scheduler sends a Linux-safe ticket to the box. The box clones a fresh VM from the frozen
marvin-build image (config/mac-mini-2012/build-builder-image.sh); the VM builds the ticket with run_ticket's build
half and pushes a branch and PR as the bot; the VM is destroyed whatever happens. The Mac then settles the outcome with
run_ticket's settle half (comment, claim, stage, breaker, redispatch) exactly as if it had built the ticket itself, and
labels the PR `from-box`. A box build never falls back to building on the box host: the host only runs the VM.

Mac side
  start REF --run-id ID    ticket_pipeline, right after the claim: starts `run` detached and returns
  run REF --run-id ID      reads the bot token and a Claude login (plan first), hands them to the box on ssh's stdin
                           (never argv, never a file on the box), waits, settles, labels the PR
  status                   the lane: running builds, why it's down (if it is), the last few results
Box side
  vm REF --sha SHA --run-id ID --login NAME [...]   takes the box's one build slot (flock), checks memory and disk
                           room, sweeps VMs a crash left, runs the VM, prints one MARVIN_BOX_RESULT line

Routing (`routes`): the project opted in (`"linux_ok": true` in its profile), the ticket is labelled `linux-ok`, nothing
about it says macOS, the box accepts `box-build` work (registry), the lane isn't resting after a failure, the box is
online, the slot is free and this Mac holds both tokens. Anything else: the ticket goes to the Macs as before.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

BOX = "mac-mini-2012"
NEED = "box-build"                 # the registry tag the box must accept (ADR 0069 point 6)
LINUX_LABEL = "linux-ok"           # a person (or triage) says this ticket builds on Linux
PR_LABEL = "from-box"              # informational: trust is by author (MARVIN-bot-gil), never by this label
CLAIM_LABEL = BOX                  # claimed:mac-mini-2012
IMAGE = "marvin-build"
RESULT_PREFIX = "MARVIN_BOX_RESULT "
REFUSED_PREFIX = "MARVIN_BOX_REFUSED "
OUTCOME_PREFIX = "MARVIN_BUILD_OUTCOME "   # run_ticket.build_only_line
LOGINS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")

HOME = Path.home()
RECORDS_DIR = HOME / ".claude" / "dispatch" / "box"
LANE_PATH = HOME / ".claude" / "dispatch" / "box-lane.json"
LOG_PATH = HOME / ".claude" / "logs" / "box-builds.jsonl"
RUN_LOGS = HOME / ".claude" / "logs" / "box-builds"
BOT_TOKEN = HOME / ".claude" / ".marvin-bot-token"
OAUTH_TOKEN = HOME / ".claude" / ".oauth-token"
API_KEY = HOME / ".claude" / ".anthropic-api-key"
BILLING_LOG = HOME / ".claude" / "logs" / "builder-billing.jsonl"
BOX_LOCK = HOME / ".cache" / "marvin" / "box-build.lock"     # on the box
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=4", "-o", "StrictHostKeyChecking=accept-new"]

# How long the lane rests after a failure that isn't the ticket's, so a broken box can't fail every ticket in turn.
REST_S = {"memory": 600, "busy": 0, "disk": 3600, "no-image": 6 * 3600, "no-secret": 6 * 3600,
          "bot-token-rejected": 6 * 3600, "engine-sha": 3600, "no-token-here": 6 * 3600, "infra": 1800}

# A ticket that names any of these needs a Mac (Xcode, Swift, the Electron dashboard, launchd...). Fail closed: a
# Python ticket that only mentions macOS in passing goes to a Mac, which can build anything.
MAC_LABELS = frozenset({"macos", "mac-only", "needs-mac", "ios", "swift", "xcode", "ui", "dashboard", "design"})
_MAC_WORDS = re.compile(
    r"(?<![\w-])(?:swift(?:ui|pm)?|xcode(?:build)?|xcrun|testflight|simulator|launchd|launchctl|plists?|osascript|"
    r"applescript|keychain|core ?ml|coreml|appkit|uikit|cocoa|homebrew|brew|macos|mac ?os|mac-only|ios|ipados|iphone|"
    r"ipad|watchos|electron|dashboard|brain-map|vitest|jsx|tcc|notarize|codesign)(?![\w])"
    r"|\.(?:swift|plist|xcodeproj|xcworkspace|jsx?|tsx?)\b", re.IGNORECASE)
_REF = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]{0,6}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID = re.compile(r"^[0-9a-f]{6,32}$")
_BOX_AGENTS = re.compile(r"^(?:\$HOME|/)[A-Za-z0-9_./-]*$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def _append_log(entry: dict) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as fh:
            fh.write(json.dumps({"at": _now().isoformat(), **entry}) + "\n")
    except OSError:
        pass   # a log that can't be written never changes the outcome


def _label_names(ticket: dict) -> set[str]:
    return {str(l.get("name", l) if isinstance(l, dict) else l).strip().lower() for l in ticket.get("labels") or []}


# ── routing ─────────────────────────────────────────────────────────────────────────────────────────────────────

def macos_reason(ticket: dict) -> str | None:
    """Why this ticket needs a Mac, or None. O(title + body)."""
    hit = sorted(_label_names(ticket) & MAC_LABELS)
    if hit:
        return f"labelled {hit[0]}, which needs a Mac"
    m = _MAC_WORDS.search(f"{ticket.get('title') or ''}\n{ticket.get('body') or ''}")
    if m:
        return f"it mentions {m.group(0).strip()!r}, which needs a Mac"
    return None


def lane_down(now: datetime | None = None, path: Path | None = None) -> str | None:
    """Why the lane is resting, or None. An unreadable file doesn't rest the lane (the other checks still hold)."""
    data = _read_json(path or LANE_PATH)
    if not isinstance(data, dict):
        return None
    try:
        until = datetime.fromisoformat(str(data["down_until"]))
    except (KeyError, ValueError):
        return None
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if (now or _now()) < until:
        return f"the box lane rests until {until.strftime('%H:%M UTC')} ({str(data.get('why', '?'))[:120]})"
    return None


def rest_lane(kind: str, why: str, now: datetime | None = None, path: Path | None = None) -> None:
    seconds = REST_S.get(kind, REST_S["infra"])
    if seconds <= 0:
        return
    _write_json(path or LANE_PATH, {"down_until": ((now or _now()) + timedelta(seconds=seconds)).isoformat(),
                                    "kind": kind, "why": why[:300]})


def _pid_alive(pid) -> bool:
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def running(records_dir: Path | None = None, alive=_pid_alive) -> list[dict]:
    """Box builds this Mac has in flight (live `run` processes); records of dead ones are removed. O(records)."""
    d = records_dir or RECORDS_DIR
    out = []
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        rec = _read_json(f)
        if isinstance(rec, dict) and alive(rec.get("pid")):
            out.append(rec)
        else:
            f.unlink(missing_ok=True)
    return out


def routes(repo: str, ticket: dict, settings: dict, *, load_profile=None, registry=None, online=None,
           in_flight=None, has_tokens=None, now: datetime | None = None) -> tuple[bool, str | None]:
    """May this ticket be built on the box right now? (True, None) or (False, why). Cheap checks first; every reader
    is injected for tests. An unreadable registry or Tailscale means no."""
    import dispatch_concurrency
    slots = dispatch_concurrency.box_slots(settings)
    if slots < 1:
        return False, "box builds are off (config/dispatch.json box_builds.slots)"
    if load_profile is None:
        import project_profile as pp
        load_profile = pp.load_profile
    try:
        profile = load_profile(repo)
    except Exception:  # noqa: BLE001 -- an unreadable profile is no opt-in
        profile = None
    if not (isinstance(profile, dict) and profile.get("linux_ok") is True):
        return False, f"{repo.split('/')[-1]} hasn't opted in to box builds (linux_ok in its profile)"
    if LINUX_LABEL not in _label_names(ticket):
        return False, f"#{ticket.get('number')} isn't labelled {LINUX_LABEL}"
    why = macos_reason(ticket)
    if why:
        return False, f"#{ticket.get('number')} stays on a Mac: {why}"
    why = lane_down(now)
    if why:
        return False, why
    import task_dispatch
    try:
        info = (registry() if registry else task_dispatch._candidates()).get(BOX)
    except Exception:  # noqa: BLE001
        info = None
    if not info or not task_dispatch.accepts(info, NEED):
        return False, f"{BOX} doesn't accept {NEED} work (registry)"
    hosts = online() if online else task_dispatch.tailscale_online_hosts_or_none()
    if not hosts or info.get("tailscale_hostname") not in hosts:
        return False, f"{BOX} is offline"
    ok, why = dispatch_concurrency.can_start_box_build(settings, len(in_flight() if in_flight else running()))
    if not ok:
        return False, why
    if not (has_tokens() if has_tokens else _have_tokens()):
        return False, "this Mac doesn't hold the bot token and a Claude login"
    return True, None


def _have_tokens() -> bool:
    return bool(_read_secret(BOT_TOKEN)) and bool(_read_secret(OAUTH_TOKEN))


# ── the Mac side ────────────────────────────────────────────────────────────────────────────────────────────────

def _read_secret(path: Path) -> str:
    try:
        v = Path(path).read_text().strip()
    except OSError:
        return ""
    return v if v and "\n" not in v and "\r" not in v and "\0" not in v else ""


def choose_login(others_running: int, settings: dict, credit_ready=None) -> tuple[str, Path, str, str]:
    """(env name, key file, mode, why), plan first (builder_auth.sh's rule, owner 2026-10-29): the plan's token while
    one of the box's plan slots is free; the API credit only for a build beyond them, only when the box has credit slots
    and the credit is ready. Anything unreadable means the plan."""
    import dispatch_concurrency
    plan_slots = max(1, dispatch_concurrency.box_slots(settings))
    if others_running < plan_slots:
        return LOGINS[0], OAUTH_TOKEN, "plan", "plan-slot"
    if settings.get("credit_slots", {}).get(BOX, 0) > 0:
        try:
            ready = bool(credit_ready() if credit_ready else dispatch_concurrency.credit_ready_local())
        except Exception:  # noqa: BLE001
            ready = False
        if ready:
            return LOGINS[1], API_KEY, "api", "credit-ok"
    return LOGINS[0], OAUTH_TOKEN, "plan", "no-credit-slot"


def engine_sha(root: Path | None = None, run=subprocess.run) -> str | None:
    """The engine commit this Mac runs, if GitHub has it (the VM fetches it); else origin/main's. None if unreadable."""
    root = root or Path(__file__).resolve().parents[1]

    def git(*a):
        p = run(["git", "-C", str(root), *a], capture_output=True, text=True, timeout=30)
        return p.stdout.strip() if p.returncode == 0 else ""
    head = git("rev-parse", "HEAD")
    if _SHA.match(head) and git("branch", "-r", "--contains", head):
        return head
    main = git("rev-parse", "origin/main")
    return main if _SHA.match(main) else None


def scrub(text: str, secrets) -> str:
    for s in secrets:
        if s and len(s) >= 8:
            text = text.replace(s, "***")
    return text


def parse_result(stdout: str) -> dict | None:
    for line in reversed((stdout or "").splitlines()):
        if line.startswith(RESULT_PREFIX):
            try:
                data = json.loads(line[len(RESULT_PREFIX):])
            except ValueError:
                return None
            return data if isinstance(data, dict) else None
    return None


def _infra(why: str) -> tuple[dict, str]:
    """A failure that is the box's, not the ticket's: run_ticket's timed-out path (no strike, a retry with backoff,
    capped with the other retries), and the breaker is fed too (#881's rule)."""
    return {"raised": False, "pr_url": None, "reason": f"Box build: {why}"[:600], "timed_out": True}, "infra"


def classify(returncode: int | None, stdout: str, ssh_timed_out: bool = False) -> tuple[dict, list[str], str | None, dict]:
    """(outcome for settle, findings, lane-rest kind or None, the box's result). Every path returns an outcome."""
    result = parse_result(stdout) or {}
    if ssh_timed_out:
        return (*_pair(_infra("the box didn't answer before the time limit; the VM is destroyed there by its own "
                             "timeout")), result)
    if returncode == 255 and not result:
        return (*_pair(_infra("the box dropped off mid-build (ssh exit 255)")), result)
    if not result:
        if returncode in (124, 137):
            return (*_pair(_infra(f"timed out on the box (exit {returncode}); the VM was destroyed")), result)
        return (*_pair(_infra(f"the box-side runner ended without a result (exit {returncode})")), result)
    refused = result.get("refused")
    if refused and refused not in REST_S:
        return (*_pair(_infra(f"the box refused it for an unknown reason ({str(refused)[:60]})")), result)
    if refused:
        kind = refused
        return ({"raised": False, "pr_url": None, "reason": f"Box build refused: {result.get('why') or refused}"[:600],
                 "env_missing": True}, [], kind, result)
    outcome = result.get("outcome")
    if isinstance(outcome, dict) and isinstance(outcome.get("raised"), bool):
        findings = [str(f) for f in outcome.get("findings") or []][:50]
        clean = {k: outcome[k] for k in ("raised", "pr_url", "reason", "env_missing", "timed_out", "model_unavailable",
                                          "too_vague") if k in outcome}
        clean.setdefault("pr_url", None)
        clean.setdefault("reason", None)
        if clean["raised"] and not (isinstance(clean["pr_url"], str) and clean["pr_url"].startswith("https://github.com/")):
            return (*_pair(_infra("the VM said it raised a PR but gave no PR link")), result)
        return clean, findings, None, result
    return (*_pair(_infra(str(result.get("vm_error") or "the VM ended without a build outcome")[:300])), result)


def _pair(t):
    outcome, kind = t
    return outcome, [], kind


class _Stopped(Exception):
    """The Mac-side runner was told to stop (SIGTERM/SIGHUP): settle as the box's failure, never leave the claim."""


def _on_stop(signum, _frame):
    raise _Stopped(f"signal {signum}")


def ssh_holding_stdin(cmd: list[str], input: str, timeout: float, **_kw):
    """Run ssh, write `input` (the secrets) to its stdin, and keep stdin OPEN until it ends. The box reads EOF on its
    stdin as "the dispatching Mac is gone" (this process killed, the Mac asleep, the link down past ssh's keepalive)
    and destroys the VM at once, instead of building on with nobody to settle it (found live 2026-10-30)."""
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out: list[str] = []
    err: list[str] = []
    readers = [threading.Thread(target=lambda: out.append(proc.stdout.read()), daemon=True),
               threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)]
    for t in readers:
        t.start()
    try:
        proc.stdin.write(input)
        proc.stdin.flush()
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    finally:
        try:
            proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        for t in readers:
            t.join(timeout=10)
    return subprocess.CompletedProcess(cmd, proc.returncode, "".join(out), "".join(err))


def _box_command(ref: str, sha: str, run_id: str, login: str, s: dict, box_agents: str) -> str:
    """The remote command line: names and numbers only, never a secret. Every value is checked before it gets here."""
    if not _BOX_AGENTS.match(box_agents):
        raise ValueError(f"bad box engine path {box_agents!r}")
    # Double quotes, not shlex: "$HOME" must expand on the box (single quotes kept it literal: caught by a test).
    script = f'"{box_agents}/lib/box_build.py"'
    return (f"timeout -k 15 {int(s['timeout_s']) + 600} \"$HOME/.agents/venv/bin/python\" {script} vm "
            f"{shlex.quote(ref)} --sha {sha} --run-id {run_id} --login {login} --timeout {int(s['timeout_s'])} "
            f"--memory-mb {int(s['memory_mb'])} --vcpus {int(s['vcpus'])} --min-disk-gb {float(s['min_disk_gb']):g} "
            f"--reserve-mb {int(s['reserve_mb'])}")


def run(ref: str, run_id: str, *, settings: dict | None = None, ssh=ssh_holding_stdin, settle=None, sha: str | None = None,
        box_agents: str = "$HOME/.agents", label_pr=None, record_failure=None, records_dir: Path | None = None,
        host: str = BOX) -> dict:
    """One box build, start to settle. Never raises; returns the settled outcome plus the box's numbers."""
    import dispatch_concurrency
    import run_ticket
    settle = settle or run_ticket.settle
    if record_failure is None:
        import failure_breaker
        record_failure = failure_breaker.record_failure
    repo, number = run_ticket.parse_ticket_arg(ref)
    ref = f"{repo}#{number}"
    settings = settings or dispatch_concurrency.load()
    s = {**dispatch_concurrency.box_settings(settings), "min_disk_gb": settings["guards"]["min_disk_gb"]}
    records = records_dir or RECORDS_DIR
    record = records / f"{run_id}.json"
    started = time.monotonic()
    secrets: list[str] = []
    result: dict = {}
    kind = None
    try:
        if not _RUN_ID.match(run_id or ""):
            raise ValueError(f"bad run id {run_id!r}")
        others = len(running(records))
        _write_json(record, {"pid": os.getpid(), "ticket": number, "repo": repo, "run_id": run_id, "machine": BOX,
                             "started": _now().isoformat()})
        login, key_file, mode, why = choose_login(others, settings)
        bot, key = _read_secret(BOT_TOKEN), _read_secret(key_file)
        secrets = [bot, key]
        _bill(run_id, mode, why)
        sha = sha or engine_sha()
        if not bot or not key or not sha:
            missing = "the bot token" if not bot else "the Claude login" if not key else "the engine commit"
            outcome, findings, kind = ({"raised": False, "pr_url": None, "env_missing": True,
                                        "reason": f"Box build not started: this Mac can't read {missing}"}, [],
                                       "no-token-here")
        else:
            cmd = ["ssh", *SSH_OPTS, host, _box_command(ref, sha, run_id, login, s, box_agents)]
            try:
                proc = ssh(cmd, input=f"{bot}\n{key}\n", capture_output=True, text=True,
                           timeout=int(s["timeout_s"]) + 900)
                rc, out, err, late = proc.returncode, proc.stdout or "", proc.stderr or "", False
            except subprocess.TimeoutExpired as exc:
                rc, out, err, late = None, (exc.stdout or "") if isinstance(exc.stdout, str) else "", "", True
            _save_run_log(run_id, scrub(out + ("\n--- stderr ---\n" + err if err else ""), secrets))
            outcome, findings, kind, result = classify(rc, out, ssh_timed_out=late)
    except _Stopped as exc:
        outcome, findings, kind = _infra(f"the Mac-side runner was stopped mid-build ({exc}); the box destroyed the VM "
                                         "when its link closed")[0], [], "infra"
    except Exception as exc:  # noqa: BLE001 -- a crash here must still settle the claim
        outcome, findings, kind = _infra(f"the Mac-side runner crashed: {exc}")[0], [], "infra"
    finally:
        record.unlink(missing_ok=True)
    if kind:
        rest_lane(kind, str(outcome.get("reason")))
    if kind == "infra":
        try:
            record_failure(number, str(outcome["reason"]), **({"project": repo} if repo != run_ticket.REPO else {}))
        except Exception:  # noqa: BLE001
            pass
    try:
        settled = settle(number, outcome, findings, repo=repo, run_id=run_id, claim_label=CLAIM_LABEL)
    except Exception as exc:  # noqa: BLE001
        settled = {**outcome, "settle_error": str(exc)[:300]}
    if outcome.get("raised"):
        try:
            (label_pr or _label_pr)(outcome["pr_url"], result)
        except Exception as exc:  # noqa: BLE001 -- a label never undoes a PR
            print(f"[box-build] could not label {outcome['pr_url']}: {exc}", file=sys.stderr)
    entry = {"ticket": ref, "run_id": run_id, "raised": bool(outcome.get("raised")), "pr_url": outcome.get("pr_url"),
             "reason": scrub(str(outcome.get("reason") or ""), secrets)[:300], "rest": kind,
             "wall_s": round(time.monotonic() - started, 1),
             **{k: result.get(k) for k in ("vm_wall_s", "host_peak_used_mb", "host_min_available_mb", "vm_peak_rss_mb",
                                           "swept", "refused") if k in result}}
    _append_log(entry)
    return {**(settled if isinstance(settled, dict) else outcome), "box": entry}


def _bill(run_id: str, mode: str, why: str) -> None:
    try:
        BILLING_LOG.parent.mkdir(parents=True, exist_ok=True)
        with BILLING_LOG.open("a") as fh:
            fh.write(json.dumps({"at": _now().strftime("%Y-%m-%dT%H:%M:%SZ"), "task": f"box-{run_id}", "mode": mode,
                                 "why": why, "machine": BOX}) + "\n")
    except OSError:
        pass


def _save_run_log(run_id: str, text: str) -> None:
    try:
        RUN_LOGS.mkdir(parents=True, exist_ok=True)
        (RUN_LOGS / f"{run_id}.log").write_text(text[-2_000_000:])
    except OSError:
        pass


def _label_pr(pr_url: str, result: dict, gh=None) -> None:
    """Mark the PR as built on the box (informational) and say how the run went. Done from the Mac with its own gh."""
    gh = gh or (lambda *a: subprocess.run(["gh", *a], capture_output=True, text=True, timeout=30))
    repo = "/".join(pr_url.split("/")[3:5])
    if gh("pr", "edit", pr_url, "--add-label", PR_LABEL).returncode != 0:
        gh("label", "create", PR_LABEL, "--repo", repo, "--color", "0e8a16",
           "--description", "Built in a disposable VM on mac-mini-2012 (ADR 0069)")
        gh("pr", "edit", pr_url, "--add-label", PR_LABEL)
    numbers = ", ".join(f"{k.replace('_', ' ')} {result[k]}" for k in ("vm_wall_s", "vm_peak_rss_mb", "host_peak_used_mb")
                        if result.get(k) is not None)
    gh("pr", "comment", pr_url, "--body",
       f"Built on {BOX} in a disposable `{IMAGE}` VM, destroyed after the run (ADR 0069). "
       f"It pushed as the bot, so ADR 0064's trust ramp applies: it waits for Gil until the bot has 5 clean approvals."
       + (f"\n\nRun: {numbers}." if numbers else ""))


def start(ref: str, run_id: str) -> bool:
    """Start `run` detached (ticket_pipeline, right after its claim); True when it started."""
    RUN_LOGS.mkdir(parents=True, exist_ok=True)
    try:
        with open(RUN_LOGS / f"{run_id}.runner.log", "a") as out:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "run", ref, "--run-id", run_id],
                             stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        return True
    except OSError as exc:
        print(f"[box-build] could not start the runner: {exc}", file=sys.stderr)
        return False


# ── the box side ────────────────────────────────────────────────────────────────────────────────────────────────

# Test files that need the private ~/.claude, which a build VM never gets: ignored in both the baseline and the verify, so
# the comparison stays fair. test_find_file skips itself once this PR's change to it is on main; then drop it here.
VM_PYTEST_IGNORE = ("lib/tests/test_find_file.py",)


def vm_command(ref: str, sha: str, run_id: str) -> str:
    """What runs inside the VM. Checked values only; the secrets are already exported by vm_run (from stdin)."""
    if not _REF.match(ref) or not _SHA.match(sha) or not _RUN_ID.match(run_id):
        raise ValueError("bad ticket, engine commit or run id")
    return "; ".join([
        'export PATH="$HOME/.local/bin:/usr/local/bin:$PATH" DISABLE_AUTOUPDATER=1 MARVIN_BOX_BUILD=1 '
        f"MARVIN_RUN_ID={run_id} PYTEST_ADDOPTS={shlex.quote(' '.join('--ignore=' + f for f in VM_PYTEST_IGNORE))}",
        # git asks gh for the bot token (GH_TOKEN); repo and global config stay untouched
        "export GIT_CONFIG_COUNT=2 GIT_CONFIG_KEY_0=credential.helper GIT_CONFIG_VALUE_0= "
        "GIT_CONFIG_KEY_1=credential.helper GIT_CONFIG_VALUE_1='!gh auth git-credential'",
        f'login="$(gh api user -q .login 2>/dev/null)"; [ -n "$login" ] || {{ echo "{REFUSED_PREFIX}bot-token-rejected"; '
        "exit 0; }",
        'uid="$(gh api user -q .id 2>/dev/null)"',
        'export GIT_AUTHOR_NAME="$login" GIT_COMMITTER_NAME="$login" '
        'GIT_AUTHOR_EMAIL="$uid+$login@users.noreply.github.com" GIT_COMMITTER_EMAIL="$uid+$login@users.noreply.github.com"',
        f'cd "$HOME/.agents" && git fetch -q origin {sha} && git checkout -q --detach {sha} || '
        f'{{ echo "{REFUSED_PREFIX}engine-sha"; exit 0; }}',
        f'exec "$HOME/.agents/venv/bin/python" lib/run_ticket.py --build-only {shlex.quote(ref)}',
    ])


def _meminfo() -> dict[str, int]:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            out[k] = int(v.split()[0]) // 1024
    except (OSError, ValueError):
        pass
    return out


def _vm_rss_mb() -> int | None:
    """Resident memory of the build VM's qemu process (one slot, so at most one), or None."""
    for p in Path("/proc").glob("[0-9]*"):
        try:
            if b"guest=run-marvin-build-" in (p / "cmdline").read_bytes():
                for line in (p / "status").read_text().splitlines():
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) // 1024
        except (OSError, ValueError):
            continue
    return None


class Sampler:
    """Peak host memory in use and the VM's peak RSS, every `every` seconds, on a thread."""

    def __init__(self, every: float = 2.0, meminfo=_meminfo, vm_rss=_vm_rss_mb):
        self.every, self.meminfo, self.vm_rss = every, meminfo, vm_rss
        self.peak_used = self.min_avail = self.peak_rss = None
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)

    def sample(self) -> None:
        m = self.meminfo()
        if "MemTotal" in m and "MemAvailable" in m:
            used = m["MemTotal"] - m["MemAvailable"]
            self.peak_used = used if self.peak_used is None else max(self.peak_used, used)
            self.min_avail = m["MemAvailable"] if self.min_avail is None else min(self.min_avail, m["MemAvailable"])
        r = self.vm_rss()
        if r is not None:
            self.peak_rss = r if self.peak_rss is None else max(self.peak_rss, r)

    def _loop(self):
        while not self._stop.is_set():
            self.sample()
            self._stop.wait(self.every)

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=5)
        self.sample()


def _watch_for_hangup(stdin, kill=os.kill) -> threading.Thread:
    """The dispatching Mac holds our stdin open for the whole run; EOF means it is gone. Then SIGTERM ourselves: the
    handler raises SystemExit in the main thread, and vm_run's cleanup destroys the VM."""
    def wait():
        try:
            while stdin.read(4096):
                pass
        except (OSError, ValueError):
            pass
        kill(os.getpid(), __import__("signal").SIGTERM)
    t = threading.Thread(target=wait, daemon=True)
    t.start()
    return t


def box_vm(ref: str, sha: str, run_id: str, login: str, *, timeout: float, memory_mb: int, vcpus: int,
           min_disk_gb: float, reserve_mb: int, stdin=None, vm=None, meminfo=_meminfo, disk_free_gb=None,
           lock_path: Path | None = None, sampler=None, watch_stdin: bool = False) -> dict:
    """Run one ticket build in a fresh VM on this box. Returns the result `vm` prints. Never raises."""
    if vm is None:
        import vm_run as vm
    stdin = stdin or sys.stdin
    gh_token, key = stdin.readline().rstrip("\n"), stdin.readline().rstrip("\n")   # read first: never left in a pipe
    if login not in LOGINS:
        return {"refused": "no-secret", "why": f"unknown login {login!r}"}
    try:
        command = vm_command(ref, sha, run_id)
    except ValueError as exc:
        return {"refused": "engine-sha", "why": str(exc)}
    if not gh_token or not key:
        return {"refused": "no-secret", "why": "the bot token or the Claude login was missing on stdin"}
    if watch_stdin:
        _watch_for_hangup(stdin)
    lock_path = lock_path or BOX_LOCK
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = open(lock_path, "a+")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return {"refused": "busy", "why": f"{BOX} is already building a ticket (one at a time)"}
        swept = vm.sweep()
        if not vm.golden_path(IMAGE).exists():
            return {"refused": "no-image", "why": "no marvin-build image; run config/mac-mini-2012/build-builder-image.sh",
                    "swept": swept}
        free = disk_free_gb() if disk_free_gb else shutil.disk_usage(vm.RUNS_DIR if vm.RUNS_DIR.exists()
                                                                     else Path.home()).free / 1e9
        if free < min_disk_gb:
            return {"refused": "disk", "why": f"{free:.0f} GB free for VM disks, minimum {min_disk_gb:g}", "swept": swept}
        avail = meminfo().get("MemAvailable")
        if avail is not None and avail - memory_mb < reserve_mb:
            return {"refused": "memory", "why": f"{avail} MB available; a build VM takes {memory_mb} MB and "
                                                f"{reserve_mb} MB must stay free for the box's own work", "swept": swept}
        started = time.monotonic()
        with (sampler or Sampler(meminfo=meminfo)) as smp:
            r = vm.run(IMAGE, command, timeout=timeout, memory_mb=memory_mb, vcpus=vcpus,
                       secrets={"GH_TOKEN": gh_token, login: key})
        out = scrub(r.output or "", [gh_token, key])
        result = {"vm_ok": r.ok, "vm_error": scrub(r.error or "", [gh_token, key])[:300], "exit_code": r.exit_code,
                  "vm_wall_s": round(time.monotonic() - started, 1), "host_peak_used_mb": smp.peak_used,
                  "host_min_available_mb": smp.min_avail, "vm_peak_rss_mb": smp.peak_rss, "swept": swept,
                  "tail": out[-4000:]}
        for line in reversed(out.splitlines()):
            if line.startswith(REFUSED_PREFIX):
                kind = line[len(REFUSED_PREFIX):].strip()
                return {**result, "refused": kind if kind in REST_S else "infra", "why": f"in the VM: {kind}"}
            if line.startswith(OUTCOME_PREFIX):
                try:
                    result["outcome"] = json.loads(line[len(OUTCOME_PREFIX):])
                except ValueError:
                    pass
                break
        return result
    finally:
        lock.close()


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def status() -> dict:
    tail = []
    try:
        tail = [json.loads(l) for l in LOG_PATH.read_text().splitlines()[-5:]]
    except (OSError, ValueError):
        pass
    return {"running": running(), "lane_down": lane_down(), "recent": tail}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("start", "run"):
        p = sub.add_parser(name)
        p.add_argument("ref")
        p.add_argument("--run-id", required=True)
        if name == "run":
            p.add_argument("--sha", default=None, help="engine commit for the VM (default: this Mac's, if on GitHub)")
            p.add_argument("--box-agents", default="$HOME/.agents", help="where box_build.py lives on the box")
    v = sub.add_parser("vm")
    v.add_argument("ref")
    v.add_argument("--sha", required=True)
    v.add_argument("--run-id", required=True)
    v.add_argument("--login", required=True)
    v.add_argument("--timeout", type=float, required=True)
    v.add_argument("--memory-mb", type=int, required=True)
    v.add_argument("--vcpus", type=int, required=True)
    v.add_argument("--min-disk-gb", type=float, required=True)
    v.add_argument("--reserve-mb", type=int, required=True)
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "start":
        return 0 if start(a.ref, a.run_id) else 1
    if a.cmd == "run":
        import signal
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, _on_stop)   # stopped mid-build: settle it, and the box sees its stdin close
        r = run(a.ref, a.run_id, sha=a.sha, box_agents=a.box_agents)
        print(json.dumps(r.get("box", r)))
        return 0 if r.get("raised") else 1
    if a.cmd == "vm":
        import signal
        import vm_run
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, vm_run._terminate_cleanly)   # GNU timeout's TERM still runs the VM's cleanup
        r = box_vm(a.ref, a.sha, a.run_id, a.login, timeout=a.timeout, memory_mb=a.memory_mb, vcpus=a.vcpus,
                   min_disk_gb=a.min_disk_gb, reserve_mb=a.reserve_mb, watch_stdin=True)
        tail = r.pop("tail", "")
        if tail:
            print(tail)
        print(RESULT_PREFIX + json.dumps(r), flush=True)
        return 0
    print(json.dumps(status(), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
