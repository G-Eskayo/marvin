#!/usr/bin/env python3
"""test_change_rule.py — code that changed without any test changing doesn't pass (ADR 0063 gate 2, #336).

Used by pipeline verify (sandbox_orchestration.execute_ticket) and meant for the direct-commit check too (#337), so
the two gates can never disagree about what counts.

- **code**: source files (by project: MARVIN's lib, skills' scripts, the dashboard's code, brain-map); **tests**: test
  files; **other**: docs, config, data and generated output (never needs a test).
- A pure rename (no content change) and comment-only or blank-line edits aren't code changes; deleting code is.
- Any test change satisfies the rule: it can't prove the test covers the change (review and the mutation check, #339,
  judge that), it only refuses the case that is certainly wrong: code changed and no test did.
- A worktree it can't read fails closed.
"""
from __future__ import annotations
import fnmatch
import re
import subprocess
from pathlib import Path

GENERATED = ("graphify-out/**", "bench/metrics/**", "**/package-lock.json", "**/*.lock")
CODE_EXT = (".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".swift", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".sh")

MARVIN_RULES = {
    "test": ["lib/tests/**", "dashboard/test/**", "**/tests/**", "**/test_*.py", "**/*_test.py", "**/*.test.*", "**/*.spec.*"],
    "code": ["lib/**", "skills/**/scripts/**", "skills/**/*.py", "dashboard/src/**", "dashboard/electron/**",
             "dashboard/webhook-server/**", "dashboard/mobile-backend/**", "brain-map/**", "bin/**"],
    "generated": list(GENERATED),
}
DEFAULT_RULES = {
    "test": ["**/test/**", "**/tests/**", "**/Tests/**", "**/*Tests/**", "**/__tests__/**", "**/test_*.py", "**/*_test.*",
             "**/*.test.*", "**/*.spec.*", "**/*Tests.swift", "**/*Test.swift"],
    "code": ["**/*"],
    "generated": list(GENERATED),
}
_COMMENT = re.compile(r"^\s*(#|//|/\*|\*|\*/|<!--|-->|\"\"\"|''')")


def _match(path: str, patterns) -> bool:
    for p in patterns:
        if fnmatch.fnmatchcase(path, p) or (p.startswith("**/") and fnmatch.fnmatchcase(path, p[3:])):
            return True
    return False


def kind(path: str, rules: dict) -> str:
    """code | test | other"""
    if _match(path, rules.get("generated", [])):
        return "other"
    if _match(path, rules["test"]):
        return "test"
    if _match(path, rules["code"]) and path.endswith(CODE_EXT):
        return "code"
    return "other"


def rules_for_profile(profile: dict | None) -> dict:
    """A project's own code_paths / test_paths, else sensible defaults for any language."""
    if profile and (profile.get("code_paths") or profile.get("test_paths")):
        return {"code": list(profile.get("code_paths") or DEFAULT_RULES["code"]),
                "test": list(profile.get("test_paths") or DEFAULT_RULES["test"]),
                "generated": list(GENERATED) + [g.get("path", g) + "/**" if isinstance(g, dict) else g
                                                for g in profile.get("generated", [])]}
    return DEFAULT_RULES


def _is_code_change(c: dict) -> bool:
    status = (c.get("status") or "M").upper()
    if status.startswith("R") and not c.get("added") and not c.get("removed"):
        return False                       # a pure rename
    lines = [l for l in [*c.get("added", []), *c.get("removed", [])] if l.strip()]
    if status.startswith(("A", "D")) and not lines:
        return status.startswith("D")      # an empty new file isn't code; a deleted file is
    return any(not _COMMENT.match(l) for l in lines)


def check(changes: list[dict], rules: dict) -> tuple[bool, str]:
    code = [c["path"] for c in changes if kind(c["path"], rules) == "code" and _is_code_change(c)]
    tests = [c["path"] for c in changes if kind(c["path"], rules) == "test"]
    if code and not tests:
        shown = ", ".join(code[:5]) + (f" and {len(code) - 5} more" if len(code) > 5 else "")
        return False, (f"Code changed ({shown}) but no test did. Write a test for each case in the ticket's "
                       f"'How we'll try to break it' section first (ADR 0063), then make it pass.")
    return True, "tests changed with the code" if code else "no code changed"


def _git(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, timeout=120).stdout


def changes_in(worktree: Path, base: str = "main") -> list[dict]:
    """Everything that differs from origin/<base> (or <base>): committed, uncommitted and untracked."""
    ref = f"origin/{base}"
    try:
        _git(worktree, "rev-parse", "--verify", "-q", ref)
    except subprocess.CalledProcessError:
        ref = base
    mb = _git(worktree, "merge-base", ref, "HEAD").strip()
    out: dict[str, dict] = {}
    for line in _git(worktree, "diff", "-M", "--name-status", mb).splitlines():
        parts = line.split("\t")
        status, path = parts[0], parts[-1]
        out[path] = {"path": path, "status": status, "added": [], "removed": []}
    for line in _git(worktree, "ls-files", "--others", "--exclude-standard").splitlines():
        out[line] = {"path": line, "status": "A", "added": [], "removed": []}
        try:
            out[line]["added"] = (Path(worktree) / line).read_text(errors="replace").splitlines()[:2000]
        except OSError:
            pass
    patch = _git(worktree, "diff", "-M", "-U0", mb)
    current = None
    for l in patch.splitlines():
        if l.startswith("+++ "):
            current = l[6:] if l.startswith("+++ b/") else None
        elif current and current in out and l.startswith("+") and not l.startswith("+++"):
            out[current]["added"].append(l[1:])
        elif current and current in out and l.startswith("-") and not l.startswith("---"):
            out[current]["removed"].append(l[1:])
    for path, c in out.items():
        if c["status"].startswith("D") and not c["removed"]:
            c["removed"] = ["(deleted)"]
    return list(out.values())


def staged_changes(repo: Path) -> list[dict]:
    """What is staged for the next commit (the direct-commit check, #337)."""
    out: dict[str, dict] = {}
    for line in _git(repo, "diff", "--cached", "-M", "--name-status").splitlines():
        parts = line.split("\t")
        out[parts[-1]] = {"path": parts[-1], "status": parts[0], "added": [], "removed": []}
    current = None
    for l in _git(repo, "diff", "--cached", "-M", "-U0").splitlines():
        if l.startswith("+++ "):
            current = l[6:] if l.startswith("+++ b/") else None
        elif current in out and l.startswith("+") and not l.startswith("+++"):
            out[current]["added"].append(l[1:])
        elif current in out and l.startswith("-") and not l.startswith("---"):
            out[current]["removed"].append(l[1:])
    for c in out.values():
        if c["status"].startswith("D") and not c["removed"]:
            c["removed"] = ["(deleted)"]
    return list(out.values())


def check_worktree(worktree: Path, base: str, rules: dict) -> tuple[bool, str]:
    try:
        return check(changes_in(Path(worktree), base), rules)
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        return False, f"could not read what changed ({e}); refusing rather than guessing"
