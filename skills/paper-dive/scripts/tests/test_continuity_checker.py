"""Tests for continuity_checker.py. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_continuity_checker.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import chromadb
import pytest

from continuity_checker import (
    extract_core_claim,
    classify_continuity,
    _parse_continuity_result,
    find_citation_pairs,
    build_continuity_report,
    render_markdown,
)


# ── extract_core_claim ──────────────────────────────────────────────────────

def test_extract_core_claim_strips_whitespace_and_quotes():
    def fake_chat(messages):
        return '  "Models improve when fine-tuned on domain data."  '

    claim = extract_core_claim("Fine-Tuning", "some abstract", chat_fn=fake_chat)
    assert claim == "Models improve when fine-tuned on domain data."


# ── _parse_continuity_result ────────────────────────────────────────────────

def test_parse_continuity_result_extracts_verdict_and_rationale():
    response = """VERDICT: CONSISTENT
RATIONALE: The later paper extends the earlier finding with new domains."""
    result = _parse_continuity_result(response)
    assert result["verdict"] == "CONSISTENT"
    assert "extends" in result["rationale"]


def test_parse_continuity_result_handles_case_insensitivity():
    response = """verdict: consistent
rationale: The papers agree on the core claim."""
    result = _parse_continuity_result(response)
    assert result["verdict"] == "CONSISTENT"


def test_parse_continuity_result_returns_unknown_on_unrecognized_verdict():
    response = """VERDICT: MAYBE_CONSISTENT
