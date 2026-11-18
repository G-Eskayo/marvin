Confirmed — only the frontmatter line currently mentions `diagnose`. Now I have everything needed to write the plan.

## North-star fit

**Reuses:** `diagnose/SKILL.md`'s own Phase 6 reciprocal handoff phrasing — "hand off to the `/improve-codebase-architecture` skill with the specifics" (`skills/diagnose/SKILL.md:154`) — as the template for the new line in `tdd/SKILL.md`'s Incremental Loop, and `skills/self-improve/scripts/rebuild-manifest.py`'s `main()`/`scan_skills()` as the existing, unmodified mechanism that turns frontmatter `calls:` into the manifest (no new tooling needed — it already reads `calls:` from any skill's frontmatter, per `scan_skills()` at `skills/self-improve/scripts/rebuild-manifest.py:188-199`).

**Simplicity:** This is a one-line doc addition plus a script re-run; no code, no new abstraction, no new file. The alternative (removing `calls: [diagnose]`) would be simpler to write but wrong per the ticket's own analysis — TDD's RED→GREEN loop has a real, named failure mode (a test that won't go GREEN for reasons beyond the current increment) that `diagnose` exists to handle, so wiring the edge in reflects an actual, intended handoff rather than papering over a mismatch.

**Tokens:** Spends ~1 sentence of context per future TDD session (negligible) in exchange for making the skill graph and routing trustworthy — a stuck RED/GREEN loop now has a named way out instead of silent guessing, which is the more expensive failure mode (burned tokens re-guessing fixes with no diagnostic discipline).

**North star 4 (tool for tools):** Directly serves this — skill metadata that matches skill behavior is what lets routing and the graph be trusted, which is the explicit purpose stated in the ticket.

**User capability:** Doc-only; it doesn't change what a human does. It makes the agent's own behavior (when stuck in TDD) more disciplined by routing it to `diagnose` instead of continuing to guess — net effect is fewer wasted cycles for whoever is waiting on the agent.

No code is being touched, so this is correctly exempt from "How we'll try to break it" per the ticket (`Docs-only: exempt`) — there is no behavior to attack, fuzz, or race.

## Tests

None — the ticket's "How we'll try to break it" section states `Docs-only: exempt`, and there is no code path, input surface, or dependency here for the misuse categories (bad/empty/huge input, dependency failure, concurrency, permissions, stale state) to apply to. Verification is a grep/diff check, not a test suite:

1. `grep -n "diagnose" skills/tdd/SKILL.md` — confirms the body now names `diagnose` (currently only the frontmatter line matches).
2. `grep -n "calls:" skills/tdd/SKILL.md` — confirms `calls: [diagnose]` is unchanged in frontmatter.
3. Run `~/.agents/venv/bin/python ~/.agents/skills/self-improve/scripts/rebuild-manifest.py` and inspect `~/.claude/manifest.json`'s `tdd` entry to confirm `"calls": ["diagnose"]` is still present post-rebuild (this is "verify fails when code changes without a test changing" applied to a doc change: the manifest rebuild is the mechanical check that the frontmatter edit didn't break).

No Decisions section is needed — the ticket is fully specified (exact line to add, exact section, exact script to run) and carries the `ready-for-agent` label with no open design choice.

## Task List

1. In `skills/tdd/SKILL.md`, under `### 3. Incremental Loop` (after the existing "Rules" list, `skills/tdd/SKILL.md:84-89`), add one line naming the handoff condition and target, phrased in `diagnose`'s own reciprocal-handoff style (`skills/diagnose/SKILL.md:154`): stop and hand off to `diagnose` when a test fails for reasons beyond the current increment — unexplained behavior, a fix that doesn't change the failure, or two attempts without progress — and resume the TDD loop once the cause is known.
2. Leave `calls: [diagnose]` in the frontmatter unchanged (`skills/tdd/SKILL.md:5`).
3. Run `~/.agents/venv/bin/python ~/.agents/skills/self-improve/scripts/rebuild-manifest.py` and confirm (via the three grep/inspection checks above) the manifest's `tdd` entry still lists `diagnose` under `calls`.
4. Run `grep -rn "diagnose" skills/tdd/SKILL.md` as the acceptance-criteria check that every frontmatter `calls:` entry is now named in the body.