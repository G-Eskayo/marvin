#!/usr/bin/env python3
"""Health-monitoring check framework (ADR 0033) -- absorbs cron_health.py's
existing job-log and repo-integrity checks into a general, extensible
registry, and adds the checks that would have caught 2026-10-01's incidents:
an empty ChromaDB collection, missing auth token files, a stale dispatch
lock, and a ticket's failure streak approaching the stuck-loop cap before
it actually parks.

Each check returns a dict shaped like RESULT_TEMPLATE below. `severity` is
one of "red"/"yellow"/"green" -- the UI-only grey staleness gradient and
the unmonitored marker are computed by the consumer (the dashboard, or
`coverage()` below), not stored on individual results.

Run standalone: ~/.agents/venv/bin/python health_checks.py [--json]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cron_health as ch  # noqa: E402
import machine_profile  # noqa: E402
import metrics_registry as mr  # noqa: E402

HOME = Path.home()
STATUS_PATH = HOME / ".claude" / "logs" / "health-status.json"
LAUNCHAGENTS_DIR = HOME / "Library" / "LaunchAgents"
SSH_OPTS = ["-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]

RESULT_TEMPLATE = {"id": "", "label": "", "severity": "green", "detail": "", "checked_at": "", "value": None}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _result(id_, label, severity, detail, value=None) -> dict:
    return {"id": id_, "label": label, "severity": severity, "detail": detail,
            "checked_at": _now().isoformat(), "value": value}


# ── tokens ──────────────────────────────────────────────────────────────

def check_token_files() -> list[dict]:
    """Local machine only -- same scoping reasoning as the dashboard's
    existing dispatch_status.js: checking the OTHER machine's token files
    needs SSH, a real extension not this cut. Both tokens found completely
    missing (laptop, found live 2026-10-01) blocked every dispatched
    ticket's claude auth and gh pr create respectively."""
    results = []
    for name, path in [("oauth-token", HOME / ".claude" / ".oauth-token"),
                        ("gh-token", HOME / ".claude" / ".gh-token")]:
        cid = f"token:{name}"
        label = f"Auth token: {name}"
        if not path.exists():
            results.append(_result(cid, label, "red", f"{path} does not exist"))
            continue
        content = path.read_text()
        if re.search(r"\s", content.strip()):
            results.append(_result(cid, label, "red", f"{path} contains embedded whitespace (corrupted — found live 2026-10-01: a copy-paste line break split a token in two)"))
            continue
        if not content.strip():
            results.append(_result(cid, label, "red", f"{path} is empty"))
            continue
        results.append(_result(cid, label, "green", f"{path} present, {len(content.strip())} chars, no whitespace"))
    return results


# ── route.py's embedding classifier ────────────────────────────────────

def check_intent_routing_collection() -> dict:
    """The exact silent failure found live 2026-10-01: the collection
    existed (get_or_create_collection succeeds either way) but held zero
    documents, so every classify() call fell through to 'unavailable' and
    route.py silently ran on its 28%-accurate keyword fallback with no
    error anywhere."""
    cid = "route:intent-routing-collection"
    label = "route.py embedding classifier (ChromaDB)"
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(HOME / ".claude" / "chroma"))
        col = client.get_or_create_collection("intent-routing", metadata={"hnsw:space": "cosine"})
        count = col.count()
    except Exception as exc:
        return _result(cid, label, "red", f"could not query collection: {exc}")
    if count == 0:
        return _result(cid, label, "red",
                        "0 documents — route.py is silently running on keyword-only fallback. "
                        "Fix: python3 ~/.agents/lib/intent_classify.py --seed", value=0)
    return _result(cid, label, "green", f"{count} reference examples indexed", value=count)


# ── dispatch lock ───────────────────────────────────────────────────────

MAX_DISPATCH_MINUTES_YELLOW = 45  # plan+exec timeouts sum to ~40min worst case per iteration
MAX_DISPATCH_MINUTES_RED = 120    # well past any legitimate single-ticket run


def check_dispatch_lock(state_path: Path | None = None) -> dict:
    """The exact lock that sat stuck 'busy: true' for 15 days after the
    mac-mini's crash (found live 2026-10-01), silently blocking the hourly
    ticket pipeline the whole time with no symptom other than 'nothing is
    happening,' which nobody could see without SSHing in and reading the
    raw file by hand."""
    cid = "dispatch:lock-age"
    label = "Local dispatch lock"
    path = state_path or (HOME / ".claude" / "dispatch-state.json")
    if not path.exists():
        return _result(cid, label, "green", "no lock file (idle)")
    try:
        state = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return _result(cid, label, "red", f"lock file unreadable: {exc}")
    if not state.get("busy"):
        return _result(cid, label, "green", "idle")
    started_at = state.get("started_at")
    if not started_at:
        return _result(cid, label, "yellow", "busy with no started_at timestamp — can't judge age")
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return _result(cid, label, "yellow", f"busy, unparseable started_at: {started_at}")
    age_min = (_now() - started).total_seconds() / 60
    task = state.get("task", "unknown task")
    if age_min >= MAX_DISPATCH_MINUTES_RED:
        return _result(cid, label, "red", f"busy {age_min:.0f}min on '{task}' — almost certainly stuck", value=age_min)
    if age_min >= MAX_DISPATCH_MINUTES_YELLOW:
        return _result(cid, label, "yellow", f"busy {age_min:.0f}min on '{task}' — longer than a normal single attempt", value=age_min)
    return _result(cid, label, "green", f"busy {age_min:.0f}min on '{task}' — normal range", value=age_min)


