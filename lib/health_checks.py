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
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cron_health as ch  # noqa: E402
import machine_profile  # noqa: E402
from task_dispatch import TAILSCALE_BIN, TAILSCALE_ENV  # noqa: E402  (absolute path -- launchd's PATH omits the shell's additions)
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


# ── sync log stuck detection (cross-machine) ───────────────────────────────

SYNC_LOG_STUCK_YELLOW_AFTER_HOURS = 0.5  # 30 minutes
SYNC_LOG_STUCK_RED_AFTER_HOURS = 4  # 4 hours


def _run_sync_log_remote(host: str) -> str:
    """Read sync-log.md directly from disk on a remote machine over SSH."""
    script = "cat \"$HOME/.claude/sync-log.md\" 2>/dev/null || echo"
    cmd = ["ssh", *SSH_OPTS, host, "bash -s"]
    proc = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=10)
    return proc.stdout if proc.returncode == 0 else ""


def _parse_sync_log_entries(text: str) -> list[tuple[str, str, str, datetime]]:
    """Parse sync-log.md entries. Returns [(machine, repo, status, datetime), ...].
    Format: ## YYYY-MM-DDTHH:MM:SS — action (machine) [repo]
            Summary line starting with REFUSING/CONFLICT or normal."""
    entries = []
    for m in re.finditer(r"^## (\S+) — ([^\n]+)\n(.*?)(?=\n## |\Z)", text, re.DOTALL | re.MULTILINE):
        ts_str, header, body = m.group(1), m.group(2), m.group(3)
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue
        # Parse header: "action (machine) [repo]"
        machine_match = re.search(r"\(([^)]+)\)", header)
        repo_match = re.search(r"\[([^\]]+)\]", header)
        machine = machine_match.group(1) if machine_match else "unknown"
        repo = repo_match.group(1) if repo_match else "unknown"
        status_line = body.strip().split("\n")[0] if body.strip() else ""
        entries.append((machine, repo, status_line, ts))
    return entries


def check_sync_stuck() -> list[dict]:
    """Cross-machine: for each (machine, repo), find the latest sync-log entry.
    If it starts with REFUSING or CONFLICT, walk backward to find when this
    streak started, and report red/yellow based on duration."""
    results = []
    me = machine_profile.registry_id()

    # Collect sync-log from this machine + each remote device.
    devices = [(me, None)] + [
        (dev, info.get("tailscale_hostname"))
        for dev, info in machine_profile.remote_devices().items()
    ]

    all_entries = []
    for dev, host in devices:
        if host is None:
            text = (HOME / ".claude" / "sync-log.md").read_text() if (HOME / ".claude" / "sync-log.md").exists() else ""
        else:
            text = _run_sync_log_remote(host)
        for machine, repo, status, ts in _parse_sync_log_entries(text):
            all_entries.append((dev, machine, repo, status, ts))

    # Group by (device, machine, repo), keep latest entry per group.
    by_key = {}
    for dev, machine, repo, status, ts in all_entries:
        key = (dev, machine, repo)
        if key not in by_key or ts > by_key[key][4]:
            by_key[key] = (dev, machine, repo, status, ts)

    # Check for stuck entries (REFUSING or CONFLICT prefix).
    for dev, machine, repo, status, ts in by_key.values():
        if not status or (not status.startswith("REFUSING") and not status.startswith("CONFLICT")):
            continue

        # Find when this streak started by walking backward through all_entries.
        streak_start = ts
        relevant_entries = sorted([e for e in all_entries if e[1] == machine and e[2] == repo],
                                  key=lambda e: e[4], reverse=True)
        for _, m, r, s, t in relevant_entries:
            if s and (s.startswith("REFUSING") or s.startswith("CONFLICT")):
                streak_start = t
            else:
                break

        age_h = (_now() - streak_start).total_seconds() / 3600
        sev = "red" if age_h >= SYNC_LOG_STUCK_RED_AFTER_HOURS else "yellow" if age_h >= SYNC_LOG_STUCK_YELLOW_AFTER_HOURS else "green"
        if sev == "green":
            continue

        cid = f"sync:stuck:{dev}:{repo}"
        label = f"Code sync — {dev} {repo}"
        reason = status.split("\n")[0] if status else "unknown"
        detail = f"{machine} {repo} not syncing since {streak_start.isoformat()}: {reason}"
        results.append(_result(cid, label, sev, detail))

    return results


# ── pipeline circuit breaker ─────────────────────────────────────────────

def _run_failure_breaker_remote(host: str) -> list[dict]:
    """Query failure_breaker.py --json on a remote machine over SSH."""
    script = "python3 ~/.agents/lib/failure_breaker.py --json"
    cmd = ["ssh", *SSH_OPTS, host, script]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return []


def check_pipeline_breaker() -> dict:
    """Red while the cross-ticket breaker (failure_breaker.py) has paused dispatch:
    the same failure hit several different tickets, i.e. the environment is
    broken, not the tickets. Cross-machine: queries local machine + each
    reachable remote device (SSH), merging trips from all machines."""
    import failure_breaker
    cid, label = "pipeline:breaker", "Ticket pipeline circuit breaker"

    # Local machine trips.
    all_trips = failure_breaker.tripped()

    # Remote machine trips (if reachable).
    for device_id, info in machine_profile.remote_devices().items():
        host = info.get("tailscale_hostname")
        if not host:
            continue
        remote_trips = _run_failure_breaker_remote(host)
        all_trips.extend(remote_trips)

    if not all_trips:
        return _result(cid, label, "green", "not tripped")

    # Merge trips by (project, signature), keeping earliest first_seen for display.
    trips_by_key = {}
    for t in all_trips:
        key = (t.get("project", "G-Eskayo/marvin"), t["signature"])
        if key not in trips_by_key or t["first_seen"] < trips_by_key[key]["first_seen"]:
            trips_by_key[key] = t

    trips = list(trips_by_key.values())
    detail_parts = []
    for t in trips:
        first_seen = t["first_seen"]
        tickets = t["tickets"]
        sig = t["signature"]
        detail_parts.append(f"{sig} across tickets {tickets} (since {first_seen})")
    detail = "dispatch paused by the circuit breaker — " + "; ".join(detail_parts) + ". Fix the cause, then `failure_breaker.py clear`"
    return _result(cid, label, "red", detail, value=len(trips))


