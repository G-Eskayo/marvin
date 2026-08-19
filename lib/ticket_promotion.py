#!/usr/bin/env python3
"""Ticket promotion for the MR pipeline (G-Eskayo/marvin#6).

suggestions.md/quarantine.md stay exactly as they are today -- this module
only decides whether an individual finding is worth promoting into a real
GitHub ticket, and if so, creates it. Deliberately biased toward a low
promotion bar: since downstream execution is cheap (Haiku tier, background,
automated) and the real judgment happens at the verification step later in
the pipeline, this module's job is "cheap enough to be worth a shot," not
"correctly predict value." Scores on compounding leverage -- reusing
daily_digest.py's existing prioritization lens ("does this item make
multiple future items cheaper, faster, or newly possible") -- not
suggestions.md's hand-typed Priority field or quarantine.md's safety tau
score, neither of which measures leverage.

Deviates slightly from "via the to-prd -> to-issues flow" in the parent
ticket's prose: to-prd's own SKILL.md is explicitly designed not to
interview the user ("just synthesize what you already know"), but
to-issues explicitly quizzes the user and iterates until approved --
fundamentally incompatible with "no manual per-item approval step
required" (an explicit, testable acceptance criterion, which takes
precedence over the descriptive prose). This module uses to-prd only, one
ready-for-agent ticket per promoted finding. A finding big enough to need
tracer-bullet decomposition is a follow-on step for a real session to run
/to-issues against the resulting ticket, same as this pipeline's own
parent PRD (#1) was broken into #2-#11.

`evaluator` and `ticket_creator` are injectable hooks, same testability
seam as sandbox_orchestration's `executor` -- both defaults shell out to
headless `claude -p`, since "does this unlock future work" and "write a
real PRD" both require real reasoning, not a heuristic.
"""
from __future__ import annotations
import re
import subprocess
from typing import Callable

EVALUATOR_MODEL = "claude-sonnet-5"
CREATOR_MODEL = "claude-sonnet-5"
EVALUATE_TIMEOUT_S = 180
CREATE_TIMEOUT_S = 600

TICKET_URL_RE = re.compile(r"TICKET_URL:\s*(\S+)")
PROMOTE_RE = re.compile(r"PROMOTE:\s*(yes|no)", re.IGNORECASE)
REASONING_RE = re.compile(r"REASONING:\s*(.+)", re.IGNORECASE | re.DOTALL)


def _default_evaluator(finding_text: str) -> dict:
    prompt = (
        "Evaluate this finding from suggestions.md/quarantine.md on compounding leverage: "
        "does it make multiple *future* items cheaper, faster, or newly possible, above its own "
        "standalone value? A foundation that makes the next few builds easier beats a bigger "
        "isolated win. Bias toward a low bar -- downstream execution is cheap and automated, and "
        "real judgment happens later at the verification step, not here.\n\n"
        f"Finding:\n{finding_text}\n\n"
        "Respond with exactly two lines:\nPROMOTE: yes or no\nREASONING: <one or two sentences>"
    )
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", EVALUATOR_MODEL],
        capture_output=True, text=True, timeout=EVALUATE_TIMEOUT_S,
    )
    stdout = result.stdout
    promote_match = PROMOTE_RE.search(stdout)
    reasoning_match = REASONING_RE.search(stdout)
    return {
        "promote": bool(promote_match and promote_match.group(1).lower() == "yes"),
        "reasoning": reasoning_match.group(1).strip() if reasoning_match else stdout.strip(),
    }


def _default_ticket_creator(finding_text: str, reasoning: str) -> str | None:
    prompt = (
        f"/to-prd Turn this finding into a PRD and publish it: {finding_text}\n\n"
        f"Compounding-leverage justification for why this was promoted: {reasoning}\n\n"
        "After publishing, end your response with exactly one line: "
        "TICKET_URL: <the issue URL you just created>"
    )
    result = subprocess.run(
        ["claude", "-p", prompt, "--model", CREATOR_MODEL],
        capture_output=True, text=True, timeout=CREATE_TIMEOUT_S,
    )
    match = TICKET_URL_RE.search(result.stdout)
    return match.group(1) if match else None


def promote_finding(
    finding_text: str,
    evaluator: Callable[[str], dict] | None = None,
    ticket_creator: Callable[[str, str], str | None] | None = None,
) -> dict:
    """Evaluate a single finding and, if it clears the compounding-leverage
    bar, create a real ticket for it. Runs synchronously to completion --
    no manual approval step exists in this interface. Returns
    {"promoted", "ticket_ref", "reasoning"}."""
    evaluator = evaluator or _default_evaluator
    ticket_creator = ticket_creator or _default_ticket_creator

    evaluation = evaluator(finding_text)
    reasoning = evaluation["reasoning"]

    if not evaluation["promote"]:
        return {"promoted": False, "ticket_ref": None, "reasoning": reasoning}

    ticket_ref = ticket_creator(finding_text, reasoning)
    return {"promoted": True, "ticket_ref": ticket_ref, "reasoning": reasoning}
