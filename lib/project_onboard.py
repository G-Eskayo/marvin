#!/usr/bin/env python3
"""Project onboarding: transform a repo into a fully wired MARVIN project.

Gathers facts, produces a readiness plan, and applies three classes of changes:
1. Local: labels, board, profile (ticket #146)
2. Repo PR: CI workflow, agent docs, CLAUDE.md block (ticket #147)

Facts are gathered once per repo via `inspect()`, and `plan()` is pure over those facts.

    project_onboard.py plan <owner/repo>              outputs JSON readiness plan
    project_onboard.py apply <owner/repo> [--local] [--pr]  applies selected pieces
"""
from __future__ import annotations

import base64
import difflib
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
TRIAGE_LABEL_COLORS = {
    "needs-triage": "d4c5f9",
    "needs-info": "ffd700",
    "ready-for-agent": "90ee90",
    "ready-for-human": "ffb6c1",
    "wontfix": "808080",
}
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


def _check_workflow_scope(gh=_gh) -> dict:
    """Check if gh has 'workflow' scope. Returns {"has_scope": bool, "message": str}.
    Message includes the fix ('gh auth refresh -h github.com -s workflow') when missing."""
    try:
        result = subprocess.run(
            ["gh", "auth", "status"], capture_output=True, text=True, timeout=TIMEOUT
        )
        output = result.stdout + result.stderr
        if "workflow" in output and result.returncode == 0:
            return {"has_scope": True, "message": "workflow scope present"}
        else:
            return {
                "has_scope": False,
                "message": "workflow scope missing; to enable: gh auth refresh -h github.com -s workflow",
            }
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {
            "has_scope": False,
            "message": "gh auth status failed; check authentication and try again",
        }


def _matches_detect_rule(file_tree: dict, rule: dict) -> bool:
    """Check if a file tree matches a detection rule."""
    if "file_glob" in rule:
        glob_pattern = rule["file_glob"]
        for path in file_tree:
            if fnmatch.fnmatch(path, glob_pattern):
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
        plan_out["ci"] = {"state": "needs-human", "reason": "cannot wire CI without a known test command"}
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

    # Repo PR: CI workflow, agent docs, CLAUDE.md block
    if not detected_stack:
        plan_out["repo_pr"] = {"state": "needs-human", "reason": "no recognised stack; R5, never guess"}
    elif not matched_stack:
        plan_out["repo_pr"] = {"state": "needs-human", "reason": f"no onboarding template for {detected_stack}"}
    else:
        # Check if all files are present
        has_ci = ".github/workflows/ci.yml" in facts.get("file_tree", {})
        has_agent_docs = facts.get("has_agent_docs", False)
        has_claude_skills = facts.get("has_claude_md_skills", False)

        if has_ci and has_agent_docs and has_claude_skills:
            plan_out["repo_pr"] = {"state": "ok", "reason": "CI workflow, agent docs, and CLAUDE.md block present"}
        elif test_command_state == "needs-human":
            plan_out["repo_pr"] = {"state": "needs-human", "reason": "cannot wire CI without a known test command"}
        else:
            plan_out["repo_pr"] = {"state": "missing", "reason": "missing: repo PR files (CI, agent docs, or CLAUDE.md block)"}

    return plan_out


def _apply_labels(repo: str, facts: dict, gh=_gh) -> dict:
    """Create missing triage labels. Returns {"action": "created"|"unchanged", "labels": [names...]}.
    Idempotent: gh label create is only called for genuinely-missing names."""
    existing = set(facts.get("labels", []))
    created = []

    for label_name in TRIAGE_LABELS:
        if label_name not in existing:
            color = TRIAGE_LABEL_COLORS[label_name]
            cmd = ["label", "create", label_name, "--repo", repo, "--color", color]
            gh(cmd)
            created.append(label_name)

    return {
        "action": "created" if created else "unchanged",
        "labels": created,
    }


def _apply_board(repo: str, facts: dict, registry_path: Path | None = None) -> dict:
    """Register board via board_registry.ensure_board(). Idempotent."""
    result = br.ensure_board(repo, path=registry_path)
    return {
        "action": "created" if result.get("created") else "unchanged",
        "board": result.get("board"),
    }


