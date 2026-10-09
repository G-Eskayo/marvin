"""Tests for ticket_promotion.py. Run via:
    ~/.agents/venv/bin/python -m pytest lib/tests/test_ticket_promotion.py -v
"""
from __future__ import annotations
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LIB))

import json

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


# ── default ticket_creator: the model writes the ticket, code creates it (marvin#305) ─────

def test_default_ticket_creator_writes_with_a_model_and_creates_a_needs_triage_issue(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stderr = ""
            stdout = (json.dumps({"result": "TITLE: Embed the roadmap sections\n---\n## What to build\nX.\n\n## North-star fit\nReuses Y."})
                      if "-p" in cmd else json.dumps({"html_url": "https://github.com/G-Eskayo/marvin/issues/50"}))
        return R()

    monkeypatch.setattr(tp.subprocess, "run", fake_run)
    ref = tp._default_ticket_creator("some finding text", "unlocks three future items")

    prompt = calls[0][calls[0].index("-p") + 1]
    assert "some finding text" in prompt and "unlocks three future items" in prompt and "North-star fit" in prompt
    create = calls[1]
    assert create[:3] == ["gh", "api", "repos/G-Eskayo/marvin/issues"]
    assert "title=Embed the roadmap sections" in create and "labels[]=needs-triage" in create
    body = create[create.index("-f", create.index("title=Embed the roadmap sections")) + 1]
    assert body.startswith("body=## What to build") and "ticket promotion" in body
    assert ref == "https://github.com/G-Eskayo/marvin/issues/50"


def test_a_ticket_the_model_did_not_write_is_not_created(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode, stderr, stdout = 0, "", json.dumps({"result": "I could not do that."})
        return R()

    monkeypatch.setattr(tp.subprocess, "run", fake_run)
    assert tp._default_ticket_creator("f", "r") is None
    assert len(calls) == 1


def test_a_finding_that_is_already_done_creates_nothing(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode, stderr, stdout = 0, "", json.dumps({"result": "NOTHING_LEFT"})
        return R()

    monkeypatch.setattr(tp.subprocess, "run", fake_run)
    assert tp._default_ticket_creator("f", "r") == tp.NOTHING_LEFT
    assert len(calls) == 1


# ── job label tracking (autonomous run accounting) ──────────────────────────

def test_default_evaluator_passes_ticket_promotion_job_label(monkeypatch):
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append({"kind": kind, "ticket": kwargs.get("ticket")})
        class R:
            text = "PROMOTE: yes\nREASONING: test"
            returncode = 0
            stderr = ""
        return R()

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(tp, "marvin_launcher", marvin_launcher)
    tp._default_evaluator("some finding text")

    assert len(launches) == 1
    assert launches[0]["ticket"] == "ticket-promotion"


def test_default_ticket_creator_passes_ticket_promotion_job_label(monkeypatch):
    import marvin_launcher
    launches = []

    def fake_launch(kind, prompt, **kwargs):
        launches.append({"kind": kind, "ticket": kwargs.get("ticket")})
        class R:
            text = "TITLE: Test\n---\n## What to build\nTest."
            returncode = 0
            stderr = ""
        return R()

    monkeypatch.setattr(marvin_launcher, "launch", fake_launch)
    monkeypatch.setattr(tp, "marvin_launcher", marvin_launcher)

    # Mock gh api for issue creation
    calls = []
    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        class R:
            returncode = 0
            stderr = ""
            stdout = json.dumps({"html_url": "https://github.com/G-Eskayo/marvin/issues/1"})
        return R()
    monkeypatch.setattr(tp.subprocess, "run", fake_run)

    tp._default_ticket_creator("finding", "reasoning")

    assert len(launches) == 1
    assert launches[0]["ticket"] == "ticket-promotion"