CATALOG_YELLOW_AFTER_HOURS = 3
CATALOG_RED_AFTER_HOURS = 24


def check_catalog_fresh(path: Path | None = None, now: datetime | None = None) -> dict:
    """The project catalog (and so the master 'Where things are' doc) must keep refreshing on its own;
    it is rebuilt hourly by the ticket pipeline and daily by the tidy agent."""
    import project_catalog
    cid, label = "catalog:fresh", "Project catalog is current"
    path = path or project_catalog.catalog_path()
    now = now or _now()
    cat = project_catalog.read_catalog(path)
    gen = project_catalog._parse((cat or {}).get("generated_at"))
    if gen is None:
        return _result(cid, label, "yellow", "no catalog built on this machine yet")
    age_h = (now - gen).total_seconds() / 3600
    n = len(cat.get("projects", []))
    sev = "green" if age_h <= CATALOG_YELLOW_AFTER_HOURS else "yellow" if age_h <= CATALOG_RED_AFTER_HOURS else "red"
    return _result(cid, label, sev, f"{n} projects, built {age_h:.1f}h ago", value=round(age_h, 1))


MAIN_HEALTH_PATH = Path.home() / ".claude" / "logs" / "main-health.json"
MAIN_HEALTH_STALE_HOURS = 24


def check_main_health(path: Path | None = None, now: datetime | None = None) -> dict:
    """Is the base branch green? Recorded by lib/main_health.py whenever origin/main moves. A red main refuses every
    marvin merge (the gate says so by name), so it should be visible BEFORE someone clicks Approve."""
    cid, label = "main:green", "The main branch passes its tests"
    path = path or MAIN_HEALTH_PATH
    now = now or _now()
    try:
        d = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return _result(cid, label, "yellow", "main has not been checked yet on this machine")
    when = datetime.fromisoformat(str(d.get("checked_at", "")).replace("Z", "+00:00")) if d.get("checked_at") else None
    if not d.get("ok"):
        names = ", ".join(d.get("failed", [])[:3]) or d.get("summary", "failing")
        return _result(cid, label, "red", f"main @ {d.get('sha', '?')} is failing: {names}. Merges are refused until it is fixed", value=len(d.get("failed", [])))
    if when is None or (now - when).total_seconds() > MAIN_HEALTH_STALE_HOURS * 3600:
        return _result(cid, label, "yellow", f"last check ({d.get('sha', '?')}) is more than a day old")
    return _result(cid, label, "green", f"main @ {d.get('sha', '?')}: {d.get('summary', 'passing')}")


GITHUB_BUDGET_YELLOW_BELOW = 0.20   # fraction of the hourly allowance
GITHUB_BUDGET_RED_BELOW = 0.05


def _read_github_budget() -> dict:
    import subprocess
    p = subprocess.run(["gh", "api", "graphql", "-f", "query={ rateLimit { limit remaining resetAt } }"],
                       capture_output=True, text=True, timeout=20)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:200] or "gh failed")
    return json.loads(p.stdout)["data"]["rateLimit"]


def check_github_budget(query=None) -> dict:
    """The pipeline, the merge gate and the dashboard all draw on ONE hourly GitHub allowance (5,000 GraphQL
    points). On 2026-10-05 it ran out mid-session and every `gh` call, including opening and merging a PR, was
    refused with no hint why. This makes the remaining budget visible before it hits zero."""
    cid, label = "github:budget", "GitHub request budget"
    try:
        b = (query or _read_github_budget)()
    except Exception as exc:  # noqa: BLE001
        if "rate limit" in str(exc).lower():  # the budget query itself was refused: that IS the answer
            return _result(cid, label, "red", "exhausted: GitHub is refusing requests until the hourly window resets", value=0)
        return _result(cid, label, "yellow", f"could not read the budget: {str(exc)[:100]}")
    limit, left = int(b["limit"]), int(b["remaining"])
    frac = left / limit if limit else 1
    sev = "red" if frac < GITHUB_BUDGET_RED_BELOW else "yellow" if frac < GITHUB_BUDGET_YELLOW_BELOW else "green"
    try:
        when = datetime.fromisoformat(str(b["resetAt"]).replace("Z", "+00:00")).strftime("%H:%M UTC")
    except (KeyError, ValueError):
        when = str(b.get("resetAt", "?"))
    return _result(cid, label, sev, f"{left:,} of {limit:,} left, resets {when}", value=left)


def check_missing_profiles(snapshot: dict | None = None, repos: list[str] | None = None, gh=None, profiles_dir: Path | None = None) -> list[dict]:
	"""Projects with ready-for-agent tickets but no execution profile will never dispatch.
	This check surfaces those projects so profiles can be created and dispatch turned on.
	Uses `ticket_agents.ready_elsewhere()` to find projects with unclaimed, unblocked,
	non-pinned ready-for-agent tickets, then checks if each has a profile."""
	if snapshot is None:
		import ticket_agents
		repos = repos or ticket_agents.board_repos()
		if not repos:
			return []
		gh = gh or ticket_agents._gh
		snapshot = ticket_agents.collect(repos, gh=gh)

	import ticket_agents
	import project_profile

	ready = ticket_agents.ready_elsewhere(snapshot)  # {repo: count}
	results = []
	for repo, count in sorted(ready.items()):
		profile = project_profile.load_profile(repo, directory=profiles_dir)
		if profile is not None:
			continue  # profile exists, nothing to report

		cid = f"profile:missing:{repo}"
		label = repo
		detail = f"{count} ready-for-agent ticket(s) waiting to dispatch; no execution profile in config/projects/ — pipeline will not attempt these tickets until the profile is created and dispatch is switched on"
		results.append(_result(cid, label, "red", detail, value=count))

	return results


# ── parallel dispatch: keeping up with the queue ───────────────────────────

_GUARD_MARKERS = ("disk ", "GitHub request budget", "circuit breaker tripped", "lacks tools")


