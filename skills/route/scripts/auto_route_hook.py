#!/usr/bin/env python3
"""UserPromptSubmit hook: on the first user message of a session, classify it via
route.py's embedding classifier (ADR 0023, 87.5% independently validated per
bench/RESULTS.md Run 29) and surface a routing suggestion -- replacing CLAUDE.md's
old hand-maintained "Routing keywords: recall=..." list with the same classifier
route.py itself now uses by default, so there is exactly one place task-type
routing logic lives (per the original bitter-lesson suggestion, suggestions.md
priority 9).

Fires at most once per session (tracked in STATE_FILE by session_id) and stays
silent when the classifier lands on 'architecture' or can't decide -- matching the
original prose's "architecture/design/mixed -> current profile is correct, say
nothing" behavior. Any failure exits 0 silently; never blocks or errors the user's
actual prompt (exit 2 would block it, any other non-zero shows a hook-error notice).

The prompt arrives as payload["prompt"] (Claude Code hooks reference,
UserPromptSubmit input). Until #560 this read "user_prompt", which no real payload
carries, so the hook returned early on every prompt from 2026-08-13 on. The old key
is still read as a fallback so an older caller can't silently break it again.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE_FILE = Path.home() / ".claude" / "auto-route-state.json"
KEEP_SECONDS = 86400          # a session's mark only matters while that session runs
MAX_PROMPT_CHARS = 4000       # classify the opening, not a 6 MB paste

ROUTED = ("recall", "coding", "research")  # architecture = the current profile is right: say nothing


def _route():
    for p in (HERE, HERE.parents[2] / "lib"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    import route  # noqa: E402
    return route


def messages() -> dict[str, str]:
    """Suggestion per intent, built from route.INTENTS so the alias and the savings
    claim (with its caveats) live in one place."""
    intents = _route().INTENTS
    return {
        intent: f"This looks like a **{intent}** task — `{intents[intent]['alias']}` "
                f"would handle it ({intents[intent]['savings']})."
        for intent in ROUTED if intent in intents
    }


# ── state: {session_id: fired_at}, pruned on write, locked across sessions ──

def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _already_fired(session_id: str) -> bool:
    return session_id in _read(STATE_FILE)


def _mark_fired(session_id: str, now: float | None = None) -> None:
    """Mirror of session_work._Locked: flock a sibling .lock, read, prune entries
    older than KEEP_SECONDS (and pre-#560 `true` values), write via temp + replace."""
    import fcntl
    import os

    now = time.time() if now is None else now
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE.with_suffix(".lock"), "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            data = {sid: t for sid, t in _read(STATE_FILE).items()
                    if isinstance(t, (int, float)) and not isinstance(t, bool)
                    and now - t < KEEP_SECONDS}
            data[session_id] = now
            tmp = STATE_FILE.with_name(f"{STATE_FILE.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, STATE_FILE)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _resolve_intent(prompt: str) -> str:
    intent, _hits, _method = _route().resolve_intent(prompt, use_embed=True)
    return intent


def classify(prompt: str) -> str | None:
    """Return the routing message for prompt, or None to stay silent
    (architecture/no-match, same as the original 'say nothing' behavior)."""
    intent = _resolve_intent(prompt[:MAX_PROMPT_CHARS])
    return messages().get(intent)


def _prompt(payload: dict) -> str:
    for key in ("prompt", "user_prompt"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    session_id = payload.get("session_id")
    prompt = _prompt(payload)
    if not isinstance(session_id, str) or not session_id or not prompt:
        return

    if _already_fired(session_id):
        return

    try:
        message = classify(prompt)
    except Exception:
        message = None

    try:
        _mark_fired(session_id)
    except Exception:
        pass  # can't remember it: worst case the suggestion shows again next prompt

    if message:
        print(message)


if __name__ == "__main__":
    try:
        main()
    except Exception:  # fail open: never block or flag the user's prompt
        pass
    sys.exit(0)
