#!/usr/bin/env python3
"""Project onboarding: transform a repo into a fully wired MARVIN project.

This module handles both the read-only 'plan' stage (ticket #141) and the 'apply' stage
(ticket #146 for --local, ticket #147 for --pr): gather facts about a project, produce a
readiness plan, and optionally apply local changes (labels, board, profile) or open a PR
with agent wiring. Facts are gathered once per repo via `inspect()`, and `plan()` is pure
over those facts. Apply modifies local state (--local) or remote state (--pr).

    project_onboard.py plan <owner/repo>              outputs JSON readiness plan
    project_onboard.py apply <owner/repo> --local     applies local changes (labels, board, profile)
    project_onboard.py apply <owner/repo> --pr        opens a PR with docs/agents and CI wiring
"""
from __future__ import annotations

import base64
import difflib
import fnmatch
import json
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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
ONBOARDING_DIR = Path.home() / ".claude" / "onboarding"


def onboarding_path(repo: str, dir: Path | None = None) -> Path:
    """Path to the onboarding plan file for a repo: ~/.claude/onboarding/<repo_name>.json"""
    dir = dir or ONBOARDING_DIR
    repo_name = repo.split("/")[1]
    return dir / f"{repo_name}.json"


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

    return plan_out


def write_onboarding_plan(repo: str, plan_out: dict, dir: Path | None = None) -> None:
    """Write the onboarding plan to ~/.claude/onboarding/<repo_name>.json"""
    dir = dir or ONBOARDING_DIR
    path = onboarding_path(repo, dir=dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "repo": repo,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pieces": plan_out,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")


def refresh_onboarding_plan(repo: str, gh=_gh, dir: Path | None = None) -> None:
    """Refresh the onboarding plan: inspect, plan, write. Raises on failure."""
    facts = inspect(repo, gh=gh)
    plan_out = plan(facts)
    write_onboarding_plan(repo, plan_out, dir=dir)


def refresh_all_onboarding_plans(repos: list[str], gh=_gh, dir: Path | None = None) -> dict:
    """Refresh onboarding plans for all repos, logging failures without blocking successes.
    Returns {"ok": [repos...], "failed": [(repo, reason), ...]}.
    On failure, leaves the existing file untouched (never overwrites with error state)."""
    dir = dir or ONBOARDING_DIR
    ok = []
    failed = []
    for repo in repos:
        try:
            refresh_onboarding_plan(repo, gh=gh, dir=dir)
            ok.append(repo)
        except Exception as e:  # noqa: BLE001
            failed.append((repo, str(e)))
    return {"ok": ok, "failed": failed}


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


def _missing_agent_doc_files(file_tree: dict) -> list[str]:
    """Return which of docs/agents/{issue-tracker,triage-labels,domain}.md are absent."""
    required = {
        "docs/agents/issue-tracker.md",
        "docs/agents/triage-labels.md",
        "docs/agents/domain.md",
    }
    return sorted(f for f in required if f not in file_tree)


def _render_issue_tracker_doc(repo: str) -> str:
    """Render issue-tracker.md for GitHub (deterministic, no prompting)."""
    return f"""# Issue Tracker

**Type**: GitHub Issues
**Repo**: {repo}
**CLI**: `gh` (must be authenticated — `gh auth status` to check)

## Conventions

- Create an issue: `gh issue create --title "..." --body "..." [--label ...]`
- Read an issue: `gh issue view <number>`
- Comment on an issue: `gh issue comment <number> --body "..."`
- List open issues: `gh issue list`
- Apply/remove labels: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`

## Consumer rules

- `to-issues` creates new issues via `gh issue create`; it does not assume any project-board
  automation exists — if this repo uses one, note it here so the skill knows to also add the
  issue to the right project/column.
- `triage` reads open issues via `gh issue list` and applies labels from
  `docs/agents/triage-labels.md` — it does not invent label names not defined there.
- Never force-push, close, or delete issues without explicit user confirmation — these skills
  only create/comment/label by default.
"""


