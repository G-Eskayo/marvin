"""Shared `claude` CLI resolution, extracted from five near-identical copies
(verify.py, daily_digest.py, research_digest.py, background_review.py,
background_architecture_review.py) that had already started to drift --
background_review.py's copy shipped with a shorter error message than the
other four.

launchd's environment doesn't source .zshrc/.zprofile, so a plain PATH
lookup can miss an install that works fine interactively (found 2026-07-02:
every daily_digest run had been silently generating "(claude call failed:
...)" as its entire content, because the caller caught the resulting
exception and returned it as if it were real output -- the job exited 0
(looked healthy) while producing nothing useful). Falls back to common
install locations if a plain PATH lookup fails, so a misconfiguration
surfaces once clearly instead of producing silently-broken output
indefinitely.
"""
from __future__ import annotations
import shutil
from pathlib import Path


def _candidates() -> tuple[Path, ...]:
    return (
        Path.home() / ".local" / "bin" / "claude",
        Path("/opt/homebrew/bin/claude"),
        Path("/usr/local/bin/claude"),
    )


def resolve_claude_bin() -> str:
    found = shutil.which("claude")
    if found:
        return found
    for candidate in _candidates():
        if candidate.exists():
            return str(candidate)
    raise FileNotFoundError(
        "claude CLI not found on PATH or in common install locations "
        "(~/.local/bin, /opt/homebrew/bin, /usr/local/bin)"
    )
