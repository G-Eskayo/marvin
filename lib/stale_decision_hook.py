#!/usr/bin/env python3
"""PostToolUse hook: check for stale decisions when memory files, CONTEXT.md, or ADRs change.

When a Write/Edit/MultiEdit of these file types completes, spawn a detached subprocess
that checks whether the new text contradicts any existing claims in memory or repo docs.
If a contradiction is found, flag it in ~/.claude/stale-decisions.md.

Never blocks or errors the originating tool call. Failures are logged, not raised.
Per-file cooldown prevents repeated checks on the same file within the cooldown window.

Mirrors background_review.py's exact structure: detached subprocess, path-matching,
per-file cooldown lock, cooldown-aware append to a durable flagged-items file.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import host_os  # noqa: E402
from hook_errors import log_hook_error  # noqa: E402
import stale_decision_check  # noqa: E402

MEMORY_DIR = host_os.memory_dir()
AGENTS_DIR = Path.home() / ".agents"
STALE_DECISION_DIR = AGENTS_DIR / "lib"
LOCKS_DIR = STALE_DECISION_DIR / ".stale_decision_locks"

# Per-file cooldown: avoid re-checking the same file multiple times in quick succession
COOLDOWN_SECONDS = 5 * 60  # 5 minutes


def _lock_file(file_path: Path) -> Path:
    """Get the lock file for a specific path."""
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    # Use the absolute path's hash as the lock name
    import hashlib
    digest = hashlib.md5(str(file_path.resolve()).encode()).hexdigest()
    return LOCKS_DIR / f"{digest}.lock"


def _cooldown_active(file_path: Path) -> bool:
    """Check if this file is in cooldown (recent check within COOLDOWN_SECONDS)."""
    lock = _lock_file(file_path)
    if not lock.exists():
        return False
    age = time.time() - lock.stat().st_mtime
    return age < COOLDOWN_SECONDS


def _mark_checked(file_path: Path) -> None:
    """Mark a file as recently checked (update lock timestamp)."""
    lock = _lock_file(file_path)
    LOCKS_DIR.mkdir(parents=True, exist_ok=True)
    lock.touch()


def _should_check(file_path: Path) -> bool:
    """Decide whether this file type should be checked.

    Match: memory files (*.md in MEMORY_DIR), CONTEXT.md at repo root, docs/adr/*.md
    """
    path_obj = Path(file_path)

    # Memory files: *.md directly in memory_dir
    if path_obj.parent.resolve() == MEMORY_DIR.resolve() and path_obj.suffix == ".md":
        return True

    # CONTEXT.md at a repo root (must have .git sibling or docs/adr subdir)
    if path_obj.name == "CONTEXT.md":
        parent = path_obj.parent
        if (parent / ".git").exists() or (parent / "docs" / "adr").exists():
            return True

    # docs/adr/*.md
    if path_obj.suffix == ".md" and path_obj.parent.name == "adr" and path_obj.parent.parent.name == "docs":
        return True

    return False


def _extract_new_text(payload: dict) -> str:
    """Extract the new/changed text from a tool payload.

    Tool can be: Write (content), Edit (new_string), MultiEdit (items with new_string).
    """
    if "content" in payload:  # Write
        return payload.get("content", "")
    elif "new_string" in payload:  # Edit
        return payload.get("new_string", "")
    elif "items" in payload:  # MultiEdit
        # Concatenate all new_string values from items
        items = payload.get("items", [])
        new_texts = [item.get("new_string", "") for item in items if isinstance(item, dict)]
        return "\n".join(new_texts)
    return ""


def _run_check_in_background(file_path: Path, new_text: str) -> None:
    """Spawn a detached subprocess to run the stale-decision check.

    The subprocess will:
    1. Call check_decision(new_text, new_file=file_path)
    2. If a contradiction is found, call flag() to append to stale-decisions.md
    3. Exit silently on any error

    Never blocks the main hook process.
    """
    script = f"""
import sys
sys.path.insert(0, r'{STALE_DECISION_DIR}')
import stale_decision_check

try:
    new_text = {repr(new_text)}
    file_path = r'{file_path}'
    from pathlib import Path
    cand = stale_decision_check.check_decision(new_text, new_file=Path(file_path))
    if cand:
        stale_decision_check.flag(cand)
except Exception:
    pass  # Fail silently
"""

    try:
        # Detached subprocess: fire and forget, never block
        subprocess.Popen(
            [sys.executable, "-c", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True  # Detach from parent session
        )
    except Exception as e:
        log_hook_error("stale_decision_hook", str(e))


def main() -> None:
    """Hook entrypoint: read tool payload from stdin, decide whether to check."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    file_path = payload.get("file_path")
    if not file_path:
        return

    path_obj = Path(file_path)

    # Only check relevant file types
    if not _should_check(path_obj):
        return

    # Respect cooldown
    if _cooldown_active(path_obj):
        return

    # Extract new text
    new_text = _extract_new_text(payload)
    if not new_text or not new_text.strip():
        return

    # Mark as checked (update cooldown)
    _mark_checked(path_obj)

    # Spawn background check (detached, non-blocking)
    _run_check_in_background(path_obj, new_text)


if __name__ == "__main__":
    main()
