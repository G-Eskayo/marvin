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
nothing" behavior. Any failure exits silently; never blocks or errors the user's
actual prompt.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

STATE_FILE = Path.home() / ".claude" / "auto-route-state.json"
MAX_PROMPT_CHARS = 20000  # Truncate before keyword scoring to prevent DoS on huge inputs
FAST_PATH_MIN_HITS = 4    # Threshold for keyword-only fast path; must be >= route.MIN_HITS

MESSAGES = {
    "recall": "This looks like a **recall** task — `claude-recall` (marvin + haiku) handles it at ~60% of this session's cost.",
    "coding": "This looks like a **coding** task — `claude-code` (lean + sonnet) saves ~9% tokens.",
    "research": "This looks like a **research** task — `claude-research` (marvin + haiku) is ~60% cheaper for synthesis.",
}


def _already_fired(session_id: str) -> bool:
    if not STATE_FILE.exists():
        return False
    try:
        data = json.loads(STATE_FILE.read_text())
    except Exception:
        return False
    return bool(data.get(session_id))


def _mark_fired(session_id: str) -> None:
    data = {}
    if STATE_FILE.exists():
        try:
            data = json.loads(STATE_FILE.read_text())
        except Exception:
            data = {}
    data[session_id] = True
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data))


def _resolve_intent(prompt: str) -> str:
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402
    intent, _hits, _method = route.resolve_intent(prompt, use_embed=True)
    return intent


def classify(prompt: str) -> str | None:
    """Return the routing message for prompt, or None to stay silent
    (architecture/no-match, same as the original 'say nothing' behavior).

    Fast path: if keyword scoring meets FAST_PATH_MIN_HITS threshold,
    returns the message immediately without calling resolve_intent (skips
    embed classifier and its 2.6s import + 1.5-10s network cost).
    Slow path: falls through to resolve_intent for less confident cases.
    """
    sys.path.insert(0, str(Path.home() / ".agents" / "skills" / "route" / "scripts"))
    import route  # noqa: E402

    # Fast path: keyword-only scoring on truncated prompt
    truncated = prompt[:MAX_PROMPT_CHARS].lower()
    scores = {intent: 0 for intent in route.INTENTS}
    for intent, cfg in route.INTENTS.items():
        for kw in cfg["keywords"]:
            if kw in truncated:
                scores[intent] += 1
    best = max(scores, key=scores.get)
    hits = scores[best]

    if hits >= FAST_PATH_MIN_HITS:
        # Confident keyword match; return without embed
        intent = best if hits >= route.MIN_HITS else route.DEFAULT_INTENT
        return MESSAGES.get(intent)

    # Slow path: use embedding classifier
    return MESSAGES.get(_resolve_intent(prompt))


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    session_id = payload.get("session_id", "")
    prompt = payload.get("user_prompt", "")
    if not session_id or not prompt:
        return

    if _already_fired(session_id):
        return

    try:
        message = classify(prompt)
    except Exception:
        message = None

    _mark_fired(session_id)

    if message:
        print(message)


if __name__ == "__main__":
    main()