def _classify_stall_reason(refusals: list[str]) -> str:
	"""Classify why a ticket cannot be dispatched based on refusal reasons from the guards."""
	if any(any(m in r for m in _GUARD_MARKERS) for r in refusals):
		return "guard refusal"
	if not refusals or any(" is full:" in r for r in refusals):
		return "no suitable machine"
	return "nothing eligible"


def evaluate_parallel_dispatch(settings: dict, pools: dict[str, list], inflight: dict[str, int],
                               local_base: int, select_for_profile) -> tuple[str, str]:
	"""(severity, detail) for the parallel dispatch queue. Evaluation order:
	1. Parallel dispatch is off -> green
	2. All slots are in use -> green
	3. Nothing waiting -> green
	4. Repos at their per-project limit -> yellow
	5. No suitable machine available -> yellow
	6. Ready ticket and idle slot -> green
	Pools maps repo -> list of ready tickets. Inflight maps repo -> count of running tickets.
	select_for_profile(profile, settings, taken, local_base, refusals) -> machine or None."""
	cid, label = "dispatch:parallel", "Parallel dispatch keeping up"

	if not settings.get("parallel"):
		return "green", "parallel dispatch is off"

	total_inflight = sum(inflight.values())
	max_total = settings.get("max_total", 2)
	if total_inflight >= max_total:
		return "green", f"{total_inflight} of {max_total} slots in use"

	if not any(pools.values()):
		return "green", "nothing waiting"

	waiting_repos = sorted([r for r in pools if pools[r]])
	max_per_project = settings.get("max_per_project", 1)

	at_limit = []
	eligible = []
	for repo in waiting_repos:
		if inflight.get(repo, 0) >= max_per_project:
			at_limit.append(repo)
		else:
			eligible.append(repo)

	if at_limit and not eligible:
		detail = "project at its limit: " + "; ".join(f"{r} ({inflight[r]} of {max_per_project})" for r in at_limit)
		return "yellow", detail

	if not eligible:
		return "green", "idle slot and ready ticket, awaiting the next scan"

	for repo in eligible:
		profile = {"machines": []}
		try:
			import project_profile
			prof = project_profile.load_profile(repo)
			if prof:
				profile = prof
		except Exception:  # noqa: BLE001
			pass

		refusals = []
		machine = select_for_profile(profile, settings, taken={}, local_base=local_base, refusals=refusals)
		if machine is not None:
			return "green", "idle slot and ready ticket, awaiting the next scan"

		reason = _classify_stall_reason(refusals)
		return "yellow", reason

	return "green", "idle slot and ready ticket, awaiting the next scan"


def check_parallel_dispatch() -> dict:
	"""Check if parallel dispatch is keeping up with the queue."""
	cid, label = "dispatch:parallel", "Parallel dispatch keeping up"

	import dispatch_concurrency
	import project_profile as pp

	settings = dispatch_concurrency.load()
	if not settings.get("parallel"):
		return _result(cid, label, "green", "parallel dispatch is off")

	import ticket_pipeline as tp
	import failure_breaker

	repos = [tp.REPO, *pp.dispatchable_repos()]
	breaker_trips = failure_breaker.tripped()
	repos = [r for r in repos if r not in {t.get("project", tp.REPO) for t in breaker_trips}]

	pools = {r: tp._unclaimed_ready_tickets(repo=r) for r in repos}
	inflight = tp._inflight_by_repo(repos)
	local_base = tp._local_slots_used()

	def select_for_profile_impl(profile, s, t, l, rf):
		return tp._select_for_profile(profile if profile else {"machines": list(tp.MARVIN_MACHINES)},
		                               s, t, l, rf)

	severity, detail = evaluate_parallel_dispatch(settings, pools, inflight, local_base, select_for_profile_impl)
	return _result(cid, label, severity, detail)


TRIGGER_MISS_LOG = Path.home() / ".claude" / "logs" / "trigger-misses.jsonl"
TRIGGER_MISS_WINDOW_HOURS = 24


def check_trigger_coverage(log_path: Path | None = None, now: datetime | None = None) -> dict:
    """Yellow when the dashboard's slow backstop poll found changes no trigger announced
    (logged by the app's reconciler): a place state changes that has no trigger yet."""
    cid, label = "triggers:missed", "Dashboard triggers cover every change"
    log_path = log_path or TRIGGER_MISS_LOG
    now = now or _now()
    cutoff = now - timedelta(hours=TRIGGER_MISS_WINDOW_HOURS)
    misses = []
    try:
        lines = log_path.read_text().splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            m = json.loads(line)
            if datetime.fromisoformat(m["at"]) >= cutoff:
                misses.append(m)
        except (ValueError, KeyError, TypeError):
            continue
    if not misses:
        return _result(cid, label, "green", f"no unannounced changes in {TRIGGER_MISS_WINDOW_HOURS}h")
    where = ", ".join(sorted({f"{m['topic']}:{m['key']}" for m in misses}))
    return _result(cid, label, "yellow", f"{len(misses)} change(s) found by polling that no trigger announced ({where})", value=len(misses))


# ── sync / parity health (both machines, measured in time) ───────────────

# Drift is normal for a few minutes between sync cycles, so staleness is judged
# by the AGE of the oldest commit a machine is missing (or hasn't pushed), not
# by a raw commit count.
SYNC_YELLOW_AFTER_HOURS = 2
SYNC_RED_AFTER_HOURS = 24

_REPO_STATE_BODY = r'''
cd "$HOME/$REPO_REL" 2>/dev/null || { echo "fetch_ok=0"; echo "head="; exit 0; }
git fetch -q origin >/dev/null 2>&1 && echo "fetch_ok=1" || echo "fetch_ok=0"
echo "head=$(git rev-parse --short HEAD 2>/dev/null)"
echo "stashes=$(git stash list 2>/dev/null | wc -l | tr -d ' ')"
echo "conflicts=$(git status --porcelain 2>/dev/null | grep -cE '^(UU|AA|DD) ')"
echo "behind=$(git rev-list --count HEAD..origin/main 2>/dev/null)"
echo "behind_oldest_ts=$(git log --format=%ct HEAD..origin/main 2>/dev/null | tail -1)"
echo "ahead=$(git rev-list --count origin/main..HEAD 2>/dev/null)"
echo "ahead_oldest_ts=$(git log --format=%ct origin/main..HEAD 2>/dev/null | tail -1)"
'''


