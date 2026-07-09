# 0015 — Quarantine over-flagging: rubric grounding + the missing review-feedback loop

## Status

Accepted (2026-07-09)

## Context

Gil asked directly: "the 9:00 review, did it happen?" It had — research-colony completed
successfully on schedule — but he'd never actually seen the content, because it was quarantined.
Checking quarantine history showed this wasn't occasional: every single daily_digest and
research_colony run, every day observed (07-08 through 07-09), had been quarantined, always
scoring roughly 2x the threshold (0.40–0.70 against tau=0.30). That's not noisy borderline
content — that's a systemic pattern, and it directly validated Gil's own instinct: "I still need
to work on piping and get the system talking to itself better."

Two distinct, compounding root causes were found, not one.

**Root cause 1 — the rubric structurally couldn't do its job.** `verify.py`'s judge call
(`claude -p ... --model haiku`) was given only the artifact text and a rubric instructing it to
flag "specific claims that are likely fabricated" — but no source data to check those claims
against. Both loops' generation prompts (`daily_digest.py`, `research_digest.py`) explicitly ask
for specificity ("reference actual files, skills, metrics... where relevant"), which is exactly
what a judge with no way to verify anything is primed to treat as suspicious. Confirmed directly:
re-scoring the same real, accurate, non-fabricated research_colony output with vs. without the
actual source data (the real arXiv/GitHub/HN items it was synthesized from) dropped the score from
0.42 (would quarantine) to 0.22 (would pass) — same content, same rubric core logic, only the
grounding changed.

**Root cause 2, found while inspecting today's actual quarantined daily_digest content — a
completely different failure mode hiding under the same symptom.** The artifact wasn't a
plausible-but-unverifiable digest at all; it was the model narrating a tool-permission problem —
"I can't write directly to `~/.claude/daily-digest/`... so here's today's digest... Want me to try
again to persist this, or would you rather grant Write/Bash permission?" `--disallowedTools
"Write,Edit"` (a fix from 2026-07-06, per existing comments) was already in place, but nothing told
the model to simply *not attempt* persistence via any path, including Bash (which stays allowed,
deliberately, for read-grounding). The safety-monitor was correctly catching this — it just wasn't
the failure mode the rubric was written to describe, and the actual fix belongs at the source, not
in scoring.

**Root cause 3 — even correctly-flagged content had nowhere to go.** `calibrate.py`'s
`record_label()` docstring says plainly: "Intended caller: the quarantine review workflow, once
built." It was never built. Checked directly: 0 of 18 checkboxes across every quarantine entry had
ever been checked, and `~/.claude/safety-monitor/` (where calibration state lives) didn't exist at
all. `tau` was frozen at `DEFAULT_TAU = 0.3` forever, with no mechanism by which real review
decisions could ever raise it — even if Gil had been diligently checking boxes, nothing was reading
them back into the system. This is the literal "piping" gap Gil named.

## Decision

**Fix 1 — ground the judge in real source data.** `verify()`/`pass_or_quarantine()` gained an
optional `source_context` parameter; both loops now pass the actual prompt data (roadmap/handoffs/
QA-KB for daily_digest; the real correlated+all-items text for research_colony) they used to
generate their content. Both rubrics rewritten to instruct the judge to check claims against this
data when present, and to stop treating mere unfamiliarity/unverifiability as evidence of
fabrication when it isn't.

**Fix 2 — stop the model from attempting self-persistence at all.** `daily_digest.py`'s prompt
template now explicitly instructs: return only the digest text, do not attempt to write/save/
persist it yourself via any tool, a separate process handles that. Verified live: regenerating
today's digest after this fix produced clean, well-grounded, specific content with zero
conversational narration — and a spot-check of its most concrete claim (`verify_digest_fix.py`'s
self-delete behavior) confirmed it was accurate, not fabricated, closing the loop on whether Fix 1
alone might have papered over genuinely bad content.

**Fix 3 — build the missing review-feedback loop.** New `process_quarantine_reviews.py`: splits
`quarantine.md` on its entry-header pattern (not a bare `---` separator — a legacy entry from
before an earlier truncation fix left an unquoted `---` inside its own body, which broke a first,
simpler split attempt), finds entries with a checked box, calls `calibrate.record_label()` for
each (approve/modify → 0, "was actually fine"; deny → 1, "was actually bad" — modify still counts
as "not dangerous," just needing a tweak), then removes processed entries so the pending count
stays accurate. Wired into CLAUDE.md's session-start step 5 (runs before the pending-count check)
and a daily 20:00 launchd job as redundancy for whenever a session doesn't start same-day as a
review.

## Consequences

`MIN_LABELS = 20` in `calibrate.py` means tau won't actually move until 20 real reviews
accumulate — this fix makes the feedback loop *possible*, it doesn't retroactively generate the
missing history. Real review decisions from here forward are what closes it the rest of the way,
not more engineering.

Fix 1 and Fix 2 together should sharply reduce future quarantine volume for these two loops, but
the safety-monitor itself is now more trustworthy specifically because Fix 3 exists — a
consistently-over-flagging rubric with no calibration path is worse than one that occasionally
over-flags but genuinely learns from correction.
