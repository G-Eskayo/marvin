#!/usr/bin/env python3
"""Project onboarding: transform a repo into a fully wired MARVIN project.

This module handles the read-only 'plan' stage (ticket #141): gather facts about a project
and produce a readiness plan without modifying anything. Facts are gathered once per repo
via `inspect()`, and `plan()` is pure over those facts.

    project_onboard.py plan <owner/repo>    outputs JSON readiness plan for the project
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import board_registry as br
import project_profile as pp


TIMEOUT = 60
TRIAGE_LABELS = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}
ONBOARDING_DIR = Path.home() / ".claude" / "onboarding"


def onboarding_path(repo: str) -> Path:
	"""Filesystem-safe path for a repo's onboarding plan."""
	safe_repo = repo.replace("/", "-")
	return ONBOARDING_DIR / f"{safe_repo}.json"


def _gh(args: list[str]) -> str:
    """Run gh CLI command, return stdout on success or empty string on failure."""
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=TIMEOUT
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def inspect(repo: str, gh=_gh) -> dict:
    """Gather facts about a repo: file tree, labels, profiles, boards, toolchain.
    All I/O lives here; read-only only.
    """
    facts = {
        "repo": repo,
        "visibility": None,
        "default_branch": None,
        "file_tree": {},
        "labels": [],
        "profile_exists": False,
        "board_exists": False,
        "clone_hint_resolves": False,
        "swift_installed": False,
        "has_package_swift": False,
        "has_workflows": False,
        "workflow_runs_swift_test": False,
        "has_agent_docs": False,
        "has_claude_md_skills": False,
    }

    repo_view = gh(["repo", "view", repo, "--json", "visibility,defaultBranchRef"])
    if repo_view:
        try:
            data = json.loads(repo_view)
            facts["visibility"] = data.get("visibility")
            ref = data.get("defaultBranchRef", {})
            facts["default_branch"] = ref.get("name") if isinstance(ref, dict) else None
        except json.JSONDecodeError:
            pass

    if not facts["default_branch"]:
        facts["default_branch"] = "main"

    tree_api = gh([
        "api", f"repos/{repo}/git/trees/{facts['default_branch']}",
        "--field", "recursive=true"
    ])
    if tree_api:
        try:
            tree_data = json.loads(tree_api)
            for item in tree_data.get("tree", []):
                path = item.get("path", "")
                item_type = item.get("type")
                facts["file_tree"][path] = item_type
                if path == "Package.swift":
                    facts["has_package_swift"] = True
        except json.JSONDecodeError:
            pass

    labels_raw = gh(["label", "list", "--repo", repo, "--json", "name"])
    if labels_raw:
        try:
            labels_data = json.loads(labels_raw)
            facts["labels"] = [l["name"] for l in labels_data]
        except json.JSONDecodeError:
            pass

    facts["profile_exists"] = pp.load_profile(repo) is not None

    try:
        boards = br.list_boards()
        facts["board_exists"] = any(b["repo"] == repo for b in boards)
    except Exception:
        pass

    profile = pp.load_profile(repo)
    if profile and profile.get("clone_hints"):
        for hint in profile["clone_hints"]:
            if Path(hint).exists():
                facts["clone_hint_resolves"] = True
                break

    try:
        result = subprocess.run(["which", "swift"], capture_output=True, timeout=5)
        facts["swift_installed"] = result.returncode == 0
    except Exception:
        pass

    has_workflows = any(p.startswith(".github/workflows/") and p.endswith(".yml") for p in facts["file_tree"])
    facts["has_workflows"] = has_workflows

    if has_workflows:
        for wf_path in facts["file_tree"]:
            if wf_path.startswith(".github/workflows/") and wf_path.endswith(".yml"):
                try:
                    wf_raw = gh(["api", f"repos/{repo}/contents/{wf_path}"])
                    if wf_raw:
                        wf_data = json.loads(wf_raw)
                        if "content" in wf_data:
                            content = base64.b64decode(wf_data["content"]).decode()
                            if "swift test" in content or "swift build" in content:
                                facts["workflow_runs_swift_test"] = True
                                break
                except Exception:
                    pass

    docs_agents_files = {
        "docs/agents/issue-tracker.md",
        "docs/agents/triage-labels.md",
        "docs/agents/domain.md",
    }
    facts["has_agent_docs"] = all(p in facts["file_tree"] for p in docs_agents_files)

    if "CLAUDE.md" in facts["file_tree"]:
        try:
            claude_raw = gh(["api", f"repos/{repo}/contents/CLAUDE.md"])
            if claude_raw:
                claude_data = json.loads(claude_raw)
                if "content" in claude_data:
                    content = base64.b64decode(claude_data["content"]).decode()
                    facts["has_claude_md_skills"] = "## Agent skills" in content
        except Exception:
            pass

    return facts