def repo_state_script(rel_path: str) -> str:
    """The one script that reads a repo's sync state. Run as-is locally or piped
    to `ssh host bash -s`, so both machines are judged by identical logic."""
    return f"REPO_REL={shlex.quote(rel_path)}\n" + _REPO_STATE_BODY


def parse_repo_state(text: str) -> dict:
    raw = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    def num(key):
        v = raw.get(key, "").strip()
        return int(v) if v.isdigit() else None

    return {
        "head": raw.get("head", "").strip(),
        "stashes": num("stashes") or 0,
        "conflicts": num("conflicts") or 0,
        "fetch_ok": raw.get("fetch_ok", "0").strip() == "1",
        "behind": num("behind") or 0,
        "behind_oldest_ts": num("behind_oldest_ts"),
        "ahead": num("ahead") or 0,
        "ahead_oldest_ts": num("ahead_oldest_ts"),
    }


_SEV_RANK = {"green": 0, "yellow": 1, "red": 2}


def evaluate_repo_sync(state: dict, now: datetime) -> tuple[str, str, int | None]:
    """(severity, detail, value) for one repo on one machine. Reports the worst
    condition found; a failed fetch is yellow, never silently green."""
    findings: list[tuple[str, str]] = []

    def age_finding(count, oldest_ts, noun):
        if not count or oldest_ts is None:
            return
        hours = (now - datetime.fromtimestamp(oldest_ts, tz=timezone.utc)).total_seconds() / 3600
        sev = "red" if hours >= SYNC_RED_AFTER_HOURS else "yellow" if hours >= SYNC_YELLOW_AFTER_HOURS else "green"
        if sev != "green":
            findings.append((sev, f"{count} commit(s) {noun}, oldest {hours:.0f}h ago"))

    if state["conflicts"]:
        findings.append(("red", "unresolved merge conflict in working tree"))
    if state["stashes"]:
        findings.append(("yellow", f"{state['stashes']} stash(es) present -- code-sync refuses to run until resolved; blocks sync"))
    if not state["fetch_ok"]:
        findings.append(("yellow", "git fetch failed -- cannot verify convergence"))
    age_finding(state["behind"], state["behind_oldest_ts"], "behind origin")
    age_finding(state["ahead"], state["ahead_oldest_ts"], "not yet pushed")

    if not findings:
        return "green", f"converged with origin ({state['head'] or '?'}), clean", state["stashes"]
    worst = max(findings, key=lambda f: _SEV_RANK[f[0]])[0]
    return worst, "; ".join(d for _, d in findings), state["stashes"] or None


def _run_repo_state(target: str | None, rel_path: str) -> str:
    """target None = this machine, else an ssh host."""
    script = repo_state_script(rel_path)
    cmd = ["bash", "-s"] if target is None else ["ssh", *SSH_OPTS, target, "bash -s"]
    proc = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=60)
    return proc.stdout


def check_repo_sync_everywhere(reachability: dict[str, str], runner=_run_repo_state) -> list[dict]:
    """Sync health of every synced repo on this machine AND every registered
    remote device. `reachability` maps machine:<id> -> severity from the
    reachability check: an asleep device is reported asleep (neutral), any
    other unreachable device is yellow ('cannot verify'), never skipped."""
    results = []
    me = machine_profile.registry_id()
    devices = [(me, None, "local")] + [
        (dev, info.get("tailscale_hostname"), reachability.get(f"machine:{dev}", "yellow"))
        for dev, info in machine_profile.remote_devices().items()
    ]
    for display_name, rel in SYNCED_REPOS.items():
        for dev, host, reach in devices:
            cid = f"repo:sync:{display_name}@{dev}"
            label = f"{display_name} sync -- {dev}"
            if reach == "asleep":
                results.append(_result(cid, label, "asleep", "cannot check while the machine is asleep"))
                continue
            if reach not in ("local", "green"):
                results.append(_result(cid, label, "yellow", f"machine unreachable ({reach}) -- sync state unverifiable"))
                continue
            try:
                state = parse_repo_state(runner(host, rel))
            except Exception as exc:  # ssh/git failure: surface it, don't skip silently
                results.append(_result(cid, label, "yellow", f"could not read sync state: {str(exc)[:120]}"))
                continue
            sev, detail, value = evaluate_repo_sync(state, _now())
            results.append(_result(cid, label, sev, detail, value=value))
    return results


# ── per-machine state that silently rots: dashboard build + GitHub credential ──

