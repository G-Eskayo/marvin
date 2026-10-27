#!/usr/bin/env python3
"""The job catalog: what every MARVIN background job is for (Gil, 2026-10-26; blind-spots note, test D).

Every launchd job declares five things:
    machine   where it runs: "both", "mini" (the primary automation host, ADR 0032), "laptop" (where Gil sits), or
              "none" (switched off on purpose)
    goal      the north star or project goal it serves (GOALS); None means no goal is recorded yet
    reporter  who records its result, ideally the job itself when it happens
    healthy   what passing means for it, so red always comes with a reason
    consumer  who reads its output (Watts check: output nobody consumes fails)
and optionally `review`: why a person should check whether its purpose is met.

The sweep never calls a job irrelevant or says to remove it (Gil, 2026-10-26). "Unused" usually means its purpose
is unmet, not gone. It asks the question; the answer comes from the job's origin (ticket, ADR, plan): either its purpose
is met elsewhere, or it is falling short and needs work to reach it. Gil decides.

health_checks.JOB_PLACEMENT is derived from this table, so placement is never kept in two places.

    job_catalog.py waste     # jobs on this Mac whose purpose needs checking: no goal recorded, no reader, flagged, or not catalogued
"""
from __future__ import annotations

import socket
import subprocess
import sys

import north_stars

MACHINES = ("both", "mini", "laptop", "none")

# docs/north-stars.md, plus the projects whose goals live in their profiles (config/projects/<repo>.json, "goal").
GOALS = {
    **{f"ns{i}": title for i, title in enumerate(north_stars.titles(), 1)},
    "project:marvin": "Work gets done without the owner chasing it, cheaply, without the paid subscription",
    "project:clarity-captions": "Any hard-of-hearing person can rely on Seal Speak",
    "project:portfolio-website-updater": "The portfolio lands interviews",
    "project:paper-dive": "Papers understood fast and turned into findings projects use",
}

JOBS: dict[str, dict] = {
    "code-sync-push": {"machine": "both", "goal": "project:marvin", "reporter": "code_sync.py (sync-log.md)",
                       "healthy": "push and pull succeed within 30 min", "consumer": "the other Macs; Health sync:stuck"},
    "cross-machine-merge": {"machine": "both", "goal": "project:marvin", "reporter": "its launchd log",
                            "healthy": "last run exit 0", "consumer": "the daily digest"},
    "daily-digest": {"machine": "both", "goal": "ns1", "reporter": "its launchd log",
                     "healthy": "a digest written today", "consumer": "the morning brief"},
    "research-colony": {"machine": "both", "goal": "project:paper-dive", "reporter": "its launchd log",
                        "healthy": "a run finished today with at least one source", "consumer": "the daily digest and the brief"},
    "desktoplive": {"machine": "both", "goal": "ns3", "reporter": "Health desktoplive:running",
                    "healthy": "the wallpaper process is running and drawing", "consumer": "the owner's desktop"},
    "dashboard-webhook": {"machine": "both", "goal": "project:marvin", "reporter": "dashboard-webhook.log",
                          "healthy": "port 7878 answers", "consumer": "the dashboard's Approve and the merge gate"},
    "ticket-pipeline": {"machine": "both", "goal": "project:marvin", "reporter": "ticket stages (ticket_stages.py)",
                        "healthy": "a scan in the last 2 h; no breaker tripped", "consumer": "Activity and MR Review"},
    "architecture-review": {"machine": "mini", "goal": "ns1", "reporter": "suggestions.md",
                            "healthy": "last run exit 0", "consumer": "the session-start report (suggestion count)"},
    "auto-fix": {"machine": "mini", "goal": "ns1", "reporter": "its daily PR (auto-fix/<date>), plus auto-fix-log.md",
                 "healthy": "last run exit 0", "consumer": "the owner, via MR Review"},
    "cron-health": {"machine": "mini", "goal": "project:marvin", "reporter": "cron-health log",
                    "healthy": "last run exit 0", "consumer": "Health cron:*",
                    "review": "purpose (nothing breaks silently) is falling short: Health missed a 2-day frozen laptop view too. Reached by the Vitals peer heartbeat (P2); this job folds in then"},
    "health-check": {"machine": "mini", "goal": "project:marvin", "reporter": "health-status.json",
                     "healthy": "a sweep in the last 30 min", "consumer": "Vitals on every machine (once peer push lands)"},
    "process-quarantine-reviews": {"machine": "mini", "goal": "ns1", "reporter": "quarantine.md",
                                   "healthy": "last run exit 0", "consumer": "the session-start report",
                                   "review": "purpose (the owner's reviews teach the safety filter, ADR 0015) is falling short: 0 of 97 reviewed. Reached by a tap-to-review card (approved 2026-10-26)"},
    "verify-digest-fix": {"machine": "mini", "goal": "ns1", "reporter": "its launchd log",
                          "healthy": "last run exit 0", "consumer": None,
                          "review": "a check for one past digest fix; is it still needed?"},
    "usage-scan": {"machine": "both", "goal": "ns1", "reporter": "token-usage.json",
                   "healthy": "a scan in the last 2 h", "consumer": "Vitals and Activity usage"},
    "cleanup-sweep": {"machine": "both", "goal": "ns1", "reporter": "mr-pipeline-sweep.md",
                      "healthy": "last run exit 0; pipeline worktrees under the disk budget", "consumer": "Health disk:*"},
    "machine-resources": {"machine": "both", "goal": "ns1", "reporter": "machine-resources samples",
                          "healthy": "a sample in the last 2 min", "consumer": "the Resources panel"},
    "history-load": {"machine": "mini", "goal": "ns1", "reporter": "history.db load log",
                     "healthy": "a load in the last 15 min", "consumer": "Vitals history, GitHub usage"},
    "seal-beta-ingest": {"machine": "mini", "goal": "project:clarity-captions", "reporter": "its launchd log",
                         "healthy": "last run exit 0", "consumer": "the Seal Speak beta view and tickets"},
    "dashboard-launch": {"machine": "laptop", "goal": "ns3", "reporter": "none needed (opens the app at login)",
                         "healthy": "the dashboard is open after login", "consumer": "the owner"},
    "morning-brief": {"machine": "laptop", "goal": "ns3", "reporter": "the brief file",
                      "healthy": "a brief built today", "consumer": "the owner, each morning"},
    "portfolio-dev-tunnel": {"machine": "laptop", "goal": "project:portfolio-website-updater",
                             "reporter": "its launchd log", "healthy": "the tunnel to the Mini's dev site is up",
                             "consumer": "the portfolio dev site on the laptop"},
    "snapshot-deploy-nightly": {"machine": "mini", "goal": "project:portfolio-website-updater",
                                "reporter": "its launchd log", "healthy": "last run exit 0",
                                "consumer": "the website map (#189)"},
    "snapshot-deploy-reactive": {"machine": "mini", "goal": "project:portfolio-website-updater",
                                 "reporter": "its launchd log", "healthy": "last run exit 0",
                                 "consumer": "the website map (#189)"},
    "open-loops": {"machine": "none", "goal": None, "reporter": None, "healthy": None, "consumer": None,
                   "review": "off until the goal tracker links loops to project goals (approved 2026-10-26)"},
    "tidy-agent": {"label": "com.giles.tidy-agent", "machine": "both", "goal": "ns3",
                   "reporter": "~/.claude/organize/agent.err.log", "healthy": "last run exit 0",
                   "consumer": "the owner's Downloads and Desktop"},
}


