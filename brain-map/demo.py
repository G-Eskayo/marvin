#!/usr/bin/env python3
"""demo.py — showcase every live-graph feature without touching anything real.

Purely local: writes synthetic lines to activity.jsonl and demo-events.jsonl
(the same files the real hook/demo channels use), which DesktopLive picks up
via its existing pollers and pushes into the page via evaluateJavaScript.
No skill invocation, no LLM call, no real file created/deleted under
~/.agents/skills/ — zero tokens, zero risk to the actual system. This is
purely a demonstration harness for what's already built.

Run:
    ~/.agents/venv/bin/python ~/.agents/brain-map/demo.py
"""
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ACTIVITY_PATH = HERE / "activity.jsonl"
DEMO_EVENTS_PATH = HERE / "demo-events.jsonl"

# Spread across categories so the showcase visits most of the tree, not just
# one corner — one real, currently-existing node id per category.
PULSE_SEQUENCE = [
    "diagnose",       # quality
    "research",       # research
    "creative",       # creation
    "self-improve",   # continuity
    "resume-tailor",  # project
    "daily-digest",   # agents
    "qa-knowledge",   # memory
]

DEMO_NODE_ID = "demo-showcase-node"
DEMO_NODE_PARENT = "Quality"


def append(path: Path, obj: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj) + "\n")


def pulse(skill: str) -> None:
    append(ACTIVITY_PATH, {"skill": skill, "ts": time.time()})
    print(f"  pulse -> {skill}")


def main() -> None:
    print("MARVIN brain-map showcase — local only, no tokens, nothing real touched.")
    print("Watch the desktop (or the artifact) for ~30 seconds.\n")

    # DesktopLive tracks its read position in demo-events.jsonl by line
    # count, not content — resetting the file each run keeps repeat "test
    # it" invocations from growing it forever with events already consumed.
    DEMO_EVENTS_PATH.write_text("", encoding="utf-8")

    print("1/3 — activity pulses across categories (camera should ease toward each in turn):")
    for skill in PULSE_SEQUENCE:
        pulse(skill)
        time.sleep(3.0)

    print("\n2/3 — synthetic node creation (grow-in animation, not a real skill):")
    append(DEMO_EVENTS_PATH, {
        "type": "add",
        "parent": DEMO_NODE_PARENT,
        "node": {
            "id": DEMO_NODE_ID, "cat": "quality",
            "desc": "Synthetic demo node — not a real skill, added by demo.py to show the grow animation.",
        },
    })
    print(f"  add -> {DEMO_NODE_ID} (under {DEMO_NODE_PARENT})")
    time.sleep(4.0)

    print("\n3/3 — same node removed (shrink-out animation):")
    append(DEMO_EVENTS_PATH, {"type": "remove", "id": DEMO_NODE_ID})
    print(f"  remove -> {DEMO_NODE_ID}")
    time.sleep(1.5)

    print("\nDone. Nothing real was created, deleted, or invoked — this only wrote two small local log files.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(1)