# One script, run locally or piped over ssh, so every machine is judged by the same
# logic. Absolute paths throughout (launchd/ssh PATHs omit /opt/homebrew/bin).
_MACHINE_STATE_SCRIPT = r'''
APP="/Applications/MARVIN Metrics.app/Contents/Resources/app.asar"
if [ -f "$APP" ]; then echo "app_built_ts=$(stat -f %m "$APP")"; else echo "app_built_ts="; fi
git -C "$HOME/.agents" fetch -q origin >/dev/null 2>&1
echo "dashboard_commit_ts=$(git -C "$HOME/.agents" log -1 --format=%ct origin/main -- dashboard/src dashboard/electron dashboard/index.html dashboard/package.json dashboard/package-lock.json dashboard/electron.vite.config.js dashboard/tailwind.config.js dashboard/postcss.config.js 2>/dev/null)"
TOK="$HOME/.claude/.gh-token"
if [ -s "$TOK" ]; then
  if GH_TOKEN="$(tr -d '[:space:]' < "$TOK")" /opt/homebrew/bin/gh api user --jq .login >/dev/null 2>&1; then echo "gh_token=ok"; else echo "gh_token=invalid"; fi
else echo "gh_token=missing"; fi
# What the dashboard Docs tab does: read a file from GitHub with the shared credential.
if [ -s "$TOK" ] && GH_TOKEN="$(tr -d '[:space:]' < "$TOK")" /opt/homebrew/bin/gh api repos/G-Eskayo/marvin/contents/README.md --jq .name >/dev/null 2>&1; then echo "docs_access=ok"; else echo "docs_access=failed"; fi
if /usr/bin/pgrep -x DesktopLive >/dev/null 2>&1; then echo "desktoplive=running"; else echo "desktoplive=stopped"; fi
# label:pid:last-exit for every MARVIN job (com.giles.* is the tidy agent), so a job failing on a machine health-check doesn't run on is still seen
echo "job_exits=$(/bin/launchctl list 2>/dev/null | /usr/bin/awk '$3 ~ /^com\.(marvin|giles)\./ {printf "%s:%s:%s,", $3, $1, $2}')"
echo "jobs=$(/bin/launchctl list 2>/dev/null | /usr/bin/awk '{print $3}' | /usr/bin/grep '^com\.marvin\.' | /usr/bin/sed 's/^com\.marvin\.//' | /usr/bin/sort | /usr/bin/tr '\n' ',')"
TREE="$HOME/.agents/brain-map/tree-data.json"
if [ -f "$TREE" ]; then echo "brain_data_ts=$(stat -f %m "$TREE")"; else echo "brain_data_ts="; fi
/bin/df -k "$HOME" | /usr/bin/awk 'NR==2 {print "disk_total_kb=" $2; print "disk_free_kb=" $4}'
WT="$HOME/.agents-pipeline-worktrees"
if [ -d "$WT" ]; then echo "worktrees_kb=$(/usr/bin/du -sk "$WT" 2>/dev/null | /usr/bin/cut -f1)"; echo "worktrees_n=$(/bin/ls -1 "$WT" | /usr/bin/wc -l | /usr/bin/tr -d ' ')"; fi
LEDGER="$HOME/.claude/logs/disk-ledger.jsonl"
if [ -f "$LEDGER" ]; then echo "disk_ledger=$(tail -14 "$LEDGER" | /usr/bin/tr '\n' '|')"; fi
'''


# Declared deployment steps (ADR 0033 acceptance #3): real incidents where plists were added but the
# install script never ran. Check that each declared plist is installed and has produced at least one run.
DECLARED_DEPLOY_STEPS = {
    "snapshot-deploy": {"ticket": 188, "doc": "docs/adr/0050-snapshot-deploy.md",
                         "plists": ["com.marvin.snapshot-deploy-nightly.plist", "com.marvin.snapshot-deploy-reactive.plist"],
                         "job_events_name": "snapshot-deploy"},
    "dashboard-rebuild": {"ticket": None, "doc": "lib/dashboard_rebuild.py",
                           "plists": [], "job_events_name": "dashboard-rebuild"},
}


def check_deploy_steps() -> list[dict]:
    """Red if any declared plist is missing from ~/Library/LaunchAgents.
    Red if installed but ~/.claude/logs/jobs/{job_events_name}.json has never been written.
    Cross-machine: local + each reachable remote device."""
    results = []
    me = machine_profile.registry_id()

    # Collect plist + job-events state from this machine + each remote device.
    devices = [(me, None)] + [
        (dev, info.get("tailscale_hostname"))
        for dev, info in machine_profile.remote_devices().items()
    ]

    for dev, host in devices:
        for name, spec in DECLARED_DEPLOY_STEPS.items():
            plists = spec.get("plists", [])
            job_events_name = spec.get("job_events_name", name)

            cid = f"deploy:missing:{dev}:{name}"
            label = f"Deployment: {dev} {name}"

            # Check if plists are installed (locally only).
            if dev == me and plists:
                missing = [p for p in plists if not (LAUNCHAGENTS_DIR / p).exists()]
                if missing:
                    results.append(_result(cid, label, "red",
                                          f"plist(s) not installed: {', '.join(missing)} — run brain-map/scripts/install-snapshot-jobs.sh"))
                    continue
            elif host and plists:
                # Remote check: stat each plist on the remote machine via SSH script.
                script = "; ".join([f"test -f \"$HOME/Library/LaunchAgents/{p}\" && echo 'ok' || echo 'missing'" for p in plists])
                cmd = ["ssh", *SSH_OPTS, host, "bash -s"]
                proc = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=10)
                missing = [p for p, line in zip(plists, proc.stdout.splitlines()) if "missing" in line]
                if missing:
                    results.append(_result(cid, label, "red",
                                          f"plist(s) not installed on {dev}: {', '.join(missing)} — run brain-map/scripts/install-snapshot-jobs.sh"))
                    continue

            # Check if the job has ever run (job_events file exists).
            job_events_file = HOME / ".claude" / "logs" / "jobs" / f"{job_events_name}.json"
            if dev == me:
                if not job_events_file.exists():
                    results.append(_result(cid, label, "red",
                                          f"installed but has never actually run — job_events file {job_events_file} does not exist"))
                    continue
                results.append(_result(cid, label, "green", f"installed and has run"))
            else:
                # Remote check: test if job_events file exists.
                script = f"test -f \"$HOME/.claude/logs/jobs/{job_events_name}.json\" && echo 'exists' || echo 'missing'"
                cmd = ["ssh", *SSH_OPTS, host, "bash -s"]
                proc = subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=10)
                if "missing" in proc.stdout:
                    results.append(_result(cid, label, "red",
                                          f"installed but has never actually run on {dev}"))
                else:
                    results.append(_result(cid, label, "green", f"installed and has run on {dev}"))

    return results


