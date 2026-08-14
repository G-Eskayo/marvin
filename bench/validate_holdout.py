#!/usr/bin/env python3
"""Run route.py's keyword vs. --embed classifier against the genuinely
held-out fixture in holdout_fixture.py — never used to write
intent_classify.REFERENCE_EXAMPLES or compare_route_classifiers.py's own
FIXTURE/AMBIGUOUS_FIXTURE (see that file's docstring for why the split
exists, per bench/RESULTS.md Runs 19-20).

Deliberately a separate script from compare_route_classifiers.py, not just a
separate data file: compare_route_classifiers.py is the fast-iteration
tuning tool (already used three times to pick reference examples); this is
the "don't look at this while tuning" validation run, kept structurally
apart to make it harder to accidentally blend the two.

Usage:
    ~/.agents/venv/bin/python bench/validate_holdout.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compare_route_classifiers import _classify_row  # noqa: E402
from holdout_fixture import HOLDOUT_AMBIGUOUS, HOLDOUT_FIXTURE  # noqa: E402


def run() -> None:
    kw_correct = 0
    embed_correct = 0
    disagreements = []

    print("HELD-OUT VALIDATION (never used to tune the reference set)")
    print(f"{'description':<58} {'expected':<13} {'keyword':<13} {'embed':<13}")
    print("-" * 100)

    for desc, expected in HOLDOUT_FIXTURE:
        kw_intent, embed_intent = _classify_row(desc)
        kw_correct += kw_intent == expected
        embed_correct += embed_intent == expected
        if kw_intent != embed_intent:
            disagreements.append((desc, expected, kw_intent, embed_intent))
        short = desc if len(desc) <= 55 else desc[:52] + "..."
        print(f"{short:<58} {expected:<13} {kw_intent:<13} {embed_intent:<13}")

    n = len(HOLDOUT_FIXTURE)
    print("-" * 100)
    print(f"keyword accuracy: {kw_correct}/{n} ({kw_correct / n:.0%})")
    print(f"embed accuracy:   {embed_correct}/{n} ({embed_correct / n:.0%})")

    if disagreements:
        print(f"\n{len(disagreements)} disagreement(s):")
        for desc, expected, kw, emb in disagreements:
            print(f"  [{expected}] \"{desc}\"")
            print(f"      keyword={kw}  embed={emb}")

    print("\n" + "=" * 100)
    print("AMBIGUOUS HOLD-OUT CASES (informational only)")
    print("=" * 100)
    print(f"{'description':<58} {'acceptable':<24} {'keyword':<13} {'embed':<13}")
    print("-" * 100)

    kw_in_set = 0
    embed_in_set = 0
    for desc, acceptable in HOLDOUT_AMBIGUOUS:
        kw_intent, embed_intent = _classify_row(desc)
        kw_in_set += kw_intent in acceptable
        embed_in_set += embed_intent in acceptable
        short = desc if len(desc) <= 55 else desc[:52] + "..."
        acc_str = "/".join(acceptable)
        print(f"{short:<58} {acc_str:<24} {kw_intent:<13} {embed_intent:<13}")

    n_amb = len(HOLDOUT_AMBIGUOUS)
    print("-" * 100)
    print(f"keyword landed in acceptable set: {kw_in_set}/{n_amb} ({kw_in_set / n_amb:.0%})")
    print(f"embed landed in acceptable set:   {embed_in_set}/{n_amb} ({embed_in_set / n_amb:.0%})")


if __name__ == "__main__":
    run()
