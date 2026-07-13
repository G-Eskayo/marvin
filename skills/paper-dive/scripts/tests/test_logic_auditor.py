"""Tests for logic_auditor.py. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_logic_auditor.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest

from logic_auditor import (
    classify_paper_type,
    classify_all,
    PAPER_TYPES,
    _parse_fields,
    extract_structure,
    extract_all,
    EXTRACTION_FIELDS,
)


# ── classify_paper_type ──────────────────────────────────────────────────────

def test_classify_paper_type_recognizes_empirical():
    def fake_chat(messages):
        return "empirical"

    assert classify_paper_type("A Title", "An abstract", chat_fn=fake_chat) == "empirical"


def test_classify_paper_type_recognizes_survey():
    def fake_chat(messages):
        return "survey"

    assert classify_paper_type("A Title", "An abstract", chat_fn=fake_chat) == "survey"


def test_classify_paper_type_recognizes_benchmark():
    def fake_chat(messages):
        return "benchmark"

    assert classify_paper_type("A Title", "An abstract", chat_fn=fake_chat) == "benchmark"


def test_classify_paper_type_recognizes_conceptual():
    def fake_chat(messages):
        return "conceptual"

    assert classify_paper_type("A Title", "An abstract", chat_fn=fake_chat) == "conceptual"


def test_classify_paper_type_is_case_insensitive_and_strips_whitespace():
    def fake_chat(messages):
        return "  Empirical  \n"

    assert classify_paper_type("A Title", "An abstract", chat_fn=fake_chat) == "empirical"


def test_classify_paper_type_extracts_label_from_extra_prose():
    # models sometimes ignore "respond with only the label" and explain themselves anyway
    def fake_chat(messages):
        return "This paper is best classified as a survey, since it synthesizes existing work."

    assert classify_paper_type("A Title", "An abstract", chat_fn=fake_chat) == "survey"


def test_classify_paper_type_falls_back_to_unknown_on_unparseable_response():
    def fake_chat(messages):
        return "I'm not sure, this could be several things at once"

    assert classify_paper_type("A Title", "An abstract", chat_fn=fake_chat) == "unknown"


def test_classify_paper_type_includes_title_and_abstract_in_prompt():
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "empirical"

    classify_paper_type("My Title", "My abstract text", chat_fn=fake_chat)
    assert "My Title" in captured["prompt"]
    assert "My abstract text" in captured["prompt"]


def test_paper_types_is_the_four_documented_types():
    assert PAPER_TYPES == {"empirical", "survey", "benchmark", "conceptual"}


# ── classify_all ─────────────────────────────────────────────────────────────

def test_classify_all_classifies_every_paper_in_the_input_dict():
    responses = iter(["empirical", "survey", "conceptual"])

    def fake_chat(messages):
        return next(responses)

    papers = {
        "seed-a": ("Title A", "Abstract A"),
        "seed-b": ("Title B", "Abstract B"),
        "seed-c": ("Title C", "Abstract C"),
    }
    result = classify_all(papers, chat_fn=fake_chat)

    assert result == {"seed-a": "empirical", "seed-b": "survey", "seed-c": "conceptual"}


def test_classify_all_handles_empty_input():
    assert classify_all({}, chat_fn=lambda messages: "empirical") == {}


# ── _parse_fields (shared line-based parser for all extraction types) ──────

def test_parse_fields_extracts_single_line_values():
    response = "CLAIM: models degrade in the middle\nGROUNDS: two tasks measured\n"
    result = _parse_fields(response, ["CLAIM", "GROUNDS"])
    assert result == {"claim": "models degrade in the middle", "grounds": "two tasks measured"}


def test_parse_fields_accumulates_multiline_values_until_next_field():
    response = (
        "CLAIM: models degrade\nin the middle of long contexts\n"
        "GROUNDS: two tasks were measured\n"
    )
    result = _parse_fields(response, ["CLAIM", "GROUNDS"])
    assert result["claim"] == "models degrade\nin the middle of long contexts"
    assert result["grounds"] == "two tasks were measured"


def test_parse_fields_is_case_insensitive_on_labels():
    response = "claim: something\nGrounds: something else\n"
    result = _parse_fields(response, ["CLAIM", "GROUNDS"])
    assert result == {"claim": "something", "grounds": "something else"}


def test_parse_fields_missing_field_is_absent_not_empty_string():
    response = "CLAIM: something\n"
    result = _parse_fields(response, ["CLAIM", "GROUNDS"])
    assert result == {"claim": "something"}
    assert "grounds" not in result


# ── extract_structure (routes to type-appropriate extraction) ──────────────

def test_extract_structure_empirical_uses_toulmin_fields():
    def fake_chat(messages):
        return "CLAIM: c\nGROUNDS: g\nWARRANT: w\nQUALIFIER: q\n"

    result = extract_structure("Title", "Abstract", "empirical", chat_fn=fake_chat)
    assert result == {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}


def test_extract_structure_survey_uses_taxonomy_fields():
    def fake_chat(messages):
        return "TAXONOMY: t\nCOVERAGE: c\nCLAIMED_GAPS: g\n"

    result = extract_structure("Title", "Abstract", "survey", chat_fn=fake_chat)
    assert result == {"taxonomy": "t", "coverage": "c", "claimed_gaps": "g"}


def test_extract_structure_benchmark_uses_construct_validity_fields():
    def fake_chat(messages):
        return "MEASURES: m\nCONSTRUCT_VALIDITY_EVIDENCE: e\nSCOPE: s\n"

    result = extract_structure("Title", "Abstract", "benchmark", chat_fn=fake_chat)
    assert result == {"measures": "m", "construct_validity_evidence": "e", "scope": "s"}


def test_extract_structure_conceptual_uses_structural_claim_fields():
    def fake_chat(messages):
        return "STRUCTURAL_CLAIMS: s\nKEY_DEFINITIONS: d\nINTERNAL_DEPENDENCIES: i\n"

    result = extract_structure("Title", "Abstract", "conceptual", chat_fn=fake_chat)
    assert result == {"structural_claims": "s", "key_definitions": "d", "internal_dependencies": "i"}


def test_extract_structure_rejects_unknown_type():
    with pytest.raises(ValueError, match="unknown"):
        extract_structure("Title", "Abstract", "unknown", chat_fn=lambda m: "")


def test_extract_structure_includes_title_and_abstract_in_prompt():
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "CLAIM: c\nGROUNDS: g\nWARRANT: w\nQUALIFIER: q\n"

    extract_structure("My Title", "My abstract", "empirical", chat_fn=fake_chat)
    assert "My Title" in captured["prompt"]
    assert "My abstract" in captured["prompt"]


def test_extraction_fields_covers_all_four_types():
    assert set(EXTRACTION_FIELDS) == PAPER_TYPES


# ── extract_all ──────────────────────────────────────────────────────────────

def test_extract_all_routes_each_paper_by_its_own_type():
    def fake_chat(messages):
        prompt = messages[0]["content"]
        if "GROUNDS" in prompt:
            return "CLAIM: c\nGROUNDS: g\nWARRANT: w\nQUALIFIER: q\n"
        return "TAXONOMY: t\nCOVERAGE: c\nCLAIMED_GAPS: g\n"

    papers = {
        "seed-a": ("Title A", "Abstract A", "empirical"),
        "seed-b": ("Title B", "Abstract B", "survey"),
    }
    result = extract_all(papers, chat_fn=fake_chat)

    assert result["seed-a"]["claim"] == "c"
    assert result["seed-b"]["taxonomy"] == "t"


def test_extract_all_handles_empty_input():
    assert extract_all({}, chat_fn=lambda m: "") == {}