# Which machine is meant to run each com.marvin.* launchd job. "both" = both machines, "mini" = the primary automation
# host only (ADR 0032, 0033), "laptop" = only where Gil sits. Edit here when a job is deliberately moved; a job that
# is not listed is reported as unplaced so a new job cannot silently run on only one machine.
JOB_PLACEMENT = {
    "code-sync-push": "both", "cross-machine-merge": "both", "daily-digest": "both", "research-colony": "both",
    "desktoplive": "both", "dashboard-webhook": "both",  # webhook on both until #112 (ADR 0032)
    "ticket-pipeline": "both",  # mini scans; the laptop's copy is a standby that scans only if the mini goes quiet (scanner_role.py)
    "architecture-review": "mini", "auto-fix": "mini", "cron-health": "mini", "health-check": "mini",
    "process-quarantine-reviews": "mini", "verify-digest-fix": "mini",
    "usage-scan": "both",  # hourly: each machine scans its own transcripts for the Metrics tab (lib/usage_report.py)
    "cleanup-sweep": "both",  # daily: each machine sweeps its own pipeline worktrees (lib/cleanup_sweep.py)
    "dashboard-launch": "laptop",
    # the website map (#189): rebuilt nightly and after MARVIN changes on the mini, where the dev site runs; the nightly
    # job also publishes it to production (ADR 0057), so it must never run on the laptop
    "snapshot-deploy-nightly": "mini", "snapshot-deploy-reactive": "mini",
}


def evaluate_job_placement(jobs: list[str], role: str) -> tuple[str, str]:
    """role: "mini" or "laptop". (severity, detail) comparing the loaded jobs with JOB_PLACEMENT."""
    loaded = set(jobs)
    missing = sorted(j for j, where in JOB_PLACEMENT.items() if where in ("both", role) and j not in loaded)
    extra = sorted(j for j in loaded if JOB_PLACEMENT.get(j) not in (None, "both", role))
    unplaced = sorted(j for j in loaded if j not in JOB_PLACEMENT)
    parts = []
    if missing:
        parts.append("missing: " + ", ".join(missing))
    if extra:
        parts.append("running here but meant for the other machine: " + ", ".join(extra))
    if unplaced:
        parts.append("not in the placement table: " + ", ".join(unplaced))
    if not parts:
        return "green", f"all {len([j for j, w in JOB_PLACEMENT.items() if w in ('both', role)])} jobs meant for this machine are loaded, none stray"
    return "yellow", "; ".join(parts)


def parse_machine_state(text: str) -> dict:
    raw = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)

    def num(key):
        v = raw.get(key, "").strip()
        return int(v) if v.isdigit() else None

    # Parse disk-ledger entries (pipe-separated JSON lines)
    disk_ledger = []
    ledger_raw = raw.get("disk_ledger", "").strip()
    if ledger_raw:
        for entry_str in ledger_raw.split("|"):
            if entry_str.strip():
                try:
                    disk_ledger.append(json.loads(entry_str))
                except (json.JSONDecodeError, ValueError):
                    pass

    return {"app_built_ts": num("app_built_ts"), "dashboard_commit_ts": num("dashboard_commit_ts"),
            "gh_token": raw.get("gh_token", "").strip(), "docs_access": raw.get("docs_access", "").strip(),
            "desktoplive": raw.get("desktoplive", "").strip(), "brain_data_ts": num("brain_data_ts"),
            "disk_free_kb": num("disk_free_kb"), "disk_total_kb": num("disk_total_kb"),
            "worktrees_kb": num("worktrees_kb"), "worktrees_n": num("worktrees_n"),
            "disk_ledger": disk_ledger,
            "jobs": [j for j in raw.get("jobs", "").strip().split(",") if j],
            "job_exits": _parse_job_exits(raw.get("job_exits", ""))}


def _parse_job_exits(text: str) -> list[tuple[str, int | None, int]]:
    """'label:pid:status,...' from `launchctl list` -> [(label, pid or None, last exit status)]."""
    out = []
    for item in text.strip().split(","):
        parts = item.rsplit(":", 2)
        if len(parts) != 3:
            continue
        label, pid, status = parts
        try:
            out.append((label, int(pid) if pid.isdigit() else None, int(status)))
        except ValueError:
            continue
    return out


# Free-space thresholds (share of the disk). Found 2026-10-06: the mac-mini at 6% free; below ~10% macOS
# evicts iCloud files aggressively, and background jobs then block reading them.
DISK_YELLOW_BELOW_PCT = 20
DISK_RED_BELOW_PCT = 10


def forecast_days_to_critical(ledger: list[dict], critical_kb: int = 15 * 1048576) -> tuple[str, float, str] | None:
    """Linear-regress free KB over ledger entries, forecast days until critical.

    Returns (severity, days_forecast, detail) or None if insufficient history.
    Green ≥30d; yellow <30d with expansion warning; red <7d.
    """
    if not ledger or len(ledger) < 2:
        return None

    import statistics

    # Extract (timestamp_days_since_epoch, free_kb) tuples
    points = []
    for entry in sorted(ledger, key=lambda e: e.get("date", "")):
        try:
            free_kb = entry.get("free_kb")
            if free_kb is not None:
                points.append(free_kb)
        except (KeyError, TypeError):
            pass

    if len(points) < 2:
        return None

    # Linear regression: least-squares fit of free_kb over day index
    n = len(points)
    x = list(range(n))  # day index 0..n-1
    y = points

    x_mean = statistics.mean(x)
    y_mean = statistics.mean(y)

    numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
    denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

    if denominator == 0:
        return None

    slope = numerator / denominator
    intercept = y_mean - slope * x_mean

    # If slope >= 0, we're gaining or flat -- no forecast needed
    if slope >= 0:
        return ("green", float("inf"), f"{points[-1] / 1048576:.0f} GiB free (stable or growing)")

    # Forecast: how many days from today (index n-1) until free_kb reaches critical?
    # free_kb = slope * day_index + intercept
    # critical_kb = slope * day_index_critical + intercept
    # day_index_critical = (critical_kb - intercept) / slope
    # days_forward = day_index_critical - (n - 1)

    current_free = points[-1]
    if current_free <= critical_kb:
        days_forecast = 0.0  # Already critical
    else:
        day_index_critical = (critical_kb - intercept) / slope
        days_forecast = max(0.0, day_index_critical - (n - 1))

    sev = "red" if days_forecast < 7 else "yellow" if days_forecast < 30 else "green"
    detail = f"{days_forecast:.0f}d forecast to 15 GiB threshold"
    if sev != "green":
        detail += " -- see docs/plans/storage-and-distribution-2026-10-06.md item E2 (external SSD)"

    return (sev, days_forecast, detail)


