#!/usr/bin/env python3
"""Onboarding health check for a new project (issue #141).

Reads repo metadata, file tree, labels, profiles and board registry without any mutations.
Reports seven pieces: profile, CI, labels, agent_docs, board, clone_toolchain, test_command.
Each piece has state (ok|missing|needs-human) and a one-line reason.

    project_onboard.py plan <owner/repo>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TIMEOUT = 30


def _sh(args: list[str]) -> str:
    """Run a command and return stdout, or empty string on failure."""
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT)
        return p.stdout if p.returncode == 0 else ""
    except Exception:
        return ""


def _gh(args: list[str]) -> str:
    """Run gh command, return stdout or empty string."""
    return _sh(["gh"] + args)


def gather(repo: str, gh=_gh, profiles_dir: Path | None = None, boards_path: Path | None = None) -> dict:
    """Read-only facts: repo visibility/branch, file tree, labels, profiles, board registry.
    Tolerant: if any call fails, record None for that fact instead of raising.
    Returns dict with keys: repo_view, tree, labels, profile_data, board_entry, clone_path.
    """
    profiles_dir = profiles_dir or (Path.home() / ".agents" / "config" / "projects")
    boards_path = boards_path or (Path.home() / ".claude" / "boards" / "registry.json")

    facts: dict = {
        "repo_view": None,
        "tree": None,
        "labels": None,
        "profile_data": None,
        "board_entry": None,
        "clone_path": None,
    }

    repo_view_raw = gh(["repo", "view", repo, "--json", "defaultBranchRef,visibility"])
    if repo_view_raw:
        try:
            facts["repo_view"] = json.loads(repo_view_raw)
        except json.JSONDecodeError:
            pass

    default_branch = facts["repo_view"].get("defaultBranchRef") if facts["repo_view"] else "main"
    tree_raw = gh(["api", f"repos/{repo}/git/trees/{default_branch}?recursive=1"])
    if tree_raw:
        try:
            tree_data = json.loads(tree_raw)
            facts["tree"] = [item["path"] for item in tree_data.get("tree", [])]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    labels_raw = gh(["label", "list", "--repo", repo, "--json", "name"])
    if labels_raw:
        try:
            facts["labels"] = [item["name"] for item in json.loads(labels_raw)]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass

    profile_file = profiles_dir / f"{repo.split('/')[-1]}.json"
    if profile_file.exists():
        try:
            facts["profile_data"] = json.loads(profile_file.read_text())
        except (json.JSONDecodeError, IOError):
            facts["profile_data"] = {}

    if boards_path.exists():
        try:
            boards_data = json.loads(boards_path.read_text())
            for board in boards_data.get("boards", []):
                if board.get("repo") == repo:
                    facts["board_entry"] = board
                    break
        except (json.JSONDecodeError, IOError, TypeError):
            pass

    import project_profile
    try:
        profile = project_profile.load_profile(repo, profiles_dir)
        if profile:
            clone = project_profile.resolve_clone(profile, ensure=False)
            facts["clone_path"] = str(clone) if clone else None
    except Exception:
        pass

    return facts


STACK_DETECTORS = {
    "swift-package": lambda tree: next((p for p in (tree or []) if p == "Package.swift"), None),
}


def _detect_stack(tree: list[str] | None) -> tuple[str | None, str | None]:
    """Detect stack type from tree. Returns (stack_name, stack_path) or (None, None)."""
    if not tree:
        return None, None
    for stack_name, detector in STACK_DETECTORS.items():
        result = detector(tree)
        if result:
            return stack_name, result
    return None, None


def plan_profile(facts: dict, stack: str | None, stack_path: str | None) -> dict:
    """Profile file present and valid → ok; absent → missing; invalid → needs-human."""
    profile_data = facts.get("profile_data")
    if profile_data is None:
        return {"state": "missing", "reason": "config/projects/{repo}.json not found"}
    if not profile_data:
        return {"state": "missing", "reason": "profile file is empty"}
    try:
        import project_profile
        project_profile._validate(profile_data, "profile")
        return {"state": "ok", "reason": "profile is valid and configured"}
    except (ValueError, KeyError, TypeError) as e:
        return {"state": "needs-human", "reason": f"profile is invalid ({str(e)[:80]})"}


def plan_ci(facts: dict, stack: str | None, stack_path: str | None) -> dict:
    """CI present (any .github/workflows/*.yml) → ok; absent → missing. Unrecognized stack → needs-human."""
    if stack is None:
        return {"state": "needs-human", "reason": "unrecognised stack"}
    tree = facts.get("tree") or []
    has_ci = any(p.startswith(".github/workflows/") and p.endswith(".yml") for p in tree)
    if has_ci:
        return {"state": "ok", "reason": "workflows found in .github/workflows/"}
    return {"state": "missing", "reason": "no CI workflows found in .github/workflows/"}


def plan_labels(facts: dict, stack: str | None, stack_path: str | None) -> dict:
    """Five canonical triage labels present → ok; some missing → missing."""
    required_labels = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}
    labels = set(facts.get("labels") or [])
    if facts.get("labels") is None:
        return {"state": "needs-human", "reason": "could not verify labels via gh"}
    missing = required_labels - labels
    if not missing:
        return {"state": "ok", "reason": "all five triage labels present"}
    return {"state": "missing", "reason": f"missing labels: {', '.join(sorted(missing))}"}


def plan_agent_docs(facts: dict, stack: str | None, stack_path: str | None) -> dict:
    """docs/agents/{issue-tracker,triage-labels,domain}.md present → ok; otherwise → missing."""
    tree = facts.get("tree") or []
    required_docs = {
        "docs/agents/issue-tracker.md",
        "docs/agents/triage-labels.md",
        "docs/agents/domain.md",
    }
    found = set(p for p in tree if p in required_docs)
    missing_docs = required_docs - found

    if missing_docs:
        return {"state": "missing", "reason": f"missing docs: {', '.join(sorted(missing_docs))}"}
    return {"state": "ok", "reason": "all three agent docs present"}


def plan_board(facts: dict, stack: str | None, stack_path: str | None) -> dict:
    """Repo in board registry → ok; absent → missing."""
    if facts.get("board_entry"):
        return {"state": "ok", "reason": "board registered"}
    return {"state": "missing", "reason": "board not found in registry"}


def plan_clone_toolchain(facts: dict, stack: str | None, stack_path: str | None) -> dict:
    """Clone found AND required tools present → ok; tools missing → needs-human; clone missing → missing."""
    if stack is None:
        return {"state": "needs-human", "reason": "unrecognised stack"}

    required_tools = []
    if stack == "swift-package":
        required_tools = ["swift", "xcode"]

    import project_profile
    env = project_profile.build_env({})
    missing_tools = [t for t in required_tools if not project_profile.have(t, env)]

    if missing_tools:
        return {"state": "needs-human", "reason": f"missing tools: {', '.join(missing_tools)} (install on this machine first)"}

    clone_path = facts.get("clone_path")
    if clone_path:
        return {"state": "ok", "reason": f"clone found at {clone_path}, tools present"}
    return {"state": "missing", "reason": "clone not found (run onboarding to clone)"}


def plan_test_command(facts: dict, stack: str | None, stack_path: str | None) -> dict:
    """Stack recognized → ok (with command); unrecognized → needs-human."""
    if stack is None:
        return {"state": "needs-human", "reason": "unrecognised stack (no known test command)"}
    if stack == "swift-package":
        cmd = f"swift test (in {stack_path})" if stack_path else "swift test"
        return {"state": "ok", "reason": f"test command: {cmd}"}
    return {"state": "needs-human", "reason": f"stack '{stack}' has no known test command"}


def plan(repo: str, gh=_gh, profiles_dir: Path | None = None, boards_path: Path | None = None) -> dict:
    """Orchestrate gather + stack detection + seven piece-functions. Returns plan dict."""
    facts = gather(repo, gh=gh, profiles_dir=profiles_dir, boards_path=boards_path)
    tree = facts.get("tree")
    stack, stack_path = _detect_stack(tree)

    return {
        "repo": repo,
        "stack": stack or "unknown",
        "pieces": {
            "profile": plan_profile(facts, stack, stack_path),
            "ci": plan_ci(facts, stack, stack_path),
            "labels": plan_labels(facts, stack, stack_path),
            "agent_docs": plan_agent_docs(facts, stack, stack_path),
            "board": plan_board(facts, stack, stack_path),
            "clone_toolchain": plan_clone_toolchain(facts, stack, stack_path),
            "test_command": plan_test_command(facts, stack, stack_path),
        },
    }


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "plan":
        sys.exit("usage: project_onboard.py plan <owner/repo>")
    repo = sys.argv[2]
    result = plan(repo)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
