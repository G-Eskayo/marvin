#!/usr/bin/env python3
"""PostToolUse hook: on Write/Edit tools, check if new content contradicts memory/repo claims.

Design: docs/design/pipeline-g-eskayo-marvin-652.md. Detached-subprocess pattern
per background_review.py — spawns stale_decision_check.py check <path> in the background,
never blocking the interactive loop. Includes cooldown to avoid burst of parallel checks.

Triggers on Write/Edit to: memory notes, CONTEXT.md, docs/adr/*.md (per hook-scope decision).
Skips MEMORY.md itself (it's an index, not claims).
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
MEMORY_DIR = HOME / ".claude" / "projects" / "-Users-gileskayo" / "memory"
CHECK_SCRIPT = Path(__file__).resolve().parent / "stale_decision_check.py"
COOLDOWN_FILE = HOME / ".claude" / "logs" / ".stale-check-cooldown"
COOLDOWN_SECONDS = 5  # Minimum time between spawning checks


def should_check_path(path_str: str) -> bool:
    """Return True if this path should trigger a stale-check."""
    path = Path(path_str)
    # Memory notes: under ~/.claude/projects/.../memory/, not MEMORY.md
    if MEMORY_DIR in path.parents and path.name != "MEMORY.md":
        return True
    # Repo CONTEXT.md and docs/adr/*.md
    if path.name == "CONTEXT.md":
        return True
    if path.name.endswith(".md") and "docs" in path.parts and "adr" in path.parts:
        return True
    return False


def get_pending_queue() -> dict:
    """Load the pending queue of checks to run."""
    queue_file = HOME / ".claude" / "logs" / ".stale-check-queue.json"
    if not queue_file.exists():
        return {}
    try:
        return json.loads(queue_file.read_text())
    except Exception:
        return {}


def save_pending_queue(queue: dict) -> None:
    """Save the pending queue of checks to run."""
    queue_file = HOME / ".claude" / "logs" / ".stale-check-queue.json"
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        queue_file.write_text(json.dumps(queue))
    except Exception:
        pass


def last_check_time() -> float:
    """Get the timestamp of the last spawned check."""
    if not COOLDOWN_FILE.exists():
        return 0.0
    try:
        return float(COOLDOWN_FILE.read_text().strip())
    except (ValueError, OSError):
        return 0.0


def update_check_time() -> None:
    """Update the timestamp of the last spawned check."""
    COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        COOLDOWN_FILE.write_text(str(time.time()))
    except Exception:
        pass


# Backward compatibility wrappers
def is_cooldown_active() -> bool:
    """Check if cooldown is active (last check was too recent)."""
    return not should_spawn_now()


def update_cooldown() -> None:
    """Update cooldown timestamp."""
    update_check_time()


def should_spawn_now() -> bool:
    """Check if enough time has passed since last spawned check."""
    return (time.time() - last_check_time()) >= COOLDOWN_SECONDS


def process_queue() -> None:
    """Process pending checks if cooldown has expired."""
    if not should_spawn_now():
        return
    queue = get_pending_queue()
    if not queue:
        return
    # Get the first pending file (FIFO)
    file_path = next(iter(queue.values()))
    if not file_path:
        return
    try:
        subprocess.Popen(
            [sys.executable, str(CHECK_SCRIPT), "check", file_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        update_check_time()
        # Remove from queue
        del queue[next(iter(queue))]
        save_pending_queue(queue)
    except Exception:
        pass


def main() -> None:
    """Read hook payload, check path, spawn check or queue if needed."""
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_name = payload.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return

    file_path = payload.get("tool_input", {}).get("file_path")
    if not file_path:
        return

    if not should_check_path(file_path):
        return

    # Try to process any pending checks from queue
    process_queue()

    # If cooldown is still active, queue this check instead of dropping it
    if not should_spawn_now():
        queue = get_pending_queue()
        import hashlib
        check_id = hashlib.md5(file_path.encode()).hexdigest()[:8]
        queue[check_id] = file_path
        save_pending_queue(queue)
        return

    # Spawn check in background, non-blocking
    try:
        subprocess.Popen(
            [sys.executable, str(CHECK_SCRIPT), "check", file_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        update_check_time()
    except Exception:
        # Never block on spawn failure
        pass


if __name__ == "__main__":
    main()