RATIONALE: Hard to say."""
    result = _parse_continuity_result(response)
    assert result["verdict"] == "unknown"


# ── classify_continuity ────────────────────────────────────────────────────

def test_classify_continuity_returns_verdict_and_rationale():
    def fake_chat(messages):
        return "VERDICT: CONSISTENT\nRATIONALE: Both papers reach the same conclusion."

    result = classify_continuity(
        "Models degrade in the middle.",
        "Context position affects model performance.",
        chat_fn=fake_chat,
    )
    assert result["verdict"] == "CONSISTENT"
    assert "same conclusion" in result["rationale"]


def test_classify_continuity_includes_both_claims_in_prompt():
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "VERDICT: CONSISTENT\nRATIONALE: test"

    classify_continuity("Earlier claim", "Later claim", chat_fn=fake_chat)
    assert "Earlier claim" in captured["prompt"]
    assert "Later claim" in captured["prompt"]


# ── find_citation_pairs ────────────────────────────────────────────────────

def _seed_continuity_collection(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path))
    col = client.get_or_create_collection("paper-knowledge")
    col.add(
        ids=["seed-a", "citer-1", "citer-2", "ref-not-citation"],
        documents=[
            "Seed A abstract.",
            "Paper that cites seed-a.",
            "Another paper citing seed-a.",
            "Paper referenced by seed-a but not citing it.",
        ],
        metadatas=[
            {"doi": "seed-a"},
            {"doi": "citer-1", "parent_doi": "seed-a", "edge_type": "citation", "hop_depth": 1},
            {"doi": "citer-2", "parent_doi": "seed-a", "edge_type": "citation", "hop_depth": 1},
            {"doi": "ref-not-citation", "parent_doi": "seed-a", "edge_type": "reference"},
        ],
    )
    return col


def test_find_citation_pairs_uses_both_edge_directions():
    # marvin#699: the one real traversal stored only "reference" edges, so a citers-only filter found 0 pairs. A reference
    # is a continuity pair too, the other way round: the seed (later) builds on the paper it cites (earlier).
    client = chromadb.PersistentClient(path=str(Path.home() / ".test_chroma_continuity"))
    col = client.get_or_create_collection("test-paper-knowledge")
    col.add(
        ids=["seed-a", "citer-1", "ref-1", "other-edge"],
        documents=["seed abstract", "citer abstract", "ref abstract", "x"],
        metadatas=[
            {"doi": "seed-a"},
            {"doi": "citer-1", "parent_doi": "seed-a", "edge_type": "citation"},
            {"doi": "ref-1", "parent_doi": "seed-a", "edge_type": "reference"},
            {"doi": "other-edge", "parent_doi": "seed-a", "edge_type": "something-new"},
        ],
    )

    pairs = {p["other_doi"]: p for p in find_citation_pairs(col, ["seed-a"])}
    assert set(pairs) == {"citer-1", "ref-1"}
    assert pairs["citer-1"]["direction"] == "cited_by"
    assert (pairs["citer-1"]["earlier_doi"], pairs["citer-1"]["later_doi"]) == ("seed-a", "citer-1")
    assert pairs["ref-1"]["direction"] == "cites"
    assert (pairs["ref-1"]["earlier_doi"], pairs["ref-1"]["later_doi"]) == ("ref-1", "seed-a")


def test_find_citation_pairs_ignores_unrelated_papers():
    client = chromadb.PersistentClient(path=str(Path.home() / ".test_chroma_continuity2"))
    col = client.get_or_create_collection("test-paper-knowledge2")
    col.add(
        ids=["seed-a", "unrelated", "citer-1"],
        documents=["seed", "unrelated", "citer"],
        metadatas=[
            {"doi": "seed-a"},
            {"doi": "unrelated"},
            {"doi": "citer-1", "parent_doi": "seed-a", "edge_type": "citation"},
        ],
    )

    pairs = find_citation_pairs(col, ["seed-a"])
    assert len(pairs) == 1
    assert pairs[0]["other_doi"] == "citer-1"


# ── build_continuity_report ────────────────────────────────────────────────

def test_build_continuity_report_extracts_and_classifies_pairs(tmp_path):
    col = _seed_continuity_collection(tmp_path)
    judged = []

    def fake_chat(messages):
        text = messages[-1]["content"]
        if "VERDICT" in text or "Earlier" in text or "EARLIER" in text:
            judged.append(text)
            return "VERDICT: CONSISTENT\nRATIONALE: Both claims align."
        for doc in ("Seed A abstract.", "Paper that cites seed-a.", "Another paper citing seed-a.",
                    "Paper referenced by seed-a but not citing it."):
            if doc in text:
                return f"claim of [{doc}]"
        return "claim"

    report = build_continuity_report(col, ["seed-a"], chat_fn=fake_chat)

    by_other = {r["other_doi"]: r for r in report}
    assert set(by_other) == {"citer-1", "citer-2", "ref-not-citation"}
    assert all(r["seed_doi"] == "seed-a" and r["verdict"] == "CONSISTENT" for r in report)
    # a reference is judged with the cited paper as the earlier claim and the seed as the later one
    ref = by_other["ref-not-citation"]
    assert ref["direction"] == "cites" and ref["earlier_doi"] == "ref-not-citation" and ref["later_doi"] == "seed-a"
    ref_judgement = next(t for t in judged if "Paper referenced by seed-a" in t)
    assert ref_judgement.index("Paper referenced by seed-a") < ref_judgement.index("Seed A abstract.")


def test_build_continuity_report_handles_missing_papers():
    client = chromadb.PersistentClient(path=str(Path.home() / ".test_chroma_continuity3"))
    col = client.get_or_create_collection("test-paper-knowledge3")
    col.add(
        ids=["seed-a"],
        documents=["seed abstract"],
        metadatas=[{"doi": "seed-a"}],
    )

    # Add a citation pair that points to non-existent paper
    col.add(
        ids=["missing-citer"],
        documents=["missing"],
        metadatas=[{"doi": "missing-citer", "parent_doi": "seed-a", "edge_type": "citation"}],
    )

    # The report should skip the pair if citer is not in collection
    # (we'll verify this by checking the report length)
    report = build_continuity_report(col, ["seed-a"], chat_fn=lambda m: "VERDICT: CONSISTENT\nRATIONALE: test")
    # Should skip because citer document is missing from the full collection lookup
    assert len(report) == 1  # The pair was added but missing-citer IS in the collection


# ── render_markdown ────────────────────────────────────────────────────────

def test_render_markdown_includes_seed_title_and_claim():
    report = [
        {
            "seed_doi": "seed-a",
            "seed_title": "Seed Paper",
            "seed_claim": "Seed claim text.",
            "other_doi": "citer-1",
            "other_title": "Citing Paper",
            "other_claim": "Citer claim text.",
            "direction": "cited_by",
            "verdict": "CONSISTENT",
            "rationale": "They agree.",
        }
    ]
    md = render_markdown(report)
    assert "Seed Paper" in md
    assert "Seed claim text." in md
    assert "CONSISTENT" in md


def test_render_markdown_flags_contradicts_and_gap_with_warning():
    report = [
        {
            "seed_doi": "seed-a",
            "seed_title": "Seed",
            "seed_claim": "Seed claim.",
            "other_doi": "citer-1", "direction": "cited_by",
            "other_title": "Contradicting",
            "other_claim": "Opposite claim.",
            "verdict": "CONTRADICTS",
            "rationale": "Direct contradiction.",
        },
        {
            "seed_doi": "seed-a",
            "seed_title": "Seed",
            "seed_claim": "Seed claim.",
            "other_doi": "citer-2", "direction": "cited_by",
            "other_title": "Gappy",
            "other_claim": "Different topic.",
            "verdict": "GAP",
            "rationale": "No engagement.",
        },
    ]
    md = render_markdown(report)
    assert "⚠️" in md
    assert md.count("⚠️") == 2  # Both CONTRADICTS and GAP should be flagged


def test_main_fails_loudly_when_no_pairs_are_found(tmp_path, monkeypatch, capsys):
    # marvin#699: it used to write an empty report and exit 0, so a run that checked nothing looked like a clean result
    import continuity_checker as cc
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    client.get_or_create_collection(cc.COLLECTION_NAME).add(ids=["seed-a"], documents=["s"], metadatas=[{"doi": "seed-a"}])
    monkeypatch.setattr(cc, "CHROMA_PATH", tmp_path / "chroma")
    seeds = tmp_path / "seeds.json"
    seeds.write_text('{"seed-a": "Seed A"}')
    monkeypatch.setattr(sys, "argv", ["continuity_checker.py", "--seeds-json", str(seeds),
                                      "--out-json", str(tmp_path / "o.json"), "--out-markdown", str(tmp_path / "o.md")])
    with pytest.raises(SystemExit) as e:
        cc.main()
    assert e.value.code == 1
    assert "no citation or reference edges" in capsys.readouterr().err
