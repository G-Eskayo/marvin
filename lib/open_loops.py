#!/usr/bin/env python3
"""Open loops (marvin#XXX): persistent surfacing of unfinished ideas until explicitly dropped or completed.

An open loop is an idea that matters but isn't done — not urgent, maybe not even started yet. Without a
proactive mechanism, these vanish from working memory and resurface as "I thought we were going to do X"
months later. Open loops resurface at a fixed interval (default: every 3 days) until Gil explicitly
drops it (not relevant anymore) or marks it done (actually finished). Each resurfacing triggers a
notification, so the person keeps the idea in view without nagging.

Store: ~/.claude/open-loops.md (markdown with ## blocks, Status lines, Next-check dates).
Scheduler: launchd job (config/launchd/com.marvin.open-loops.plist) calls `run_resurfacing()` multiple
times per day. Headless, no session dependency.

    open_loops.py add <title> <context>        # add a new loop
    open_loops.py list                          # show all loops
    open_loops.py drop <id> <reason>            # mark as not relevant
    open_loops.py complete <id>                 # mark as actually finished
"""
from __future__ import annotations
import os
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))

CLAUDE = Path.home() / ".claude"
STORE = CLAUDE / "open-loops.md"
RESURFACING_INTERVAL_DAYS = 3
_DATE = r"(\d{4}-\d{2}-\d{2})"


def _day(s: str) -> datetime:
    """Parse ISO date string to datetime."""
    return datetime.fromisoformat(s[:10]).replace(tzinfo=timezone.utc)


def _now_date(now: datetime) -> str:
    """Today's date in ISO format."""
    return now.astimezone().strftime("%Y-%m-%d")


def _blocks(text: str) -> list[str]:
    """Split markdown into blocks (## delimited)."""
    return re.split(r"^(?=## )", text, flags=re.M)[1:]


def _parse_block(block: str) -> dict | None:
    """Parse a single open-loops block into a dict. Returns None if malformed."""
    try:
        id_match = re.search(r"^## (\S+)\s+(.+)$", block, re.M)
        if not id_match:
            return None
        loop_id, title = id_match.groups()

        added_match = re.search(r"^\*\*Added\*\*:\s*" + _DATE, block, re.M)
        if not added_match:
            return None

        status_match = re.search(r"^\*\*Status\*\*:\s*(\w+)(?:\s+" + _DATE + ")?", block, re.M)
        if not status_match:
            return None
        status = status_match.group(1)

        next_check_match = re.search(r"^\*\*Next-check\*\*:\s*" + _DATE, block, re.M)
        next_check = next_check_match.group(1) if next_check_match else None

        context_match = re.search(r"^\*\*Context\*\*:\s*(.+?)(?=\n\*\*|\Z)", block, re.M | re.S)
        context = context_match.group(1).strip() if context_match else ""

        return {
            "id": loop_id,
            "title": title.strip(),
            "added": _day(added_match.group(1)),
            "status": status,
            "next_check": _day(next_check) if next_check else None,
            "context": context,
            "raw": block,
        }
    except (ValueError, IndexError, AttributeError):
        return None


def _render_block(loop: dict, now: datetime) -> str:
    """Render a loop dict as markdown block."""
    added = loop["added"].astimezone().strftime("%Y-%m-%d")
    lines = [f"## {loop['id']} {loop['title']}", ""]
    lines.append(f"**Added**: {added}")

    if loop["status"] in ("done", "dropped"):
        status_date = now.astimezone().strftime("%Y-%m-%d")
        lines.append(f"**Status**: {loop['status']} {status_date}")
    else:
        lines.append(f"**Status**: {loop['status']}")
        next_check = (loop.get("next_check") or now).astimezone().strftime("%Y-%m-%d")
        lines.append(f"**Next-check**: {next_check}")

    lines.append(f"**Context**: {loop['context']}")
    return "\n".join(lines) + "\n"


def add_loop(title: str, context: str, now: datetime | None = None,
             store_path: Path | None = None) -> str:
    """Add a new loop. Returns its ID."""
    now = now or datetime.now(timezone.utc)
    store_path = store_path or STORE
    loop_id = str(uuid.uuid4())[:8]

    loop = {
        "id": loop_id,
        "title": title,
        "added": now,
        "status": "open",
        "next_check": now,
        "context": context,
    }

    store_path.parent.mkdir(parents=True, exist_ok=True)
    text = store_path.read_text() if store_path.exists() else "# Open Loops\n\n"
    text = text.rstrip() + "\n\n" + _render_block(loop, now)

    tmp = store_path.with_suffix(".md.tmp")
    tmp.write_text(text)
    tmp.replace(store_path)

    return loop_id


def list_loops(now: datetime | None = None, store_path: Path | None = None) -> list[dict]:
    """List all loops (open, resurfaced, dropped, or done). Excludes malformed blocks."""
    now = now or datetime.now(timezone.utc)
    store_path = store_path or STORE

    if not store_path.exists():
        return []

    loops = []
    for block in _blocks(store_path.read_text()):
        parsed = _parse_block(block)
        if parsed:
            loops.append(parsed)
    return loops


