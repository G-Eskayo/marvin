#!/usr/bin/env python3
"""
continuity_checker.py — examines whether later papers actually build on or
engage with earlier work, or whether they contradict it without acknowledgment
/ claim to build on it but have gaps in the logical chain (paper-dive synthesis
tool, see issue #26).

v1 scope (2026-08-31): hand-picked seed papers only, examining citers found
via the citation-graph edges already present in paper-knowledge. For each seed,
pulls every paper linked to it in either direction (a citer is later, a reference
is earlier) and classifies the continuity relationship of each pair.

Model choice (unvalidated on real abstracts, noted in docstring): qwen2.5:14b
for judgment, same caliber as logic_auditor's classification task.

Reuses extract_core_claim from argument_mapper.py to keep claim-extraction
consistent across all synthesis tools, avoiding unnecessary duplication of the
ollama_chat/prompt plumbing.
"""
from __future__ import annotations
import json
import sys
import urllib.request
from pathlib import Path

CHROMA_PATH = Path.home() / ".claude" / "chroma"
COLLECTION_NAME = "paper-knowledge"
OLLAMA_URL = "http://localhost:11434/api/chat"
CONTINUITY_MODEL = "qwen2.5:14b"

CONTINUITY_VERDICTS = {"CONSISTENT", "GAP", "CONTRADICTS"}


def ollama_chat(model: str, messages: list[dict], timeout: int = 60) -> str:
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]


# Reuse from argument_mapper
CLAIM_PROMPT = """Below is an academic paper's title and abstract. State its single core claim or finding in ONE crisp sentence -- what did they actually show or argue, not what topic they cover. No preamble, no "This paper...", just the claim itself.

Title: {title}

Abstract: {abstract}

Core claim (one sentence):"""


def extract_core_claim(title: str, abstract: str, chat_fn=None) -> str:
    chat_fn = chat_fn or (lambda messages: ollama_chat(CONTINUITY_MODEL, messages))
    prompt = CLAIM_PROMPT.format(title=title, abstract=abstract)
    response = chat_fn([{"role": "user", "content": prompt}])
    return response.strip().strip('"')


CONTINUITY_PROMPT = """Below are two academic papers' core claims. The first (EARLIER) is the earlier paper. The second (LATER) cites it. Classify the continuity relationship:

- CONSISTENT: The later paper builds on or extends the earlier claim. It engages with the earlier work's core assertion, even if critical of it.
- GAP: The later paper claims to build on the earlier work (via citation) but doesn't actually engage with its core claim. The papers address different questions or use different premises.
- CONTRADICTS: The later paper's core claim directly contradicts the earlier paper's core claim, without acknowledging or engaging with that contradiction.

Judge only the explicit relationship between the TWO stated claims, not whether the papers are actually related or whether the citation is appropriate.

EARLIER claim: {earlier_claim}

LATER claim: {later_claim}

Respond in exactly this format:
VERDICT: <one of: CONSISTENT, GAP, CONTRADICTS>
RATIONALE: <one sentence explaining the verdict>"""


def classify_continuity(earlier_claim: str, later_claim: str, chat_fn=None) -> dict[str, str]:
    """Classifies the continuity relationship between two claims.
    Returns {"verdict": one of CONTINUITY_VERDICTS, "rationale": str}."""
    chat_fn = chat_fn or (lambda messages: ollama_chat(CONTINUITY_MODEL, messages))
    prompt = CONTINUITY_PROMPT.format(earlier_claim=earlier_claim, later_claim=later_claim)
    response = chat_fn([{"role": "user", "content": prompt}])
    return _parse_continuity_result(response)


def _parse_continuity_result(response: str) -> dict[str, str]:
    """Parses the VERDICT and RATIONALE lines from continuity response."""
    import re
    result = {}
    for line in response.splitlines():
        if line.strip().upper().startswith("VERDICT:"):
            verdict_text = line.strip()[len("VERDICT:"):].strip().upper()
            # Match whole verdict words, not substrings
            found = [v for v in CONTINUITY_VERDICTS if re.search(r'\b' + re.escape(v) + r'\b', verdict_text)]
            result["verdict"] = found[0] if len(found) == 1 else "unknown"
        elif line.strip().upper().startswith("RATIONALE:"):
            result["rationale"] = line.strip()[len("RATIONALE:"):].strip()
    return result


# How each stored edge orients a continuity pair (marvin#699). paper_graph stores a non-seed paper with the edge that
# found it: "citation" = it cites its parent (it is the later work); "reference" = its parent cites it (it is earlier).
_DIRECTION = {"citation": "cited_by", "reference": "cites"}


