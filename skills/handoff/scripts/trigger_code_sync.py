#!/usr/bin/env python3
"""PostToolUse hook: when a handoff doc is written to ~/.claude/handoffs/,
trigger code_sync.py's push — session/topic-switch moments are the natural
checkpoint for "commit and push whatever's changed in ~/.agents." See
docs/adr/0021-bidirectional-code-sync-scoped-commit-exception.md.

Same file-matching logic as emit-resume-prompt.py (deliberately duplicated,
not factored out — two ~15-line matchers reading the same stdin shape isn't
worth a shared helper yet). Never errors the originating tool: any failure
exits silently, matching every other PostToolUse hook's fail-open contract.
"""
import json
import subprocess
import sys
from pathlib import Path


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    if payload.get("tool_name", "") not in ("Write", "Edit", "MultiEdit"):
        return
    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return

    p = Path(fp)
    handoff_dir = Path.home() / ".claude" / "handoffs"
    try:
        in_handoffs = handoff_dir.resolve() in [d.resolve() for d in p.parents]
    except Exception:
        in_handoffs = False
    if not in_handoffs or p.suffix.lower() != ".md":
        return

    venv_python = Path.home() / ".agents" / "venv" / "bin" / "python"
    code_sync = Path.home() / ".agents" / "lib" / "code_sync.py"
    try:
        subprocess.run([str(venv_python), str(code_sync), "push"], timeout=60, capture_output=True)
    except Exception:
        pass


if __name__ == "__main__":
    main()
