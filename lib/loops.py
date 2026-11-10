#!/usr/bin/env python3
"""The loop registry (ADR 0083, marvin#1123): every MARVIN feedback loop, and whether it actually closes.

A loop works only when all four steps run: notice -> act -> verify -> remember. Each loop is one entry in
config/loops.json (this module is its only reader). Its status is derived every time, never stored:

    not wired   `wired` is false, or its action job has never reported a run (job_events)
    broken      its watched or verify signal is red, or its action job failed `n` runs in a row
    stalled     no full cycle within `cycle_days`, or its watched signal is amber
    closed      otherwise

A **full cycle** is a passed run of the action job while the verify signal isn't red; the last one is shown.

Signals, one vocabulary:  job:<name> (its job_events run log)   check:<id or prefix> (health-status.json; the worst of
the matching checks)   contract:<producer> (the output contract's finding, also in health-status.json)   none.

    loops.py status            # every loop, worst first, as JSON (what the Vitals Loops panel shows)
    loops.py fix <loop-id>     # the loop's own fix, from the registry; the caller never chooses a command

Complexity: O(L x r + C) for L loops, r <= 20 runs kept per job, C health checks; one read of the health file.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "config" / "loops.json"
HEALTH_STATUS = Path.home() / ".claude" / "logs" / "health-status.json"

ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
SIGNAL_RE = re.compile(r"^(none|(job|check|contract):[A-Za-z0-9][A-Za-z0-9:@._~/-]{0,79})$")
BROKEN_RE = re.compile(r"^(red|failed_runs:([1-9]|1\d|20))$")
OWNERS = ("marvin", "gil")
LEVELS = ("auto", "one_tap", "decision")
FIX_KINDS = ("rerun", "relogin", "install_job", "rollback", "ticket", "decision")
ARG_RE = {"rerun": ID_RE, "install_job": ID_RE, "relogin": re.compile(r"^[a-z][a-z-]{1,40}$"),
          "rollback": re.compile(r"^[1-9]\d{0,6}$"), "decision": re.compile(r"^[1-9]\d{0,6}$"), "ticket": None}
TEXT_MAX = 300
KEYS = {"id", "name", "watches", "broken_when", "action", "verify", "cycle_days", "owner", "fix", "wired", "ticket", "why"}
STATUS_ORDER = ("broken", "stalled", "not_wired", "closed")
SEVERITY_RANK = {"red": 3, "yellow": 2, "unmonitored": 1, "green": 0}


class LoopError(ValueError):
    pass


def _text(entry: dict, key: str, required: bool = True) -> str | None:
    v = entry.get(key)
    if v is None and not required:
        return None
    if not isinstance(v, str) or not v.strip() or len(v) > TEXT_MAX or any(c in v for c in "\0\r"):
        raise LoopError(f"{entry.get('id', '?')}: {key} must be one line of text, at most {TEXT_MAX} characters")
    return v.strip()


def validate(entry: object) -> dict:
    """One registry entry, checked; raises LoopError naming what's wrong. Nothing half-valid is ever shown."""
    if not isinstance(entry, dict):
        raise LoopError("a loop is a JSON object")
    lid = entry.get("id")
    if not isinstance(lid, str) or not ID_RE.match(lid):
        raise LoopError(f"not a loop id: {str(lid)[:60]!r}")
    extra = set(entry) - KEYS
    if extra:
        raise LoopError(f"{lid}: unknown key(s) {sorted(extra)}")
    out = {"id": lid, "name": _text(entry, "name"), "action": _text(entry, "action"), "why": _text(entry, "why", False)}
    for k in ("watches", "verify"):
        v = entry.get(k)
        if not isinstance(v, str) or not SIGNAL_RE.match(v):
            raise LoopError(f"{lid}: {k} must be none, job:<name>, check:<id> or contract:<producer>, got {str(v)[:60]!r}")
        out[k] = v
    if not isinstance(entry.get("broken_when"), str) or not BROKEN_RE.match(entry["broken_when"]):
        raise LoopError(f"{lid}: broken_when must be red or failed_runs:<1-20>")
    out["broken_when"] = entry["broken_when"]
    days = entry.get("cycle_days")
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 90:
        raise LoopError(f"{lid}: cycle_days must be a whole number of days, 1 to 90")
    out["cycle_days"] = days
    if entry.get("owner") not in OWNERS:
        raise LoopError(f"{lid}: owner must be one of {', '.join(OWNERS)}")
    out["owner"] = entry["owner"]
    if not isinstance(entry.get("wired"), bool):
        raise LoopError(f"{lid}: wired must be true or false")
    out["wired"] = entry["wired"]
    t = entry.get("ticket")
    if t is not None and (isinstance(t, bool) or not isinstance(t, int) or t <= 0):
        raise LoopError(f"{lid}: ticket must be an issue number")
    out["ticket"] = t
    fix = entry.get("fix")
    if not isinstance(fix, dict) or set(fix) - {"level", "kind", "arg"}:
        raise LoopError(f"{lid}: fix must be {{level, kind, arg}}")
    if fix.get("level") not in LEVELS:
        raise LoopError(f"{lid}: fix level must be one of {', '.join(LEVELS)}")
    if fix.get("kind") not in FIX_KINDS:
        raise LoopError(f"{lid}: fix kind must be one of {', '.join(FIX_KINDS)}")
    pattern, arg = ARG_RE[fix["kind"]], fix.get("arg")
    if pattern is None:
        if arg is not None:
            raise LoopError(f"{lid}: a {fix['kind']} fix takes no arg")
    elif not isinstance(arg, (str, int)) or isinstance(arg, bool) or not pattern.match(str(arg)):
        raise LoopError(f"{lid}: {fix['kind']} fix needs a valid arg, got {str(arg)[:40]!r}")
    out["fix"] = {"level": fix["level"], "kind": fix["kind"], "arg": None if arg is None else str(arg)}
    return out


