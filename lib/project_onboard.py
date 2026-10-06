#!/usr/bin/env python3
"""Project onboarding: transform a repo into a fully wired MARVIN project.

This module handles the read-only 'plan' stage (ticket #141): gather facts about a project
and produce a readiness plan without modifying anything. Facts are gathered once per repo
via `inspect()`, and `plan()` is pure over those facts.

    project_onboard.py plan <owner/repo>    outputs JSON readiness plan for the project
"""
from __future__ import annotations

import base64
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import board_registry as br
import project_profile as pp


TIMEOUT = 60
TRIAGE_LABELS = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}
CONFIG_ONBOARDING = Path(__file__).resolve().parent.parent / "config" / "onboarding"


def _load_stack_templates() -> list[dict]:
    """Load all stack templates from config/onboarding/<stack>/, sorted by priority."""
    stacks = []
    if CONFIG_ONBOARDING.exists():
        for stack_dir in sorted(CONFIG_ONBOARDING.iterdir()):
            if stack_dir.is_dir():
                profile_path = stack_dir / "profile.json"
                if profile_path.exists():
                    try:
                        with open(profile_path) as f:
                            stack = json.load(f)
                            stacks.append(stack)
                    except (json.JSONDecodeError, OSError):
                        pass
    stacks.sort(key=lambda s: s.get("priority", 999))
    return stacks


def _gh(args: list[str]) -> str:
    """Run gh CLI command, return stdout on success or empty string on failure."""
    try:
        result = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=TIMEOUT
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def _matches_detect_rule(file_tree: dict, rule: dict) -> bool:
    """Check if a file tree matches a detection rule."""
    if "file_glob" in rule:
        glob_pattern = rule["file_glob"]
        for path in file_tree:
            if fnmatch.fnmatch(path, glob_pattern):
                return True
            if glob_pattern.startswith("**/"):
                basename = path.rsplit("/", 1)[-1]
                pattern_suffix = glob_pattern[3:]
                if fnmatch.fnmatch(basename, pattern_suffix):
                    return True
    elif "file" in rule:
        if rule["file"] in file_tree:
            return True
    return False


def _file_content_contains_any(content: str, patterns: list[str]) -> bool:
    """Check if content contains any of the patterns."""
    return any(pattern in content for pattern in patterns)


def _get_file_content(repo: str, path: str, gh=_gh) -> str:
    """Fetch file content from GitHub, return empty string on failure."""
    try:
        result = gh(["api", f"repos/{repo}/contents/{path}"])
        if result:
            data = json.loads(result)
            if "content" in data:
                return base64.b64decode(data["content"]).decode()
    except (json.JSONDecodeError, Exception):
        pass
    return ""


def _is_test_file(path: str) -> bool:
    """Check if a path matches test file naming patterns."""
    name = path.split("/")[-1]
    return name.startswith("test_") and name.endswith(".py") or (name.endswith("_test.py"))


def _test_touches_machine_local_state(content: str) -> bool:
    """Check if test content reads machine-local state."""
    markers = [
        "Path.home(",
        "expanduser(",
        'os.environ["HOME"]',
        'os.environ.get("HOME"',
        "~/.claude",
    ]
    return any(marker in content for marker in markers)


def _all_requirements_pinned(content: str) -> bool:
    """Check if all requirements in requirements.txt are pinned with ==."""
    for line in content.split("\n"):
        line = line.strip()
        if line and not line.startswith("#"):
            if "==" not in line:
                return False
    return True