def _apply_profile(repo: str, facts: dict, profiles_dir: Path | None = None) -> dict:
    """Draft profile from stack template, show diff vs. existing, handle conflicts.
    Returns {"action": "created"|"unchanged"|"conflict"|"needs-human", "diff": str, "profile": dict}.
    Never overwrites an edited profile."""
    profiles_dir = profiles_dir or pp.PROFILES_DIR
    repo_name = repo.split("/")[1]
    profile_path = profiles_dir / f"{repo_name}.json"

    # Determine stack
    detected_stack = facts.get("detected_stack")
    if not detected_stack:
        return {
            "action": "needs-human",
            "reason": "no recognised stack; R5, never guess",
            "diff": "",
        }

    # Load template
    template_path = CONFIG_ONBOARDING / detected_stack / "profile.json"
    if not template_path.exists():
        return {
            "action": "needs-human",
            "reason": f"no onboarding template for {detected_stack}",
            "diff": "",
        }

    try:
        with open(template_path) as f:
            template = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {
            "action": "needs-human",
            "reason": f"template could not be loaded: {template_path}",
            "diff": "",
        }

    # Build skeleton
    skeleton = {
        "repo": repo,
        "base_branch": facts.get("default_branch", "main"),
        "clone_hints": [],
        "dispatch": "off",
        "merge_from_dashboard": False,
        "verify": [],
    }

    # Merge template's profile_fragment onto skeleton
    draft = skeleton.copy()
    profile_fragment = template.get("profile_fragment", {})
    if isinstance(profile_fragment, dict):
        draft.update(profile_fragment)

    # Force dispatch and merge_from_dashboard to safe defaults (R2, AC3)
    draft["dispatch"] = "off"
    draft["merge_from_dashboard"] = False

    # Validate the draft
    try:
        draft = pp._validate(draft, f"draft profile for {repo}")
    except (ValueError, TypeError):
        return {
            "action": "needs-human",
            "reason": "profile validation failed",
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
                "diff": "",
            }

        # Compare: if identical, it's unchanged; if different, it's a conflict
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


def _get_seed_template(template_name: str) -> str:
    """Load a seed template from skills/setup-matt-pocock-skills/. Return empty string on failure."""
    skills_dir = Path(__file__).resolve().parent.parent / "skills" / "setup-matt-pocock-skills"
    template_path = skills_dir / f"{template_name}.md"
    if template_path.exists():
        content = template_path.read_text()
        # Extract the markdown content from inside the triple backticks
        lines = content.split("\n")
        in_code = False
        extracted = []
        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                extracted.append(line)
        return "\n".join(extracted)
    return ""


