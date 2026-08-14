"""RETIRED — this was the held-out validation fixture v2 for route.py's
embedding classifier (ADR 0023) through bench/RESULTS.md Runs 26-28. Kept as
an archived record only, no longer imported by validate_holdout.py.

Why retired: built (Run 26) to replace v1 after v1 was spent by category-level
leakage. Worked for one fully independent read (Run 26: 72%). But Run 27
diagnosed and fixed `architecture` directly from this set's own miss list,
and Run 28 did the same for `coding` — both legitimate, disciplined fixes,
but both mean this file's results directly shaped which categories got
tuned. By Run 28, all four categories had either been read from this set
(recall, research) or directly diagnosed and fixed against it (architecture,
coding). See bench/holdout_fixture.py for the fresh v3 set that replaced it
2026-08-13, and RESULTS.md Run 29 for the first read against it.
"""
from __future__ import annotations

HOLDOUT_FIXTURE: list[tuple[str, str]] = [
    ("did we cover this ground already", "recall"),
    ("what's the short version of what we agreed on", "recall"),
    ("jog my memory on this one", "recall"),
    ("where did we leave this off", "recall"),
    ("what came out of that earlier discussion", "recall"),
    ("I think we touched on this before, what did we say", "recall"),
    ("what's the deal with the thing we set up last time", "recall"),
    ("recap the last few things we worked through", "recall"),
    ("what did that investigation actually conclude", "recall"),
    ("I don't remember the details, can you pull them up", "recall"),
    ("what's out there on this subject", "research"),
    ("dig into how this typically gets approached", "research"),
    ("what's the standard way people handle this", "research"),
    ("any good writeups on this topic", "research"),
    ("what's the background on this concept", "research"),
    ("how does this compare across different implementations", "research"),
    ("what's the received wisdom here", "research"),
    ("pull together what's known about this area", "research"),
    ("what would an expert say about this", "research"),
    ("trace the origins of this idea", "research"),
    ("the config isn't loading right, sort it out", "coding"),
    ("port this over to the new module", "coding"),
    ("the endpoint returns the wrong status code, correct it", "coding"),
    ("add logging around this section", "coding"),
    ("simplify this conditional", "coding"),
    ("the script crashes on empty input, handle that", "coding"),
    ("get the linter passing on this file", "coding"),
    ("extract this into its own helper", "coding"),
    ("the deploy script needs a dry-run mode", "coding"),
    ("patch this so it doesn't choke on missing fields", "coding"),
    ("does this hold together as the system grows", "architecture"),
    ("what's the right layer for this to live in", "architecture"),
    ("are we introducing unnecessary coupling here", "architecture"),
    ("what happens to this if requirements change later", "architecture"),
    ("would we build this the same way if we started over", "architecture"),
    ("what's the blast radius if this assumption is wrong", "architecture"),
    ("should this be configurable or hardcoded", "architecture"),
    ("what's the cost of doing this the quick way versus the right way", "architecture"),
    ("does this design still make sense given what we know now", "architecture"),
    ("how many moving parts does this actually need", "architecture"),
]

HOLDOUT_AMBIGUOUS: list[tuple[str, tuple[str, ...]]] = [
    ("what's the reason we ended up here", ("recall", "architecture")),
    ("could this be done more simply", ("coding", "architecture")),
    ("what's the current state of this", ("recall", "research")),
    ("help me understand this part", ("coding", "research")),
    ("what would you suggest here", ("research", "architecture")),
    ("has anyone run into this before", ("recall", "research")),
]
