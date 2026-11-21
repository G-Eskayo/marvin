"""Label catalog: canonical label definitions for MARVIN projects.

A label catalog centralizes definitions of triage labels, their colors, and project
IDs so that any gate, dashboard, or tool can reason about label correctness without
re-defining them. The catalog is the single source of truth for label validation and healing.

    label_catalog.known_project_ids()         {"marvin", ...}
    label_catalog.lookup("ready-for-agent")   {"color": "90ee90", "description": "..."}
    label_catalog.call_repo(argv, env, cwd)   ("G-Eskayo/marvin",) or None
    label_catalog.without_label(argv, "bug")  argv with "bug" removed from --remove-label
"""
from __future__ import annotations
import os
import re
import subprocess
from pathlib import Path

TRIAGE_LABELS = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}
TRIAGE_LABEL_COLORS = {
    "needs-triage": "d4c5f9",
    "needs-info": "ffd700",
    "ready-for-agent": "90ee90",
    "ready-for-human": "ffb6c1",
    "wontfix": "808080",
}

FIXED = {
    "needs-triage": {"color": "d4c5f9", "description": "Needs triage"},
    "needs-info": {"color": "ffd700", "description": "Needs information"},
    "ready-for-agent": {"color": "90ee90", "description": "Ready for agent"},
    "ready-for-human": {"color": "ffb6c1", "description": "Ready for human review"},
    "wontfix": {"color": "808080", "description": "Will not fix"},
    "bug": {"color": "d73a4a", "description": "Bug report"},
    "enhancement": {"color": "a2eeef", "description": "Enhancement request"},
    "breaking-change": {"color": "5319e7", "description": "Breaking change"},
    "needs-reengagement": {"color": "d93f0b", "description": "Sent back: rebuild on the current base branch"},
    "main-red": {"color": "b60205", "description": "Main branch is failing"},
    "linux-ok": {"color": "c2e0c6", "description": "Linux compatible"},
    "from-box": {"color": "0e8a16", "description": "From Box"},
    "purpose-metric": {"color": "bfd4f2", "description": "Purpose metric"},
    "missed-purpose": {"color": "e99695", "description": "Missed purpose"},
    "watch": {"color": "fbca04", "description": "Watch for changes"},
    "regression": {"color": "d73a4a", "description": "Regression"},
    "hold": {"color": "bfdadc", "description": "On hold"},
    "priority:p0": {"color": "b60205", "description": "Priority: critical"},
    "priority:p1": {"color": "ff6b6b", "description": "Priority: high"},
    "priority:p2": {"color": "ffa94d", "description": "Priority: medium"},
    "priority:p3": {"color": "51cf66", "description": "Priority: low"},
}

CORE = frozenset({"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix",
                  "bug", "enhancement", "needs-reengagement", "priority:p0", "priority:p1",
                  "priority:p2", "priority:p3"})

_REMOTE = re.compile(r"github\.com[:/]([\w.-]+/[\w.-]+?)(?:\.git)?/?$", re.A)
_CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def known_project_ids(registry: Path | None = None) -> set[str]:
    """{"marvin"} ∪ project IDs from config/project_tags.json, or just {"marvin"} on any error."""
    result = {"marvin"}

    try:
        import json
        # Try to read from config/project_tags.json
        config_path = registry or (_CONFIG_DIR / "project_tags.json")
        if config_path.exists():
            data = json.loads(config_path.read_text())
            projects = data.get("projects", {})
            if isinstance(projects, dict):
                result.update(projects.keys())
    except Exception:
        pass

    return result


def lookup(label: str) -> dict | None:
    """{"color", "description"} for a known label, or None.

    Handles:
    - Catalogued names in FIXED
    - project:<id> for ids in known_project_ids()
    - claimed:<m> for any machine name m
    """
    if label in FIXED:
        return FIXED[label]

    # project:<id> family
    if label.startswith("project:"):
        project_id = label[8:]
        if project_id in known_project_ids():
            return {"color": "c5def5", "description": f"Work on {project_id}"}

    # claimed:<machine> family
    if label.startswith("claimed:"):
        machine = label[8:]
        return {"color": "ededed", "description": f"Claimed by {machine}"}

    return None


