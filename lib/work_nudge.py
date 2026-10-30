#!/usr/bin/env python3
"""Tell the map's Work half that a worker started or stopped (#854): rewrite brain-map/work.json in the background.

Called by the hooks that already record a worker (chat_helpers.py on a helper's start and stop, ticket_stages.py on
every stage), so a new helper or builder reaches the map within one activity poll, with nothing polling for it.
Only the installed checkout does this (`~/.agents`): a test with its own home, or a worktree, never writes the live
map. It never waits and never raises: the writer runs detached, and a failure only means the map is a little behind.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = Path("brain-map") / "scripts" / "work_view.py"


def nudge(repo: Path = REPO, home: Path | None = None, popen=subprocess.Popen) -> bool:
    """Start the work.json writer if this is the installed checkout. True if it was started."""
    try:
        home = Path.home() if home is None else home
        if Path(repo).resolve() != (home / ".agents").resolve():
            return False
        script = Path(repo) / SCRIPT
        if not script.is_file():
            return False
        popen([sys.executable, str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True)
        return True
    except Exception:  # noqa: BLE001 -- a worker's own hook must never fail because the map couldn't be told
        return False