def plan(facts: dict) -> dict:
    """Pure logic: map facts to the 6 ADR readiness pieces.
    Returns {"<piece>": {"state": "ok"|"missing"|"needs-human", "reason": "..."}, ...}
    """
    plan_out = {}

    # Profile
    if facts.get("profile_exists"):
        plan_out["profile"] = {"state": "ok", "reason": "profile exists in config/projects/"}
    else:
        plan_out["profile"] = {"state": "missing", "reason": "profile not yet created"}

    # CI
    if facts.get("workflow_runs_swift_test"):
        plan_out["ci"] = {"state": "ok", "reason": "workflow found running swift test"}
    elif facts.get("has_workflows"):
        plan_out["ci"] = {"state": "needs-human", "reason": "workflow exists but does not run swift test"}
    else:
        plan_out["ci"] = {"state": "missing", "reason": "no CI workflow present"}

    # Triage labels
    existing_labels = set(facts.get("labels", []))
    if TRIAGE_LABELS <= existing_labels:
        plan_out["triage_labels"] = {"state": "ok", "reason": "all 5 triage labels present"}
    else:
        missing = TRIAGE_LABELS - existing_labels
        plan_out["triage_labels"] = {
            "state": "missing",
            "reason": f"missing: {', '.join(sorted(missing))}",
        }

    # Agent docs
    if facts.get("has_agent_docs") and facts.get("has_claude_md_skills"):
        plan_out["agent_docs"] = {"state": "ok", "reason": "docs/agents files and CLAUDE.md block present"}
    else:
        missing_parts = []
        if not facts.get("has_agent_docs"):
            missing_parts.append("docs/agents files")
        if not facts.get("has_claude_md_skills"):
            missing_parts.append("CLAUDE.md Agent skills block")
        plan_out["agent_docs"] = {
            "state": "missing",
            "reason": f"missing: {', '.join(missing_parts)}",
        }

    # Board
    if facts.get("board_exists"):
        plan_out["board"] = {"state": "ok", "reason": "board registered"}
    else:
        plan_out["board"] = {"state": "missing", "reason": "board not yet registered"}

    # Clone and toolchain
    if facts.get("clone_hint_resolves") and facts.get("swift_installed"):
        plan_out["clone_and_toolchain"] = {
            "state": "ok",
            "reason": "clone exists and swift toolchain present",
        }
    elif facts.get("clone_hint_resolves"):
        plan_out["clone_and_toolchain"] = {
            "state": "missing",
            "reason": "clone exists but swift toolchain not found; install Xcode or add to PATH",
        }
    elif facts.get("profile_exists"):
        plan_out["clone_and_toolchain"] = {
            "state": "missing",
            "reason": "clone not yet created but can be cloned from profile hints",
        }
    else:
        plan_out["clone_and_toolchain"] = {
            "state": "needs-human",
            "reason": "no profile with clone_hints; manual clone path required",
        }

    # Test command (for swift-package shape only)
    if facts.get("has_package_swift"):
        if facts.get("workflow_runs_swift_test"):
            plan_out["test_command"] = {
                "state": "ok",
                "reason": "swift test defined in workflow",
            }
        else:
            plan_out["test_command"] = {
                "state": "missing",
                "reason": "Package.swift found but no test target defined in CI",
            }
    else:
        plan_out["test_command"] = {
            "state": "needs-human",
            "reason": "not a swift-package project; stack detection required",
        }

    return plan_out


def write_plan(repo: str, gh=_gh, path: Path | None = None) -> dict:
    """Generate and persist a plan for a repo.
    Calls inspect() and plan(), wraps as {"repo": ..., "generated_at": ..., "pieces": {...}},
    and atomically writes to the onboarding directory. Returns the full document.
    """
    facts = inspect(repo, gh)
    pieces = plan(facts)
    doc = {
        "repo": repo,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pieces": pieces,
    }
    output_path = path or onboarding_path(repo)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2) + "\n")
    tmp.replace(output_path)
    return doc


def main():
    """CLI entry point: project_onboard.py plan <owner/repo>"""
    if len(sys.argv) != 3 or sys.argv[1] != "plan":
        sys.exit("usage: project_onboard.py plan <owner/repo>")

    repo = sys.argv[2]
    facts = inspect(repo)
    result = plan(facts)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