def label_call(argv: list[str]) -> dict | None:
    """{"cmd", "add", "remove"} for issue|pr create|edit with label changes, else None.

    Parses --add-label, --label, -l (all mean add), --remove-label (remove).
    Handles --flag=value and --flag value, repeats, and comma-separated values.
    """
    if len(argv) < 2 or argv[0] not in ("issue", "pr") or argv[1] not in ("create", "edit"):
        return None

    cmd = argv[0]
    adds = set()
    removes = set()

    i = 2
    while i < len(argv):
        arg = argv[i]

        if arg.startswith("--add-label"):
            flag, sep, value = arg.partition("=")
            if sep:
                # --add-label=a,b
                for label in value.split(","):
                    label = label.strip()
                    if label:  # skip empty strings
                        adds.add(label)
            else:
                # --add-label a,b
                i += 1
                if i < len(argv):
                    for label in argv[i].split(","):
                        label = label.strip()
                        if label:
                            adds.add(label)

        elif arg.startswith("--remove-label"):
            flag, sep, value = arg.partition("=")
            if sep:
                # --remove-label=a,b
                for label in value.split(","):
                    label = label.strip()
                    if label:
                        removes.add(label)
            else:
                # --remove-label a,b
                i += 1
                if i < len(argv):
                    for label in argv[i].split(","):
                        label = label.strip()
                        if label:
                            removes.add(label)

        elif arg.startswith("--label"):
            flag, sep, value = arg.partition("=")
            if sep:
                # --label=a,b
                for label in value.split(","):
                    label = label.strip()
                    if label:
                        adds.add(label)
            else:
                # --label a,b
                i += 1
                if i < len(argv):
                    for label in argv[i].split(","):
                        label = label.strip()
                        if label:
                            adds.add(label)

        elif arg in ("-l",):
            # -l label
            i += 1
            if i < len(argv):
                for label in argv[i].split(","):
                    label = label.strip()
                    if label:
                        adds.add(label)

        i += 1

    if not adds and not removes:
        return None

    return {
        "cmd": cmd,
        "add": list(adds),
        "remove": list(removes),
    }


def failed_label(stderr: str, call: dict) -> tuple[str, bool] | None:
    """(label_name, is_add) if stderr says a label in this call failed, or None.

    Only returns a label if it's actually in call["add"] or call["remove"], not just
    any label mentioned in stderr (keeps assignee/milestone "not found" untouched).
    """
    m = re.search(r"'([^']+)' not found", stderr)
    if not m:
        return None

    label = m.group(1)

    # Check if it's in the labels we tried to add
    if call.get("add") and label in call["add"]:
        return (label, True)

    # Check if it's in the labels we tried to remove
    if call.get("remove") and label in call["remove"]:
        return (label, False)

    return None


def call_repo(argv: list[str], env: dict | None = None, cwd: str | None = None) -> str | None:
    """owner/repo that a gh call targets.

    Checks in order: --repo/-R flag, issue/PR URL in positional args, GH_REPO env var, cwd's origin.
    """
    env = os.environ if env is None else env

    # Check for --repo or -R flag
    for i, arg in enumerate(argv):
        if arg in ("--repo", "-R"):
            if i + 1 < len(argv):
                return argv[i + 1]
        elif arg.startswith("--repo="):
            return arg.split("=", 1)[1]

    # Check for issue/PR URL in positional args
    for arg in argv:
        if not arg.startswith("-"):
            # Check if it looks like a GitHub issue/PR URL
            m = _REMOTE.search(arg)
            if m:
                return m.group(1)
            # Check for owner/repo#N format
            if re.match(r"[\w.-]+/[\w.-]+#\d+", arg):
                return arg.split("#")[0]

    # Check GH_REPO env var
    if "GH_REPO" in env:
        return env["GH_REPO"]

    # Fall back to cwd's origin
    try:
        p = subprocess.run(["git", "remote", "get-url", "origin"],
                          capture_output=True, text=True, cwd=cwd, timeout=10)
        m = _REMOTE.search(p.stdout.strip()) if p.returncode == 0 else None
        return m.group(1) if m else None
    except (OSError, subprocess.SubprocessError):
        return None


def without_label(argv: list[str], label: str) -> list[str]:
    """argv with label removed from every --remove-label value.

    If a --remove-label flag becomes empty, the flag itself is removed.
    """
    new_argv = []
    skip_next = False

    i = 0
    while i < len(argv):
        arg = argv[i]

        if skip_next:
            skip_next = False
            i += 1
            continue

        if arg.startswith("--remove-label"):
            flag, sep, value = arg.partition("=")
            if sep:
                # --remove-label=a,b,c
                remaining = [l.strip() for l in value.split(",") if l.strip() != label and l.strip()]
                if remaining:
                    new_argv.append(f"--remove-label={','.join(remaining)}")
                # else: skip the flag entirely if empty
            else:
                # --remove-label a,b,c
                if i + 1 < len(argv):
                    remaining = [l.strip() for l in argv[i + 1].split(",") if l.strip() != label and l.strip()]
                    if remaining:
                        new_argv.append(arg)
                        new_argv.append(",".join(remaining))
                    skip_next = True  # always skip the value part
                else:
                    new_argv.append(arg)
        else:
            new_argv.append(arg)

        i += 1

    return new_argv
