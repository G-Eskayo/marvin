## North-star fit

**Reuses before adding anything new:**
- `docs/n8n/platform-research.md` — a full n8n feasibility pass (architecture, licensing, self-hosting, hardware sizing, debugging) already done 2026-07-08, and it already covers the exact prior art #57 cites: §"NetworkChuck's n8n + Claude Code project" documents `theNetworkChuck/n8n-claude-code-guide`'s hub-and-spoke pattern (n8n → SSH → `claude -p --session-id/-r`) in detail, including its blast-radius caveat (`--dangerously-skip-permissions`).
- `docs/adr/0013-task-dispatch-general-primitive-v1-scope.md` + its built `lib/` — task-dispatch's v1 already reduced "an ad-hoc headless `claude -p` reasoning task, per the NetworkChuck/Terry precedent" to its general work-unit model and shipped it. Terry's core mechanism question ("can something external trigger headless Claude Code reasoning on MARVIN's own infra?") is therefore not open research any more — it's a solved, already-built pattern.
- `docs/plans/ticket-triage-2026-10-07.md` §D (row 72) — the authoritative scope note that narrowed this spike's remaining question to "Health + tool-usage feeds as inputs," per the 2026-10-07 triage comment on this ticket.

**Why this is the simplest sufficient approach:** given the two reuse points above, the actual remaining research gap is much narrower than the ticket body implies — not "is n8n+Claude-Code-over-SSH feasible" (already answered) but "what does it look like specifically to turn MARVIN's own Health/tool-usage feeds into network-safety actions, as a future, separate project." Re-deriving the n8n/NetworkChuck feasibility case from scratch would violate the research-efficiency principle (start from what's known, research only the gaps).

**Where it spends vs. saves tokens:** spends none right now — this plan does not execute the spike. If/when it's unblocked, the doc-first design can skip re-researching n8n mechanics entirely and start directly from the two docs above, saving a full research pass.

**Phone-OS / capability fit:** neutral for now — the ticket itself says Terry is "explicitly a separate future project, not a MARVIN feature," so it's a tie-breaker-only concern, not blocking.

**North star argues against proceeding today:** yes, explicitly. This isn't my judgment call to override — it's the ticket's own recorded instruction.

## Why I'm not planning execution now

Two things from the ticket itself override "pick this up":

1. **An explicit, unmet sequencing gate, stated directly on the ticket by the owner (2026-10-07 comment):** *"Do the doc-first design after clarity-captions ships."* I checked whether that condition is now satisfied. It is not: clarity-captions' own repo shows v1.0 (build 5) was submitted for App Review on 2026-10-20 with an expedite request, and as of today (2026-10-22) is still not confirmed released — issue #147 ("1.1: ship the iPad app," 2026-10-21) explicitly defers its own submission step with *"submit it once 1.0 is released (App Store Connect allows one version in review at a time)"*, and issue #141 (battery, still open) scopes its own next steps to *"after v1 ships, not before 10/25."* Neither has flipped. The memory note that "other projects may proceed in parallel now" (2026-10-21) is a general loosening of the broader project freeze, not a stated override of this specific ticket's own condition — it's genuinely ambiguous whether Gil meant it to reach this ticket too (see Decisions below).
2. **The `ready-for-agent` label itself looks stale against that condition.** Per `docs/agents/triage-labels.md`, `ready-for-agent` means "no further human context needed" — but this ticket's own comment makes pickup conditional on an external, time-varying fact (App Store release status) that an agent has to go verify, which is exactly the kind of thing that label is supposed to mean isn't outstanding.

Per my brief: a denial/earlier-failure note on the ticket is a requirement for this attempt, and "if something is genuinely ambiguous, make the most reasonable call yourself and note it." The reasonable call here is: don't commit to starting the doc-first design while the owner's own stated precondition is unmet, and surface the contradiction rather than silently either stall or silently proceed.

## Tests-first list

Not applicable, and I'm not inventing any. Reasons:
- This is a research-spike ticket (template: "Research question" + "Acceptance criteria"), not a build ticket — it carries no "How we'll try to break it" section and no Attacks list, consistent with its sibling spike #63 (same template, same absence).
- Per the "Tests try to break it" principle, adversarial tests apply to code/outward-facing surfaces; the deliverable here is a doc, and in any case I'm not proceeding to produce that doc in this pass (see above) — writing a tests list for work I'm explicitly not starting would be inventing scope the ticket doesn't support yet.
- If/when the ticket unblocks, the real rigor-equivalent for a research deliverable is: every claim cited to a source tier (as `platform-research.md` already models with [Official]/[Community]/[Low-confidence] tags), no speculation presented as fact, and the final recommendation independently challenged before being written up — that's a doc-quality bar, not a test suite, and belongs in the design doc itself when it's actually written.

## Decisions

<!-- marvin:decisions -->
### proceed: Should the Terry doc-first design start now, or stay blocked on clarity-captions shipping?
- [ ] A: Keep it blocked — wait until clarity-captions/Seal Speak v1 is confirmed accepted on the App Store, then start the doc-first design
- [ ] B: Start the doc-first design now — the 2026-10-21 "other projects may proceed in parallel" note was meant to cover this ticket too
- [ ] C: Start now, but scope only the narrower "Health + tool-usage feeds as safety inputs" question from the 2026-10-07 triage note, not the full original feasibility question

### label: Correct the `ready-for-agent` label given the unmet condition? (optional)
- [ ] Move to `needs-info` until clarity-captions ships, then auto-restore to `ready-for-agent`
- [ ] Leave as-is — the label is fine, the comment is advisory only

## Task List

TOO_VAGUE: Not vague in content — vague in *readiness*. The ticket's own 2026-10-07 comment makes starting conditional on "clarity-captions ships," and I verified that condition is not yet met (clarity-captions v1.0 is still in/near App Store review as of 2026-10-22, with its own next-version ticket explicitly waiting on "1.0 is released"). Committing to a concrete implementation/task list now would mean silently overriding an explicit owner instruction recorded on the ticket, which I was told to treat as a requirement for this attempt, not a suggestion. The Decisions section above is the un-skippable fork: which of A/B/C the owner picks determines whether this becomes "wait, re-check later," a full doc-first design starting from `docs/n8n/platform-research.md` + ADR 0013, or a narrower design scoped only to Health/tool-usage-as-safety-input. A task list written before that answer would just be guessing which of three different pieces of work to do.