#!/usr/bin/env python3
"""Three-way comparison on the genuinely held-out fixture (holdout_fixture.py):
keyword classifier, embedding classifier (ADR 0023, production default), and
a Jev-pattern (typesafe.ai System One Choice primitive, reproduced on
Claude Haiku's own --json-schema, see jev_pattern_classify.py) classifier.

Same discipline as validate_holdout.py: read-only consumer of the holdout
fixture, never used to tune REFERENCE_EXAMPLES or jev_pattern_classify's
criteria text. Unlike the other two classifiers (free, local), the Jev-
pattern one costs real money per call (a fresh `claude -p` process each
time, no session reuse) -- this script reports that cost explicitly,
since "is it worth it" has to weigh accuracy against a real per-call price,
not just accuracy in isolation.

Usage:
    ~/.agents/venv/bin/python bench/validate_holdout_jev.py [--limit N]
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from compare_route_classifiers import _classify_row  # noqa: E402
from holdout_fixture import HOLDOUT_AMBIGUOUS, HOLDOUT_FIXTURE  # noqa: E402
from jev_pattern_classify import classify_jev  # noqa: E402


def run(limit: int | None = None) -> None:
    fixture = HOLDOUT_FIXTURE[:limit] if limit else HOLDOUT_FIXTURE
    ambiguous = HOLDOUT_AMBIGUOUS[:limit] if limit else HOLDOUT_AMBIGUOUS

    kw_correct = embed_correct = jev_correct = 0
    jev_errors = 0
    total_cost = 0.0
    total_latency = 0.0
    rows = []

    print("HELD-OUT VALIDATION: keyword vs embed vs jev-pattern")
    print(f"{'description':<50} {'expected':<13} {'kw':<13} {'embed':<13} {'jev':<13} {'jev_conf':<9} {'jev_$':<8}")
    print("-" * 125)

    for desc, expected in fixture:
        kw_intent, embed_intent = _classify_row(desc)
        t0 = time.time()
        jev = classify_jev(desc)
        wall = time.time() - t0

        kw_correct += kw_intent == expected
        embed_correct += embed_intent == expected
        if jev["error"]:
            jev_errors += 1
        else:
            jev_correct += jev["choice"] == expected
        total_cost += jev["cost_usd"]
        total_latency += wall

        short = desc if len(desc) <= 47 else desc[:44] + "..."
        conf = f"{jev['confidence']:.2f}" if jev["confidence"] is not None else "ERR"
        print(f"{short:<50} {expected:<13} {kw_intent:<13} {embed_intent:<13} "
              f"{str(jev['choice']):<13} {conf:<9} ${jev['cost_usd']:.4f}")
        rows.append((desc, expected, kw_intent, embed_intent, jev))

    n = len(fixture)
    print("-" * 125)
    print(f"keyword accuracy: {kw_correct}/{n} ({kw_correct/n:.0%})  [free, local]")
    print(f"embed accuracy:   {embed_correct}/{n} ({embed_correct/n:.0%})  [free, local Ollama]")
    print(f"jev accuracy:     {jev_correct}/{n} ({jev_correct/n:.0%})  "
          f"({jev_errors} error(s))  [${total_cost:.4f} total, "
          f"${total_cost/n:.4f}/call, {total_latency/n:.1f}s/call avg]")

    print("\n" + "=" * 125)
    print("AMBIGUOUS HOLD-OUT CASES (informational only)")
    print("=" * 125)
    kw_in = embed_in = jev_in = 0
    for desc, acceptable in ambiguous:
        kw_intent, embed_intent = _classify_row(desc)
        jev = classify_jev(desc)
        kw_in += kw_intent in acceptable
        embed_in += embed_intent in acceptable
        jev_in += jev["choice"] in acceptable
        total_cost += jev["cost_usd"]
        short = desc if len(desc) <= 47 else desc[:44] + "..."
        print(f"{short:<50} {'/'.join(acceptable):<24} {kw_intent:<13} {embed_intent:<13} {str(jev['choice']):<13}")

    n_amb = len(ambiguous)
    print("-" * 125)
    print(f"keyword in acceptable set: {kw_in}/{n_amb} ({kw_in/n_amb:.0%})")
    print(f"embed in acceptable set:   {embed_in}/{n_amb} ({embed_in/n_amb:.0%})")
    print(f"jev in acceptable set:     {jev_in}/{n_amb} ({jev_in/n_amb:.0%})")
    print(f"\ngrand total jev-pattern cost this run: ${total_cost:.4f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap items per fixture (cost control)")
    args = ap.parse_args()
    run(limit=args.limit)
