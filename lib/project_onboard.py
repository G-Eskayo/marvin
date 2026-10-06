#!/usr/bin/env python3
"""Project onboarding: transform a repo into a fully wired MARVIN project.

This module handles both the read-only 'plan' stage (ticket #141) and the 'apply' stage
(ticket #146): gather facts about a project, produce a readiness plan, and optionally
apply local changes (labels, board, profile). Facts are gathered once per repo via
`inspect()`, and `plan()` is pure over those facts. Apply modifies local state only.

    project_onboard.py plan <owner/repo>              outputs JSON readiness plan
    project_onboard.py apply <owner/repo> --local     applies local changes (labels, board, profile)
"""
from __future__ import annotations

import base64
import difflib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import board_registry as br
import project_profile as pp


TIMEOUT = 60
TRIAGE_LABELS = {
    "needs-triage": "d4c5f9",
    "needs-info": "ffd700",
    "ready-for-agent": "90ee90",
    "ready-for-human": "ffb6c1",
    "wontfix": "808080",
}
CLAIM_LABEL_COLOR = "5319E7"


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


def _apply_labels(repo: str, facts: dict, machines: list[str] | None = None, gh=_gh) -> dict:
    """Create missing triage and claim labels. Returns {"action": "created"|"unchanged", "labels": [names...]}.
    Idempotent: gh label create is only called for genuinely-missing names."""
    machines = machines or []
    existing = set(facts.get("labels", []))
    all_label_names = set(TRIAGE_LABELS.keys()) | {f"claimed:{m}" for m in machines}
    created = []

    for label_name, color in TRIAGE_LABELS.items():
        if label_name not in existing:
            cmd = ["label", "create", label_name, "--repo", repo, "--color", color,
                   "--description", f"Triage label: {label_name}"]
            _gh_label_create(repo, label_name, color, cmd, gh)
            created.append(label_name)

    for machine in machines:
        label_name = f"claimed:{machine}"
        if label_name not in existing:
            cmd = ["label", "create", label_name, "--repo", repo, "--color", CLAIM_LABEL_COLOR,
                   "--description", f"Being worked on by {machine}"]
            _gh_label_create(repo, label_name, CLAIM_LABEL_COLOR, cmd, gh)
            created.append(label_name)

    return {
        "action": "created" if created else "unchanged",
        "labels": created,
    }


def _gh_label_create(repo: str, label_name: str, color: str, cmd: list[str], gh) -> None:
    """Helper to create a label via gh. Silently ignores if label already exists or creation fails."""
    gh(cmd)


def _apply_board(repo: str, facts: dict, registry_path: Path | None = None) -> dict:
    """Register board via board_registry.ensure_board(). Idempotent."""
    result = br.ensure_board(repo, path=registry_path)
    return {
        "action": "created" if result["created"] else "unchanged",
        "board": result["board"],
    }


def _apply_profile(repo: str, facts: dict, profiles_dir: Path | None = None) -> dict:
    """Draft profile from stack template, show diff vs. existing, handle conflicts.
    Returns {"action": "created"|"unchanged"|"conflict"|"needs-human", "diff": str, "profile": dict}.
    Never overwrites an edited profile."""
    profiles_dir = profiles_dir or pp.PROFILES_DIR
    repo_name = repo.split("/")[1]
    profile_path = profiles_dir / f"{repo_name}.json"

    # Determine stack
    if facts.get("has_package_swift"):
        stack = "swift-package"
    else:
        return {
            "action": "needs-human",
            "reason": "no onboarding template for this stack",
            "diff": "",
        }

    # Load template
    template_path = Path(__file__).resolve().parent.parent / "config" / "onboarding" / stack / "profile.json"
    if not template_path.exists():
        return {
            "action": "needs-human",
            "reason": f"template not found: {template_path}",
            "diff": "",
        }

    with open(template_path) as f:
        template_fragment = json.load(f)

    # Build skeleton
    skeleton = {
        "repo": repo,
        "base_branch": facts.get("default_branch", "main"),
        "clone_hints": _guess_clone_hints(repo_name),
        "dispatch": "off",
        "merge_from_dashboard": False,
    }

    # Merge template onto skeleton
    draft = skeleton.copy()
    for key in ("executor", "verify", "setup", "generated"):
        if key in template_fragment:
            draft[key] = template_fragment[key]

    # Hard-code dispatch and merge_from_dashboard to off/false (R2 safety)
    draft["dispatch"] = "off"
    draft["merge_from_dashboard"] = False

    # Validate the draft
    try:
        draft = pp._validate(draft, f"draft profile for {repo}")
    except ValueError as e:
        return {
            "action": "needs-human",
            "reason": f"profile validation failed: {e}",
            "diff": "",
        }

    # Check for existing profile
    if profile_path.exists():
        existing_text = profile_path.read_text()
        try:
            existing = json.loads(existing_text)
        except json.JSONDecodeError:
            return {
                "action": "conflict",
                "reason": "existing profile is not valid JSON",
                "diff": existing_text[:500],
            }

        # Compare: if identical, it's unchanged; if different, it's a conflict (edited by person)
        draft_text = json.dumps(draft, indent=2) + "\n"
        if existing_text == draft_text:
            return {"action": "unchanged", "diff": ""}

        # Diff found: treat as conflict, never overwrite
        diff_lines = list(difflib.unified_diff(
            existing_text.splitlines(keepends=True),
            draft_text.splitlines(keepends=True),
            fromfile="existing",
            tofile="draft",
        ))
        return {
            "action": "conflict",
            "reason": "existing profile differs from draft; edit detected",
            "diff": "".join(diff_lines),
        }

    # No existing profile: create it
    draft_text = json.dumps(draft, indent=2) + "\n"
    diff_lines = list(difflib.unified_diff(
        [],
        draft_text.splitlines(keepends=True),
        fromfile="/dev/null",
        tofile=f"config/projects/{repo_name}.json",
    ))

    return {
        "action": "created",
        "diff": "".join(diff_lines),
        "profile": draft,
    }