def _render_triage_labels_doc() -> str:
    """Render triage-labels.md with default label names."""
    return """# Triage Labels

The `triage` skill moves an issue through five canonical roles. Each maps to a string this repo
actually uses — override any that differ from the default.

| Canonical role   | This repo's label/status | Meaning                                          |
|-------------------|---------------------------|---------------------------------------------------|
| `needs-triage`    | `needs-triage`            | Maintainer needs to evaluate                       |
| `needs-info`      | `needs-info`              | Waiting on reporter for more detail                |
| `ready-for-agent` | `ready-for-agent`         | Fully specified — an AFK agent can pick this up with no further human context |
| `ready-for-human` | `ready-for-human`         | Needs human implementation, not agent-suitable     |
| `wontfix`         | `wontfix`                 | Will not be actioned                               |

## Consumer rules

- `triage` only ever applies one of these five — if a case doesn't clearly fit one, that's a sign
  the issue needs more information (`needs-info`), not a reason to invent a sixth label.
- If this repo's issue tracker has no existing label set, the defaults in the right column are
  fine as-is — create them as real labels/tags rather than leaving them purely conventional.
- `ready-for-agent` specifically means "no further human context needed" — don't apply it to an
  issue that's well-written but still assumes tribal knowledge only a human maintainer has.
"""


def _render_domain_doc() -> str:
    """Render domain.md for single-context layout (deterministic, no prompting)."""
    return """# Domain Docs

**Layout**: Single-context

## Single-context (most repos)

- `CONTEXT.md` at the repo root — the domain glossary. Devoid of implementation details; terms
  and their meanings only.
- `docs/adr/` at the repo root — one file per architectural decision, numbered sequentially.

## Consumer rules

- `improve-codebase-architecture`, `diagnose`, and `tdd` read `CONTEXT.md` for domain vocabulary
  before proposing names for new modules/concepts — a suggestion using a term not in `CONTEXT.md`
  should either match existing language or trigger adding the new term, not invent parallel
  vocabulary.
- These skills read `docs/adr/` for past decisions in the area being touched, and should not
  re-litigate a settled decision without flagging that they're doing so and why.
- If `CONTEXT.md`/`docs/adr/` don't exist yet, that's fine — `grill-with-docs` creates them
  lazily, only when the first term/decision actually resolves. Don't scaffold empty files
  preemptively.
"""


def _render_claude_md_block() -> str:
    """Render the CLAUDE.md ## Agent skills block."""
    return """## Agent skills

### Issue tracker

GitHub Issues on `{repo}`, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, all real labels on this repo with default naming (no overrides).
See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
"""


def _ci_yml_for_stack(detected_stack: str | None) -> str | None:
    """Read ci.yml from config/onboarding/<stack>/, return content or None."""
    if not detected_stack:
        return None
    ci_path = CONFIG_ONBOARDING / detected_stack / "ci.yml"
    if ci_path.exists():
        try:
            return ci_path.read_text()
        except OSError:
            pass
    return None


def _check_workflow_scope(run=subprocess.run) -> bool:
    """Check if gh token has 'workflow' scope. Returns True if present, False if missing.
    Raises on unexpected errors."""
    try:
        result = run(["gh", "auth", "status"], capture_output=True, text=True, timeout=TIMEOUT)
        if result.returncode == 0:
            output = result.stdout + result.stderr
            return "workflow" in output.split("Token scopes:")[-1] if "Token scopes:" in output else False
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _pr_files_to_write(repo: str, facts: dict, plan_out: dict) -> dict[str, str]:
    """Compute which files should be written to for --pr. Only includes files that are missing
    or need updating (AC1). Never includes .github/workflows/ci.yml when stack is unknown (R5).
    Note: CLAUDE.md handling is deferred to _apply_pr for proper merging."""
    files = {}

    missing_agent_docs = _missing_agent_doc_files(facts.get("file_tree", {}))

    if "docs/agents/issue-tracker.md" in missing_agent_docs:
        files["docs/agents/issue-tracker.md"] = _render_issue_tracker_doc(repo)

    if "docs/agents/triage-labels.md" in missing_agent_docs:
        files["docs/agents/triage-labels.md"] = _render_triage_labels_doc()

    if "docs/agents/domain.md" in missing_agent_docs:
        files["docs/agents/domain.md"] = _render_domain_doc()

    ci_state = plan_out.get("ci", {}).get("state")
    if ci_state == "missing":
        detected_stack = facts.get("detected_stack")
        ci_content = _ci_yml_for_stack(detected_stack)
        if ci_content:
            files[".github/workflows/ci.yml"] = ci_content

    return files


