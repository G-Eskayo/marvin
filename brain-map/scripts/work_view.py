#!/usr/bin/env python3
"""The Work half of the map's Body and Work mock-up (#854, CONTEXT.md "Body and Work").

Work is what MARVIN is working on: one node per monitored system or project (the project catalog's active and recent
projects, MARVIN included), each holding its **workers**:

- chat helpers and spawned agents, from their run logs (lib/chat_helpers.py, ~/.claude/logs/jobs/helper-*.json). A
  helper a chat started is a chat helper; one with no chat behind it (a pipeline run's own Agent call) is a spawned
  agent.
- pipeline builders, one per ticket, from the ticket stages (lib/ticket_stages.py).
- the scheduled jobs that serve it, from each job's declared goal (lib/job_catalog.py): `project:<id>` is that
  project, a north star (`ns<N>`) is MARVIN's own, and no goal is Unassigned. A job loaded on this Mac that the
  catalog doesn't know is Unassigned too.

A worker whose project can't be found goes under **Unassigned**, never dropped. Gil, 2026-10-30: nothing fades. A
worker shows only while it runs, and one that finished cleanly leaves at once. One that died (failed, crashed, or
killed with no stop) stays, red, until a retry passes (its ticket's or job's next run) or someone dismisses it in the
page's tray. Its `ended` names that one failure, so dismissing it never hides a later one. Jobs follow the same rule:
idle and switched-off jobs aren't drawn.

A helper's project: the catalog project whose local folder holds its working folder (longest wins), else the repo
that folder pushes to (a worktree in a temp folder), else the repo most of the tickets in its report name.

    work_view.py [--out PATH]     write work.json beside the map (the page reads it on its activity poll)

Standard library only (it is started from hooks, see lib/work_nudge.py). O(helpers + tickets + jobs + projects);
one `git remote` call per distinct helper folder no catalog folder holds.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import plistlib
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LIB = HERE.parents[1] / "lib"
sys.path.insert(0, str(LIB))
import chat_helpers  # noqa: E402  (state_of: the one rule for a helper killed mid-run)

UNASSIGNED = "Unassigned"
HALF_ID, HALF_NAME = "half:work", "Work"
BUILDER_DEAD_S = 30 * 60  # a builder with no stage event this long and no end died (matches job_events' crash rule)
JOB_CRASHED_S = 30 * 60   # dashboard/electron/main/jobs.js CRASHED_AFTER_MS
MONITORED = ("active", "recent")
OUT_PATH = HERE.parent / "work.json"
_REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$")


def _ts(value) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


# ── projects ────────────────────────────────────────────────────────────────

def monitored_projects(catalog: list[dict]) -> list[dict]:
    """The catalog's active and recent projects, MARVIN included, in catalog order."""
    out = []
    for p in catalog or []:
        if isinstance(p, dict) and p.get("id") and p.get("status") in MONITORED:
            out.append({"id": p["id"], "name": p.get("name") or p["id"], "repo": p.get("repo") or "",
                        "paths": [str(x) for x in p.get("localPaths") or [] if isinstance(x, str)],
                        "desc": p.get("description") or ""})
    return out


def project_for_path(folder: str, projects: list[dict]) -> str | None:
    best, best_len = None, -1
    folder = os.path.normpath(folder) if folder else ""
    for p in projects:
        for root in p.get("paths", []):
            root = os.path.normpath(root)
            if (folder == root or folder.startswith(root + os.sep)) and len(root) > best_len:
                best, best_len = p["id"], len(root)
    return best


def project_for_repo(repo: str | None, projects: list[dict]) -> str | None:
    if not repo:
        return None
    want = repo.lower()
    return next((p["id"] for p in projects if (p.get("repo") or "").lower() == want), None)