def _all_pyproject_deps_pinned(content: str) -> bool:
    """Check if all dependencies in pyproject.toml are pinned with exact versions."""
    try:
        import re
        deps_section = re.search(
            r'\[project\]\s*dependencies\s*=\s*\[(.*?)\]',
            content,
            re.DOTALL
        )
        if deps_section:
            deps_text = deps_section.group(1)
            for dep in re.findall(r'"([^"]+)"', deps_text):
                dep = dep.strip()
                if dep and not re.match(r'.*==.*', dep):
                    return False
        return True
    except Exception:
        return False


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
        "detected_stack": None,
        "workflow_contents": "",
        "package_json_scripts": {},
        "tools_installed": {},
        "has_requirements_file": False,
        "requirements_pinned": False,
        "python_tests_touch_home": False,
        "machine_local_test_files": [],
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

    workflow_contents_list = []
    if has_workflows:
        for wf_path in facts["file_tree"]:
            if wf_path.startswith(".github/workflows/") and wf_path.endswith(".yml"):
                content = _get_file_content(repo, wf_path, gh)
                if content:
                    workflow_contents_list.append(content)
                    if "swift test" in content or "swift build" in content:
                        facts["workflow_runs_swift_test"] = True
    facts["workflow_contents"] = "\n".join(workflow_contents_list)

    if "package.json" in facts["file_tree"]:
        package_json_content = _get_file_content(repo, "package.json", gh)
        if package_json_content:
            try:
                package_json = json.loads(package_json_content)
                facts["package_json_scripts"] = package_json.get("scripts", {})
            except json.JSONDecodeError:
                pass

    stacks = _load_stack_templates()
    for stack in stacks:
        detect_rule = stack.get("detect", {})
        if _matches_detect_rule(facts["file_tree"], detect_rule):
            if "content_any" in detect_rule:
                if detect_rule.get("file") == "package.json":
                    content = _get_file_content(repo, "package.json", gh)
                    if content and _file_content_contains_any(content, detect_rule["content_any"]):
                        facts["detected_stack"] = stack.get("name")
                        break
            else:
                facts["detected_stack"] = stack.get("name")
                break

    for tool in ["swift", "node", "npm", "python", "xcodegen"]:
        try:
            result = subprocess.run(["which", tool], capture_output=True, timeout=5)
            facts["tools_installed"][tool] = result.returncode == 0
        except Exception:
            facts["tools_installed"][tool] = False

    if facts.get("detected_stack") == "python":
        for req_file in ["requirements.txt", "pyproject.toml"]:
            if req_file in facts["file_tree"]:
                facts["has_requirements_file"] = True
                content = _get_file_content(repo, req_file, gh)
                if content:
                    if req_file == "requirements.txt":
                        facts["requirements_pinned"] = _all_requirements_pinned(content)
                    elif req_file == "pyproject.toml":
                        facts["requirements_pinned"] = _all_pyproject_deps_pinned(content)
                break

        test_files = [p for p in facts["file_tree"] if _is_test_file(p)]
        machine_local_files = []
        for test_file in test_files:
            content = _get_file_content(repo, test_file, gh)
            if content and _test_touches_machine_local_state(content):
                machine_local_files.append(test_file)
        facts["python_tests_touch_home"] = len(machine_local_files) > 0
        facts["machine_local_test_files"] = machine_local_files

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
    """Pure logic: map facts to the ADR readiness pieces.
    Returns {"<piece>": {"state": "ok"|"missing"|"needs-human", "reason": "..."}, ...}
    """
    plan_out = {}

    # Profile
    if facts.get("profile_exists"):
        plan_out["profile"] = {"state": "ok", "reason": "profile exists in config/projects/"}
    else:
        plan_out["profile"] = {"state": "missing", "reason": "profile not yet created"}

    # Stack detection
    detected_stack = facts.get("detected_stack")
    if detected_stack:
        plan_out["stack"] = {"state": "ok", "reason": f"detected as {detected_stack}"}
    else:
        plan_out["stack"] = {"state": "needs-human", "reason": "no recognised stack markers found; R5, never guess"}

    # Test command (redefined per stack)
    if detected_stack == "swift-package":
        plan_out["test_command"] = {"state": "ok", "reason": "swift test is a SwiftPM convention"}
    elif detected_stack == "xcodegen-app":
        plan_out["test_command"] = {"state": "ok", "reason": "xcodebuild test is standard for Xcode apps"}
    elif detected_stack == "node-electron":
        if facts.get("package_json_scripts", {}).get("test"):
            plan_out["test_command"] = {"state": "ok", "reason": "test script found in package.json"}
        else:
            plan_out["test_command"] = {"state": "needs-human", "reason": "no test script in package.json; R5, never guess"}
    elif detected_stack == "python":
        problems = []
        if not facts.get("has_requirements_file"):
            problems.append("no requirements file (requirements.txt or pyproject.toml)")
        elif not facts.get("requirements_pinned"):
            problems.append("requirements file is unpinned")
        if problems:
            plan_out["test_command"] = {"state": "needs-human", "reason": "; ".join(problems)}
        else:
            plan_out["test_command"] = {"state": "ok", "reason": "pytest is standard for Python"}
    else:
        plan_out["test_command"] = {"state": "needs-human", "reason": "unrecognised stack; cannot determine test command"}

    # CI (data-driven from stack template)
    stacks = _load_stack_templates()
    matched_stack = None
    for stack in stacks:
        if stack.get("name") == detected_stack:
            matched_stack = stack
            break

    test_command_state = plan_out.get("test_command", {}).get("state")
    if test_command_state == "needs-human":
        reason = "cannot wire CI without a known test command"
        if detected_stack == "python" and facts.get("python_tests_touch_home"):
            machine_local_files = facts.get("machine_local_test_files", [])
            files_str = ", ".join(machine_local_files[:3])
            if len(machine_local_files) > 3:
                files_str += f", ... ({len(machine_local_files)} total)"
            reason += f"; tests read machine-local state: {files_str}"
        plan_out["ci"] = {"state": "needs-human", "reason": reason}
    elif detected_stack == "python" and facts.get("python_tests_touch_home"):
        machine_local_files = facts.get("machine_local_test_files", [])
        files_str = ", ".join(machine_local_files[:3])
        if len(machine_local_files) > 3:
            files_str += f", ... ({len(machine_local_files)} total)"
        reason = f"tests read machine-local state: {files_str}"
        plan_out["ci"] = {"state": "needs-human", "reason": reason}
    elif matched_stack:
        ci_markers = matched_stack.get("ci_contains_any", [])
        found_ci = any(marker in facts.get("workflow_contents", "") for marker in ci_markers) if ci_markers else False
        if found_ci or facts.get("workflow_runs_swift_test"):
            plan_out["ci"] = {"state": "ok", "reason": f"CI found running {detected_stack} tests"}
        elif facts.get("has_workflows"):
            plan_out["ci"] = {"state": "needs-human", "reason": "workflow exists but does not run detected stack tests"}
        else:
            plan_out["ci"] = {"state": "missing", "reason": "no CI workflow present"}
    else:
        if facts.get("workflow_runs_swift_test"):
            plan_out["ci"] = {"state": "ok", "reason": "workflow found running tests"}
        elif facts.get("has_workflows"):
            plan_out["ci"] = {"state": "needs-human", "reason": "workflow exists but does not run tests"}
        else:
            plan_out["ci"] = {"state": "missing", "reason": "no CI workflow present"}

    if matched_stack and matched_stack.get("macos_runner") and facts.get("visibility") == "private":
        if "cost_warning" not in plan_out["ci"]:
            plan_out["ci"]["cost_warning"] = "macOS runners cost 10x more on private repos"

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
    if matched_stack:
        required_tools = matched_stack.get("requires_tools", [])
        tools_missing = [t for t in required_tools if not facts.get("tools_installed", {}).get(t)]
        if facts.get("clone_hint_resolves") and not tools_missing:
            plan_out["clone_and_toolchain"] = {
                "state": "ok",
                "reason": "clone exists and all required tools present",
            }
        elif facts.get("clone_hint_resolves") and tools_missing:
            plan_out["clone_and_toolchain"] = {
                "state": "missing",
                "reason": f"clone exists but missing tools: {', '.join(tools_missing)}",
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
    else:
        if facts.get("clone_hint_resolves") and facts.get("swift_installed"):
            plan_out["clone_and_toolchain"] = {
                "state": "ok",
                "reason": "clone exists and swift toolchain present",
            }
        elif facts.get("clone_hint_resolves"):
            plan_out["clone_and_toolchain"] = {
                "state": "missing",
                "reason": "clone exists but toolchain not found; install required tools or add to PATH",
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

    # Generated paths (proposal with confirm flag)
    if matched_stack:
        candidates = matched_stack.get("generated_candidates", [])
        file_tree = facts.get("file_tree", {})
        proposals = []
        for candidate in candidates:
            path = candidate.get("path")
            if path and path in file_tree:
                proposal = dict(candidate)
                proposal["confirm"] = True
                proposals.append(proposal)
        if proposals:
            plan_out["generated_paths"] = {
                "state": "needs-human",
                "reason": "generated files found; confirm which to track",
                "proposals": proposals,
            }
        else:
            plan_out["generated_paths"] = {"state": "ok", "reason": "no tracked generated files detected", "proposals": []}
    else:
        plan_out["generated_paths"] = {"state": "ok", "reason": "no stack detected; skipping generated paths", "proposals": []}

    return plan_out


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
