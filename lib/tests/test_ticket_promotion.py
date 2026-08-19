"""Tests for ticket_promotion.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_promotion.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import ticket_promotion as tp  # noqa: E402


def _promoting_evaluator(finding_text):
    return {"promote": True, "reasoning": "unlocks three future items"}


def _skipping_evaluator(finding_text):
    return {"promote": False, "reasoning": "purely standalone, no leverage"}


# ── promote/don't-promote decision ──────────────────────────────────────────

def test_creates_ticket_when_evaluator_says_promote():
    created = []
    result = tp.promote_finding(
        "some finding text",
        evaluator=_promoting_evaluator,
        ticket_creator=lambda finding, reasoning: created.append((finding, reasoning)) or "G-Eskayo/marvin#42",
    )
    assert result["promoted"] is True
    assert result["ticket_ref"] == "G-Eskayo/marvin#42"
    assert len(created) == 1


def test_skips_ticket_creation_when_evaluator_says_dont_promote():
    created = []
    result = tp.promote_finding(
        "some finding text",
        evaluator=_skipping_evaluator,
        ticket_creator=lambda finding, reasoning: created.append((finding, reasoning)) or "should-not-be-called",
    )
    assert result["promoted"] is False
    assert result["ticket_ref"] is None
    assert created == []


def test_reasoning_captured_in_result_and_passed_to_ticket_creator():
    captured = {}
    tp.promote_finding(
        "some finding text",
        evaluator=_promoting_evaluator,
        ticket_creator=lambda finding, reasoning: captured.update(finding=finding, reasoning=reasoning) or "G-Eskayo/marvin#42",
    )
    assert captured["reasoning"] == "unlocks three future items"
    assert captured["finding"] == "some finding text"


def test_reasoning_present_even_when_not_promoted():
    result = tp.promote_finding("some finding text", evaluator=_skipping_evaluator, ticket_creator=lambda f, r: "x")
    assert result["reasoning"] == "purely standalone, no leverage"


def test_no_manual_approval_step_runs_synchronously_to_completion():
    # promote_finding takes only the finding + injectable hooks -- no
    # external confirmation/approval call is possible in this interface.
    result = tp.promote_finding(
        "some finding text", evaluator=_promoting_evaluator,
        ticket_creator=lambda f, r: "G-Eskayo/marvin#1",
    )
    assert result["promoted"] is True  # completed fully, no pause


# ── default evaluator (mocked subprocess) ───────────────────────────────────

def test_default_evaluator_uses_compounding_leverage_lens(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "PROMOTE: yes\nREASONING: unlocks future work"
            returncode = 0
        return R()

    monkeypatch.setattr(tp.subprocess, "run", fake_run)
    result = tp._default_evaluator("some finding")

    prompt = calls[0][calls[0].index("-p") + 1]
    assert "compounding leverage" in prompt.lower() or "cheaper, faster" in prompt.lower()
    assert result["promote"] is True
    assert "unlocks future work" in result["reasoning"]


def test_default_evaluator_parses_no_decision(monkeypatch):
    def fake_run(cmd, **kwargs):
        class R:
            stdout = "PROMOTE: no\nREASONING: standalone win only"
            returncode = 0
        return R()

    monkeypatch.setattr(tp.subprocess, "run", fake_run)
    result = tp._default_evaluator("some finding")
    assert result["promote"] is False
    assert "standalone win only" in result["reasoning"]


# ── default ticket_creator (mocked subprocess, runs to-prd headlessly) ─────

def test_default_ticket_creator_invokes_to_prd_and_returns_ticket_ref(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            stdout = "Published the PRD.\nTICKET_URL: https://github.com/G-Eskayo/marvin/issues/50"
            returncode = 0
        return R()

    monkeypatch.setattr(tp.subprocess, "run", fake_run)
    ref = tp._default_ticket_creator("some finding text", "unlocks three future items")

    prompt = calls[0][calls[0].index("-p") + 1]
    assert "/to-prd" in prompt
    assert "some finding text" in prompt
    assert "unlocks three future items" in prompt
    assert ref == "https://github.com/G-Eskayo/marvin/issues/50"