def _merge_claude_md_block(repo: str, facts: dict, repo_path: Path) -> bool:
    """Merge Agent skills block into CLAUDE.md or AGENTS.md (whichever exists first).
    Returns True if a change was made, False if already present."""
    block = _render_claude_md_block().format(repo=repo)

    candidates = ["CLAUDE.md", "AGENTS.md"]
    target_file = None

    for candidate in candidates:
        path = repo_path / candidate
        if path.exists():
            target_file = path
            break

    if not target_file:
        (repo_path / "CLAUDE.md").write_text(block + "\n")
        return True

    content = target_file.read_text()
    if "## Agent skills" in content:
        return False

    lines = content.split("\n")
    if lines and lines[0].startswith("#"):
        lines.insert(1, "")
        lines.insert(2, block)
    else:
        lines.insert(0, block)

    target_file.write_text("\n".join(lines))
    return True


def _apply_pr(repo: str, facts: dict, plan_out: dict, *, gh=_gh,
              run=subprocess.run) -> dict:
    """Apply PR mode: clone repo, create/update onboarding branch, write files, open PR.
    Returns {"action": "created"|"updated"|"unchanged"|"needs-human", "pr_url": ..., ...}
    AC2: checks workflow scope before any git operations.
    AC3: idempotent — reuses existing PR if one exists.
    AC4: never commits/pushes to default branch, uses fixed branch name."""
    files_to_write = _pr_files_to_write(repo, facts, plan_out)

    need_claude_md = not facts.get("has_claude_md_skills")

    if not files_to_write and not need_claude_md:
        return {"action": "unchanged", "pr_url": None, "branch": "onboarding/agent-wiring"}

    if not _check_workflow_scope(run=run):
        return {
            "action": "needs-human",
            "reason": "gh token missing 'workflow' scope; run: gh auth refresh -h github.com -s workflow",
            "pr_url": None,
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        repo_path = tmpdir_path / "repo"

        try:
            run(["gh", "repo", "clone", repo, str(repo_path)], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            return {
                "action": "needs-human",
                "reason": f"failed to clone {repo}",
                "pr_url": None,
            }

        default_branch = facts.get("default_branch", "main")
        branch_name = "onboarding/agent-wiring"

        try:
            run(["git", "fetch", "origin", default_branch], cwd=repo_path, check=True, capture_output=True)
            run(["git", "checkout", "-B", branch_name, f"origin/{default_branch}"],
                cwd=repo_path, check=True, capture_output=True)
        except subprocess.CalledProcessError:
            return {
                "action": "needs-human",
                "reason": f"failed to create branch {branch_name}",
                "pr_url": None,
            }

        for file_path, content in files_to_write.items():
            full_path = repo_path / file_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content)

        claude_changed = False
        if need_claude_md:
            claude_changed = _merge_claude_md_block(repo, facts, repo_path)

        try:
            status_result = run(["git", "status", "--porcelain"], cwd=repo_path,
                               check=True, capture_output=True, text=True)
            if not status_result.stdout.strip():
                return {"action": "unchanged", "pr_url": None, "branch": branch_name}

            run(["git", "add", "-A"], cwd=repo_path, check=True, capture_output=True)
            run(["git", "commit", "-m", "Wire agent skills: add docs/agents and CI workflow"],
                cwd=repo_path, check=True, capture_output=True)
            run(["git", "push", "-u", "--force-with-lease", "origin", branch_name],
                cwd=repo_path, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            return {
                "action": "needs-human",
                "reason": f"git operation failed: {e}",
                "pr_url": None,
            }

        title = "Wire agent skills: add docs/agents and CI workflow"
        body = "Onboarding PR: adds `docs/agents/` files and `.github/workflows/ci.yml` to set up MARVIN agent integration."

        try:
            result = run(["gh", "pr", "create", "--repo", repo, "--title", title, "--body", body,
                         "--base", default_branch, "--head", branch_name],
                        check=True, capture_output=True, text=True)
            pr_url = result.stdout.strip()
            return {"action": "created", "pr_url": pr_url, "branch": branch_name}
        except subprocess.CalledProcessError as e:
            if "already exists" in (e.stderr or ""):
                try:
                    view_result = run(["gh", "pr", "view", branch_name, "--repo", repo,
                                      "--json", "url", "-q", ".url"],
                                     check=True, capture_output=True, text=True)
                    pr_url = view_result.stdout.strip()
                    run(["gh", "pr", "edit", pr_url, "--body", body],
                       check=True, capture_output=True)
                    return {"action": "updated", "pr_url": pr_url, "branch": branch_name}
                except subprocess.CalledProcessError:
                    return {
                        "action": "needs-human",
                        "reason": "PR already exists but could not be updated",
                        "pr_url": None,
                    }
            return {
                "action": "needs-human",
                "reason": f"PR creation failed: {e.stderr or e}",
                "pr_url": None,
            }


def apply(repo: str, facts: dict | None = None, *, profiles_dir: Path | None = None,
          registry_path: Path | None = None, gh=_gh) -> dict:
    """Apply local changes: create missing labels, register board, draft profile.
    Idempotent: running twice produces no changes on the second run.

    Returns: {"labels": {...}, "board": {...}, "profile": {...}} with per-piece
    "action" (created/unchanged/conflict/needs-human) and "diff" where relevant.
    Only writes profile file when action is "created" (keeps _apply_profile pure).
    """
    if facts is None:
        facts = inspect(repo, gh=gh)

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

    return {
        "labels": labels_result,
        "board": board_result,
        "profile": profile_result,
    }


def main():
    """CLI entry point: project_onboard.py plan|apply <owner/repo> [--local|--pr]"""
    if len(sys.argv) < 3:
        sys.exit("usage: project_onboard.py plan <owner/repo> | apply <owner/repo> [--local|--pr]")

    cmd = sys.argv[1]
    repo = sys.argv[2]

    if cmd == "plan":
        if len(sys.argv) != 3:
            sys.exit("usage: project_onboard.py plan <owner/repo>")
        facts = inspect(repo)
        result = plan(facts)
        print(json.dumps(result, indent=2))

    elif cmd == "apply":
        if len(sys.argv) != 4:
            sys.exit("usage: project_onboard.py apply <owner/repo> [--local|--pr]")

        mode = sys.argv[3]
        if mode not in ("--local", "--pr"):
            sys.exit("usage: project_onboard.py apply <owner/repo> [--local|--pr]")

        facts = inspect(repo)
        plan_out = plan(facts)

        if mode == "--local":
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

        elif mode == "--pr":
            result = _apply_pr(repo, facts, plan_out)

            print(f"\nOnboarding apply for {repo} --pr:\n")
            action = result["action"]

            if action == "created":
                print(f"  PR created: {result['pr_url']}")
                print(f"  branch: {result['branch']}")
            elif action == "updated":
                print(f"  PR updated: {result['pr_url']}")
                print(f"  branch: {result['branch']}")
            elif action == "unchanged":
                print(f"  nothing to commit (all files already present)")
                print(f"  branch: {result['branch']}")
            elif action == "needs-human":
                print(f"  needs-human — {result.get('reason', 'unknown error')}")

            print()

    else:
        sys.exit(f"unknown command: {cmd}\nusage: project_onboard.py plan|apply <owner/repo>")


if __name__ == "__main__":
    main()