# ── ticket failure streaks (early warning before the park fires) ────────

def check_ticket_failure_streaks(repo: str = "G-Eskayo/marvin", run=subprocess.run) -> list[dict]:
    """Early-warning layer in front of run_ticket.py's own 3-strike guard
    (G-Eskayo/marvin, fixed 2026-10-01): a ticket sitting at streak 2 is
    one more automated failure from being parked -- worth surfacing before
    that happens, not just after."""
    try:
        proc = run(["gh", "issue", "list", "--repo", repo, "--label", "claimed:mac-mini,claimed:macbook-pro",
                    "--state", "open", "--json", "number,title,labels"],
                   capture_output=True, text=True, timeout=20)
        claimed = json.loads(proc.stdout) if proc.returncode == 0 else []
    except (subprocess.TimeoutExpired, json.JSONDecodeError):
        claimed = []

    results = []
    for issue in claimed:
        n = issue["number"]
        try:
            cproc = run(["gh", "issue", "view", str(n), "--repo", repo, "--json", "comments"],
                        capture_output=True, text=True, timeout=20)
            comments = json.loads(cproc.stdout)["comments"] if cproc.returncode == 0 else []
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError):
            continue
        streak = 0
        for c in reversed(comments):
            if "did not pass verification" in c.get("body", ""):
                streak += 1
            else:
                break
        cid = f"ticket:streak:{n}"
        label = f"#{n} {issue['title'][:40]}"
        if streak >= 2:
            results.append(_result(cid, label, "yellow",
                                    f"{streak} consecutive automated failures — one more parks it", value=streak))
        else:
            results.append(_result(cid, label, "green", f"{streak} consecutive failure(s)", value=streak))
    return results


# ── cron jobs (absorbed from cron_health.py -- literally the same
# check_job() + persistent offset-tracking state, not a reimplementation,
# per ADR 0033. Reimplementing the log-scan naively (whole-tail regex, no
# offset tracking) was tried first and rejected: it re-flagged every
# already-seen historical failure on every run, which is exactly the
# false-alarm problem check_job()'s state file already solved.) ─────────

def _plist_label_to_job_name(label: str) -> str:
    for prefix in ("com.marvin.", "com.giles.", "com.gileskayo."):
        if label.startswith(prefix):
            return label[len(prefix):]
    return label


def discover_launchd_jobs() -> list[str]:
    """The coverage fix (ADR 0033): enumerate real plists instead of
    trusting a hand-maintained list. cron_health.py's own JOBS dict was
    found live 2026-10-01 covering 5 of 14 real jobs -- ticket-pipeline,
    the subsystem that spent the whole session spiraling, wasn't in it."""
    if not LAUNCHAGENTS_DIR.exists():
        return []
    names = []
    for plist in LAUNCHAGENTS_DIR.glob("com.*.plist"):
        label = plist.stem
        if label in ("com.apple.BKAgentService",):
            continue
        names.append(_plist_label_to_job_name(label))
    return sorted(names)


def check_cron_job_log(job_name: str, state: dict, now: datetime) -> dict | None:
    """Thin wrapper over cron_health.check_job() -- same JOBS table, same
    offset-tracked state (mutates `state` in place; caller persists it via
    cron_health._save_state so this shares one state file with the
    existing session-start markdown consumer, not a second copy)."""
    cid = f"cron:{job_name}"
    label = f"Cron job: {job_name}"
    entry = ch.JOBS.get(job_name)
    if entry is None:
        return None  # has a plist but no known log-scan target yet -- not a failure, a coverage gap
    scheduled, log_paths = entry
    line = ch.check_job(job_name, scheduled, log_paths, state, now)
    if line is None:
        return _result(cid, label, "green", "no failure indicators since last check")
    severity = "yellow" if "may not have run" in line else "red"
    return _result(cid, label, severity, line)


# ── repo integrity (absorbed from cron_health.py) ───────────────────────

CONFLICT_MARKER_RE = re.compile(r"^(<{7}|={7}|>{7})(?: |$)", re.MULTILINE)
SYNCED_REPOS = {"~/.agents": ".agents", "~/.claude": ".claude"}