def load(path: Path | None = None) -> tuple[list[dict], list[dict]]:
    """(valid loops, problems). A bad entry is a problem, never a crash; a duplicate id keeps the first."""
    try:
        doc = json.loads((path or REGISTRY).read_text())
        entries = doc.get("loops") if isinstance(doc, dict) else None
        if not isinstance(entries, list):
            raise ValueError("no loops list")
    except (OSError, ValueError) as exc:
        return [], [{"loop": None, "error": f"registry unreadable: {exc}"[:200]}]
    loops, problems, seen = [], [], set()
    for e in entries:
        try:
            lp = validate(e)
        except LoopError as exc:
            problems.append({"loop": e.get("id") if isinstance(e, dict) else None, "error": str(exc)[:200]})
            continue
        if lp["id"] in seen:
            problems.append({"loop": lp["id"], "error": "duplicate id; the first one is kept"})
            continue
        seen.add(lp["id"])
        loops.append(lp)
    return loops, problems


# ── signals ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _parse(ts) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(ts))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def read_runs(job: str, directory: Path) -> list[dict] | None:
    """The job's runs, oldest first; None when it has never reported."""
    try:
        runs = json.loads((directory / f"{job}.json").read_text()).get("runs")
    except (OSError, ValueError, AttributeError):
        return None
    return [r for r in runs if isinstance(r, dict)] if isinstance(runs, list) else None


def failed_in_a_row(runs: list[dict]) -> int:
    n = 0
    for r in reversed(runs):
        if r.get("status") == "running":
            continue
        if r.get("status") not in ("failed", "crashed"):
            break
        n += 1
    return n


