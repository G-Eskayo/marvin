#!/usr/bin/env python3
"""PostToolUse hook: when memory/docs files are written, check for stale decisions.

Mirrors background_review.py's pattern: hook fires on Write/Edit, spawns a detached
subprocess that runs the actual check logic without stalling the interactive session.
Applies per-path cooldown to avoid checking the same file repeatedly in quick succession.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".agents" / "lib"))
from hook_errors import log_hook_error  # noqa: E402
import host_os  # noqa: E402
import stale_decision_check  # noqa: E402

MEMORY_DIR = host_os.memory_dir()
AGENTS_DIR = Path.home() / ".agents"

# Use temp directory for lock/log, not the synced repo
LOCK_DIR = Path(tempfile.gettempdir()) / "marvin_stale_decision_check"
LOCK_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOCK_DIR / "hook.log"



def run_check(file_path: str) -> None:
    """Run the check synchronously (only called from the detached relaunch).

    Writes to a log file with start/end markers so the hook chain can see
    success/failure even though the detached process runs without anyone watching.
    """
    try:
        p = Path(file_path)
        if not p.exists():
            return

        # Determine what kind of file this is
        is_memory = p.parent.resolve() == MEMORY_DIR.resolve() and p.name != "MEMORY.md"
        is_context_or_adr = p.name == "CONTEXT.md" or (p.parent.name == "adr" and p.suffix.lower() == ".md")
        is_claude_md = p.name == "CLAUDE.md" and p.parent == Path.home() / ".claude"

        if not (is_memory or is_context_or_adr or is_claude_md):
            return

        with LOG_FILE.open("a") as log:
            log.write(f"\n=== check {datetime.now(timezone.utc).isoformat()} ===\n")
            log.write(f"File: {file_path}\n")
            log.flush()

            try:
                # Read the file content
                content = p.read_text(errors="ignore")

                # Check all file types: memory, CONTEXT.md, ADR, CLAUDE.md
                flags = stale_decision_check.check_claim(p, content)

                log.write(f"Found {len(flags)} flag(s)\n")

                # Write any flags to contradictions.md
                for flag in flags:
                    stale_decision_check._append_flag(flag)
                    log.write(f"  - {flag.issue[:100]}\n")

                log.write(f"=== end (exit 0) ===\n")
            except Exception as e:
                log.write(f"Exception: {type(e).__name__}: {e}\n")
                log.write(f"=== end (exit 1) ===\n")

    except Exception as e:
        log_hook_error("stale_decision_check", f"run_check for {file_path}", e)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--run-check":
        # Relaunched-and-detached mode: run the check
        run_check(sys.argv[2] if len(sys.argv) > 2 else "")
        return

    try:
        payload = json.load(sys.stdin)
    except Exception as e:
        log_hook_error("stale_decision_check", "parsing stdin payload", e)
        return

    # Only trigger on Write/Edit
    if payload.get("tool_name") not in ("Write", "Edit", "MultiEdit"):
        return

    fp = (payload.get("tool_input") or {}).get("file_path", "")
    if not fp:
        return

    p = Path(fp)

    # Check if it's a file we care about
    try:
        # Memory files: in MEMORY_DIR and not MEMORY.md itself
        in_memory = p.parent.resolve() == MEMORY_DIR.resolve() and p.name != "MEMORY.md"
        in_context_md = p.name == "CONTEXT.md"
        in_adr = p.parent.name == "adr" and p.suffix.lower() == ".md"
        in_claude_md = p.name == "CLAUDE.md" and p.parent == Path.home() / ".claude"
    except Exception as e:
        log_hook_error("stale_decision_check", f"resolving path {fp}", e)
        return

    if not (in_memory or in_context_md or in_adr or in_claude_md):
        return

    if not p.exists():
        return

    # Spawn detached subprocess to run the check. Don't skip on cooldown —
    # idempotency (via _is_already_flagged) prevents duplicate flags, and
    # skipping silently drops edits that land during cooldown. Always spawn
    # to ensure the final content is checked.
    try:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--run-check", str(p)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # detach fully
        )
        print("[stale-decision-check] check launched", flush=True)
    except Exception as e:
        log_hook_error("stale_decision_check", "spawning detached check subprocess", e)


if __name__ == "__main__":
    main()