def _guess_clone_hints(repo_name: str) -> list[str]:
    """Generate likely clone paths for a repo."""
    return [
        f"~/Developer/{repo_name}",
        f"~/Documents/Projects/{repo_name}",
    ]


def apply(repo: str, facts: dict | None = None, plan_result: dict | None = None, *,
          local_only: bool = True, profiles_dir: Path | None = None,
          registry_path: Path | None = None, gh=_gh) -> dict:
    """Apply local changes: create missing labels, register board, draft profile.
    Idempotent: running twice produces no changes on the second run.

    Returns: {"labels": {...}, "board": {...}, "profile": {...}} with per-piece
    "action" (created/unchanged/conflict/needs-human) and "diff" where relevant.
    """
    if facts is None:
        facts = inspect(repo, gh=gh)

    machines = facts.get("machines", [])

    labels_result = _apply_labels(repo, facts, machines=machines, gh=gh)
    board_result = _apply_board(repo, facts, registry_path=registry_path)
    profile_result = _apply_profile(repo, facts, profiles_dir=profiles_dir)

    return {
        "labels": labels_result,
        "board": board_result,
        "profile": profile_result,
    }


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
    triage_names = set(TRIAGE_LABELS.keys())
    if triage_names <= existing_labels:
        plan_out["triage_labels"] = {"state": "ok", "reason": "all 5 triage labels present"}
    else:
        missing = triage_names - existing_labels
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


def main():
    """CLI entry point: project_onboard.py plan|apply <owner/repo> [--local]"""
    if len(sys.argv) < 3:
        sys.exit("usage: project_onboard.py plan <owner/repo> | apply <owner/repo> --local")

    cmd = sys.argv[1]
    repo = sys.argv[2]

    if cmd == "plan":
        if len(sys.argv) != 3:
            sys.exit("usage: project_onboard.py plan <owner/repo>")
        facts = inspect(repo)
        result = plan(facts)
        print(json.dumps(result, indent=2))

    elif cmd == "apply":
        if len(sys.argv) != 4 or sys.argv[3] != "--local":
            sys.exit("usage: project_onboard.py apply <owner/repo> --local")

        facts = inspect(repo)
        result = apply(repo, facts=facts)

        # Print human-readable summary
        print(f"\nOnboarding apply for {repo} --local:\n")

        # Labels
        labels = result["labels"]
        if labels["action"] == "created":
            print(f"  labels: created {', '.join(labels['labels'])}")
        else:
            print(f"  labels: unchanged")

        # Board
        board = result["board"]
        if board["action"] == "created":
            print(f"  board: created {repo}")
        else:
            print(f"  board: unchanged")

        # Profile
        profile = result["profile"]
        if profile["action"] == "created":
            print(f"  profile: created config/projects/{repo.split('/')[1]}.json")
            if profile.get("diff"):
                print("\n  diff (new file):")
                for line in profile["diff"].split("\n")[:20]:
                    if line:
                        print(f"    {line}")
        elif profile["action"] == "unchanged":
            print(f"  profile: unchanged")
        elif profile["action"] == "conflict":
            print(f"  profile: conflict — existing differs from draft (edit detected)")
            if profile.get("diff"):
                print("\n  diff:")
                for line in profile["diff"].split("\n")[:30]:
                    if line:
                        print(f"    {line}")
        else:  # needs-human
            print(f"  profile: needs-human — {profile.get('reason', '')}")

        print()

    else:
        sys.exit(f"unknown command: {cmd}\nusage: project_onboard.py plan|apply <owner/repo>")


if __name__ == "__main__":
    main()