def waste(jobs: dict | None = None, loaded: dict | None = None) -> list[dict]:
    """Rows {job, why, review} for every job that serves no goal, has no consumer or is flagged, plus any job loaded on
    a machine (`loaded`: machine -> job names) that isn't catalogued. A switched-off job is listed only for its review
    note. O(jobs + loaded)."""
    jobs = JOBS if jobs is None else jobs
    rows = []
    for name, j in jobs.items():
        if j.get("goal") is None and j.get("machine") != "none":
            rows.append({"job": name, "why": "no goal recorded: what was it built for?", "review": j.get("review")})
        elif j.get("consumer") is None and j.get("machine") != "none":
            rows.append({"job": name, "why": "nobody reads its output: is its purpose met elsewhere, or falling short?", "review": j.get("review")})
        elif j.get("review"):
            rows.append({"job": name, "why": "check its purpose: met elsewhere, or falling short?", "review": j["review"]})
    for machine, names in (loaded or {}).items():
        if not isinstance(names, list):
            continue
        for n in names:
            if isinstance(n, str) and n.strip() and n not in jobs:
                rows.append({"job": n, "why": f"runs on {machine} but isn't in the job catalog", "review": None})
    return rows


def report(rows: list[dict]) -> str:
    if not rows:
        return "Every job has a goal and a reader; no purpose needs checking."
    lines = [f"{len(rows)} job(s) whose purpose needs checking (met elsewhere, or falling short?):"]
    for r in rows:
        lines.append(f"- {r['job']}: {r['why']}" + (f" ({r['review']})" if r.get("review") else ""))
    return "\n".join(lines)


def _loaded_here() -> dict:
    out = subprocess.run(["/bin/launchctl", "list"], capture_output=True, text=True).stdout
    names = []
    for line in out.splitlines():
        label = line.split()[-1] if line.split() else ""
        if label.startswith("com.marvin."):
            names.append(label[len("com.marvin."):])
        elif label.startswith("com.giles."):
            names.append(label[len("com.giles."):])
    return {socket.gethostname().split(".")[0]: names}


def main(argv: list[str]) -> int:
    if argv[:1] == ["waste"]:
        print(report(waste(loaded=_loaded_here())))
        return 0
    print(__doc__.strip().splitlines()[-1].strip())
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