def git_remote(folder: str) -> str | None:
    """owner/name of the GitHub repo a folder pushes to, or None (not a repo, gone, not GitHub)."""
    if not folder or not os.path.isdir(folder):
        return None
    try:
        url = subprocess.run(["git", "-C", folder, "remote", "get-url", "origin"], capture_output=True, text=True,
                             timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = _REMOTE.search(url)
    return m.group(1) if m else None


# ── workers ─────────────────────────────────────────────────────────────────

def helper_workers(docs: list[dict], projects: list[dict], now: float, remote_of=None) -> list[dict]:
    """One worker per helper that is running or died. A clean finish leaves at once."""
    remote_of = remote_of or git_remote
    remotes: dict[str, str | None] = {}
    out = []
    for doc in docs or []:
        h = doc.get("helper") if isinstance(doc, dict) else None
        runs = doc.get("runs") if isinstance(doc, dict) else None
        if not isinstance(h, dict) or not isinstance(runs, list) or not runs or not isinstance(runs[-1], dict):
            continue
        run, aid = runs[-1], h.get("agent_id")
        if not isinstance(aid, str) or not aid:
            continue
        state = chat_helpers.state_of(doc, now)
        if state == "running":
            end = None
        elif state == "stale":
            started = _ts(run.get("started_at")) or 0.0
            end, state = started + chat_helpers.STALE_S, "failed"
        elif state == "passed":
            continue
        else:
            end, state = _ts(run.get("finished_at")) or _ts(run.get("started_at")), "failed"
        cwd = h.get("cwd") if isinstance(h.get("cwd"), str) else ""
        pid = project_for_path(cwd, projects) if cwd else None
        if pid is None and cwd:
            if cwd not in remotes:
                remotes[cwd] = remote_of(cwd)
            pid = project_for_repo(remotes[cwd], projects)
        if pid is None:
            repos = Counter(l.get("repo") for l in h.get("links") or [] if isinstance(l, dict) and l.get("repo"))
            for repo, _n in repos.most_common():
                pid = project_for_repo(repo, projects)
                if pid:
                    break
        kind = "helper" if h.get("chat") else "agent"
        out.append({"id": f"helper:{aid}", "name": str(doc.get("label") or aid)[:80], "kind": kind, "state": state,
                    "project": pid, "agent": aid, "ended": end,
                    "desc": ("Chat helper" if kind == "helper" else "Spawned agent") + f": {state}"})
    return out


def builder_workers(stages: dict, projects: list[dict], now: float) -> list[dict]:
    """One worker per ticket whose pipeline run is going, or whose last run died. `stages`: (repo, n) -> events."""
    out = []
    for key, events in (stages or {}).items():
        try:
            repo, number = key
        except (TypeError, ValueError):
            continue
        events = [e for e in events or [] if isinstance(e, dict) and _ts(e.get("timestamp")) is not None]
        if not events:
            continue
        last = events[-1]
        at = _ts(last["timestamp"])
        if last.get("status") == "failed":
            state, end = "failed", at
        elif last.get("stage") == "done":
            continue
        elif now - at > BUILDER_DEAD_S:
            state, end = "failed", at + BUILDER_DEAD_S
        else:
            state, end = "running", None
        title = next((e.get("title") for e in events if e.get("title")), None)
        out.append({"id": f"builder:{repo}#{number}", "name": f"#{number}" + (f" {title}" if title else ""),
                    "kind": "builder", "state": state, "project": project_for_repo(repo, projects), "ended": end,
                    "desc": f"Pipeline builder: {last.get('stage')} {last.get('status')}"})
    return out


def _job_state(log: dict | None, now: float) -> tuple[str, float | None]:
    """(running | failed | idle, when the failure happened)."""
    runs = [r for r in (log or {}).get("runs") or [] if isinstance(r, dict) and r.get("started_at")]
    if not runs:
        return "idle", None
    last = runs[-1]
    started = _ts(last.get("started_at"))
    if last.get("status") == "running":
        if started is not None and now - started <= JOB_CRASHED_S:
            return "running", None
        return "failed", (started or 0.0) + JOB_CRASHED_S
    if last.get("status") == "failed":
        return "failed", _ts(last.get("finished_at")) or started
    return "idle", None


def job_workers(jobs: dict, logs: dict, loaded: list[str], projects: list[dict], now: float,
                goals: dict | None = None, paths: dict | None = None) -> list[dict]:
    """Every job that is running or whose last run failed (catalogued, or loaded here and not catalogued), under the
    project it serves. Idle and switched-off jobs aren't drawn."""
    ids = {p["id"] for p in projects}
    marvin = next((p["id"] for p in projects if p["id"] == "marvin"), None)
    goals, paths = goals or {}, paths or {}
    out = []
    names = list(jobs or {}) + [n for n in dict.fromkeys(loaded or []) if isinstance(n, str) and n and n not in (jobs or {})]
    for name in names:
        j = (jobs or {}).get(name)
        goal = j.get("goal") if j else None
        if isinstance(goal, str) and goal.startswith("project:"):
            pid = goal[len("project:"):]
            pid = pid if pid in ids else None
        elif isinstance(goal, str) and re.fullmatch(r"ns\d+", goal):
            pid = marvin
        else:
            pid = None
        if j and j.get("machine") == "none":
            continue
        state, ended = _job_state(logs.get(name), now)
        if state == "idle":
            continue
        if j is None:
            desc = "Scheduled job running here that the job catalog doesn't list"
        elif goal is None:
            desc = "Scheduled job with no declared goal"
        else:
            desc = f"Scheduled job ({j.get('machine')}); serves: {goals.get(goal, goal)}"
        w = {"id": f"job:{name}", "name": name, "kind": "job", "state": state, "project": pid, "ended": ended,
             "desc": desc}
        if paths.get(name):
            w["path"] = paths[name]
        out.append(w)
    return out


# ── the tree ────────────────────────────────────────────────────────────────

def worker_node(w: dict) -> dict:
    node = {"id": w["id"], "name": w["name"], "cat": "work", "desc": w.get("desc", ""), "children": [],
            "expandable": False, "expanded": True,
            "worker": {k: w[k] for k in ("kind", "state", "agent", "ended") if k in w}}
    if w.get("path"):
        node["path"], node["openable"] = w["path"], True
    return node


def work_trunk(projects: list[dict], workers: list[dict], node_id_of=None) -> dict:
    """Work: one node per project (in catalog order) with its workers, then Unassigned. Every worker lands somewhere."""
    node_id_of = node_id_of or (lambda p: p["id"])
    children, by_pid = [], {}
    for p in projects:
        node = {"id": node_id_of(p), "name": p["name"], "projectId": p["id"], "cat": "work",
                "desc": (p.get("desc") or "").split(". ")[0], "children": [], "expandable": False, "expanded": True}
        by_pid[p["id"]] = node
        children.append(node)
    unassigned = {"id": UNASSIGNED, "name": UNASSIGNED, "projectId": None, "cat": "work",
                  "desc": "Workers whose project can't be determined, and jobs with no declared goal",
                  "children": [], "expandable": False, "expanded": True}
    for w in workers:
        (by_pid.get(w.get("project")) or unassigned)["children"].append(worker_node(w))
    children.append(unassigned)
    return {"id": HALF_ID, "name": HALF_NAME, "cat": "work", "desc": "What MARVIN is working on",
            "children": children, "expandable": False, "expanded": True}


# ── live sources ────────────────────────────────────────────────────────────

def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def newest_catalog(claude_dir: Path) -> list[dict]:
    d = claude_dir / "catalog"
    try:
        files = sorted(d.glob("projects.*.json"), key=lambda p: p.stat().st_mtime)
    except OSError:
        return []
    doc = _read_json(files[-1]) if files else None
    return doc.get("projects", []) if isinstance(doc, dict) else []


def _stage_key(stem: str):
    m = re.fullmatch(r"([\w.-]+)__([\w.-]+)-(\d+)", stem)
    if m:
        return f"{m.group(1)}/{m.group(2)}", int(m.group(3))
    return None


def launchd_jobs(agents_dir: Path, launch_dir: Path) -> tuple[list[str], dict]:
    """Jobs loaded on this Mac (their launchd plists) and each one's script, relative to the agents folder."""
    names, paths = [], {}
    for prefix in ("com.marvin.", "com.giles."):
        for f in sorted(launch_dir.glob(prefix + "*.plist")) if launch_dir.is_dir() else []:
            try:
                with f.open("rb") as fh:
                    data = plistlib.load(fh)
            except Exception:  # noqa: BLE001 -- a plist launchd accepts but plistlib doesn't: name only
                data = {}
            name = (data.get("Label") or f.stem).removeprefix(prefix)
            names.append(name)
            for arg in reversed(data.get("ProgramArguments") or []):
                if isinstance(arg, str) and arg.startswith(str(agents_dir) + "/") and " " not in arg:
                    paths[name] = arg[len(str(agents_dir)) + 1:]
                    break
    return names, paths


def read_live(claude_dir: Path | None = None, jobs: dict | None = None, loaded: list[str] | None = None,
              now: float | None = None, remote_of=None, goals: dict | None = None, paths: dict | None = None) -> dict:
    claude_dir = claude_dir or Path.home() / ".claude"
    now = time.time() if now is None else now
    projects = monitored_projects(newest_catalog(claude_dir))
    jobs_dir, stages_dir = claude_dir / "logs" / "jobs", claude_dir / "logs" / "ticket-stages"
    helpers, logs = [], {}
    for f in sorted(jobs_dir.glob("*.json")) if jobs_dir.is_dir() else []:
        doc = _read_json(f)
        if not isinstance(doc, dict):
            continue
        if f.stem.startswith(chat_helpers.PREFIX) and isinstance(doc.get("helper"), dict):
            helpers.append(doc)
        else:
            logs[f.stem] = doc
    stages = {}
    for f in sorted(stages_dir.glob("*.json")) if stages_dir.is_dir() else []:
        key = _stage_key(f.stem)
        events = _read_json(f) if key else None
        if key and isinstance(events, list):
            stages[key] = events
    workers = (helper_workers(helpers, projects, now, remote_of) + builder_workers(stages, projects, now)
               + job_workers(jobs or {}, logs, loaded or [], projects, now, goals, paths))
    return {"generated_at": now, "projects": projects, "workers": workers}


def write(out: Path, doc: dict) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)


def live_doc() -> dict:
    """read_live with this Mac's real job catalog and launchd jobs."""
    import job_catalog  # noqa: PLC0415  (reads the north stars; only needed for a real run)
    loaded, paths = launchd_jobs(Path.home() / ".agents", Path.home() / "Library" / "LaunchAgents")
    return read_live(jobs=job_catalog.JOBS, loaded=loaded, goals=job_catalog.GOALS, paths=paths, remote_of=git_remote)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Write the map's Work half (work.json).")
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args(argv)
    lock_path = args.out.with_name(f".{args.out.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:  # one writer at a time; each reads the latest state, so the last one wins
        fcntl.flock(lock, fcntl.LOCK_EX)
        write(args.out, live_doc())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
