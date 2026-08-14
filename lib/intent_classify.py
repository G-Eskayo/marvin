#!/usr/bin/env python3
"""Embedding-based intent classifier for route.py.

Reuses the same Ollama nomic-embed-text + ChromaDB pattern retrieve.py already
runs (see skills/self-improve/scripts/retrieve.py, rebuild-embeddings.py).
Replaces route.py's hand-listed keyword scoring with a nearest-example match
against a small ChromaDB collection of natural-language task descriptions per
intent, seeded from the concepts behind route.py's current keyword lists.

Fixed similarity threshold for v1 (per ADR 0023) -- no calibration loop yet,
unlike safety-monitor/calibrate.py, because routing has no existing labeling
mechanism to feed one.

CLI usage:
    python3 intent_classify.py --seed          # (re)build the intent-routing collection
    python3 intent_classify.py "fix the bug"   # classify a task description
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import chromadb
import requests

HOME = Path.home()
CHROMA_PATH = HOME / ".claude" / "chroma"
OLLAMA_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text"
COLLECTION_NAME = "intent-routing"

# Fixed v1 threshold. score = 1 - dist/2 (ChromaDB cosine distance ranges
# 0-2, not 0-1 -- see qa-knowledge's documented gotcha; 1-dist alone is not
# a valid similarity). Empirically calibrated 2026-08-13 against the 40-item
# holdout fixture (bench/holdout_fixture.py) vs. 8 genuinely off-topic probes:
# on-topic best-match distances topped out at 0.524 (score 0.738); off-topic
# probes started overlapping at distance 0.396 (score 0.802). The two
# distributions overlap substantially with this reference-set size -- a
# single threshold CANNOT cleanly separate on-topic from off-topic queries
# here. 0.72 is set to preserve every validated on-topic match (score floor
# 0.738) while catching only the most extreme off-topic outliers -- a weak
# sanity floor, not a reliable "is this even related" classifier. A real fix
# needs the learned-threshold calibration loop already deferred by ADR 0023
# decision 2, not a better constant.
THRESHOLD = 0.72

# Reference examples per intent, written from the concepts behind route.py's
# INTENTS[...]["keywords"] lists, not the literal keyword strings. Must cover
# every key in route.py's INTENTS dict (enforced by
# test_reference_examples_cover_every_route_py_intent).
REFERENCE_EXAMPLES: dict[str, list[str]] = {
    "recall": [
        "What did we decide about the routing threshold last session?",
        "Remind me what the bench results were for the lean profile.",
        "Do you remember what we built for the quarantine review workflow?",
        "What was the outcome of that experiment we ran last week?",
        "Pull up what we discussed about the cross-machine sync bug.",
        "What did I tell you about how the finance-os project should work?",
        # Added Run 17 fast-follow (2026-08-13) -- casual status-check phrasing
        # the original 6 didn't cover, per compare_route_classifiers.py's misses.
        "What did we land on for the caching strategy?",
        "Did we ever finish the migration we started last month?",
        "What's the status of the intent classifier work?",
        "Catch me up on what happened in the last session.",
        "What was the outcome of the calibration discussion?",
        "Have we already tried this approach before?",
        # Added Run 25 fast-follow (2026-08-13) -- recall regressed (10/10
        # -> 7/10 on FIXTURE) as a side effect of Run 24's research/coding
        # expansion. Two specific pulls identified: research's new "Has this
        # been documented/solved..." examples share surface pattern with
        # genuine recall phrasing ("has this come up before"), and coding's
        # new "last commit"/"roll back" examples share "last"/"turned up"
        # vocabulary with recall's own session-history phrasing ("daily
        # digest", "audit turned up"). Examples below sharpen the contrast
        # explicitly (our own past conversations/sessions, not external
        # research; a summary/log artifact, not a code change) rather than
        # just adding more generic recall phrasing.
        "What did the last digest or summary say about this?",
        "Did the review we ran turn up anything on this before?",
        "Has this exact question come up in one of our own past conversations?",
        "Did we already run into this exact issue in an earlier session, not elsewhere?",
        "What came up the last time we looked at this together?",
        "Is this something we've already talked through before, between us?",
    ],
    "research": [
        "Can you research the latest papers on retrieval-augmented generation?",
        "What is hierarchical navigable small world search and how does it work?",
        "Summarize the state of the art in speech recognition.",
        "Explain how vector databases handle approximate nearest neighbor search.",
        "Tell me about recent developments in model distillation.",
        "Give me an overview of the arxiv paper on mixture of experts.",
        # Added Run 17 fast-follow -- "how/why does X work" and "what's the
        # latest on X" phrasing, which Run 17 showed getting misrouted.
        "What's the current thinking on this technique?",
        "Any new developments in this area worth knowing about?",
        "How does this technique compare to the alternatives?",
        "What's the theory behind why this approach works?",
        "Look into what's being published on this topic.",
        "Walk me through how this algorithm works under the hood.",
        # Added Run 19 fast-follow (2026-08-13) -- research was the weakest
        # category on the grown fixture (5/10 misses): current-thinking/
        # opinion-status, literature-review, prior-art/precedent,
        # theoretical-limits, and solved-vs-open-question phrasing. New
        # examples target those concepts without reusing the fixture's exact
        # sentences (Run 19 flagged tuning-against-the-measurement-set risk).
        "What's people's current take on this idea?",
        "Has anyone published results on this yet?",
        "What does prior work say about this?",
        "Has someone else already solved this same problem?",
        "What's the theoretical ceiling on how well this can work?",
        "Is this well-understood already or still an open research question?",
        "What's the academic consensus on this approach?",
        "Dig up what's known about this technique so far.",
        # Added Run 24 fast-follow (2026-08-13) -- three specific misses that
        # survived the Run 19 expansion, targeted directly: "who else has
        # built X" losing to recall's own "have we built/tried this" phrasing
        # (needs explicit external/other-teams framing), "literature says
        # about failure mode" losing to coding's bug association (needs
        # literature+failure paired explicitly), "current thinking on X"
        # losing to recall's status-check phrasing (needs explicit contrast
        # with internal/our-own decisions). Drawn from FIXTURE's misses
        # (already a tuning set, not the spent HOLDOUT_FIXTURE) per Run 21's
        # contamination discipline.
        "What are other teams outside this project doing about this same problem?",
        "Has this exact failure mode been documented in published research?",
        "What's the field's current position on this, independent of what we've decided internally?",
        "Pull up any published analysis of this kind of problem.",
        "What do external sources say about this, not just our own notes?",
        "Is there prior art elsewhere for exactly this kind of issue?",
    ],
    "coding": [
        "Fix the bug in the date validator that's throwing an off-by-one error.",
        "Implement a function to dedupe entries in the queue file.",
        "Refactor this script so the routing table isn't duplicated.",
        "Run the test suite and tell me what's failing.",
        "Write a script that seeds the ChromaDB collection from a JSON file.",
        "Debug why the LRU cache is evicting the wrong entry.",
        # Added Run 17 fast-follow -- short imperative fix/test/flag requests,
        # which Run 17 showed getting misrouted to architecture or recall.
        "Add a flag to this script for the new option.",
        "There's a typo here, fix it.",
        "Write a test for this edge case.",
        "Track down why this is failing.",
        "The script throws an error, figure out what's wrong.",
        "Clean up this function so it reads better.",
        # Added Run 24 fast-follow (2026-08-13) -- three specific misses:
        # "add a --seed flag to X.py" losing to architecture (needs a flag
        # request paired explicitly with argument-parser implementation, not
        # just "add a flag"), "write a unit test for the threshold fallback
        # path" losing to recall (needs test-writing paired with "fallback
        # path"/edge-case framing explicitly), "revert that last change, it
        # broke something" losing to recall (needs undo/rollback framed as an
        # action to take, not a past event to recall).
        "Add a new command-line flag to this script for the extra option.",
        "Put together a test that exercises the fallback branch.",
        "Undo the last commit -- it introduced a regression.",
        "Roll back that change, something broke because of it.",
        "Write a test covering the edge case where the primary path fails.",
        "This script needs a new flag; wire it into the argument parser.",
        # Added Run 28 (2026-08-13) -- 4 misses on the fresh v2 holdout, none
        # on FIXTURE (already 10/10 there, no tuning-set signal available).
        # Deliberately small/surgical (5 examples, not another 10) to test
        # Run 27's hypothesis that smaller expansions cost less: "port this to
        # the new module" pulled to architecture (module-placement language
        # read as a design decision, not an implementation action), "add
        # logging around this section" pulled to recall (coding already has
        # "add error handling around this call" but one example didn't
        # generalize to sibling vocabulary), "simplify this conditional"
        # pulled to architecture (simplification read as system-level, not
        # code-construct-level), "patch this so it doesn't choke on missing
        # fields" pulled to research (near-identical in meaning to coding's
        # existing "crashes on empty input, handle that" but different surface
        # vocabulary wasn't covered).
        "Move this code into the new module and update the imports.",
        "Add some logging statements around this block so we can see what's happening.",
        "Simplify this if/else block, it's needlessly nested.",
        "Patch this so it doesn't choke when a required field is missing.",
        "Migrate this function to live in the new module.",
        # Added Run 30 (2026-08-13) -- diagnosed live during the session-
        # persistence verify check (route.py's own --help example, "fix the
        # bug in utils.py", scored 0.8012 recall vs 0.7876 coding). Nearest
        # neighbor was recall's "Did we already run into this exact issue in
        # an earlier session, not elsewhere?" -- bare "bug in {file}" phrasing
        # with no session-history context still shares enough "bug"/"issue"
        # vocabulary to lose to recall's contrastive examples (added Run 25
        # for a different regression). None of coding's existing fix/debug
        # examples are this terse and bare -- they either name the specific
        # defect ("off-by-one error") or lack a filename entirely. Confirmed
        # the pattern generalizes (3/6 bare "bug in X.py" probes misrouted to
        # recall before this fix). Small/surgical per Run 28's finding that
        # smaller expansions cost less; phrasings deliberately distinct from
        # the probe sentences used to diagnose this, not copies of them.
        "utils.py has a bug in it, fix that.",
        "Track down the bug in the parser and fix it.",
        "There's a bug somewhere in the sync script, find it and fix it.",
    ],
    "architecture": [
        "Should we use a shared classifier or keep three separate keyword tables?",
        "How should we design the calibration loop for routing decisions?",
        "What's the best way to structure the intent-routing collection?",
        "Compare a flag-gated rollout versus a hard cutover for this classifier.",
        "What are the trade-offs of embedding-based routing versus keyword matching?",
        "Let's plan out the phased build for replacing route.py's classifier.",
        # Added Run 17 fast-follow -- module-placement/sequencing/tradeoff
        # phrasing to sharpen the boundary against coding/research.
        "What's the right way to structure this?",
        "Should this live in module A or module B?",
        "What are the tradeoffs of doing it this way versus that way?",
        "How should we sequence this work?",
        "Is this the right abstraction or are we overengineering?",
        "What's the long-term maintenance cost of this choice?",
        # Added Run 27 (2026-08-13) -- architecture had never been expanded
        # since Run 17 (fewest reference examples of any category) and Run 26's
        # fresh holdout showed it as the weakest category by far (4/10).
        # Diagnosed pattern across FIXTURE + holdout misses: 5 of 9 pulled to
        # recall specifically -- architecture had zero examples of
        # hypothetical/future-oriented design questions ("what if requirements
        # change", "would we regret this"), so that phrasing style defaulted
        # to recall's retrospective "what did we conclude" framing by default.
        # 2 pulled to coding ("system"/"moving parts" read as runtime/component
        # counting, not design). 2 pulled to research (revisiting a decision
        # read as "what does the field say" instead of "what do we now know").
        "What happens to this design if the requirements shift down the line?",
        "If we look back on this decision in a year, what would we wish we'd done differently?",
        "Would we design this the same way knowing what we know now, or take a different approach?",
        "What's the downside if this design assumption turns out to be wrong?",
        "How much of the system would be affected if this choice needs to be reversed later?",
        "Can this be built with fewer moving parts without losing what it needs to do?",
        "Is this worth building right now, or should it wait until we have more information?",
        "Should we commit to this design now or defer the decision?",
        "Given everything we've learned since, does this design decision still hold up?",
        "Now that circumstances have changed, is this still the right structural choice?",
    ],
}


def embed_text(text: str, task: str = "query") -> list[float] | None:
    """Embed via Ollama nomic-embed-text. task='query' for classify() input,
    'document' for reference examples -- nomic-embed is trained on this
    asymmetric prefix convention (matches rebuild-embeddings.py's usage)."""
    prefix = "search_query: " if task == "query" else "search_document: "
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": EMBED_MODEL, "input": f"{prefix}{text}"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["embeddings"][0]
    except Exception:
        return None


def _get_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return client.get_or_create_collection(
        COLLECTION_NAME, metadata={"hnsw:space": "cosine"}
    )


def build_collection() -> int:
    """(Re)embed every reference example into the intent-routing collection.
    Uses upsert (not add) so re-seeding after REFERENCE_EXAMPLES grows or
    changes is idempotent -- add() errors on ids that already exist, and
    ids are stable ("{intent}-{index}"), so a bigger reference set would
    otherwise require deleting the collection first. Returns the number of
    examples written."""
    col = _get_collection()
    ids, embeddings, documents, metadatas = [], [], [], []
    for intent, examples in REFERENCE_EXAMPLES.items():
        for i, example in enumerate(examples):
            ids.append(f"{intent}-{i}")
            embeddings.append(embed_text(example, task="document"))
            documents.append(example)
            metadatas.append({"intent": intent})
    col.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    return len(ids)


def classify(description: str) -> dict:
    """Return {"status": "ok"|"no_match"|"unavailable", "intent": str|None, "score": float|None}.

    "unavailable" signals the caller (route.py) should fall back to the
    keyword classifier -- Ollama or ChromaDB unreachable, not a real verdict.
    """
    vec = embed_text(description, task="query")
    if vec is None:
        return {"status": "unavailable", "intent": None, "score": None}

    try:
        col = _get_collection()
        res = col.query(
            query_embeddings=[vec], n_results=5, include=["metadatas", "distances"]
        )
    except Exception:
        return {"status": "unavailable", "intent": None, "score": None}

    metadatas = res["metadatas"][0]
    distances = res["distances"][0]
    if not metadatas:
        return {"status": "unavailable", "intent": None, "score": None}

    scored = sorted(
        ((1.0 - dist / 2.0, meta["intent"]) for meta, dist in zip(metadatas, distances)),
        key=lambda x: x[0],
        reverse=True,
    )
    best_score, best_intent = scored[0]
    if best_score < THRESHOLD:
        return {"status": "no_match", "intent": None, "score": round(best_score, 4)}
    return {"status": "ok", "intent": best_intent, "score": round(best_score, 4)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("description", nargs="?", default="", help="task description to classify")
    ap.add_argument("--seed", action="store_true", help="(re)build the intent-routing collection")
    args = ap.parse_args()

    if args.seed:
        n = build_collection()
        print(f"intent-routing: seeded {n} reference examples")
        return

    if not args.description:
        ap.print_help()
        sys.exit(1)

    result = classify(args.description)
    print(result)


if __name__ == "__main__":
    main()
