#!/usr/bin/env python3
"""Finds this machine's most-recently-active interactive Claude Code
session and prints its transcript info as JSON. Part of session
continuity (see docs/adr — arrival-triggered on-demand handoff
generation): the arriving machine SSHes here to ask "what was Gil just
doing on this machine."

Uses `claude agents --json` (lists live sessions, filtered to `kind:
interactive` — excludes background subagents, which aren't "Gil working")
to get candidate session IDs, then finds each one's actual transcript file
via `find` rather than reconstructing Claude Code's cwd-to-directory-name
slugging convention by hand — that convention isn't documented and
guessing it wrong would silently point at the wrong (or no) file.

"Most recently active" = the transcript file's own mtime, not the
session's startedAt — a session opened days ago but still sitting there
would have an old startedAt even if Gil typed in it 2 minutes ago; the
file only gets touched on real activity.

Usage: find_freshest_session.py
Prints: {"session_id": ..., "transcript_path": ..., "mtime": <epoch float>, "cwd": ...}
or {} if no interactive sessions / nothing found.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path


def _resolve_claude_bin() -> str:
    """SSH's non-interactive shell doesn't source .zshrc/.zprofile, so PATH
    may not include wherever `claude` was actually installed — same gotcha
    documented in daily_digest.py, hit again live while testing this script
    over SSH (bare "claude" resolved fine locally, failed remotely)."""
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    ):
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError("claude CLI not found on PATH or in common install locations")


def main() -> None:
    result = subprocess.run([_resolve_claude_bin(), "agents", "--json"], capture_output=True, text=True, timeout=15)
    try:
        sessions = json.loads(result.stdout)
    except Exception:
        print("{}")
        return

    candidates = []
    for s in sessions:
        if s.get("kind") != "interactive":
            continue
        session_id = s.get("sessionId")
        cwd = s.get("cwd")
        if not session_id:
            continue
        find_result = subprocess.run(
            ["find", str(Path.home() / ".claude" / "projects"), "-name", f"{session_id}.jsonl"],
            capture_output=True, text=True, timeout=10,
        )
        paths = [p for p in find_result.stdout.splitlines() if p.strip()]
        if not paths:
            continue
        transcript_path = paths[0]
        mtime = Path(transcript_path).stat().st_mtime
        candidates.append({"session_id": session_id, "transcript_path": transcript_path, "mtime": mtime, "cwd": cwd})

    if not candidates:
        print("{}")
        return

    freshest = max(candidates, key=lambda c: c["mtime"])
    print(json.dumps(freshest))


if __name__ == "__main__":
    main()