def find_citation_pairs(collection, seed_slugs: list[str]) -> list[dict]:
    """Every (earlier, later) pair between a seed and a paper linked to it, in both directions. A seed that Semantic
    Scholar doesn't index only ever gets reference edges (paper_graph can't find who cites it), so a citers-only filter
    found nothing for the one real run (2026-07-13). Returns {seed_doi, other_doi, direction, earlier_doi, later_doi}."""
    data = collection.get(include=["metadatas"])
    pairs = []

    for doi, meta in zip(data["ids"], data["metadatas"]):
        parent = meta.get("parent_doi")
        direction = _DIRECTION.get(meta.get("edge_type"))
        if parent in seed_slugs and direction:
            earlier, later = (parent, doi) if direction == "cited_by" else (doi, parent)
            pairs.append({"seed_doi": parent, "other_doi": doi, "direction": direction,
                          "earlier_doi": earlier, "later_doi": later})

    return pairs


def build_continuity_report(
    collection,
    seed_slugs: list[str],
    chat_fn=None,
) -> list[dict]:
    """For each seed and each paper linked to it, extracts both claims and classifies continuity, always earlier claim
    first. Returns list of {seed_*, other_*, direction, earlier_doi, later_doi, verdict, rationale}."""
    data = collection.get(include=["documents", "metadatas"])
    by_id = {i: (doc, meta) for i, doc, meta in zip(data["ids"], data["documents"], data["metadatas"])}

    claims: dict[str, str] = {}

    def claim(doi: str) -> tuple[str, str]:
        doc, meta = by_id[doi]
        title = meta.get("title") or doi
        if doi not in claims:
            claims[doi] = extract_core_claim(title, doc, chat_fn=chat_fn)
        return title, claims[doi]

    result = []
    for pair in find_citation_pairs(collection, seed_slugs):
        seed_id, other_id = pair["seed_doi"], pair["other_doi"]
        if seed_id not in by_id or other_id not in by_id:
            continue
        seed_title, seed_claim = claim(seed_id)
        other_title, other_claim = claim(other_id)
        earlier_claim, later_claim = ((seed_claim, other_claim) if pair["direction"] == "cited_by"
                                      else (other_claim, seed_claim))
        continuity = classify_continuity(earlier_claim, later_claim, chat_fn=chat_fn)
        result.append({
            "seed_doi": seed_id,
            "seed_title": seed_title,
            "seed_claim": seed_claim,
            "other_doi": other_id,
            "other_title": other_title,
            "other_claim": other_claim,
            "direction": pair["direction"],
            "earlier_doi": pair["earlier_doi"],
            "later_doi": pair["later_doi"],
            "verdict": continuity.get("verdict", "unknown"),
            "rationale": continuity.get("rationale", ""),
        })

    return result


def render_markdown(report: list[dict]) -> str:
    lines = [
        "# Continuity Check Report — Citation Engagement Analysis",
        "",
        "Generated by `continuity_checker.py`. For each seed paper and its citers, "
        "examines whether the later work actually builds on or engages with the earlier "
        "claim, or whether it contradicts, has gaps, or is consistent (LLM-assessed via "
        "core claim comparison, qwen2.5:14b, unvalidated on real abstracts).",
        "",
    ]

    # Group by seed for readability
    by_seed = {}
    for entry in report:
        seed_id = entry["seed_doi"]
        by_seed.setdefault(seed_id, []).append(entry)

    for seed_id, entries in by_seed.items():
        seed_title = entries[0]["seed_title"] if entries else seed_id
        lines.append(f"## {seed_title}")
        lines.append(f"**Seed DOI**: {seed_id}")
        lines.append(f"**Seed Claim**: {entries[0]['seed_claim']}")
        lines.append("")

        for entry in entries:
            verdict = entry["verdict"]
            flag = "⚠️ " if verdict in ["CONTRADICTS", "GAP"] else ""
            how = "cites this seed" if entry["direction"] == "cited_by" else "is cited by this seed"
            lines.append(f"### {flag}{entry['other_title']} ({how})")
            lines.append(f"**Verdict**: {verdict}")
            lines.append(f"**Rationale**: {entry['rationale']}")
            lines.append(f"**Its Claim**: {entry['other_claim']}")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Check continuity of citations in paper-knowledge.")
    ap.add_argument("--seeds-json", required=True, help="Path to a JSON file: {slug: title, ...}")
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-markdown", required=True)
    args = ap.parse_args()

    import chromadb

    seed_titles = json.loads(Path(args.seeds_json).read_text())
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection(COLLECTION_NAME)

    report = build_continuity_report(collection, seed_slugs=list(seed_titles.keys()))
    if not report:
        # An empty report used to exit 0 and look like a clean result (marvin#699)
        print(f"[continuity-checker] no citation or reference edges found for {len(seed_titles)} seed(s) in "
              f"{COLLECTION_NAME}; nothing was checked. Run paper_graph.py on these seeds first.", file=sys.stderr)
        sys.exit(1)

    Path(args.out_json).write_text(json.dumps(report, indent=2))
    Path(args.out_markdown).write_text(render_markdown(report))
    print(f"[continuity-checker] checked {len(report)} citation pair(s) and wrote to {args.out_json} and {args.out_markdown}", file=sys.stderr)


if __name__ == "__main__":
    main()
