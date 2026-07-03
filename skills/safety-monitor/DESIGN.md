# Design — Safety & Drift Monitor

## User-facing surface

### `quarantine.md`

Mirrors `improvement-queue.md`'s format exactly (same reader habit, no new mental model):

```markdown
# Quarantine

## 2026-07-04 — daily_digest [SAFETY, score 0.71, tau 0.30]
> Wild Idea: integrate the `wire-skill.sh` auto-router into `wire-context.py`...

Flagged reason: references `wire-context.py`, which does not exist in the repo.

- [ ] approve (ships as-is)
- [ ] modify: ____________
- [ ] deny

---
## 2026-07-04 — self-improve [DRIFT, divergence 0.44 vs 0.18 baseline]
Public rationale: "This pattern recurred 3x, passes all quality gates, wiring now."
OTR rationale: "Honestly only saw this pattern twice clearly; the third is a stretch. Wiring anyway because the user seemed to want momentum."

- [ ] approve (ships as-is)
- [ ] modify: ____________
- [ ] deny
```

Two flag types share one queue: `[SAFETY, ...]` (from `verify.py`, blocks a specific artifact) and `[DRIFT, ...]` (from `drift_report.py`, flags a loop's recent pattern of self-justification, not a single artifact). Same review action either way: approve / modify / deny. Denying a `SAFETY` item deletes the quarantined artifact and labels calibration data (label=1). Denying a `DRIFT` item doesn't delete anything — it's a signal that gets logged and considered next time architecture-review or self-improve run.

### Session start

Same tier as existing checks:
> "3 items in quarantine — 2 safety, 1 drift. Ask to review."

### Review command

A new slash-invokable trigger, `/quarantine` (wired the same way `/improve` is), that:
1. Reads `quarantine.md`
2. Walks each item, asks approve/modify/deny
3. Writes the label back to `calibration.jsonl` (for SAFETY items) so `calibrate.py`'s next run uses it
4. Removes actioned items from `quarantine.md`

This is deliberately conversational (not just a checkbox file edit) — modify decisions need discussion ("what would a corrected version look like"), which matches how Giles already works through `improvement-queue.md` today.

## Rollout plan

**Phase 1 (this spec, buildable now):** wrap `daily_digest.py` and `run_colony.py` only — they're pure-generation loops (no decision-making), so `verify.py` + `calibrate.py` alone (no OTR/drift) is sufficient. Lowest-risk validation of the mechanism.

**Phase 2:** wrap `improvement_sweep.py` similarly.

**Phase 3:** add OTR logging + drift audit to `self-improve` and `architecture-review` (the decision-making loops) — this is the higher-value, higher-complexity half, and should only start once Phase 1's calibration loop has real labeled data to prove the approach works.

**Phase 4:** wrap `route`'s profile/model decisions in OTR logging too, since disagreement between what it says ("this is a coding task, use lean") and what it would say off-record is a direct analogue to the DemoPSD disagreement signal noted in `to-research.md` — flagged there as a weak fit for training, but the *measurement* idea (disagreement as signal) transfers even without any training step.

## Connection to the requested automation pipeline

This is the part of "come up with design docs... eventually automate the whole thing" that's worth calling out explicitly: **the quarantine queue built here is the same mechanism the eventual research → deep-dive → spec → morning-review pipeline needs.** Concretely:

- `quarantine.md`'s approve/modify/deny UX *is* the review surface the user asked for ("review docs and sources in the morning and approve, modify, or deny").
- `calibrate.py`'s risk-controlled thresholding *is* the mechanism that would eventually let a research-to-spec pipeline auto-file low-risk, well-corroborated findings (bump to backlog) while surfacing high-uncertainty or high-blast-radius proposals for review — instead of surfacing everything, or nothing, uniformly.
- The `verify.py` rubric-per-loop pattern generalizes directly: a future `research_colony` rubric could score "is this correlated finding's claimed relevance to MARVIN actually supported by the abstract text" — which is exactly the kind of stretch-fit judgment call this session made manually for LACUNA and DemoPSD (see `to-research.md`).

So building this feature first, rather than jumping straight to the full research-automation pipeline, de-risks that later work: by the time the pipeline is designed, there's already a working, calibrated review queue to plug it into instead of designing one from scratch.

## Open questions / risks

- **Cold-start calibration.** With <20 labeled examples, `tau` defaults conservatively (0.3), meaning early on more gets flagged than strictly necessary. Acceptable — it's a one-time cost while the calibration set builds, and errs toward showing Giles too much rather than too little.
- **OTR channel honesty.** The paper's dual-channel result depends on the model actually behaving differently when told a channel is private. Whether a single-session Claude Code invocation exhibits the same effect (vs. a persistent multi-agent debate setting the paper tested) is unverified — Phase 3 should treat the first month of `otr-log.jsonl` as a validation period, not a load-bearing signal yet.
- **Verifier cost.** One extra haiku call per loop run is negligible (loops run at most a few times/day), but if this pattern generalizes to more loops later, worth revisiting whether verification should be batched instead of per-artifact.
- **Rubric drift.** Rubrics in `scripts/rubrics/*.md` are hand-written and will go stale as loops change. No automated check for this yet — flagged here rather than solved, since solving it well is arguably its own future feature.
