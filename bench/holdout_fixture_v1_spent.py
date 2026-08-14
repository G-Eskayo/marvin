"""RETIRED — this was the held-out validation fixture for route.py's embedding
classifier (ADR 0023) through bench/RESULTS.md Runs 21-25. Kept as an archived
record only, no longer imported by validate_holdout.py.

Why retired: it was built (Run 21) to never inform reference-set tuning
decisions, and it worked for exactly one round. But Run 24 targeted
research/coding for expansion *because* Run 21's results on this set showed
those were the weakest categories — a category-level information leak, even
though no wording was ever copied. Run 25's recall fix drew on the same
knowledge. By Run 25, three tuning passes (20, 24, 25) had leaned on
knowledge this set produced, so any further accuracy read against it would no
longer be independent. See bench/holdout_fixture.py for the fresh v2 set that
replaced it 2026-08-13, and RESULTS.md Run 26 for the first read against it.
"""
from __future__ import annotations

HOLDOUT_FIXTURE: list[tuple[str, str]] = [
    ("quick check — did we already handle this case somewhere", "recall"),
    ("what was that thing we tried that didn't work", "recall"),
    ("loop me in on where we left off with this", "recall"),
    ("what's the history here", "recall"),
    ("did this ever actually get resolved", "recall"),
    ("what did you tell me about this the other day", "recall"),
    ("bring me up to speed on this thread", "recall"),
    ("what was our conclusion on this", "recall"),
    ("I feel like we covered this already, what did we say", "recall"),
    ("what's already been tried on this", "recall"),
    ("look up how other teams have approached this", "research"),
    ("what's the going wisdom on this problem", "research"),
    ("survey the field on this and tell me what's out there", "research"),
    ("what's the maturity level of this technique", "research"),
    ("break down the tradeoffs of the main approaches in this space", "research"),
    ("what's known about the failure modes of this method", "research"),
    ("find me a good primer on this subject", "research"),
    ("what's the intuition behind why this works", "research"),
    ("how mature is this area of research", "research"),
    ("what have other people found when trying this", "research"),
    ("this keeps timing out, figure out why", "coding"),
    ("swap this library out for a lighter one", "coding"),
    ("the output format is wrong, correct it", "coding"),
    ("add error handling around this call", "coding"),
    ("this variable name is misleading, rename it", "coding"),
    ("split this into smaller functions", "coding"),
    ("the build is broken, find out why", "coding"),
    ("hook this up to the existing pipeline", "coding"),
    ("there's a race condition somewhere, hunt it down", "coding"),
    ("tidy up the imports at the top of this file", "coding"),
    ("does this design hold up if we scale it 10x", "architecture"),
    ("what's a cleaner way to split responsibilities here", "architecture"),
    ("are we solving the right problem with this approach", "architecture"),
    ("what would a simpler version of this system look like", "architecture"),
    ("how does this decision affect what we build next", "architecture"),
    ("is this consistent with how we've done things elsewhere", "architecture"),
    ("what's the failure mode if this assumption turns out wrong", "architecture"),
    ("should this be one component or several", "architecture"),
    ("what's driving the complexity here, can we cut it", "architecture"),
    ("how do we future-proof this choice", "architecture"),
]

HOLDOUT_AMBIGUOUS: list[tuple[str, tuple[str, ...]]] = [
    ("why did we choose this approach", ("recall", "architecture")),
    ("how do we usually handle this kind of thing", ("recall", "architecture")),
    ("is there a faster way to do this", ("coding", "architecture")),
    ("walk me through what's happening here", ("coding", "research")),
    ("what's out there for solving this", ("research", "architecture")),
    ("did this work last time", ("recall", "coding")),
]