def check_repo_integrity(display_name: str, rel_path: str) -> dict:
    cid = f"repo:integrity:{display_name}"
    label = f"{display_name} — stash/conflict integrity"
    repo = HOME / rel_path
    try:
        stash = subprocess.run(["git", "-C", str(repo), "stash", "list"],
                               capture_output=True, text=True, timeout=10)
        n_stash = len([l for l in stash.stdout.splitlines() if l.strip()])
    except subprocess.TimeoutExpired:
        return _result(cid, label, "yellow", "git stash list timed out")
    if n_stash:
        return _result(cid, label, "yellow", f"{n_stash} stash(es) present — blocks code-sync until resolved", value=n_stash)
    status = subprocess.run(["git", "-C", str(repo), "status", "--short"],
                            capture_output=True, text=True, timeout=10)
    if re.search(r"^(UU|AA|DD) ", status.stdout, re.MULTILINE):
        return _result(cid, label, "red", "unresolved merge conflict in working tree")
    return _result(cid, label, "green", "clean, no stashes")


# ── machine reachability ─────────────────────────────────────────────────

def check_machine_reachability() -> list[dict]:
    results = []
    for device_id, info in machine_profile.remote_devices().items():
        cid = f"machine:{device_id}"
        label = f"Machine: {device_id}"
        host = info.get("tailscale_hostname")
        if not host:
            results.append(_result(cid, label, "yellow", "no tailscale_hostname registered"))
            continue
        try:
            proc = subprocess.run(["ssh", *SSH_OPTS, host, "echo ok"],
                                  capture_output=True, text=True, timeout=8)
            if proc.returncode == 0:
                results.append(_result(cid, label, "green", f"reachable ({host})"))
            else:
                results.append(_result(cid, label, "red", f"unreachable ({host}): {proc.stderr.strip()[:200]}"))
        except subprocess.TimeoutExpired:
            results.append(_result(cid, label, "red", f"unreachable ({host}): timed out"))
    return results


# ── coverage ─────────────────────────────────────────────────────────────

def coverage(results: list[dict]) -> dict:
    """What fraction of real, discovered infrastructure has a check at
    all. Jobs with a plist but no entry in JOB_LOG_PATHS show up as
    explicitly unmonitored rather than silently absent."""
    discovered = discover_launchd_jobs()
    checked_ids = {r["id"] for r in results}
    unmonitored = [j for j in discovered if f"cron:{j}" not in checked_ids]
    n_covered = len(discovered) - len(unmonitored)
    return {
        "known_jobs": discovered,
        "unmonitored_jobs": unmonitored,
        "covered": n_covered,
        "total": len(discovered),
        "fraction": round(n_covered / len(discovered), 2) if discovered else 1.0,
    }


# ── numeric anomaly tracking (tier 2, reuses metrics_registry.py) ───────

# Metrics where a bigger number is the healthier direction -- everything
# else recorded (lock age, failure streaks, cron failure-hit counts) is
# "lower is better" by default, since every other numeric check here
# counts something bad.
HIGHER_IS_BETTER = {"route:intent-routing-collection"}


def record_anomaly_metrics(results: list[dict]) -> dict | None:
    """Any check carrying a numeric `value` gets recorded as a subsystem
    snapshot via the same baseline/compare primitive metrics_registry.py
    already provides for ticket code-quality metrics (G-Eskayo/marvin#2) --
    reused here, not reimplemented, per ADR 0033. A generic deviation from
    a metric's own rolling baseline is how a storm like #30's (1,139
    comments) gets flagged without anyone having pre-written a
    'storm detector' rule."""
    numeric = {r["id"]: {"value": r["value"], "higher_is_better": r["id"] in HIGHER_IS_BETTER}
               for r in results if r.get("value") is not None}
    if not numeric:
        return None
    baseline = mr.latest("health-monitor")  # read before this run's own record() below
    mr.record("health-monitor", numeric)
    if baseline is None:
        return None
    return mr.compare("health-monitor", baseline, numeric)


# ── orchestration ────────────────────────────────────────────────────────

def run_all() -> dict:
    results: list[dict] = []
    results += check_token_files()
    results.append(check_intent_routing_collection())
    results.append(check_dispatch_lock())
    results += check_ticket_failure_streaks()
    cron_state = ch._load_state()
    cron_now = datetime.now().astimezone()
    for job in discover_launchd_jobs():
        r = check_cron_job_log(job, cron_state, cron_now)
        if r:
            results.append(r)
    ch._save_state(cron_state)
    for name, rel in SYNCED_REPOS.items():
        results.append(check_repo_integrity(name, rel))
    results += check_machine_reachability()

    cov = coverage(results)
    anomaly = record_anomaly_metrics(results)

    severities = [r["severity"] for r in results]
    overall = "red" if "red" in severities else "yellow" if "yellow" in severities else "green"

    return {
        "generated_at": _now().isoformat(),
        "overall": overall,
        "coverage": cov,
        "anomaly": anomaly,
        "checks": results,
    }


def write_status(status: dict | None = None) -> dict:
    status = status if status is not None else run_all()
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, indent=2))
    return status


if __name__ == "__main__":
    out = write_status()
    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
    else:
        print(f"overall: {out['overall']}  coverage: {out['coverage']['covered']}/{out['coverage']['total']}")
        for r in out["checks"]:
            print(f"  [{r['severity']:>6}] {r['label']}: {r['detail']}")
        if out["coverage"]["unmonitored_jobs"]:
            print(f"  unmonitored jobs: {', '.join(out['coverage']['unmonitored_jobs'])}")
