#!/usr/bin/env python3
"""
connections.py — gold threads derived from files that are already the source of truth, so the map connects
agents, machines, projects and skills, not only skills to skills (docs/plans/map-connections-2026-10-08.md).

Pure functions: callers pass in what they read (generate.py does the reading) and the set of node ids on the map.
A thread whose end isn't on the map is left out here; nothing is invented.

  runs-on        agent -> machine     lib/health_checks.py JOB_PLACEMENT (the Health tab flags any job running elsewhere)
  builds         ticket-pipeline -> project   config/projects/*.json with dispatch "on"
  skill-project  skill -> its project  a `project:<skill>` node, or enrichment.json `skill_projects`
"""
from __future__ import annotations

import ast
from pathlib import Path

PIPELINE_NODE = "ticket-pipeline"


def _thread(a: str, b: str, kind: str, label: str) -> dict:
    return {"a": a, "b": b, "label": label, "type": kind}


def runs_on(placement: dict[str, str], node_ids: set[str], machines: dict[str, str]) -> list[dict]:
    """placement: {job: "both"|"mini"|"laptop"}; machines: {"mini": node id, "laptop": node id}.
    Labels name no machine: the public snapshot shows machines anonymised."""
    out = []
    for job, where in sorted(placement.items()):
        if job not in node_ids:
            continue
        roles = ("mini", "laptop") if where == "both" else (where,)
        for role in roles:
            machine = machines.get(role)
            if machine in node_ids:
                label = (f"launchd job com.marvin.{job}, scheduled here"
                         + (" (and on the other Mac)" if where == "both" else ""))
                out.append(_thread(job, machine, "runs-on", label))
    return out


def builds(profiles: list[dict], node_ids: set[str]) -> list[dict]:
    """profiles: parsed config/projects/*.json. A project the pipeline is switched on for gets a thread."""
    out = []
    if PIPELINE_NODE not in node_ids:
        return out
    for p in profiles:
        name = (p.get("repo") or "").split("/")[-1]
        if p.get("dispatch") == "on" and name in node_ids:
            out.append(_thread(PIPELINE_NODE, name, "builds",
                               f"the ticket pipeline builds and verifies {name}'s tickets (config/projects/{name}.json)"))
    return sorted(out, key=lambda t: t["b"])


def skill_projects(skill_ids: set[str], project_ids: set[str], overrides: dict[str, str]) -> list[dict]:
    """A project node named `project:<skill>` belongs to that skill; overrides cover names that differ."""
    links = {s: f"project:{s}" for s in skill_ids if f"project:{s}" in project_ids}
    links.update({s: p for s, p in overrides.items() if s in skill_ids and p in project_ids})
    return [_thread(s, p, "skill-project", f"the {s} skill is how the {p.removeprefix('project:')} project gets done")
            for s, p in sorted(links.items())]


def tracked(projects: list[dict], node_ids: set[str]) -> list[dict]:
    """project -> "Activity tab" for projects with board=True (project status tracked in Activity tab)."""
    out = []
    activity_tab = "Activity tab"
    if activity_tab not in node_ids:
        return out
    for p in projects:
        project_id = p.get("id") or p.get("name")
        if p.get("board") and project_id in node_ids:
            out.append(_thread(project_id, activity_tab, "tracked",
                               f"{project_id} is tracked in the Activity tab (project_catalog.py board field)"))
    return sorted(out, key=lambda t: t["a"])


def documented(projects: list[dict], node_ids: set[str]) -> list[dict]:
    """project -> "Docs tab" for projects with docs.context or docs.readme."""
    out = []
    docs_tab = "Docs tab"
    if docs_tab not in node_ids:
        return out
    for p in projects:
        project_id = p.get("id") or p.get("name")
        docs = p.get("docs") or {}
        if (docs.get("context") or docs.get("readme")) and project_id in node_ids:
            out.append(_thread(project_id, docs_tab, "documented",
                               f"{project_id} has documentation (CONTEXT.md or README.md)"))
    return sorted(out, key=lambda t: t["a"])


def read_job_placement(health_checks_py: Path) -> dict[str, str]:
    """JOB_PLACEMENT from lib/health_checks.py, read with ast (no import: the module pulls in the whole health stack)."""
    try:
        module = ast.parse(Path(health_checks_py).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    for node in module.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "JOB_PLACEMENT" for t in node.targets):
            try:
                return dict(ast.literal_eval(node.value))
            except ValueError:
                return {}
    return {}


def machine_roles(network: dict) -> dict[str, str]:
    """{"mini": id, "laptop": id} from marvin-network.json device kinds (desktop = the always-on mini)."""
    kinds = {"desktop": "mini", "laptop": "laptop"}
    out: dict[str, str] = {}
    for device_id, info in sorted(network.get("devices", {}).items()):
        role = kinds.get(info.get("kind"))
        if role and role not in out:
            out[role] = device_id
    return out
