#!/usr/bin/env python3
"""Compare route.py's keyword classifier against the --embed classifier
(intent_classify.py, ADR 0023) on a held-out fixture of task descriptions —
phrased differently from the reference examples the embedding classifier was
seeded on, so this isn't just re-testing the seed set.

Two separate fixtures, reported separately (per Run 18's finding that
blending them would misrepresent what the number means):

- FIXTURE: clean cases with one defensible expected intent each. Accuracy
  here is a real measurement.
- AMBIGUOUS_FIXTURE: cases a human could reasonably route more than one way
  (e.g. "should we refactor this or leave it as is" is coding-flavored AND
  architecture-flavored). Each has a *set* of acceptable intents. Scored
  separately and never folded into the headline accuracy number — a
  classifier landing on one defensible answer isn't wrong, and pretending
  there's one right answer here would be dishonest measurement, not rigor.

Per roadmap §G: "every routing decision must be bench-validated before
shipping." Local-only, no Claude API calls — just classifier agreement
against hand-labeled expected intents.

Usage:
    ~/.agents/venv/bin/python bench/compare_route_classifiers.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROUTE_SCRIPTS = Path.home() / ".agents" / "skills" / "route" / "scripts"
sys.path.insert(0, str(ROUTE_SCRIPTS))
import route  # noqa: E402

# (description, expected_intent) — held-out phrasings, distinct from both
# intent_classify.REFERENCE_EXAMPLES and each other (no recycling).
FIXTURE: list[tuple[str, str]] = [
    ("hey what did we land on for the caveman token savings number", "recall"),
    ("did we already build the intent classify module or is this the first time", "recall"),
    ("what's the plan we settled on for the finance-os bills feature", "recall"),
    ("remind me why lean lost to marvin on the harder bench tasks", "recall"),
    ("what was in last night's daily digest", "recall"),
    ("did we already look into this before, what did we conclude", "recall"),
    ("what was the reasoning behind the threshold we picked", "recall"),
    ("has this come up in a previous conversation", "recall"),
    ("what did the audit turn up last time we ran it", "recall"),
    ("what number did we settle on for that", "recall"),
    ("what's the latest on quantization techniques for local LLMs", "research"),
    ("how do HNSW indexes actually work under the hood", "research"),
    ("give me a rundown of recent multi-agent orchestration papers", "research"),
    ("what's the current thinking on prompt caching efficiency", "research"),
    ("explain how BM25 reranking complements semantic search", "research"),
    ("is there a well-known algorithm for this kind of problem", "research"),
    ("what does the literature say about this failure mode", "research"),
    ("who else has built something like this and how did they do it", "research"),
    ("what's the theoretical limit here", "research"),
    ("is this a solved problem or still an open question", "research"),
    ("the LRU cache test is failing, can you track down why", "coding"),
    ("add a --seed flag to intent_classify.py", "coding"),
    ("there's a typo in the routing table, fix it", "coding"),
    ("write a unit test for the threshold fallback path", "coding"),
    ("the merge script is throwing a KeyError, debug it", "coding"),
    ("this function is way too long, split it up", "coding"),
    ("the import is missing, add it", "coding"),
    ("make this run faster", "coding"),
    ("revert that last change, it broke something", "coding"),
    ("wire this new module into the existing script", "coding"),
    ("should the calibration loop live in calibrate.py or a new module", "architecture"),
    ("what's the tradeoff between a flag-gated rollout and a hard cutover here", "architecture"),
    ("how should we structure the roadmap sections going forward", "architecture"),
    ("walk me through the pros and cons of two embedding backends coexisting", "architecture"),
    ("what's the best way to phase the correlate.py migration", "architecture"),
    ("is this over-engineered for what we actually need", "architecture"),
    ("what would we regret about this decision in six months", "architecture"),
    ("does this fit with how the rest of the system is built", "architecture"),
    ("is it worth building this now or waiting", "architecture"),
    ("what's the simplest version of this that could work", "architecture"),
]

# (description, acceptable_intents) — genuinely dual-purpose phrasings.
# Not folded into FIXTURE's accuracy; reported separately.
AMBIGUOUS_FIXTURE: list[tuple[str, tuple[str, ...]]] = [
    ("what did we decide about the architecture for the routing classifier", ("recall", "architecture")),
    ("should we refactor this or leave it as is", ("coding", "architecture")),
    ("explain why this bug happens", ("coding", "research")),
    ("what's the best library for this", ("research", "architecture")),
    ("remind me how this algorithm works", ("recall", "research")),
    ("let's fix the design so this doesn't happen again", ("coding", "architecture")),
    ("what changed since last time", ("recall", "coding")),
    ("is this the same problem we hit before", ("recall", "coding")),
]


def _classify_row(desc: str) -> tuple[str, str]:
    kw_intent, _kw_hits, _ = route.resolve_intent(desc, use_embed=False)
    embed_intent, _embed_score, _method = route.resolve_intent(desc, use_embed=True)
    return kw_intent, embed_intent


def run_clean() -> None:
    kw_correct = 0
    embed_correct = 0
    disagreements = []

    print(f"{'description':<58} {'expected':<13} {'keyword':<13} {'embed':<13}")
    print("-" * 100)

    for desc, expected in FIXTURE:
        kw_intent, embed_intent = _classify_row(desc)

        kw_correct += kw_intent == expected
        embed_correct += embed_intent == expected

        if kw_intent != embed_intent:
            disagreements.append((desc, expected, kw_intent, embed_intent))

        short = desc if len(desc) <= 55 else desc[:52] + "..."
        print(f"{short:<58} {expected:<13} {kw_intent:<13} {embed_intent:<13}")

    n = len(FIXTURE)
    print("-" * 100)
    print(f"keyword accuracy: {kw_correct}/{n} ({kw_correct / n:.0%})")
    print(f"embed accuracy:   {embed_correct}/{n} ({embed_correct / n:.0%})")

    if disagreements:
        print(f"\n{len(disagreements)} disagreement(s):")
        for desc, expected, kw, emb in disagreements:
            print(f"  [{expected}] \"{desc}\"")
            print(f"      keyword={kw}  embed={emb}")


def run_ambiguous() -> None:
    print("\n" + "=" * 100)
    print("AMBIGUOUS CASES (informational only — not folded into accuracy above)")
    print("=" * 100)
    print(f"{'description':<58} {'acceptable':<24} {'keyword':<13} {'embed':<13}")
    print("-" * 100)

    kw_in_set = 0
    embed_in_set = 0

    for desc, acceptable in AMBIGUOUS_FIXTURE:
        kw_intent, embed_intent = _classify_row(desc)
        kw_in_set += kw_intent in acceptable
        embed_in_set += embed_intent in acceptable

        short = desc if len(desc) <= 55 else desc[:52] + "..."
        acc_str = "/".join(acceptable)
        print(f"{short:<58} {acc_str:<24} {kw_intent:<13} {embed_intent:<13}")

    n = len(AMBIGUOUS_FIXTURE)
    print("-" * 100)
    print(f"keyword landed in acceptable set: {kw_in_set}/{n} ({kw_in_set / n:.0%})")
    print(f"embed landed in acceptable set:   {embed_in_set}/{n} ({embed_in_set / n:.0%})")


if __name__ == "__main__":
    run_clean()
    run_ambiguous()