def due_for_resurfacing(now: datetime | None = None, store_path: Path | None = None) -> list[dict]:
    """Loops that are open or resurfaced with Next-check <= now. Not dropped/done."""
    now = now or datetime.now(timezone.utc)
    due = []
    for loop in list_loops(now, store_path):
        if loop["status"] in ("dropped", "done"):
            continue
        next_check = loop.get("next_check")
        if next_check and next_check <= now:
            due.append(loop)
    return due


def run_resurfacing(now: datetime | None = None, notify_fn: Callable | None = None,
                    store_path: Path | None = None) -> None:
    """Resurface loops due for resurfacing. Call from launchd multiple times per day."""
    now = now or datetime.now(timezone.utc)
    notify_fn = notify_fn or _default_notify
    store_path = store_path or STORE

    if not store_path.exists():
        return

    due = due_for_resurfacing(now, store_path)
    if not due:
        return

    text = store_path.read_text()
    today = _now_date(now)

    for loop in due:
        try:
            notify_fn("Open loop", f"{loop['title']}: {loop['context'][:100]}", open_target=str(store_path))
        except Exception:
            pass  # notify failing should never break the batch

        # Advance next-check and update status
        new_interval = now + timedelta(days=RESURFACING_INTERVAL_DAYS)
        updated_loop = {**loop, "status": "resurfaced", "next_check": new_interval}
        new_block = _render_block(updated_loop, now)
        text = text.replace(loop["raw"], new_block, 1)

    tmp = store_path.with_suffix(".md.tmp")
    tmp.write_text(text)
    tmp.replace(store_path)


def drop(loop_id: str, now: datetime | None = None, reason: str = "",
         store_path: Path | None = None) -> bool:
    """Mark a loop as dropped (not relevant). Returns True if successful, False if already terminal or not found."""
    now = now or datetime.now(timezone.utc)
    store_path = store_path or STORE

    if not store_path.exists():
        return False

    loops = list_loops(now, store_path)
    target = next((l for l in loops if l["id"] == loop_id), None)
    if not target or target["status"] in ("done", "dropped"):
        return False

    text = store_path.read_text()
    updated_loop = {**target, "status": "dropped"}
    new_block = _render_block(updated_loop, now)
    text = text.replace(target["raw"], new_block, 1)

    tmp = store_path.with_suffix(".md.tmp")
    tmp.write_text(text)
    tmp.replace(store_path)

    return True


def complete(loop_id: str, now: datetime | None = None,
             store_path: Path | None = None) -> bool:
    """Mark a loop as done (actually finished). Returns True if successful, False if already terminal or not found."""
    now = now or datetime.now(timezone.utc)
    store_path = store_path or STORE

    if not store_path.exists():
        return False

    loops = list_loops(now, store_path)
    target = next((l for l in loops if l["id"] == loop_id), None)
    if not target or target["status"] in ("done", "dropped"):
        return False

    text = store_path.read_text()
    updated_loop = {**target, "status": "done"}
    new_block = _render_block(updated_loop, now)
    text = text.replace(target["raw"], new_block, 1)

    tmp = store_path.with_suffix(".md.tmp")
    tmp.write_text(text)
    tmp.replace(store_path)

    return True


def _default_notify(title: str, message: str, open_target: str | None = None) -> None:
    """Default notifier: import notify.py if available."""
    try:
        import notify
        notify.notify(title, message, open_target)
    except (ImportError, Exception):
        pass


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: open_loops.py add|list|drop|complete|resurface")

    cmd = sys.argv[1]
    now = datetime.now(timezone.utc)

    if cmd == "add":
        if len(sys.argv) < 4:
            sys.exit("usage: open_loops.py add <title> <context>")
        title = sys.argv[2]
        context = " ".join(sys.argv[3:])
        loop_id = add_loop(title, context, now)
        print(f"Added: {loop_id}")

    elif cmd == "list":
        loops = list_loops(now)
        for loop in loops:
            status_str = loop["status"]
            if loop.get("next_check"):
                status_str += f" (next: {loop['next_check'].astimezone().strftime('%Y-%m-%d')})"
            print(f"{loop['id']} {loop['title']} [{status_str}]")

    elif cmd == "drop":
        if len(sys.argv) < 3:
            sys.exit("usage: open_loops.py drop <id> [reason]")
        loop_id = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else ""
        if drop(loop_id, now, reason):
            print(f"Dropped: {loop_id}")
        else:
            print(f"Not found or already terminal: {loop_id}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "complete":
        if len(sys.argv) < 3:
            sys.exit("usage: open_loops.py complete <id>")
        loop_id = sys.argv[2]
        if complete(loop_id, now):
            print(f"Completed: {loop_id}")
        else:
            print(f"Not found or already terminal: {loop_id}", file=sys.stderr)
            sys.exit(1)

    elif cmd == "resurface":
        run_resurfacing(now)

    else:
        sys.exit(f"unknown command: {cmd}")
