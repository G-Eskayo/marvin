"""Tests for prompt_override parameter in logic_auditor.py.
Run via: ~/.agents/venv/bin/python -m pytest scripts/tests/test_logic_auditor_prompt_override.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))

import pytest
from logic_auditor import judge_extraction, judge_all, _safe_format_prompt, _GENERAL_FALLACY_CHECKLIST


# ── judge_extraction with prompt_override ────────────────────────────────────

def test_judge_extraction_uses_default_prompt_when_no_override():
    """Without prompt_override, behavior is unchanged from prior behavior."""
    def fake_chat(messages):
        # Verify the prompt contains the type-specific rubric
        assert "WARRANT" in messages[0]["content"]  # empirical-specific field
        return "NONE"

    extraction = {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}
    result = judge_extraction(extraction, "empirical", chat_fn=fake_chat)
    assert result == []


def test_judge_extraction_uses_override_prompt_when_provided():
    """With prompt_override, uses the override instead of the type-specific one."""
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "NONE"

    extraction = {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}
    override = "Custom prompt: check {claim} and {grounds} only."
    result = judge_extraction(extraction, "empirical", chat_fn=fake_chat,
                             prompt_override=override)

    assert "Custom prompt" in captured["prompt"]
    assert "check c and g only" in captured["prompt"]
    assert result == []


def test_judge_extraction_override_interpolates_extraction_fields():
    """prompt_override is formatted with extraction fields like the default prompt."""
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "FINDING: test finding\n"

    extraction = {"claim": "models degrade", "grounds": "two tasks", "warrant": "w", "qualifier": "q"}
    override = "CLAIM: {claim}\nGROUNDS: {grounds}"
    result = judge_extraction(extraction, "empirical", chat_fn=fake_chat,
                             prompt_override=override)

    assert "CLAIM: models degrade" in captured["prompt"]
    assert "GROUNDS: two tasks" in captured["prompt"]
    assert result == ["test finding"]


def test_judge_extraction_override_includes_fallacies_list():
    """prompt_override gets the fallacies list like the default prompt does."""
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "NONE"

    extraction = {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}
    override = "Check for: {fallacies}"
    result = judge_extraction(extraction, "empirical", chat_fn=fake_chat,
                             prompt_override=override)

    assert "hasty generalization" in captured["prompt"]  # part of fallacies list
    assert result == []


def test_judge_extraction_override_works_with_survey_type():
    """prompt_override works for survey type and the override text reaches the model."""
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "NONE"

    extraction_survey = {"taxonomy": "survey-taxonomy", "coverage": "many papers", "claimed_gaps": "AI safety"}
    override = "Override survey: {taxonomy} with gaps {claimed_gaps}"
    result = judge_extraction(extraction_survey, "survey", chat_fn=fake_chat,
                             prompt_override=override)
    assert "Override survey: survey-taxonomy with gaps AI safety" in captured["prompt"]
    assert result == []


def test_judge_extraction_override_works_with_benchmark_type():
    """prompt_override works for benchmark type and the override text reaches the model."""
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "NONE"

    extraction_bench = {"measures": "accuracy", "construct_validity_evidence": "baseline comparison", "scope": "ImageNet"}
    override = "Override benchmark: {measures} with evidence {construct_validity_evidence}"
    result = judge_extraction(extraction_bench, "benchmark", chat_fn=fake_chat,
                             prompt_override=override)
    assert "Override benchmark: accuracy with evidence baseline comparison" in captured["prompt"]
    assert result == []


def test_judge_extraction_override_works_with_conceptual_type():
    """prompt_override works for conceptual type and the override text reaches the model."""
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "NONE"

    extraction_conceptual = {"structural_claims": "if X then Y", "key_definitions": "X is process A", "internal_dependencies": "Y depends on X"}
    override = "Override conceptual: {structural_claims} with definitions {key_definitions}"
    result = judge_extraction(extraction_conceptual, "conceptual", chat_fn=fake_chat,
                             prompt_override=override)
    assert "Override conceptual: if X then Y with definitions X is process A" in captured["prompt"]
    assert result == []


def test_judge_extraction_override_parses_findings_same_as_default():
    """prompt_override responses are parsed for findings the same way."""
    def fake_chat(messages):
        return "FINDING: first issue\nFINDING: second issue\n"

    extraction = {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}
    override = "Just check: {claim}"
    result = judge_extraction(extraction, "empirical", chat_fn=fake_chat,
                             prompt_override=override)

    assert result == ["first issue", "second issue"]


def test_judge_extraction_override_handles_missing_extraction_fields():
    """prompt_override fills missing fields like default does."""
    captured = {}

    def fake_chat(messages):
        captured["prompt"] = messages[0]["content"]
        return "NONE"

    extraction = {"claim": "only claim"}  # missing grounds, warrant, qualifier
    override = "Check: {claim} and {grounds}"
    result = judge_extraction(extraction, "empirical", chat_fn=fake_chat,
                             prompt_override=override)

    assert "only claim" in captured["prompt"]
    assert "(not extracted)" in captured["prompt"]
    assert result == []


def test_judge_extraction_override_none_same_as_not_provided():
    """Explicitly passing prompt_override=None is identical to not providing it."""
    captured1 = {}
    captured2 = {}

    def make_chat(captured):
        def fake_chat(messages):
            captured["prompt"] = messages[0]["content"]
            return "NONE"
        return fake_chat

    extraction = {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}

    # Without the parameter
    judge_extraction(extraction, "empirical", chat_fn=make_chat(captured1))
    # With explicit None
    judge_extraction(extraction, "empirical", chat_fn=make_chat(captured2),
                    prompt_override=None)

    assert captured1["prompt"] == captured2["prompt"]


# ── judge_all with prompt_override ───────────────────────────────────────────

def test_judge_all_threads_override_through_all_papers():
    """judge_all passes prompt_override to every judge_extraction call."""
    prompts_seen = []

    def make_chat():
        def fake_chat(messages):
            prompts_seen.append(messages[0]["content"])
            return "NONE"
        return fake_chat

    papers = {
        "seed-a": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
        "seed-b": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
    }
    override = "Custom: {claim}"
    result = judge_all(papers, chat_fn=make_chat(), prompt_override=override)

    assert len(prompts_seen) == 2
    assert all("Custom: c" in prompt for prompt in prompts_seen)
    assert result == {"seed-a": [], "seed-b": []}


def test_judge_all_without_override_uses_default_prompts():
    """Without prompt_override, judge_all uses type-specific prompts."""
    prompts_seen = []

    def make_chat():
        def fake_chat(messages):
            prompts_seen.append(messages[0]["content"])
            return "NONE"
        return fake_chat

    papers = {
        "seed-a": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
        "seed-b": ({"taxonomy": "t", "coverage": "c", "claimed_gaps": "g"}, "survey"),
    }
    result = judge_all(papers, chat_fn=make_chat())

    # First should have empirical-specific field, second survey-specific
    assert "WARRANT" in prompts_seen[0]
    assert "TAXONOMY" in prompts_seen[1]
    assert result == {"seed-a": [], "seed-b": []}


def test_judge_all_override_with_empirical_papers_only():
    """judge_all override works with same-type papers."""
    captured_prompts = []

    def make_chat():
        def fake_chat(messages):
            captured_prompts.append(messages[0]["content"])
            return "NONE"
        return fake_chat

    papers = {
        "emp1": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
        "emp2": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
    }
    override = "Override for all: {claim}"
    result = judge_all(papers, chat_fn=make_chat(), prompt_override=override)

    assert all("Override for all:" in p for p in captured_prompts)
    assert result == {"emp1": [], "emp2": []}


def test_judge_all_override_none_same_as_not_provided():
    """judge_all with prompt_override=None is same as not providing it."""
    captured1 = []
    captured2 = []

    def make_chat(captured):
        def fake_chat(messages):
            captured.append(messages[0]["content"])
            return "NONE"
        return fake_chat

    papers = {
        "seed-a": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
    }

    judge_all(papers, chat_fn=make_chat(captured1))
    judge_all(papers, chat_fn=make_chat(captured2), prompt_override=None)

    assert captured1[0] == captured2[0]


# ── Integration: override + findings ─────────────────────────────────────────

def test_judge_extraction_override_can_produce_different_findings():
    """An override prompt can produce different findings than the default.
    Uses the same model (via chat_fn) with different prompts."""
    captured_prompts = []

    def model_chat(messages):
        prompt = messages[0]["content"]
        captured_prompts.append(prompt)
        # Return different results based on which prompt was sent
        if "QUALIFIER" in prompt:  # default prompt checks QUALIFIER
            return "FINDING: warrant is too weak"
        else:
            return "NONE"

    extraction = {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}

    # Default version (contains "QUALIFIER" check)
    default_result = judge_extraction(extraction, "empirical", chat_fn=model_chat)
    # Lenient version with custom override
    override_result = judge_extraction(extraction, "empirical", chat_fn=model_chat,
                                      prompt_override="Lenient: check {claim} only")

    assert default_result == ["warrant is too weak"]
    assert override_result == []
    assert len(captured_prompts) == 2
    assert captured_prompts[0] != captured_prompts[1]  # Different prompts were used


def test_judge_all_can_show_accuracy_change_with_override():
    """judge_all shows how prompt changes affect findings (not different chat functions).
    Same model behaves differently based on prompt content."""
    captured_prompts = []

    def model_chat(messages):
        prompt = messages[0]["content"]
        captured_prompts.append(prompt)
        # Model returns different findings based on which prompt was sent
        if "QUALIFIER" in prompt:  # default prompt contains "QUALIFIER"
            return "FINDING: issue found"
        else:
            return "NONE"

    papers = {
        "seed-a": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
        "seed-b": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
    }

    # Default: contains "QUALIFIER" (real judgment prompt checks this)
    default_findings = judge_all(papers, chat_fn=model_chat)
    default_acc = sum(1 for f in default_findings.values() if len(f) == 0) / len(default_findings)

    # Override: lenient version without QUALIFIER
    override_findings = judge_all(papers, chat_fn=model_chat,
                                 prompt_override="lenient check: {claim}")
    override_acc = sum(1 for f in override_findings.values() if len(f) == 0) / len(override_findings)

    assert default_acc == 0.0  # 0 papers with no findings (both have "issue found")
    assert override_acc == 1.0  # 2 papers with no findings (both have "NONE")
    assert len(captured_prompts) == 4  # 2 papers × 2 runs = 4 prompts
    # First two prompts should be different from last two
    assert captured_prompts[0] != captured_prompts[2]


# ── Error handling: type mismatches, format errors ────────────────────────────

def test_judge_extraction_override_with_wrong_field_type_raises():
    """prompt_override with wrong field names for paper type raises ValueError."""
    def fake_chat(messages):
        return "NONE"

    # Try to use empirical fields on a survey paper
    extraction_survey = {"taxonomy": "t", "coverage": "c", "claimed_gaps": "g"}
    override = "Check the {claim} field"  # empirical-specific field

    with pytest.raises(ValueError, match="requires fields"):
        judge_extraction(extraction_survey, "survey", chat_fn=fake_chat,
                        prompt_override=override)


def test_judge_extraction_override_with_literal_braces_raises():
    """prompt_override with malformed braces raises ValueError."""
    def fake_chat(messages):
        return "NONE"

    extraction = {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}
    # Unmatched brace in what looks like a JSON snippet
    override = "Check JSON: {\"key\": \"value\" and {claim}"

    with pytest.raises(ValueError, match="formatting failed"):
        judge_extraction(extraction, "empirical", chat_fn=fake_chat,
                        prompt_override=override)


def test_safe_format_prompt_rejects_missing_fields():
    """_safe_format_prompt raises ValueError when template requires unavailable fields."""
    fields = {"claim": "c", "grounds": "g"}
    template = "Check {claim}, {grounds}, and {warranty}"  # warranty doesn't exist

    with pytest.raises(ValueError, match="requires fields"):
        _safe_format_prompt(template, _GENERAL_FALLACY_CHECKLIST, fields)


def test_safe_format_prompt_rejects_malformed_template():
    """_safe_format_prompt raises ValueError when template has unmatched braces."""
    fields = {"claim": "c"}
    # Unmatched closing brace causes Formatter.parse to raise ValueError
    template = "Check {claim} and }"

    with pytest.raises(ValueError, match="formatting failed"):
        _safe_format_prompt(template, _GENERAL_FALLACY_CHECKLIST, fields)


def test_safe_format_prompt_allows_fallacies():
    """_safe_format_prompt correctly includes the fallacies parameter."""
    fields = {"claim": "c"}
    template = "Check {claim} for {fallacies}"

    result = _safe_format_prompt(template, "list of fallacies", fields)
    assert "Check c for list of fallacies" == result


def test_safe_format_prompt_rejects_attribute_access():
    """_safe_format_prompt prevents format() attribute traversal attacks."""
    fields = {"claim": "c"}
    # Try to access __class__ via format()
    template = "Check {claim.__class__}"

    with pytest.raises(ValueError):
        _safe_format_prompt(template, "fallacies", fields)


# ── Design tests: error handling and correctness ──────────────────────────────

def test_judge_extraction_malformed_prompt_raises_not_returns():
    """Design test 12: incompatible/malformed prompt_override raises ValueError, not a finding."""
    def fake_chat(messages):
        return "NONE"

    extraction = {"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}
    # Override that requires a field not in empirical extraction
    override = "Check {claim} and {missing_field}"

    with pytest.raises(ValueError, match="requires fields"):
        judge_extraction(extraction, "empirical", chat_fn=fake_chat,
                        prompt_override=override)


def test_judge_extraction_all_paper_types_with_wrong_fields_raises():
    """For each paper type, using fields from other types raises, not returns."""
    def fake_chat(messages):
        return "NONE"

    test_cases = [
        # Use survey field on empirical
        ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical",
         "Check {taxonomy}"),
        # Use empirical field on survey
        ({"taxonomy": "t", "coverage": "c", "claimed_gaps": "g"}, "survey",
         "Check {claim}"),
        # Use empirical field on benchmark
        ({"measures": "m", "construct_validity_evidence": "c", "scope": "s"}, "benchmark",
         "Check {claim}"),
        # Use benchmark field on conceptual
        ({"structural_claims": "s", "key_definitions": "d", "internal_dependencies": "i"},
         "conceptual", "Check {measures}"),
    ]

    for extraction, paper_type, override in test_cases:
        with pytest.raises(ValueError, match="requires fields"):
            judge_extraction(extraction, paper_type, chat_fn=fake_chat,
                           prompt_override=override)


def test_judge_all_propagates_malformed_prompt_error():
    """judge_all raises ValueError when any paper's prompt is malformed."""
    def fake_chat(messages):
        return "NONE"

    papers = {
        "seed-a": ({"claim": "c", "grounds": "g", "warrant": "w", "qualifier": "q"}, "empirical"),
    }
    # Override requires a field that doesn't exist in empirical
    override = "Check {unknown_field}"

    with pytest.raises(ValueError, match="requires fields"):
        judge_all(papers, chat_fn=fake_chat, prompt_override=override)
