#!/usr/bin/env python3
"""Label catalog and healing for the GitHub gate (bin/gh label healing, marvin#???).

When a gh issue/pr create/edit call references a label that doesn't exist on the target repo,
the gate can either create the missing label or remove it from the command and retry. This module
catalogs all labels used in the codebase and provides a decision function to heal missing-label
errors automatically.

Catalog:
  - CORE: the 5 triage labels (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix)
    with their standard colours and descriptions
  - FIXED: other individually-catalogued labels actually used with --add-label/--remove-label/-l
    in the codebase: needs-reengagement, owner-decisions, watch, regression, missed-purpose, etc.
  - Dynamic families: project:<id> (validated against config/project_tags.json) and
    claimed:<machine> (validated against ~/.claude/marvin-network.json)

Usage:
  parse_label_call(argv) -> dict | None     # parse {issue,pr} {create,edit} command
  resolve_repo(call, env, cwd=None) -> str | None  # determine target repo
  missing_label(stderr) -> str | None       # extract missing label name from error message
  heal_step(call, missing_name, create_label) -> dict  # decide: retry, create-then-retry, or stop
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

# ── Catalog data ────────────────────────────────────────────────────────────

CORE = {
    "needs-triage": {"color": "d4c5f9", "description": "Maintainer needs to evaluate"},
    "needs-info": {"color": "ffd700", "description": "Waiting on reporter for more detail"},
    "ready-for-agent": {"color": "90ee90", "description": "Fully specified — an AFK agent can pick this up with no further human context"},
    "ready-for-human": {"color": "ffb6c1", "description": "Needs human implementation, not agent-suitable"},
    "wontfix": {"color": "808080", "description": "Will not be actioned"},
}

FIXED = {
    "needs-reengagement",
    "owner-decisions",
    "watch",
    "regression",
    "missed-purpose",
    "purpose-metric",
    "linux-ok",
    "from-box",
    "hold",
    "pinned",
    "held",
    "foundation",
    "site-deploy-failed",
    "priority:p0",
    "priority:p1",
    "priority:p2",
    "priority:p3",
    "bug",
}


def _load_project_tags(path: Path | None = None) -> set[str]:
    """Registered project IDs from config/project_tags.json."""
    path = path or Path(__file__).resolve().parents[1] / "config" / "project_tags.json"
    try:
        data = json.loads(path.read_text())
        return set(data.get("projects", {}).keys())
    except (OSError, json.JSONDecodeError):
        return set()


def _load_devices(path: Path | None = None) -> set[str]:
    """Device names from ~/.claude/marvin-network.json."""
    path = path or Path.home() / ".claude" / "marvin-network.json"
    try:
        data = json.loads(path.read_text())
        devices = data.get("devices", {})
        return set(devices.keys()) if isinstance(devices, dict) else set()
    except (OSError, json.JSONDecodeError):
        return set()


def is_catalogued(name: str, project_tags: set[str] | None = None, devices: set[str] | None = None) -> bool:
    """Whether a label name is in the catalog (CORE, FIXED, or dynamic families)."""
    if name in CORE or name in FIXED:
        return True
    if name.startswith("project:"):
        project_tags = project_tags or _load_project_tags()
        return name[8:] in project_tags
    if name.startswith("claimed:"):
        devices = devices or _load_devices()
        return name[8:] in devices
    return False


# ── Parse label calls ──────────────────────────────────────────────────────

_LABEL_FLAGS = {"-l", "--label", "--add-label", "--remove-label"}


def parse_label_call(argv: list[str]) -> dict | None:
    """Parse {issue,pr} {create,edit} command for label operations.

    Returns:
        {"cmd": "issue"|"pr", "repo": str|None, "target": str|None,
         "add": [names...], "remove": [names...]}
        or None if not a label-bearing call.
    """
    if len(argv) < 2 or argv[0] not in ("issue", "pr") or argv[1] not in ("create", "edit"):
        return None
    if "--help" in argv or "-h" in argv:
        return None

    call = {"cmd": argv[0], "repo": None, "target": None, "add": [], "remove": []}
    rest = list(argv[2:])
    i = 0

    while i < len(rest):
        a = rest[i]

        if a == "--repo" or a == "-R":
            i += 1
            if i < len(rest):
                call["repo"] = rest[i]
        elif a.startswith("--repo="):
            call["repo"] = a.split("=", 1)[1]
        elif a == "--label":
            i += 1
            if i < len(rest):
                for label in rest[i].split(","):
                    label = label.strip()
                    if label:
                        call["add"].append(label)
        elif a.startswith("--label="):
            for label in a.split("=", 1)[1].split(","):
                label = label.strip()
                if label:
                    call["add"].append(label)
        elif a == "--add-label":
            i += 1
            if i < len(rest):
                for label in rest[i].split(","):
                    label = label.strip()
                    if label:
                        call["add"].append(label)
        elif a.startswith("--add-label="):
            for label in a.split("=", 1)[1].split(","):
                label = label.strip()
                if label:
                    call["add"].append(label)
        elif a == "--remove-label":
            i += 1
            if i < len(rest):
                for label in rest[i].split(","):
                    label = label.strip()
                    if label:
                        call["remove"].append(label)
        elif a.startswith("--remove-label="):
            for label in a.split("=", 1)[1].split(","):
                label = label.strip()
                if label:
                    call["remove"].append(label)
        elif a == "-l":
            i += 1
            if i < len(rest):
                for label in rest[i].split(","):
                    label = label.strip()
                    if label:
                        call["add"].append(label)
        elif a.startswith("-l"):
            for label in a[2:].split(","):
                label = label.strip()
                if label:
                    call["add"].append(label)
        elif not a.startswith("-") and call["target"] is None:
            call["target"] = a

        i += 1

    return call if (call["add"] or call["remove"]) else None


# ── Resolve repo ────────────────────────────────────────────────────────────

def resolve_repo(call: dict, env: dict, cwd: str | None = None) -> str | None:
    """Determine the target repo for a label call.

    Checks in order:
      1. --repo/-R flag in the call
      2. target URL (issue/PR URL in positional arg)
      3. GH_REPO environment variable
      4. Current git repo (via pr_ticket_check.repo_here())
    """
    if call.get("repo"):
        return call["repo"]

    target = call.get("target")
    if target:
        m = re.search(r"github\.com/([\w.-]+/[\w.-]+)", target)
        if m:
            return m.group(1)

    if env.get("GH_REPO"):
        return env["GH_REPO"]

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import pr_ticket_check
        return pr_ticket_check.repo_here(cwd)
    except Exception:  # noqa: BLE001
        return None


# ── Detect missing labels ────────────────────────────────────────────────────

_MISSING_LABEL = re.compile(r"(?:label\s+'([^']+)'\s+not found|could not (?:add|remove) label:\s+'([^']+)'\s+not found)", re.I)


def missing_label(stderr: str) -> str | None:
    """Extract the missing label name from a GitHub error message, or None.

    Matches: "label '<name>' not found" or "could not add/remove label: '<name>' not found".
    """
    m = _MISSING_LABEL.search(stderr or "")
    if m:
        return m.group(1) or m.group(2)
    return None


# ── Heal decision ────────────────────────────────────────────────────────────

def heal_step(
    call: dict,
    missing_name: str,
    create_label: Callable[[str, str], None],
    project_tags: set[str] | None = None,
    devices: set[str] | None = None,
) -> dict:
    """Decide how to heal a missing-label error.

    Args:
        call: parsed label call (from parse_label_call)
        missing_name: the label name that wasn't found
        create_label: injected function (name, repo) -> None; raises on error (except "already exists")
        project_tags: cached set of project IDs (optional optimization)
        devices: cached set of device names (optional optimization)

    Returns:
        {"action": "retry"|"create-then-retry"|"stop",
         "argv_patch": [...],  # new label args to use in retry, or None if no change
         "hint": "..."}        # user-facing message if action is "stop"
    """
    in_add = missing_name in call.get("add", [])
    in_remove = missing_name in call.get("remove", [])

    if not in_add and not in_remove:
        return {
            "action": "stop",
            "hint": f"label '{missing_name}' not found and not in this call; stopping",
        }

    catalogued = is_catalogued(missing_name, project_tags=project_tags, devices=devices)

    if in_remove:
        return {
            "action": "retry",
            "argv_patch": ["--remove-label", missing_name],
            "hint": f"label '{missing_name}' not found; removing from --remove-label and retrying",
        }
    elif in_add:
        if catalogued:
            return {
                "action": "create-then-retry",
                "argv_patch": None,
                "hint": f"label '{missing_name}' is catalogued; creating before retry",
            }
        else:
            return {
                "action": "stop",
                "hint": f"label '{missing_name}' is not catalogued; refusing to create unknown label",
            }
    else:
        return {
            "action": "stop",
            "hint": f"label '{missing_name}' not found and not in this call; stopping",
        }


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("Label catalog module loaded successfully.")