def _apply_repo_pr(repo: str, facts: dict, *, worktree: Path | None = None, gh=_gh) -> dict:
    """Create PR with CI workflow, agent docs, and CLAUDE.md block.
    Returns {"action": "created"|"updated"|"unchanged"|"needs-human"|"conflict", ...}.
    Checks workflow scope before any git operation (AC2)."""

    # Detect stack
    detected_stack = facts.get("detected_stack")
    if not detected_stack:
        return {
            "action": "needs-human",
            "reason": "no recognised stack; R5, never guess",
            "files": [],
        }

    # Check if template exists
    stacks = _load_stack_templates()
    matched_stack = None
    for stack in stacks:
        if stack.get("name") == detected_stack:
            matched_stack = stack
            break

    if not matched_stack:
        return {
            "action": "needs-human",
            "reason": f"no onboarding template for {detected_stack}",
            "files": [],
        }

    # Check workflow scope BEFORE any git operation (AC2)
    scope_check = _check_workflow_scope()
    if not scope_check["has_scope"]:
        return {
            "action": "needs-human",
            "reason": scope_check["message"],
            "files": [],
        }

    # Load profile to get clone hints
    profile = pp.load_profile(repo)
    if not profile or not profile.get("clone_hints"):
        return {
            "action": "needs-human",
            "reason": "clone required to prepare PR; no profile with clone_hints found",
            "files": [],
        }

    # Resolve clone path
    clone_path = None
    for hint in profile.get("clone_hints", []):
        if Path(hint).exists():
            clone_path = Path(hint)
            break

    if not clone_path:
        return {
            "action": "needs-human",
            "reason": "clone required to prepare PR; no resolvable clone_hints",
            "files": [],
        }

    try:
        # Determine what files are missing
        file_tree = facts.get("file_tree", {})
        has_ci = ".github/workflows/ci.yml" in file_tree
        has_agent_docs = facts.get("has_agent_docs", False)
        has_claude_skills = facts.get("has_claude_md_skills", False)

        # If everything exists, return unchanged
        if has_ci and has_agent_docs and has_claude_skills:
            return {"action": "unchanged", "files": []}

        # Build the list of files to create
        files_to_create = {}

        # CI workflow
        if not has_ci:
            ci_path = CONFIG_ONBOARDING / detected_stack / "ci.yml"
            if ci_path.exists():
                files_to_create[".github/workflows/ci.yml"] = ci_path.read_text()

        # Agent docs
        if not has_agent_docs:
            # issue-tracker.md - use GitHub variant since we're using gh CLI
            issue_tracker = _get_seed_template("issue-tracker-github")
            if issue_tracker:
                files_to_create["docs/agents/issue-tracker.md"] = issue_tracker

            # triage-labels.md
            triage_labels = _get_seed_template("triage-labels")
            if triage_labels:
                files_to_create["docs/agents/triage-labels.md"] = triage_labels

            # domain.md - single-context layout
            domain = _get_seed_template("domain.md")
            if domain:
                files_to_create["docs/agents/domain.md"] = domain

        # CLAUDE.md block
        if not has_claude_skills:
            claude_block = """## Agent skills

### Issue tracker

GitHub Issues on `{repo}`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, all real labels on this repo with default naming (no overrides).
See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
""".format(repo=repo)
            files_to_create["CLAUDE.md"] = claude_block

        # Clone and prepare branch
        default_branch = facts.get("default_branch", "main")
        branch_name = "marvin-onboarding"

        try:
            subprocess.run(
                ["git", "-C", str(clone_path), "fetch", "origin"],
                capture_output=True, text=True, timeout=60, check=False
            )
        except Exception:
            pass

        # Create/reset branch from origin/<default_branch>
        try:
            subprocess.run(
                ["git", "-C", str(clone_path), "checkout", "-B", branch_name, f"origin/{default_branch}"],
                capture_output=True, text=True, timeout=60, check=True
            )
        except subprocess.CalledProcessError:
            return {
                "action": "needs-human",
                "reason": f"could not create/reset branch {branch_name}",
                "files": [],
            }

        # Write files to clone
        for file_path, content in files_to_create.items():
            target_path = clone_path / file_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content)

        # Stage only the files we created (AC1)
        try:
            subprocess.run(
                ["git", "-C", str(clone_path), "add"] + list(files_to_create.keys()),
                capture_output=True, text=True, timeout=60, check=True
            )
        except subprocess.CalledProcessError:
            return {
                "action": "needs-human",
                "reason": "could not stage files",
                "files": [],
            }

        # Check if there are actual changes to commit
        status_result = subprocess.run(
            ["git", "-C", str(clone_path), "status", "--short"],
            capture_output=True, text=True, timeout=60, check=True
        )
        if not status_result.stdout.strip():
            return {"action": "unchanged", "files": []}

        # Commit
        try:
            subprocess.run(
                ["git", "-C", str(clone_path), "commit", "-m",
                 "Onboarding: add CI workflow, agent docs, CLAUDE.md block"],
                capture_output=True, text=True, timeout=60, check=True
            )
        except subprocess.CalledProcessError as e:
            return {
                "action": "needs-human",
                "reason": f"could not commit: {e.stderr or 'unknown error'}",
                "files": [],
            }

        # Push to remote
        try:
            subprocess.run(
                ["git", "-C", str(clone_path), "push", "origin", f"{branch_name}:{branch_name}"],
                capture_output=True, text=True, timeout=60, check=True
            )
        except subprocess.CalledProcessError as e:
            # Check if remote branch has unpushed commits
            if "non-fast-forward" in (e.stderr or ""):
                return {
                    "action": "conflict",
                    "reason": "remote branch has commits not from this process",
                    "files": list(files_to_create.keys()),
                }
            return {
                "action": "needs-human",
                "reason": f"could not push: {e.stderr or 'unknown error'}",
                "files": list(files_to_create.keys()),
            }

        # Open or update PR
        try:
            result = subprocess.run(
                ["gh", "pr", "create", "--repo", repo, "--base", default_branch,
                 "--head", branch_name, "--title", "Onboarding: add CI, agent docs, CLAUDE.md",
                 "--body", "Automated onboarding changes: CI workflow, agent documentation, and CLAUDE.md skills block."],
                capture_output=True, text=True, timeout=60, check=True
            )
            pr_url = result.stdout.strip()
            return {
                "action": "created",
                "pr_url": pr_url,
                "files": list(files_to_create.keys()),
            }
        except subprocess.CalledProcessError as e:
            if "already exists" not in (e.stderr or ""):
                return {
                    "action": "needs-human",
                    "reason": f"could not create PR: {e.stderr or 'unknown error'}",
                    "files": list(files_to_create.keys()),
                }
            # PR already exists, get its URL
            try:
                view_result = subprocess.run(
                    ["gh", "pr", "view", branch_name, "--repo", repo, "--json", "url", "-q", ".url"],
                    capture_output=True, text=True, timeout=60, check=True
                )
                pr_url = view_result.stdout.strip()
                return {
                    "action": "updated",
                    "pr_url": pr_url,
                    "files": list(files_to_create.keys()),
                }
            except subprocess.CalledProcessError:
                return {
                    "action": "needs-human",
                    "reason": "PR exists but could not retrieve URL",
                    "files": list(files_to_create.keys()),
                }

    except Exception as e:
        return {
            "action": "needs-human",
            "reason": f"unexpected error: {str(e)}",
            "files": [],
        }


