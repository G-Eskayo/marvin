#!/usr/bin/env python3
"""Label catalog: data-driven healing of missing GitHub labels.

When `gh issue/pr create|edit` fails because a label doesn't exist, this module
captures the error, creates the missing label, and retries the original call.

Real gh's error format for a missing label (empirically observed):
    could not add label: label not found
    or: could not remove label: label not found
    or similar variants with label name in quotes
    exit code: 1

The catalog covers every label MARVIN uses across all repos:
  - FIXED: a closed set of literal label names (defined below)
  - CORE: the five triage labels (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix)
  - project:<id>: derived from ~/.claude/boards/registry.json board names
  - claimed:<machine>: derived from known machines in marvin-network.json + fixed classes

The healing algorithm (run_with_healing):
  a. Parse the original call to find which labels it's trying to add/remove
  b. Run the call and capture stderr
  c. If it fails with "label 'X' not found", check if X is catalogued
  d. If yes, create the label and retry the original call (up to once per missing label, up to N retries total)
  e. If create fails (permission, rate limit, already-exists race): restore original error
  f. If a label is not catalogued: preserve original error unchanged (let the caller see the typo)

The design reuses existing patterns:
  - pr_ticket_check.py's argv-walking style for parsing label flags
  - project_onboard.py's triage label definitions and colors
  - support.py's support-label definitions and colors
  - machine_profile._load_registry() for claimed:<machine> membership
  - ~/. claude/boards/registry.json for project:<id> membership
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, NamedTuple

try:
    import machine_profile
    import project_onboard
    import support
except ImportError:
    machine_profile = None
    project_onboard = None
    support = None


MAX_LABEL_RETRIES = 5
# Match: "could not add label: 'name' not found" or similar with optional quotes
LABEL_NOT_FOUND_RE = re.compile(
    r"could not (?:add|remove) label:\s+(?:'([^']+)'|(\S+))\s+not found",
    re.IGNORECASE | re.MULTILINE
)


class LabelCall(NamedTuple):
    """Parsed label-related gh call."""
    repo: str | None  # from --repo, -R, URL target, GH_REPO, or cwd
    target: str | None  # issue/PR URL or number
    add_labels: list[str]  # unique label names to add
    remove_labels: list[str]  # unique label names to remove


# ── Catalog: data ──────────────────────────────────────────────────────────────

def _triage_colors() -> dict[str, str]:
    """Core triage label colors from project_onboard.py."""
    if project_onboard:
        return project_onboard.TRIAGE_LABEL_COLORS.copy()
    return {
        "needs-triage": "d4c5f9",
        "needs-info": "ffd700",
        "ready-for-agent": "90ee90",
        "ready-for-human": "ffb6c1",
        "wontfix": "808080",
    }


def _support_colors() -> dict[str, str]:
    """Support label colors from support.py."""
    if support:
        return support.LABEL_COLORS.copy()
    return {
        "trying-here": "c5def5",
        "solved-here": "0e8a16",
        "helper-trying": "fbca04",
        "needs-you": "d93f0b",
        "answered": "1d76db",
        "verified": "0e8a16",
        "idea-new": "c2e0c6",
        "idea-proposal": "bfd4f2",
        "idea-ticket": "5319e7",
        "idea-shipped": "0e8a16",
        "idea-dismissed": "cccccc",
    }


FIXED = {
    # Triage (5 core)
    "needs-triage": {"color": "d4c5f9", "description": "Needs triage"},
    "needs-info": {"color": "ffd700", "description": "Needs information"},
    "ready-for-agent": {"color": "90ee90", "description": "Ready for agent"},
    "ready-for-human": {"color": "ffb6c1", "description": "Needs human judgment"},
    "wontfix": {"color": "808080", "description": "Won't fix"},

    # Priority (4)
    "priority:p0": {"color": "ff0000", "description": "Priority 0: critical"},
    "priority:p1": {"color": "ff9800", "description": "Priority 1: high"},
    "priority:p2": {"color": "ffeb3b", "description": "Priority 2: medium"},
    "priority:p3": {"color": "90ee90", "description": "Priority 3: low"},

    # Type (2)
    "bug": {"color": "d73a49", "description": "Bug"},
    "enhancement": {"color": "a2eeef", "description": "Enhancement"},

    # Health and status (10)
    "needs-reengagement": {"color": "ffa500", "description": "Needs reengagement"},
    "hold": {"color": "cccccc", "description": "On hold"},
    "pinned": {"color": "cccccc", "description": "Pinned"},
    "watch": {"color": "1f883d", "description": "Watch"},
    "foundation": {"color": "5b1e38", "description": "Foundation"},
    "breaking-change": {"color": "d73a49", "description": "Breaking change"},
    "linux-ok": {"color": "1f883d", "description": "Works on Linux"},
    "regression": {"color": "d73a49", "description": "Regression"},
    "missed-purpose": {"color": "ffa500", "description": "Missed purpose"},
    "owner-decisions": {"color": "0366d6", "description": "Owner decisions needed"},

    # Pipeline/process (3)
    "from-box": {"color": "bfdadc", "description": "From Box"},
    "main-red": {"color": "d73a49", "description": "Main is red"},
    "site-deploy-failed": {"color": "d73a49", "description": "Site deploy failed"},
}

# Add support labels with their colors
_support_colors_map = _support_colors()
if support:
    for state in support.STATES:
        FIXED[f"support:{state}"] = {
            "color": _support_colors_map.get(state, "cccccc"),
            "description": f"Support: {state}",
        }
else:
    # Fallback support states if module not available
    for state in ("trying-here", "solved-here", "helper-trying", "needs-you", "answered", "verified",
                  "idea-new", "idea-proposal", "idea-ticket", "idea-shipped", "idea-dismissed"):
        FIXED[f"support:{state}"] = {
            "color": _support_colors_map.get(state, "cccccc"),
            "description": f"Support: {state}",
        }


def known_projects(registry_path: Path | None = None) -> set[str]:
    """Project IDs from ~/.claude/boards/registry.json."""
    registry_path = registry_path or Path.home() / ".claude" / "boards" / "registry.json"
    try:
        data = json.loads(registry_path.read_text())
        projects = {board["name"] for board in data.get("boards", []) if "name" in board}
        # Always include marvin itself
        projects.add("marvin")
        return projects
    except (OSError, ValueError, KeyError):
        return {"marvin"}


def known_machines(network_path: Path | None = None) -> set[str]:
    """Machine IDs from marvin-network.json devices + two fixed Mac classes."""
    network_path = network_path or Path.home() / ".claude" / "marvin-network.json"
    machines = {"mac-mini", "macbook-pro"}  # fixed class names
    if machine_profile:
        try:
            registry = machine_profile._load_registry()
            machines.update(registry.keys())
        except Exception:
            pass
    if network_path.exists():
        try:
            data = json.loads(network_path.read_text())
            devices = data.get("devices", {})
            if isinstance(devices, dict):
                machines.update(devices.keys())
        except (OSError, ValueError, KeyError):
            pass
    return machines


def is_catalogued(name: str, projects: set[str] | None = None, machines: set[str] | None = None) -> bool:
    """Check if a label name is in the catalog (FIXED, project:<id>, or claimed:<machine>)."""
    if name in FIXED:
        return True
    projects = projects or known_projects()
    machines = machines or known_machines()
    if name.startswith("project:"):
        return name[8:] in projects
    if name.startswith("claimed:"):
        return name[8:] in machines
    return False


# ── Parsing ────────────────────────────────────────────────────────────────────

def label_call(argv: list[str]) -> LabelCall | None:
    """Parse a gh call; return None if not an issue/pr create|edit, or if no label flags."""
    if not argv or "--help" in argv or "-h" in argv:
        return None

    if len(argv) < 2 or argv[0] not in ("issue", "pr"):
        return None

    action = argv[1]
    if action not in ("create", "edit"):
        return None

    repo = None
    target = None
    add_labels = []
    remove_labels = []
    skip_next = False

    for i, arg in enumerate(argv[2:], start=2):
        if skip_next:
            skip_next = False
            continue

        if arg == "--repo" and i + 1 < len(argv):
            repo = argv[i + 1]
            skip_next = True
        elif arg.startswith("--repo="):
            repo = arg[7:]
        elif arg == "-R" and i + 1 < len(argv):
            repo = argv[i + 1]
            skip_next = True
        elif arg.startswith("-R"):
            repo = arg[2:]
        elif arg in ("--add-label", "-l") and i + 1 < len(argv):
            vals = argv[i + 1].split(",")
            add_labels.extend(v.strip() for v in vals if v.strip())
            skip_next = True
        elif arg.startswith("--add-label="):
            vals = arg[12:].split(",")
            add_labels.extend(v.strip() for v in vals if v.strip())
        elif arg.startswith("-l"):
            vals = arg[2:].split(",")
            add_labels.extend(v.strip() for v in vals if v.strip())
        elif arg == "--label" and i + 1 < len(argv):
            # --label is used in gh issue create (not --add-label)
            vals = argv[i + 1].split(",")
            add_labels.extend(v.strip() for v in vals if v.strip())
            skip_next = True
        elif arg.startswith("--label="):
            vals = arg[8:].split(",")
            add_labels.extend(v.strip() for v in vals if v.strip())
        elif arg == "--remove-label" and i + 1 < len(argv):
            vals = argv[i + 1].split(",")
            remove_labels.extend(v.strip() for v in vals if v.strip())
            skip_next = True
        elif arg.startswith("--remove-label="):
            vals = arg[15:].split(",")
            remove_labels.extend(v.strip() for v in vals if v.strip())
        elif not arg.startswith("-") and not target and action == "edit":
            # positional argument after 'edit' is the issue/PR number or URL
            target = arg

    # deduplicate
    add_labels = list(dict.fromkeys(v for v in add_labels if v))
    remove_labels = list(dict.fromkeys(v for v in remove_labels if v))

    if not add_labels and not remove_labels:
        return None

    return LabelCall(repo=repo, target=target, add_labels=add_labels, remove_labels=remove_labels)


def drop_label_value(argv: list[str], flag: str, value: str) -> list[str]:
    """Return argv with one value dropped from a repeated flag.

    Example: argv = ['issue', 'edit', '5', '--add-label', 'a,b,c']
             drop_label_value(argv, '--add-label', 'b')
             -> ['issue', 'edit', '5', '--add-label', 'a,c']
    """
    result = []
    skip_next = False
    for i, arg in enumerate(argv):
        if skip_next:
            skip_next = False
            continue

        if arg in (flag, flag[2:] if flag.startswith("--") else None) and i + 1 < len(argv):
            vals = argv[i + 1].split(",")
            remaining = [v.strip() for v in vals if v.strip() and v.strip() != value]
            if remaining:
                result.append(arg)
                result.append(",".join(remaining))
            skip_next = True
        elif arg.startswith(flag + "="):
            vals = arg[len(flag) + 1:].split(",")
            remaining = [v.strip() for v in vals if v.strip() and v.strip() != value]
            if remaining:
                result.append(flag + "=" + ",".join(remaining))
        else:
            result.append(arg)

    return result


def resolve_repo(call: LabelCall, env: dict, ask_cwd: Callable[[], str] | None = None) -> str | None:
    """Resolve the repo for a label call: explicit flag, URL target, GH_REPO, or cwd."""
    if call.repo:
        return call.repo

    if call.target and "/" in call.target:
        # URL-like target: extract owner/repo from https://github.com/owner/repo or similar
        parts = call.target.split("/")
        # Find github.com and take the next two parts (owner/repo)
        for i, part in enumerate(parts):
            if part in ("github.com", "github.com:"):
                if i + 2 < len(parts):
                    return f"{parts[i + 1]}/{parts[i + 2]}"
        # Fallback: if it looks like owner/repo (no https://), use as-is or extract last two segments
        # For plain issue URLs like owner/repo/issues/123, take owner/repo
        if len(parts) >= 2:
            # Take the first two non-empty parts that look like owner/repo
            non_empty = [p for p in parts if p and p not in ("http:", "https:")]
            if len(non_empty) >= 2:
                return f"{non_empty[0]}/{non_empty[1]}"

    if env.get("GH_REPO"):
        return env["GH_REPO"]

    if ask_cwd:
        try:
            cwd_repo = ask_cwd()
            if cwd_repo:
                return cwd_repo
        except Exception:
            pass

    return None


# ── Healing ────────────────────────────────────────────────────────────────────

def run_with_healing(
    real: str,
    argv: list[str],
    env: dict,
    ask: Callable = subprocess.run,
    say: Callable | None = None,
    projects: set[str] | None = None,
    machines: set[str] | None = None,
) -> tuple[int, str, dict | None] | None:
    """Run gh with healing for missing labels.

    Returns: (exit_code, stderr_to_write, heal_log | None) or None if not a label call

    If the call succeeds, heal_log is None.
    If the call fails but we can't heal it, heal_log is None and stderr is preserved.
    If we attempt healing, heal_log contains details of what we tried.
    """
    call = label_call(argv)
    if not call:
        return None

    projects = projects or known_projects()
    machines = machines or known_machines()

    # Capture stdin once if present (for --body-file -, -F -, or --body-file=-)
    stdin_data = None
    for i, arg in enumerate(argv):
        if arg in ("--body-file", "-F") and i + 1 < len(argv) and argv[i + 1] == "-":
            # --body-file - or -F - (space-separated)
            try:
                stdin_data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
            except Exception:
                pass
            break
        elif arg.startswith("--body-file=-") or arg.startswith("-F-"):
            # --body-file=- or -F- (equals or combined form)
            try:
                stdin_data = sys.stdin.buffer.read() if hasattr(sys.stdin, "buffer") else sys.stdin.read()
            except Exception:
                pass
            break

    heal_log = {}
    attempts = 0
    last_stdout = ""
    any_healing_attempted = False

    while attempts < MAX_LABEL_RETRIES:
        attempts += 1

        # Run the call with stderr captured
        env_copy = {**env, "MARVIN_GH_GATE_INSIDE": "1"}
        try:
            if stdin_data is not None:
                p = ask([real, *argv], input=stdin_data, capture_output=True, env=env_copy)
            else:
                p = ask([real, *argv], capture_output=True, text=True, env=env_copy)

            rc = p.returncode if hasattr(p, "returncode") else p
            stderr = p.stderr if hasattr(p, "stderr") else ""
            stdout = p.stdout if hasattr(p, "stdout") else ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            last_stdout = stdout
        except Exception as e:
            return None

        if rc == 0:
            # Success: write captured stdout
            if last_stdout:
                sys.stdout.write(last_stdout)
            # Return heal_log if any healing happened, None otherwise
            return (rc, stderr, heal_log if any_healing_attempted else None)

        # Check for label-not-found error
        match = LABEL_NOT_FOUND_RE.search(stderr)
        if not match:
            # Some other error; write stdout and return error
            if last_stdout:
                sys.stdout.write(last_stdout)
            return (rc, stderr, heal_log if any_healing_attempted else None)

        # Extract label name from either quoted (group 1) or unquoted (group 2)
        missing_label = match.group(1) or match.group(2)

        # Check if it's catalogued
        if not is_catalogued(missing_label, projects, machines):
            # Not catalogued; write stdout and return original error
            if last_stdout:
                sys.stdout.write(last_stdout)
            return (rc, stderr, heal_log if any_healing_attempted else None)

        # Try to create the label
        any_healing_attempted = True
        label_info = FIXED.get(missing_label, {"color": "cccccc", "description": missing_label})
        create_argv = [real, "label", "create", missing_label, "--color", label_info["color"],
                       "--description", label_info["description"]]

        # Resolve the target repo for label creation
        target_repo = resolve_repo(call, env)
        if target_repo:
            create_argv.extend(["--repo", target_repo])

        try:
            create_result = ask(create_argv, capture_output=True, text=True, env=env_copy)
            create_rc = create_result.returncode if hasattr(create_result, "returncode") else create_result
            create_stderr = create_result.stderr if hasattr(create_result, "stderr") else ""
            if isinstance(create_stderr, bytes):
                create_stderr = create_stderr.decode("utf-8", "replace")
        except Exception as e:
            # Create failed; return original error
            if say:
                say(f"label healing: couldn't create label '{missing_label}': {str(e)[:100]}")
            if last_stdout:
                sys.stdout.write(last_stdout)
            return (rc, stderr, heal_log if any_healing_attempted else None)

        if create_rc != 0:
            # Label create failed (permission, rate limit, already exists race, etc.)
            if "already exists" in create_stderr.lower():
                # Another caller created it; just retry the original call
                heal_log[f"attempt_{attempts}"] = f"label '{missing_label}' created by another caller, retrying"
                continue
            # Some other failure; return original error
            if say:
                say(f"label healing: couldn't create label '{missing_label}': {create_stderr[:100]}")
            if last_stdout:
                sys.stdout.write(last_stdout)
            return (rc, stderr, heal_log if any_healing_attempted else None)

        # Label created; log and retry
        heal_log[f"attempt_{attempts}"] = f"created label '{missing_label}', retrying"

    # Reached max retries without success; write stdout if any
    if last_stdout:
        sys.stdout.write(last_stdout)
    return (rc, stderr, heal_log if any_healing_attempted else None)
