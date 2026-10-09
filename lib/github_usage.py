#!/usr/bin/env python3
"""github_usage.py — this Mac's GitHub use, for the Metrics tab's GitHub section.

Read from the GitHub gate's own logs (bin/gh): every gh call (~/.claude/logs/gh-calls.jsonl) and every reading of
GitHub's allowance (gh-budget.jsonl). Both Macs and every job share one allowance, so this is how to see what spends
it, when it ran low, and what was refused or held back. Not synced (the call log names folders); the dashboard reads
the other Mac's over ssh (lib/usage_report.py).

    github_usage.py     print the summary as JSON
"""
from __future__ import annotations
import json
import socket
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOGS = Path.home() / ".claude" / "logs"
CALLS_PATH = LOGS / "gh-calls.jsonl"
BUDGET_PATH = LOGS / "gh-budget.jsonl"
GROUPS = ("dashboard", "pipeline", "tests", "health", "people", "other")
PIPELINE = ("ticket_pipeline", "ticket-pipeline", "run_ticket", "ticket_queue", "rework_status", "ticket_evidence",
            "ticket_agents", "dispatch", "mr_raiser", "merge", "cleanup", "project_onboard", "code-sync", "code_sync")


def group_of(caller: str) -> str:
    c = (caller or "").lower()
    if "marvin-metrics" in c or "dashboard" in c:
        return "dashboard"
    if "pytest" in c:
        return "tests"
    if "health" in c:
        return "health"
    if any(p in c for p in PIPELINE):
        return "pipeline"
    if c in ("zsh", "bash", "sh", "fish", "shell", "login", "-zsh") or "claude" in c:
        return "people"
    return "other"


def display_name(caller: str) -> str:
    """One name per program: the dashboard app's launchd label carries process ids that change every launch."""
    c = caller or "?"
    if c.startswith("application.") and "marvin-metrics" in c:
        return "MARVIN dashboard app"
    return c.replace("com.marvin.", "") if c.startswith("com.marvin.") else c


def read_jsonl(path: Path) -> list[dict]:
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return []
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


def summarize(calls: list[dict], budget: list[dict], now: datetime, hours: int = 48) -> dict:
    t_now = now.timestamp()
    start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    buckets = {}
    for i in range(hours):
        h = start + timedelta(hours=i)
        buckets[h] = {"hour": h.strftime("%Y-%m-%dT%H:00Z"), "total": 0, "refused": 0, "deferred": 0, "groups": {g: 0 for g in GROUPS}}
    per_caller: dict[str, dict] = defaultdict(lambda: {"calls": 0, "refused": 0, "deferred": 0, "cmds": Counter()})
    for r in calls:
        t = float(r.get("t", 0))
        when = datetime.fromtimestamp(t, timezone.utc).replace(minute=0, second=0, microsecond=0)
        b = buckets.get(when)
        caller = display_name(str(r.get("caller", "?")))
        if b:
            b["total"] += 1
            b["groups"][group_of(caller)] += 1
            b["refused"] += 1 if r.get("refused") else 0
            b["deferred"] += 1 if r.get("deferred") else 0
        if t_now - t <= 86400:
            c = per_caller[caller]
            c["calls"] += 1
            c["refused"] += 1 if r.get("refused") else 0
            c["deferred"] += 1 if r.get("deferred") else 0
            c["cmds"][r.get("cmd") or "(other)"] += 1
    top = sorted(per_caller.items(), key=lambda kv: -kv[1]["calls"])[:10]
    series = sorted((b for b in budget if t_now - float(b.get("at", 0)) <= hours * 3600), key=lambda b: b["at"])
    return {
        "machine": socket.gethostname().split(".")[0],
        "generated_at": now.isoformat(),
        "hours": list(buckets.values()),
        "top": [{"caller": k, "group": group_of(k), "calls": v["calls"], "refused": v["refused"], "deferred": v["deferred"],
                 "commands": [{"cmd": c, "calls": n} for c, n in v["cmds"].most_common(4)]} for k, v in top],
        "budget": [{"at": b["at"], "graphql": b.get("graphql"), "core": b.get("core")} for b in series],
        "latest_budget": series[-1] if series else None,
    }


def main(argv: list[str]) -> int:
    calls = read_jsonl(CALLS_PATH)
    print(json.dumps(summarize(calls, read_jsonl(BUDGET_PATH), datetime.now(timezone.utc))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
