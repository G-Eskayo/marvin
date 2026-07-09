#!/usr/bin/env python3
"""Retrieve transferable patterns from OTHER domains for a technical/engineering
problem, as input to cross-domain creative synthesis.

This script does retrieval only. The actual synthesis (deciding how a
mechanism from an unrelated domain could combine with the problem at hand)
is the model's job — see creative/SKILL.md's "Cross-Domain Pattern
Synthesis" section for how to use this output.

Usage:
    ~/.agents/venv/bin/python cross_domain_synthesis.py "how should we dedupe ingestion events"
    ~/.agents/venv/bin/python cross_domain_synthesis.py "cache invalidation strategy" --n 5
    ~/.agents/venv/bin/python cross_domain_synthesis.py "problem" --domain aws-cloud --json
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

QA_AGENT_SCRIPTS = Path.home() / ".agents" / "skills" / "qa-agent" / "scripts"
sys.path.insert(0, str(QA_AGENT_SCRIPTS))
from qa_scan import infer_domain    # noqa: E402
from qa_query import query_kb       # noqa: E402


def synthesize(problem: str, n: int = 3, domain: str | None = None) -> dict:
    """Infer the problem's own domain (unless given), then fetch top-N
    transferable patterns from OTHER domains via qa_query's lateral mode.
    Falls back to a plain (non-lateral) query if no domain can be inferred —
    there's nothing to exclude, so cross-domain framing wouldn't be honest."""
    inferred = domain or infer_domain("", problem)
    if inferred:
        results = query_kb(problem, n=n, lateral_domain=inferred)
    else:
        results = query_kb(problem, n=n)
    return {"problem": problem, "domain": inferred, "lateral": bool(inferred),
            "results": results}


def print_human(synthesis: dict) -> None:
    if synthesis["domain"]:
        print(f"problem domain (inferred): {synthesis['domain']}")
        print(f"showing top {len(synthesis['results'])} transferable pattern(s) from OTHER domains\n")
    else:
        print("could not infer a domain for this problem — showing general top matches "
              "(not guaranteed cross-domain)\n")

    if not synthesis["results"]:
        print("No results in qa-knowledge. Run qa_scan.py on some projects first, "
              "or this problem may be too novel for the current KB.")
        return

    for i, r in enumerate(synthesis["results"], 1):
        m = r["metadata"]
        domain_str  = f"  domain={m['domain']}"       if m.get("domain")       else ""
        ptype_str   = f"  pattern={m['pattern_type']}" if m.get("pattern_type") else ""
        outcome_str = f"\n   outcome: {m['outcome']}"  if m.get("outcome")      else ""
        print(f"{i}. [{m.get('category', '?')}] {r['document']}")
        relevance = 1 / (1 + r["distance"])
        print(f"   project={m.get('project', '?')}  confidence={m.get('confidence', '?')}"
              f"  relevance={relevance:.2f}{domain_str}{ptype_str}{outcome_str}")
        print()

    print("For each mechanism above: ask how it could combine with the problem "
          "statement. Generate one candidate approach per mechanism — these should "
          "surface combinations a same-domain search would never produce.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("problem", help="the technical/engineering problem statement")
    ap.add_argument("--n", type=int, default=3, help="number of patterns to retrieve (default 3)")
    ap.add_argument("--domain", default=None,
                    help="override the inferred domain (excluded from results)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="output raw JSON for sub-agent consumption")
    args = ap.parse_args()

    data = synthesize(args.problem, n=args.n, domain=args.domain)

    if args.as_json:
        print(json.dumps(data, indent=2))
    else:
        print_human(data)


if __name__ == "__main__":
    main()
