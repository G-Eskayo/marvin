#!/usr/bin/env python3
"""
logic_auditor.py — judges whether a paper's own argument is internally
consistent (paper-dive synthesis tool, see marvin-roadmap.md §K's "long-term
vision" item, scoped down via a grill-with-docs session 2026-07-13). Full
design: ~/Documents/Projects/experiments/anthropic-fellows-memory-paper/
docs/logic-auditor-design.md and that project's CONTEXT.md.

Distinct from argument_mapper.py (structural core-claim + "builds on" graph
only, no judgment of argument quality). v1 scope: the 15 hand-picked seed
papers only, per-paper only (cross-paper comparison deferred to a future
competing-ideas-surface tool, see ADR 0001).

Model choice validated 2026-07-13 (see the design doc's "Model" section):
qwen2.5:3b for this classifier and layer 1 (Toulmin extraction), qwen2.5:14b
for layer 2 (formal inference-validity) -- 3b/7b both got the inferential
direction backwards on a real test case, 14b did not.
"""
from __future__ import annotations
import json
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/chat"
# Validated 2026-07-13 against all 15 real seed abstracts: 3b (even with a prompt refined to
# counter its "named attack/method -> conceptual" bias) still misclassified MINJA and
# many-shot-jailbreaking as conceptual despite both reporting concrete measured attack success
# rates. 7b was WORSE, not better -- overcorrected to "empirical" broadly and broke two
# previously-correct survey/benchmark classifications (sok-trust-authorization-mismatch,
# sorry-bench). 14b fixed both stubborn cases with zero regressions on the rest.
CLASSIFY_MODEL = "qwen2.5:14b"

PAPER_TYPES = {"empirical", "survey", "benchmark", "conceptual"}


def ollama_chat(model: str, messages: list[dict], timeout: int = 60) -> str:
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode()
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"]


CLASSIFY_PROMPT = """Below is an academic paper's title and abstract. Classify what KIND of argument it makes, choosing exactly one of these four types:

- empirical: presents new experiments or measurements to support a claim
- survey: synthesizes/categorizes existing work into a taxonomy (includes "SoK" / systematization-of-knowledge papers) -- the real argument is that the taxonomy correctly carves up the space, not new experimental evidence
- benchmark: introduces a measurement instrument or dataset -- the real argument is about construct validity (does it measure what it claims to)
- conceptual: proposes a model or framework via explicit structural claims ("if X, then Y"), without primarily relying on new experiments

IMPORTANT: naming a specific method, attack, or system (e.g. an attack called "MINJA" or an
algorithm like GCG) does NOT by itself make a paper conceptual. What matters is the EVIDENCE: if
the abstract reports specific measured results from running something -- percentages, success
rates, hours of testing, benchmark scores, statistical findings -- classify it empirical, even
though it also names and describes a method. Reserve "conceptual" for papers whose central
argument is a structural or theoretical claim without new experimental measurement backing it
(a taxonomy, a formal framework, an argument about how systems relate to each other).

Title: {title}

Abstract: {abstract}

Respond with ONLY one word: empirical, survey, benchmark, or conceptual."""


def classify_paper_type(title: str, abstract: str, chat_fn=None) -> str:
    """Returns one of PAPER_TYPES, or "unknown" if the response can't be
    parsed into exactly one of them -- deliberately not guessing/defaulting
    silently, since a wrong type routes the paper to the wrong evaluation
    method downstream."""
    chat_fn = chat_fn or (lambda messages: ollama_chat(CLASSIFY_MODEL, messages))
    prompt = CLASSIFY_PROMPT.format(title=title, abstract=abstract)
    response = chat_fn([{"role": "user", "content": prompt}]).strip().lower()

    found = [t for t in PAPER_TYPES if t in response]
    if len(found) == 1:
        return found[0]
    return "unknown"


def classify_all(papers: dict[str, tuple[str, str]], chat_fn=None) -> dict[str, str]:
    """papers: {slug: (title, abstract)}. Returns {slug: type}."""
    return {
        slug: classify_paper_type(title, abstract, chat_fn=chat_fn)
        for slug, (title, abstract) in papers.items()
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Classify paper-knowledge seed papers by argument type.")
    ap.add_argument("--seeds-json", required=True, help="Path to a JSON file: {slug: title, ...}")
    ap.add_argument("--out-json", required=True)
    args = ap.parse_args()

    from pathlib import Path
    import chromadb

    CHROMA_PATH = Path.home() / ".claude" / "chroma"
    seed_titles = json.loads(Path(args.seeds_json).read_text())

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection = client.get_or_create_collection("paper-knowledge")
    data = collection.get(ids=list(seed_titles), include=["documents"])
    abstracts = dict(zip(data["ids"], data["documents"]))

    papers = {slug: (title, abstracts[slug]) for slug, title in seed_titles.items() if slug in abstracts}
    result = classify_all(papers)

    Path(args.out_json).write_text(json.dumps(result, indent=2))
    for slug, ptype in result.items():
        print(f"{slug}: {ptype}")