def evaluate_machine_state(state: dict, now: datetime) -> list[tuple[str, str, str]]:
    """[(check_key, severity, detail)] for one machine. The dashboard app is a native
    build that only rebuilds where a merge happened, so it silently drifts behind the
    code (found 2026-10-02: a month behind, routing Approve to the wrong webhook);
    and a GitHub credential can expire without anything noticing."""
    out = []
    built, newest = state["app_built_ts"], state["dashboard_commit_ts"]
    if built is None:
        out.append(("dashboard:build", "yellow", "dashboard app is not installed"))
    elif newest is None or built >= newest:
        out.append(("dashboard:build", "green", "installed app is at least as new as the latest dashboard change"))
    else:
        behind_h = (newest - built) / 3600
        age = (now - datetime.fromtimestamp(built, tz=timezone.utc)).total_seconds() / 86400
        sev = "red" if behind_h >= SYNC_RED_AFTER_HOURS else "yellow" if behind_h >= SYNC_YELLOW_AFTER_HOURS else "green"
        detail = f"installed app built {age:.0f}d ago, {behind_h:.0f}h older than the latest dashboard change -- run dashboard/scripts/rebuild_and_install.sh"
        out.append(("dashboard:build", sev, detail if sev != "green" else "installed app is current"))
    tok = state["gh_token"]
    if tok == "ok":
        out.append(("auth:gh", "green", "shared GitHub token (~/.claude/.gh-token) authenticates"))
    elif tok == "invalid":
        out.append(("auth:gh", "red", "shared GitHub token is INVALID -- dashboard merges and ticket-pipeline gh/git calls on this machine will fail"))
    else:
        out.append(("auth:gh", "yellow", "no ~/.claude/.gh-token on this machine"))
    docs = state.get("docs_access")
    if docs == "ok":
        out.append(("docs:access", "green", "the Docs tab's GitHub read works (shared credential)"))
    elif docs:
        out.append(("docs:access", "red", "cannot read repo files from GitHub -- the dashboard Docs tab will be empty on this machine"))
    live = state.get("desktoplive")
    if live == "running":
        out.append(("desktoplive:running", "green", "the desktop brain-map background is running"))
    elif live:
        out.append(("desktoplive:running", "yellow", "the desktop brain-map background (DesktopLive) is not running"))
    ts = state.get("brain_data_ts")
    if ts is not None:
        days = (now - datetime.fromtimestamp(ts, tz=timezone.utc)).total_seconds() / 86400
        out.append(("brainmap:data", "yellow" if days >= 7 else "green",
                    f"brain-map data last regenerated {days:.0f}d ago" + (" -- it is rebuilt by use on this machine, so an idle machine shows an old picture" if days >= 7 else "")))
    free, total = state.get("disk_free_kb"), state.get("disk_total_kb")
    if free is not None and total:
        pct = 100 * free / total
        sev = "red" if pct < DISK_RED_BELOW_PCT else "yellow" if pct < DISK_YELLOW_BELOW_PCT else "green"
        detail = f"{free / 1048576:.0f} GiB free of {total / 1048576:.0f} ({pct:.0f}%)"
        if state.get("worktrees_kb") is not None:
            detail += f"; {state.get('worktrees_n') or 0} pipeline worktrees use {state['worktrees_kb'] / 1048576:.1f} GiB"
        if sev != "green":
            detail += " -- check ~/.claude/logs/mr-pipeline-sweep.md and docs/plans/storage-and-distribution-2026-10-06.md"
        out.append(("disk:space", sev, detail))
    ledger = state.get("disk_ledger")
    if ledger:
        forecast = forecast_days_to_critical(ledger, critical_kb=15 * 1048576)
        if forecast:
            sev, days, detail = forecast
            out.append(("disk:headroom", sev, detail))
    if state.get("job_exits"):
        # A running job's status is its previous instance's (a KeepAlive restart shows -15), so only idle jobs count.
        failed = [(label, status) for label, pid, status in state["job_exits"] if pid is None and status != 0]
        if failed:
            out.append(("jobs:exit", "red", "last run failed: " + ", ".join(f"{label} (exit {status})" for label, status in failed)
                        + " -- read the job's log on this machine (tidy-agent: ~/.claude/organize/agent.err.log)"))
        else:
            out.append(("jobs:exit", "green", f"all {len(state['job_exits'])} scheduled jobs last exited cleanly or are running"))
    if state.get("jobs"):
        role = "laptop" if "macbook" in state.get("_device", "") else "mini"
        sev, detail = evaluate_job_placement(state["jobs"], role)
        out.append(("jobs:placement", sev, detail))
    return out


def _run_machine_state(target: str | None, script: str = _MACHINE_STATE_SCRIPT) -> str:
    cmd = ["bash", "-s"] if target is None else ["ssh", *SSH_OPTS, target, "bash -s"]
    return subprocess.run(cmd, input=script, capture_output=True, text=True, timeout=60).stdout


def check_machine_state_everywhere(reachability: dict[str, str], runner=_run_machine_state) -> list[dict]:
    results = []
    me = machine_profile.registry_id()
    devices = [(me, None, "local")] + [
        (dev, info.get("tailscale_hostname"), reachability.get(f"machine:{dev}", "yellow"))
        for dev, info in machine_profile.remote_devices().items()
    ]
    labels = {"dashboard:build": "Dashboard app build", "auth:gh": "GitHub credential", "docs:access": "Docs tab GitHub access",
              "desktoplive:running": "Desktop brain-map background", "brainmap:data": "Brain-map data freshness", "jobs:placement": "Scheduled jobs vs. placement",
              "disk:space": "Disk space", "disk:headroom": "Disk headroom forecast", "jobs:exit": "Scheduled jobs' last run"}
    for dev, host, reach in devices:
        if reach == "asleep":
            for key, label in labels.items():
                results.append(_result(f"{key}@{dev}", f"{label} -- {dev}", "asleep", "cannot check while the machine is asleep"))
            continue
        if reach not in ("local", "green"):
            for key, label in labels.items():
                results.append(_result(f"{key}@{dev}", f"{label} -- {dev}", "yellow", f"machine unreachable ({reach}) -- unverifiable"))
            continue
        try:
            state = parse_machine_state(runner(host, _MACHINE_STATE_SCRIPT))
        except Exception as exc:
            for key, label in labels.items():
                results.append(_result(f"{key}@{dev}", f"{label} -- {dev}", "yellow", f"could not read machine state: {str(exc)[:100]}"))
            continue
        state["_device"] = dev
        for key, sev, detail in evaluate_machine_state(state, _now()):
            results.append(_result(f"{key}@{dev}", f"{labels[key]} -- {dev}", sev, detail))
    return results


