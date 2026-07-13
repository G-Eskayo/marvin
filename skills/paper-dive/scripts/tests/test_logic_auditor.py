"""Tests for logic_auditor.py. Run via:
    ~/.agents/venv/bin/python -m pytest scripts/tests/test_logic_auditor.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest

from logic_auditor import classify_paper_type, classify_all, PAPER_TYPES


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
