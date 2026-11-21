## North-star fit

- **Reuses:** the existing split-reference-file convention already used in this repo for exactly this purpose — `skills/tdd/SKILL.md` links out to `tests.md`, `mocking.md`, `deep-modules.md`, `interface-design.md`, `refactoring.md` (inline markdown links, same folder, loaded on demand instead of inline); `skills/safety-monitor/SKILL.md` does the same with `SOURCES.md`/`ARCHITECTURE.md`/`REQUIREMENTS.md`/`DESIGN.md`. This ticket applies the identical pattern to `diagnose/SKILL.md`, just with a different target file (`gotchas.md`). No new mechanism needed.
- **Simplest sufficient approach:** cut the 32-bullet, append-only incident list (currently `skills/diagnose/SKILL.md:80-112`, not the stale "12"/"30" counts in the ticket text — I checked the live file) out verbatim into `gotchas.md`, leave a one-line pointer in place. Nothing else in the skill changes.
- **Token saving:** `SKILL.md` is loaded in full on every diagnose trigger; the gotcha list is currently ~35 of its 155 lines (~2,000+ tokens) and grows every time an incident is confirmed. After the move, `SKILL.md` stays flat-cost and `gotchas.md` is read only "early in Phase 3 when the symptom fits" — an on-demand cost, not a fixed per-trigger one.
- **More capable, not more passive:** this is a maintainer-facing doc reorg; it doesn't change what the agent does, only what it's forced to pay for every time, so there's no passivity trade-off to weigh.
- No north star argues against this.

## Verification (ticket marks "How we'll try to break it" as docs-only / exempt — no automated tests apply)

Since this is a pure doc move, "tests" are verification checks I'll run after editing, not code tests:
1. **Count check:** bullet count in `gotchas.md` equals the current bullet count in `SKILL.md`'s list. I counted the live file precisely: **32 bullets**, at `SKILL.md:81-112` (line 80 is the intro sentence being replaced, not a bullet). I'll diff line-for-line to confirm verbatim content, not just count, since a count match alone could hide a mangled bullet.
2. **No bullets left behind:** `rg "^\- \*" skills/diagnose/SKILL.md` returns nothing after the edit.
3. **Pointer present:** `SKILL.md` contains the one-line pointer in Phase 3, at the same location the list occupied (between the "show ranked list to the user" paragraph and Phase 4's header).
4. **No dangling references:** I already ran `rg -n "gotcha" skills docs CLAUDE.md` and `rg -n "diagnose/SKILL.md|diagnose.*gotcha" skills docs CLAUDE.md`. Nothing references the removed list by line number or by "the inline list in SKILL.md" — the only other hits are unrelated gotcha mentions in other skills (`paper-dive`, `safety-monitor`, `triage`), historical prose in `skills/diagnose/retrospective.md` and `skills/self-improve/retrospective.md` describing *what was added* (not *where* it lives structurally), and `docs/skills.md`'s generic link to `SKILL.md`. None need edits.
5. **Misuse not covered by the ticket's own section**, checked anyway per the north-stars testing principle:
   - *Malformed/partial move*: verified by the line-for-line diff in (1), not just a count — catches truncation or a bullet silently merged with its neighbor.
   - *A person's mistake (wrong order)*: bullets moved in original order, since several later entries cross-reference earlier ones by theme (e.g. the "crash counted as 0" bullet is referenced from a later bullet) — order is preserved, not sorted or deduped.
   - *Stale state*: confirmed I'm reading the file fresh in this worktree, not relying on the ticket's embedded (stale) counts.

No Decisions section — nothing here needs the owner's choice; naming/heading for `gotchas.md` is a mechanical call, not a design option.

## Task List

1. Create `skills/diagnose/gotchas.md` with heading `# Diagnose — MARVIN-specific gotcha classes` and a one-line intro ("read early in Phase 3 when the symptom fits... append new confirmed incidents here, not in SKILL.md"), followed by all 32 bullets from `SKILL.md:81-112`, copied verbatim and in original order.
2. In `skills/diagnose/SKILL.md`, replace lines 80-112 (the intro line + all 32 bullets) with the single pointer line: `**MARVIN-specific gotcha classes:** read [`gotchas.md`](gotchas.md) (same folder) early when the symptom fits, before deeper instrumentation. Add new confirmed incidents there, not here.` — placed where the old list started, immediately before the blank line leading into Phase 4.
3. Diff `gotchas.md`'s bullets against the pre-edit version of `SKILL.md` (via `git show HEAD:skills/diagnose/SKILL.md`) to confirm verbatim, in-order, complete (32-for-32) migration.
4. Re-run `rg -n "gotcha" skills docs CLAUDE.md` and `rg "^\- \*" skills/diagnose/SKILL.md` to confirm no dangling references and no bullets left inline.