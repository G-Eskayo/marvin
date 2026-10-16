"""PreToolUse guard: never hand Gil a file that lives in a throwaway temp dir.

Gil, 2026-10-15, after mock-ups were sent from the session scratchpad again:
"I have no idea where you put those mock ups and why they are not in docs or using
the dashboard". The rule (memory: feedback-use-outbox-not-scratchpad-for-deliverables,
feedback-use-dashboard-docs-not-artifacts) was prose only, so it slipped. This makes it
mechanical: SendUserFile or an Artifact publish of a path under /tmp, /private/tmp or
/var/folders is denied, with the reason naming where the file belongs instead.

Fails open on its own bugs (logs to hook_errors), so a guard defect never blocks work.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_errors import log_hook_error  # noqa: E402

_TEMP_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")

REASON = (
    "That file is in a throwaway temp/scratchpad dir that Gil can't find later. Move it first: "
    "docs Gil reviews (plans, mock-ups, proposals) go to ~/.agents/docs/plans/<topic>-YYYY-MM-DD.md, "
    "with images in ~/.agents/docs/screenshots/<ticket>-*.png, committed and pushed to main so the "
    "dashboard Docs tab shows them (and the mock-ups go on the ticket); other deliverables go to "
    "~/.claude/outbox/<topic>/. (deliverable_location_guard.py)"
)


def _is_temp(path: object) -> bool:
    if not isinstance(path, str) or not path:
        return False
    norm = os.path.normpath(path) + "/"
    return norm.startswith(_TEMP_ROOTS)


def _paths(tool: str, tool_input: dict) -> list:
    if tool == "SendUserFile":
        files = tool_input.get("files")
        return files if isinstance(files, list) else []
    if tool == "Artifact" and tool_input.get("action", "publish") == "publish":
        paths = tool_input.get("file_paths")
        return [tool_input.get("file_path")] + (paths if isinstance(paths, list) else [])
    return []


def check(tool: str, tool_input: dict) -> dict | None:
    if not any(_is_temp(p) for p in _paths(tool, tool_input or {})):
        return None
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": REASON,
        }
    }


def main() -> None:
    try:
        data = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))
        decision = check(str(data.get("tool_name") or ""), data.get("tool_input") or {})
        if decision is not None:
            sys.stdout.write(json.dumps(decision, ensure_ascii=False, separators=(",", ":")))
    except Exception as exc:
        log_hook_error("deliverable_location_guard", "main", exc)


if __name__ == "__main__":
    main()