def signal(sig: str, checks: list[dict], jobs_dir: Path) -> dict:
    """{"state": red|yellow|green|unknown, "detail": str} for one signal."""
    if sig == "none":
        return {"state": "unknown", "detail": "no signal declared"}
    kind, ref = sig.split(":", 1)
    if kind == "job":
        runs = read_runs(ref, jobs_dir)
        if not runs:
            return {"state": "unknown", "detail": f"{ref} has never reported a run"}
        last = runs[-1]
        bad = failed_in_a_row(runs)
        if bad:
            return {"state": "red", "detail": f"{ref}: {bad} failed run(s) in a row: {str(last.get('error') or '')[:120]}"}
        return {"state": "green", "detail": f"{ref}: last run {last.get('status')}"}
    cid = f"contract:{ref}" if kind == "contract" else ref
    hits = [c for c in checks if isinstance(c, dict) and isinstance(c.get("id"), str)
            and (c["id"] == cid or (kind == "check" and c["id"].startswith(cid)))]
    if not hits:
        return {"state": "unknown", "detail": f"no health check {cid}"}
    worst = max(hits, key=lambda c: SEVERITY_RANK.get(c.get("severity"), 1))
    sev = worst.get("severity")
    state = sev if sev in ("red", "yellow", "green") else "unknown"
    return {"state": state, "detail": f"{worst['id']}: {str(worst.get('detail') or '')[:160]}"}


# ── status ───────────────────────────────────────────────────────────────────────────────────────────────────────

def evaluate(loop: dict, checks: list[dict], jobs_dir: Path, now: datetime) -> dict:
    watched = signal(loop["watches"], checks, jobs_dir)
    verify = signal(loop["verify"], checks, jobs_dir)
    job = loop["action"][4:] if loop["action"].startswith("job:") else None
    runs = read_runs(job, jobs_dir) if job else None
    last_cycle = None
    if runs and verify["state"] != "red":
        passed = [_parse(r.get("finished_at")) for r in runs if r.get("status") == "passed"]
        passed = [p for p in passed if p]
        last_cycle = max(passed) if passed else None

    out = {**loop, "watched": watched, "verified": verify, "last_cycle": last_cycle.isoformat() if last_cycle else None}
    if not loop["wired"]:
        return {**out, "status": "not_wired", "reason": loop.get("why") or "not plugged into the loop kernel yet"}
    if job and runs is None:
        return {**out, "status": "not_wired", "reason": f"its job {job} doesn't report its runs yet"}
    m = re.match(r"failed_runs:(\d+)", loop["broken_when"])
    in_a_row = failed_in_a_row(runs or [])
    if watched["state"] == "red" or verify["state"] == "red" or (m and in_a_row >= int(m.group(1))):
        why = (watched if watched["state"] == "red" else verify if verify["state"] == "red"
               else {"detail": f"{job} failed {in_a_row} runs in a row"})["detail"]
        return {**out, "status": "broken", "reason": why}
    if job and (last_cycle is None or now - last_cycle > timedelta(days=loop["cycle_days"])):
        since = "never" if last_cycle is None else f"{(now - last_cycle).days} days ago"
        return {**out, "status": "stalled", "reason": f"no full cycle in {loop['cycle_days']} day(s) (last: {since})"}
    if watched["state"] == "yellow":
        return {**out, "status": "stalled", "reason": watched["detail"]}
    return {**out, "status": "closed", "reason": watched["detail"] if watched["state"] != "unknown" else "cycling"}


def status(registry: Path | None = None, health: Path | None = None, jobs_dir: Path | None = None,
           now: datetime | None = None) -> dict:
    import job_events
    now = now or datetime.now(timezone.utc)
    loops, problems = load(registry)
    try:
        hs = json.loads((health or HEALTH_STATUS).read_text())
        checks = hs.get("checks") if isinstance(hs, dict) and isinstance(hs.get("checks"), list) else []
    except (OSError, ValueError):
        checks, hs = [], {}
    rows = [evaluate(lp, checks, jobs_dir or job_events.JOBS_DIR, now) for lp in loops]
    rows.sort(key=lambda r: (STATUS_ORDER.index(r["status"]), r["name"].lower()))
    counts = {s: sum(r["status"] == s for r in rows) for s in STATUS_ORDER}
    return {"generated_at": now.isoformat(), "health_at": (hs or {}).get("generated_at"), "counts": counts,
            "loops": rows, "problems": problems}


