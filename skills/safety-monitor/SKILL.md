---
name: safety-monitor
description: Calibrated verifier that scores an autonomous loop's output for risk (fabricated references, unsupported claims) before it ships, quarantining flagged artifacts for review instead of blocking the loop. Use when wiring a new autonomous/background loop, reviewing quarantined items, or asked about the safety/drift monitor.
tags: [intent:safety, intent:quality, intent:monitor, type:library]
---

# Safety Monitor

**Phase 1 only** (see `DESIGN.md` for the full rollout plan). This covers
pure-generation loops — scoring an artifact's text against a loop-specific
rubric and quarantining it if it looks risky. The dual-channel drift audit
(`otr_log.py`, `drift_report.py`) described in `ARCHITECTURE.md` is **not
built yet** — don't reference those scripts as if they exist.

## What this actually does

`verify.py` sends an artifact + a loop-specific rubric to a cheap model
(haiku) and gets back a risk score in [0, 1]. `calibrate.py` picks the
threshold (tau) that decides pass vs. quarantine — a conservative default
(0.3) until at least 20 labeled examples exist for that loop, then a
risk-controlled threshold computed from real approve/deny labels. Anything
over tau lands in `~/.claude/quarantine.md` instead of shipping silently.

This is a **library**, not a cron job — `verify.py` and `calibrate.py` are
meant to be called synchronously from inside an existing loop script, right
before it writes its output. Nothing runs on a schedule yet.

## Scripts

| Script | Purpose |
|--------|---------|
| `scripts/verify.py` | `verify(text, loop_name) -> float` risk score; `quarantine(...)` writes a flagged item; `pass_or_quarantine(text, loop_name) -> bool` is the one-line integration point |
| `scripts/calibrate.py` | `get_tau(loop_name) -> float`; `calibrate(...)` recomputes tau from labeled data; `record_label(loop_name, score, label)` for when a review workflow exists to call it |
| `scripts/rubrics/daily_digest.md` | Rubric for `improve/scripts/daily_digest.py`'s output |
| `scripts/rubrics/research_colony.md` | Rubric for `research-colony/scripts/research_digest.py`'s output |
| `scripts/rubrics/self_improve.md` | Rubric for the retrospective-log.md line `background_review.py` appends |
| `scripts/rubrics/improvement_sweep.md` | Rubric for `improvement_sweep.py`'s queue entries — checks extraction coherence (tag/message/path mismatch), not hallucination, since this loop has no LLM call |

A rubric must exist for a loop before `verify()` can score it — `verify()`
raises (and fails open, returning 0.0 / "pass") if `rubrics/<loop_name>.md`
is missing. Add a new rubric before wiring a new loop in.

## Output files

- `~/.claude/quarantine.md` — human review queue; same approve/modify/deny
  convention as `improvement-queue.md`. No `/quarantine` review command
  exists yet — items are reviewed by reading and editing the file directly.
- `~/.claude/safety-monitor/tau.json` — per-loop threshold, created lazily.
- `~/.claude/safety-monitor/calibration.jsonl` — labeled `{loop, score,
  label}` rows, created lazily by `record_label()`. Empty until a review
  workflow starts calling it — `calibrate()` uses `DEFAULT_TAU` (0.3) until
  then.

## Integration status

All four loops from `SOURCES.md` are wired in:

- `background_review.py` (self_improve) — wired first, since it's the
  highest-blast-radius one (writes directly to the git-tracked, append-only
  `retrospective-log.md`). Verification is post-hoc: snapshot the log before
  the review runs, diff after, score the new line(s), revert the append +
  quarantine if flagged.
- `daily_digest.py` and `research_digest.py` — wrapped the same way as each
  other: `pass_or_quarantine(content, loop_name="...")` right before the
  write; on `False`, a short quarantine notice is written in place of the
  real content so the day's output file still exists (no retry-loop burning
  a fresh `claude` call on every re-run) but is clearly marked incomplete.
- `improvement_sweep.py` — same `pass_or_quarantine()` wrap, but this loop
  has no LLM call at all (its content is a deterministic regex/sort over a
  static-analysis scan), so `rubrics/improvement_sweep.md` checks extraction
  coherence (a `[KIND]` tag mismatched with its message, a garbled fragment,
  a malformed path) rather than hallucination. On quarantine, the block is
  simply not appended — no stub needed, since the next handoff produces a
  fresh (different) block rather than re-running the same one.

## Manual invocation / smoke test

```bash
# Score arbitrary text against a rubric
echo "some artifact text" | ~/.agents/venv/bin/python \
  ~/.agents/skills/safety-monitor/scripts/verify.py daily_digest

# Check/recompute a loop's threshold
~/.agents/venv/bin/python ~/.agents/skills/safety-monitor/scripts/calibrate.py daily_digest

# Show the quarantine queue
cat ~/.claude/quarantine.md
```

## Triggers

- "wire safety-monitor into X", "review quarantine", "show quarantine queue"
- Session start: if `~/.claude/quarantine.md` exists with unresolved items, mention the count (not yet wired into the session-start checklist — see below)

## Known gotchas

- `verify()`'s subagent call is `--tools ""` plus an explicit "you have no
  tool access" line in the prompt — both are load-bearing, not either alone.
  A rubric that asks "does this reference something that doesn't exist"
  invites haiku to go check by exploring the filesystem even when
  `source_context` already has what it needs, which measured 113s vs ~50-58s
  and blew through the old 60s timeout. See `retrospective.md` (2026-07-13)
  and the inline comment in `scripts/verify.py`. Keep this in mind for any
  new rubric-based subagent call, not just this one.

## Known gaps (tracked, not silently assumed fixed)

- Session-start check for `quarantine.md` is described in `REQUIREMENTS.md`
  (FR6) but not yet added to `~/.claude/CLAUDE.md`'s checklist.
- No `/quarantine` review command yet — `record_label()` exists but nothing
  calls it, so `calibrate()` will sit on `DEFAULT_TAU` indefinitely until
  one is built. Expect over-flagging until then — confirmed in testing that
  even a well-constructed, genuinely generalizable retrospective-log entry
  scored above tau; that's the documented cold-start conservatism, not a bug,
  but it's a real cost until real labels exist.
- OTR/drift audit (`otr_log.py`, `drift_report.py`) still not built — Phase 3.