# ── machine reachability ─────────────────────────────────────────────────

# How long a laptop may be offline on Tailscale and still read as "asleep"
# (lid closed / carried away) rather than a problem worth looking at.
ASLEEP_MAX_HOURS = 72


def _tailscale_peer(host: str) -> dict | None:
    """Tailscale's own view of one peer: {"online": bool, "last_seen": datetime|None},
    or None if Tailscale can't be asked or doesn't know the host. An *online*
    peer reports a zero LastSeen, which is treated as 'no timestamp'."""
    try:
        proc = subprocess.run([TAILSCALE_BIN, "status", "--json"],
                              capture_output=True, text=True, timeout=10, env=TAILSCALE_ENV)
        if proc.returncode != 0:
            return None
        peers = json.loads(proc.stdout).get("Peer") or {}
    except Exception:
        return None
    want = host.lower()
    for peer in peers.values():
        names = {str(peer.get("HostName", "")).lower(),
                 str(peer.get("DNSName", "")).lower().split(".")[0]}
        if want in names:
            raw = peer.get("LastSeen") or ""
            last_seen = None
            if raw and not raw.startswith("0001-"):
                try:
                    last_seen = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    last_seen = None
            return {"online": bool(peer.get("Online")), "last_seen": last_seen}
    return None


def classify_unreachable(kind: str, peer: dict | None, now: datetime) -> tuple[str, str]:
    """Severity for a device we could not reach over ssh. 'red' is reserved for
    "needs your immediate attention", so a normal lid-close must not be red.
    A laptop that Tailscale reports OFFLINE recently is `asleep` (neutral);
    online-but-unreachable is a real fault; an always-on desktop being down is
    red; and when Tailscale can't say, a laptop is `yellow` (unknown), never
    silently asleep. Remotely, sleep and a crash look the same -- this is a
    heuristic keyed on device kind + how long it has been gone."""
    if kind != "laptop":
        return "red", "unreachable (always-on device)"
    if peer is None:
        return "yellow", "unreachable and cannot tell if it is asleep (Tailscale state unavailable)"
    if peer["online"]:
        return "red", "on the network but not answering ssh"
    last = peer["last_seen"]
    if last is None:
        return "asleep", "offline (lid closed or away); last-seen time unknown"
    hours = (now - last).total_seconds() / 3600
    if hours <= ASLEEP_MAX_HOURS:
        return "asleep", f"offline (lid closed or away) for {hours:.0f}h"
    return "yellow", f"offline for {hours / 24:.0f} days -- longer than a normal lid-close"


def overall_severity(severities: list[str]) -> str:
    """`asleep` is neutral: it never raises the overall status above green."""
    return "red" if "red" in severities else "yellow" if "yellow" in severities else "green"


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
                continue
            why = proc.stderr.strip()[:200]
        except subprocess.TimeoutExpired:
            why = "timed out"
        severity, detail = classify_unreachable(info.get("kind", "desktop"), _tailscale_peer(host), _now())
        results.append(_result(cid, label, severity, f"{detail} ({host}: {why})"))
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
    results.append(check_pipeline_breaker())
    results += check_sync_stuck()
    results += check_deploy_steps()
    results.append(check_parallel_dispatch())
    results += check_missing_profiles()
    results.append(check_trigger_coverage())
    results.append(check_catalog_fresh())
    results.append(check_github_budget())
    results.append(check_main_health())
    cron_state = ch._load_state()
    cron_now = datetime.now().astimezone()
    for job in discover_launchd_jobs():
        r = check_cron_job_log(job, cron_state, cron_now)
        if r:
            results.append(r)
    ch._save_state(cron_state)
    for name, rel in SYNCED_REPOS.items():
        results.append(check_repo_integrity(name, rel))
    reach_results = check_machine_reachability()
    results += reach_results
    results += check_repo_sync_everywhere({r["id"]: r["severity"] for r in reach_results})
    results += check_machine_state_everywhere({r["id"]: r["severity"] for r in reach_results})

    cov = coverage(results)
    anomaly = record_anomaly_metrics(results)

    severities = [r["severity"] for r in results]
    overall = overall_severity(severities)

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


import job_events  # noqa: E402  (run log shown in the dashboard's Health tab)


@job_events.reported("health-check", "Health check sweep")
def _cli() -> None:
    out = write_status()

    # Notify on red disk:headroom (once per device per day)
    for result in out.get("checks", []):
        if result.get("id", "").startswith("disk:headroom") and result.get("severity") == "red":
            try:
                import disk_forecast_notify as dfn  # noqa: E402
                device = result["id"].split("@")[1] if "@" in result["id"] else machine_profile.registry_id()
                # Extract days forecast from detail (rough parse: "N days forecast...")
                detail = result.get("detail", "")
                days = 0.0
                if "forecast" in detail:
                    import re
                    match = re.search(r"(\d+\.?\d*)d", detail)
                    if match:
                        days = float(match.group(1))
                dfn.notify_red_headroom(device, days, detail)
            except Exception:
                pass

    if "--json" in sys.argv:
        print(json.dumps(out, indent=2))
    else:
        print(f"overall: {out['overall']}  coverage: {out['coverage']['covered']}/{out['coverage']['total']}")
        for r in out["checks"]:
            print(f"  [{r['severity']:>6}] {r['label']}: {r['detail']}")
        if out["coverage"]["unmonitored_jobs"]:
            print(f"  unmonitored jobs: {', '.join(out['coverage']['unmonitored_jobs'])}")
    job_events.step("Sweep finished", f"overall {out['overall']}, coverage {out['coverage']['covered']}/{out['coverage']['total']}")


if __name__ == "__main__":
    _cli()
