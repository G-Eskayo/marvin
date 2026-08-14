"""Genuinely held-out validation fixture v3 for route.py's embedding
classifier (ADR 0023). Built 2026-08-13 to replace v2 (now archived as
holdout_fixture_v2_spent.py) after Runs 27-28 diagnosed and fixed
`architecture` and `coding` directly from v2's own miss list — legitimate,
disciplined fixes, but ones that mean v2's results shaped which categories
got tuned. By the end of Run 28, all four categories had either been read
from v2 (recall, research) or directly diagnosed and fixed against it
(architecture, coding).

DO NOT use these phrasings, or near-paraphrases of them, to write new
entries in intent_classify.REFERENCE_EXAMPLES. DO NOT let this run's own
result shape which categories get targeted in a later tuning pass — the
same category-level leak that spent v1 and v2. If a future tuning decision
is informed by anything learned from a run against this file, this file is
spent too, and a v4 needs to be written before trusting another
"independent" number.

Not cherry-picked toward v1/v2's known failure patterns (e.g. doesn't reuse
the "port this to the new module" / "simplify this conditional" shapes that
were v2's coding misses) — the goal is an unbiased naturalistic sample, not
another stress test aimed at already-diagnosed weak spots.
"""
from __future__ import annotations

# (description, expected_intent) — 10 per intent, all new phrasing, never
# used to write REFERENCE_EXAMPLES, FIXTURE/AMBIGUOUS_FIXTURE, v1, or v2.
HOLDOUT_FIXTURE: list[tuple[str, str]] = [
    ("circle back to what we talked about earlier", "recall"),
    ("what's the gist of where we landed on this", "recall"),
    ("did I already ask you this", "recall"),
    ("what came out of the last round of testing", "recall"),
    ("give me the rundown on what happened before", "recall"),
    ("what did we settle on for this one", "recall"),
    ("has this topic been raised before in our chats", "recall"),
    ("what's the backstory on this decision", "recall"),
    ("what did we find out the last time we looked into this", "recall"),
    ("run me through what we already know about this", "recall"),
    ("what's the general approach people take for this", "research"),
    ("look into the theory behind this", "research"),
    ("what's been published about this recently", "research"),
    ("how do experts typically frame this problem", "research"),
    ("what's the going rate of success with this method", "research"),
    ("explore what other implementations of this look like", "research"),
    ("what's the deeper explanation for why this happens", "research"),
    ("canvas what's already out there on this", "research"),
    ("what's the historical context behind this technique", "research"),
    ("how do the leading approaches to this differ", "research"),
    ("the header isn't rendering correctly, sort that out", "coding"),
    ("consolidate these two functions into one", "coding"),
    ("the retry logic is looping forever, cap it", "coding"),
    ("swap out this deprecated call for the new one", "coding"),
    ("the script silently swallows errors, surface them", "coding"),
    ("trim the dead code out of this file", "coding"),
    ("the api call needs a timeout added", "coding"),
    ("normalize the casing on these variable names", "coding"),
    ("the test suite is flaky, stabilize it", "coding"),
    ("wrap this in a try/except so it fails gracefully", "coding"),
    ("what's the impact on the rest of the system if we change this", "architecture"),
    ("is this the right layer of abstraction for this logic", "architecture"),
    ("how does this fit into the bigger picture", "architecture"),
    ("what would need to change elsewhere if we did this differently", "architecture"),
    ("is this decision reversible if it turns out wrong", "architecture"),
    ("what's the minimum viable version of this design", "architecture"),
    ("does this introduce a single point of failure", "architecture"),
    ("how do we keep this extensible for future needs", "architecture"),
    ("what's the actual constraint driving this design choice", "architecture"),
    ("is this solving the root problem or just a symptom", "architecture"),
]

# (description, acceptable_intents) — genuinely dual-purpose, never used
# elsewhere. Scored separately, same discipline as AMBIGUOUS_FIXTURE.
HOLDOUT_AMBIGUOUS: list[tuple[str, tuple[str, ...]]] = [
    ("what led us here", ("recall", "architecture")),
    ("is there a simpler way to think about this", ("research", "architecture")),
    ("what do we do about this", ("coding", "architecture")),
    ("can you break this down for me", ("coding", "research")),
    ("what's the deal with this", ("recall", "research")),
    ("how do we get this working", ("coding", "architecture")),
]