def apply(repo: str, facts: dict | None = None, *, profiles_dir: Path | None = None,
          registry_path: Path | None = None, local: bool = False, pr: bool = False, gh=_gh) -> dict:
    """Apply local and/or repo PR changes. Idempotent: running twice produces no changes on second run.

    If local=True: create missing labels, register board, draft profile.
    If pr=True: create PR with CI workflow, agent docs, and CLAUDE.md block.

    Returns: {"labels": {...}, "board": {...}, "profile": {...}, "repo_pr": {...}} with per-piece
    "action" and "diff"/"pr_url" where relevant.
    """
    if facts is None:
        facts = inspect(repo, gh=gh)

    result = {}

    if local:
        labels_result = _apply_labels(repo, facts, gh=gh)
        board_result = _apply_board(repo, facts, registry_path=registry_path)
        profile_result = _apply_profile(repo, facts, profiles_dir=profiles_dir)

        # Write profile to disk only if it was created (idempotent)
        if profile_result.get("action") == "created":
            profiles_dir = profiles_dir or pp.PROFILES_DIR
            repo_name = repo.split("/")[1]
            profile_path = profiles_dir / f"{repo_name}.json"
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            profile_text = json.dumps(profile_result["profile"], indent=2) + "\n"
            profile_path.write_text(profile_text)

        result["labels"] = labels_result
        result["board"] = board_result
        result["profile"] = profile_result

    if pr:
        repo_pr_result = _apply_repo_pr(repo, facts, gh=gh)
        result["repo_pr"] = repo_pr_result

    return result


def main():
    """CLI entry point: project_onboard.py plan <owner/repo> | apply <owner/repo> [--local] [--pr]"""
    if len(sys.argv) < 3:
        sys.exit("usage: project_onboard.py plan <owner/repo> | apply <owner/repo> [--local] [--pr]")

    cmd = sys.argv[1]
    repo = sys.argv[2]

    if cmd == "plan":
        if len(sys.argv) != 3:
            sys.exit("usage: project_onboard.py plan <owner/repo>")
        facts = inspect(repo)
        result = plan(facts)
        print(json.dumps(result, indent=2))

    elif cmd == "apply":
        if len(sys.argv) < 3:
            sys.exit("usage: project_onboard.py apply <owner/repo> [--local] [--pr]")

        # Parse flags
        local = "--local" in sys.argv
        pr = "--pr" in sys.argv

        if not local and not pr:
            sys.exit("usage: project_onboard.py apply <owner/repo> [--local] [--pr]\nat least one flag required")

        facts = inspect(repo)
        result = apply(repo, facts=facts, local=local, pr=pr)

        # Print human-readable summary
        flags_str = " ".join(["--local" if local else "", "--pr" if pr else ""]).strip()
        print(f"\nOnboarding apply for {repo} {flags_str}:\n")

        # Labels
        if "labels" in result:
            labels = result["labels"]
            if labels["action"] == "created":
                print(f"  labels: created {', '.join(labels['labels'])}")
            else:
                print(f"  labels: unchanged")

        # Board
        if "board" in result:
            board = result["board"]
            if board["action"] == "created":
                print(f"  board: created {repo}")
            else:
                print(f"  board: unchanged")

        # Profile
        if "profile" in result:
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

        # Repo PR
        if "repo_pr" in result:
            repo_pr = result["repo_pr"]
            if repo_pr["action"] == "created":
                print(f"  repo_pr: created — {repo_pr.get('pr_url', '')}")
            elif repo_pr["action"] == "updated":
                print(f"  repo_pr: updated — {repo_pr.get('pr_url', '')}")
            elif repo_pr["action"] == "unchanged":
                print(f"  repo_pr: unchanged")
            elif repo_pr["action"] == "conflict":
                print(f"  repo_pr: conflict — {repo_pr.get('reason', '')}")
            else:  # needs-human
                print(f"  repo_pr: needs-human — {repo_pr.get('reason', '')}")

        print()

    else:
        sys.exit(f"unknown command: {cmd}\nusage: project_onboard.py plan|apply <owner/repo>")


if __name__ == "__main__":
    main()