# ── fixes: from the registry only ────────────────────────────────────────────────────────────────────────────────

def _issues() -> str:
    import instance
    return f"https://github.com/{instance.tickets_repo()}/issues/"


def _open(number: int) -> dict:
    """Open a ticket inside the dashboard (Workshop), never a browser: repo and number, plus the URL for reference."""
    import instance
    return {"how": "open", "repo": instance.tickets_repo(), "number": number, "url": f"{_issues()}{number}"}


def fix_plan(loop: dict, home: str | None = None) -> dict:
    """What the loop's fix button does, as data. Pure: the argv comes only from the registry entry."""
    fix, home = loop["fix"], home or str(Path.home())
    kind, arg = fix["kind"], fix.get("arg")
    if kind == "rerun":
        return {"how": "run", "argv": ["/bin/launchctl", "kickstart", f"gui/{os.getuid()}/com.marvin.{arg}"],
                "says": f"Started {arg} again"}
    if kind == "install_job":
        return {"how": "run", "argv": [f"{home}/.agents/venv/bin/python", f"{home}/.agents/lib/job_units.py", "install", arg],
                "says": f"Installed {arg}"}
    if kind == "relogin":
        return {"how": "renew", "account": arg}
    if kind in ("rollback", "decision"):
        return _open(int(arg))
    title = f"Loop not closing: {loop['name']}"
    body = (f"The Vitals Loops panel shows **{loop['name']}** (`{loop['id']}`) as not closing.\n\n"
            f"- Watches: `{loop['watches']}`\n- Action: {loop['action']}\n- Verify: `{loop['verify']}`\n"
            f"- Owner: {loop['owner']}\n\nPart of #1123 (ADR 0083). Filed from Vitals > Loops.\n")
    return {"how": "ticket", "title": title, "body": body}


def run_fix(loop_id: str, registry: Path | None = None, runner=None, gh=None) -> dict:
    loops, _ = load(registry)
    loop = next((lp for lp in loops if lp["id"] == loop_id), None) if isinstance(loop_id, str) else None
    if loop is None:
        return {"ok": False, "error": f"no loop {str(loop_id)[:48]!r}"}
    plan = fix_plan(loop)
    if plan["how"] == "run":
        runner = runner or (lambda argv: subprocess.run(argv, capture_output=True, text=True, timeout=120))
        try:
            r = runner(plan["argv"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:200], **plan}
        ok = r.returncode == 0
        return {"ok": ok, **plan, **({} if ok else {"error": (r.stderr or r.stdout or "").strip()[-200:]})}
    if plan["how"] == "ticket":
        if gh is None:
            import proposals
            gh = proposals.run_gh
        import instance
        args = ["issue", "create", "-R", instance.tickets_repo(), "--title", plan["title"], "--label", "needs-triage",
                "--label", "project:marvin"]
        rc, out, err = gh(args, plan["body"])
        m = re.search(r"/issues/(\d+)\s*$", (out or "").strip())
        if rc != 0 or not m:
            return {"ok": False, "how": "ticket", "error": (err or out or "gh failed").strip()[:200]}
        return {"ok": True, **_open(int(m.group(1))), "says": f"Filed #{m.group(1)}"}
    return {"ok": True, **plan}


def main(argv: list[str]) -> int:
    if argv == ["status"]:
        print(json.dumps(status()))
        return 0
    if len(argv) == 2 and argv[0] == "fix":
        out = run_fix(argv[1])
        print(json.dumps(out))
        return 0 if out.get("ok") else 1
    print("usage: loops.py status | fix <loop-id>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
