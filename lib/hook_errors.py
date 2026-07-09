"""Shared failure logger for PostToolUse hooks.

Hooks intentionally swallow exceptions rather than crash the caller's tool
call — but a swallowed exception with no trace is how the brain-map
staleness bug (a silent early-return that ran undetected for hours) and the
cross-machine-merge self-SSH bug both went unnoticed. Call log_hook_error
from every except block a hook uses to fail open, so the failure leaves a
trace even though execution continues normally.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

LOG_PATH = Path.home() / ".claude" / "logs" / "hook-errors.log"


def log_hook_error(hook_name: str, context: str, exc: BaseException) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts} [{hook_name}] {context}: {type(exc).__name__}: {exc}\n")
    except Exception:
        pass
