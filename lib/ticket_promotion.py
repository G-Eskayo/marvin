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
precedence over the descriptive prose). This module creates one ticket per promoted finding: the model
writes it, code publishes it labelled needs-triage, so a person or the
triage agent decides before anything runs (marvin#305). A finding big enough to need
tracer-bullet decomposition is a follow-on step for a real session to run
/to-issues against the resulting ticket, same as this pipeline's own
parent PRD (#1) was broken into #2-#11.

`evaluator` and `ticket_creator` are injectable hooks, same testability
seam as sandbox_orchestration's `executor` -- both defaults shell out to
headless `claude -p`, since "does this unlock future work" and "write a
real PRD" both require real reasoning, not a heuristic.
"""
from __future__ import annotations
import json
import re
import subprocess

import marvin_launcher
from typing import Callable

EVALUATOR_MODEL = "claude-sonnet-5"
CREATOR_MODEL = "claude-sonnet-5"
EVALUATE_TIMEOUT_S = 180
CREATE_TIMEOUT_S = 600

NOTHING_LEFT = "NOTHING_LEFT"  # the finding's own updates say it's all done: consumed, no ticket
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
    stdout = marvin_launcher.launch("background-analyst", prompt, model=EVALUATOR_MODEL, permission_mode=None,
                                    timeout=EVALUATE_TIMEOUT_S).text
    promote_match = PROMOTE_RE.search(stdout)
    reasoning_match = REASONING_RE.search(stdout)
    return {
        "promote": bool(promote_match and promote_match.group(1).lower() == "yes"),
        "reasoning": reasoning_match.group(1).strip() if reasoning_match else stdout.strip(),
    }


def _default_ticket_creator(finding_text: str, reasoning: str) -> str | None:
    """The model writes the ticket; code creates it (marvin#305). A headless run can't be relied on to publish
    (its tools are refused without a person to approve), and a promoted finding goes to triage, not straight to
    the pipeline: `needs-triage`, never `ready-for-agent`."""
    prompt = (
        "Turn this finding into one GitHub ticket for the MARVIN repo. Reply with exactly:\n"
        "TITLE: <a short title>\n---\n<the body: '## What to build' (the end-to-end behaviour), "
        "'## North-star fit' (what it reuses, why it's the simplest sufficient approach, its token effect, whether "
        "it leaves the user more capable), '## Acceptance criteria' (checkboxes)>\n\n"
        "The finding may have been partly done since it was written: include only what its own updates say still "
        "remains. If nothing remains, reply with exactly NOTHING_LEFT.\n\n"
        f"Finding:\n{finding_text}\n\nWhy it was promoted (compounding leverage): {reasoning}"
    )
    text = marvin_launcher.launch("background-analyst", prompt, model=CREATOR_MODEL, tools="", permission_mode=None,
                                  timeout=CREATE_TIMEOUT_S).text
    if text.strip() == "NOTHING_LEFT":
        return NOTHING_LEFT
    m = re.match(r"\s*TITLE:\s*(.+?)\s*\n-{3,}\s*\n(.+)", text, re.S)
    if not m:
        return None
    body = m.group(2).strip() + "\n\n_Promoted from suggestions.md by ticket promotion (marvin#305)._"
    out = subprocess.run(["gh", "api", "repos/G-Eskayo/marvin/issues", "-f", f"title={m.group(1)}",
                          "-f", f"body={body}", "-f", "labels[]=needs-triage"], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return None
    return json.loads(out.stdout).get("html_url")


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
