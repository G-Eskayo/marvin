#!/usr/bin/env python3
"""PreToolUse guard for `gh pr merge`, scoped to one repo semantically.

The settings.json pattern rule (`Bash(gh pr merge * -R G-Eskayo/marvin *)`)
only matches one literal flag ordering -- `-R`/`--repo` can appear before
or after the PR number, and a pure text pattern can't express "this flag's
value is X" independent of position (see permissions.md's own warning on
argument-constraining Bash patterns being fragile). This hook parses the
actual command and checks the repo semantically instead, so it isn't
order-dependent.

Fails open always: anything that isn't recognizably a `gh pr merge` call
targeting exactly ALLOWED_REPO falls through with no output, leaving the
normal permission flow (the settings.json rule, or an ask prompt) to
decide -- this hook only ever adds an allow, never a deny, so a bug here
can make merges need approval again, never merge something unapproved.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_errors import log_hook_error  # noqa: E402

ALLOWED_REPO = "G-Eskayo/marvin"

_MERGE_RE = re.compile(r"^\s*gh\s+pr\s+merge\b")
_REPO_FLAG_RE = re.compile(r"(?:-R|--repo)(?:=|\s+)([^\s]+)")


def _allow_decision() -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": f"gh pr merge targeting {ALLOWED_REPO} (gh_merge_guard.py)",
        }
    }


def check(command: str) -> dict | None:
    if not _MERGE_RE.match(command):
        return None
    match = _REPO_FLAG_RE.search(command)
    if not match or match.group(1) != ALLOWED_REPO:
        return None
    return _allow_decision()


def main() -> None:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        command = str((data.get("tool_input") or {}).get("command") or "")
        decision = check(command)
        if decision is not None:
            sys.stdout.write(json.dumps(decision, ensure_ascii=False, separators=(",", ":")))
    except Exception as exc:
        log_hook_error("gh_merge_guard", "main", exc)


if __name__ == "__main__":
    main()
