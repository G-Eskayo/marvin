## North-star fit

**Reuses before adding anything:** `lib/owner_decisions.py` (`ADDRESSED_MARKER`, the "waiting on MARVIN" check), `lib/supersession.py::section()` (already generated the "Earlier answers" checklist verbatim in this ticket's body), `docs/agents/decisions-format.md` (Decisions-block syntax and the "don't pre-tick, don't guess" rule), and the executor pattern in `docs/design/737-review-variations.md` ("replies with `<!-- marvin:decisions-addressed -->`… ends with a fresh Decisions section"). No new file, script, or abstraction is needed — this ticket is answered entirely with existing machinery.

**Why this is the simplest sufficient approach:** The owner's Decisions comment (id `7084843647`) answers only one of two questions. `deep-latency` → **"Keep it."** — already the as-built default (`dashboard/mobile-backend/voice_api.js` on `origin/voice-endpoint-670`: `deepWaitMs=8000`/`deepStreamMaxMs=120000` race, the holding line, `deepPending` → Thread fallback). Nothing to build. `deep-tools` → **no box ticked**, only a note ("I want it to be interactive like a lab assistant… but we are still working on that"). Per `docs/agents/decisions-format.md`, "Don't answer the questions yourself... don't pre-tick a box unless it records an answer the owner already gave." A note is not a tick. The only correct move is to say so and leave the existing, still-open `deep-tools` question (already a valid `<!-- marvin:decisions -->` block in PR #1401's body) exactly where it is — not invent a 4th option, not silently build toward option 3 because it *sounds* closest to the note, and not open a new Decisions block that would just duplicate the one already live. That guessing-vs-asking line is almost certainly why the two prior automated attempts burned 3 review iterations each and failed: review correctly flags unapproved/guessed feature work against an unchosen "(optional)" decision.

**Resource cost:** effectively zero — one GitHub PR comment, no new branch work, no CI run, no commits expected.

**Leaves the user more capable:** Gil keeps the actual choice on `deep-tools` (and on whatever the "lab assistant / human-understandable reporting" work becomes, which belongs with ADR 0085's front-desk direction, not guessed into this PR) instead of MARVIN quietly picking for him.

No Decisions section is needed from me for this plan — the interpretation above isn't ambiguous: one question has a clear chosen-and-already-built answer, the other has no chosen answer at all, and the rule for that case is explicit in the repo's own docs.

## Verification checks (no code changes, so no unit tests apply)

This ticket's deliverable is a GitHub reply, not application code, so there is nothing to unit-test; instead these are the pre-flight checks that stand in for "tests first," one per the ticket's break-it list plus misuse it didn't name:

1. **"The PR changed since the decisions: re-read it before acting."** — Re-fetch PR #1401's live body/comments/commits immediately before posting (already done once for this plan; must redo at execution time, not reuse this planning snapshot).
2. **"The notes contradict a chosen option: say so... instead of guessing."** — Confirm the reply text states plainly that `deep-tools` has no chosen option and nothing is built for it, rather than treating the note as implicit approval of any of the three listed options.
3. **Stale/concurrent decisions** — Check for a newer "Decisions from the owner" comment than `7084843647` before posting, in case Gil answered again in the interim; if one exists, address that one instead.
4. **Malformed/unstructured ask** — The reply must contain zero question-shaped headings or sentences ending in "?" outside a proper `<!-- marvin:decisions -->` block, or `~/.agents/bin/gh`'s decisions gate refuses the comment (`DECISIONS_NOT_ASKABLE`/`DECISIONS_UNSTRUCTURED`).
5. **Wrong tool/permissions** — Post via `~/.agents/bin/gh`, never raw `gh` (reference-github-gate), since this is a mutating `pr comment`.
6. **Missing/garbled marker** — Confirm the literal string `<!-- marvin:decisions-addressed -->` is present verbatim in the posted body (not paraphrased).
7. **Earlier-answers false negatives** — Independently confirmed (not just trusting the ticket's auto-generated list) that none of the 5 cited docs restate either decision's answer — all 5 only cite ticket #670 as a scheduling/roadmap pointer (`dashboard-ux-potholes-2026-10-29.md:487`, `marvin-business-plan-2026-10-25.md:53`, `marvin-website-2026-11-02.md:226`, `project-homepod-appletv-spike.md`, `project-investor-demo-plan.md:19`) — so "kept, explicitly" with a one-line reason is correct for each, no file edits needed.
8. **Repeat/self-closing race** — Issue #1404 "closes itself once PR #1401 is addressed," so no manual close step should be taken; a second close attempt would be redundant.

## Task List

1. Immediately before acting: re-fetch PR #1401's current body, comments, and commit list; re-check branch `voice-endpoint-670` is still the head and the PR is still open.
2. Confirm no "Decisions from the owner" comment newer than `7084843647` exists; if one does, restart analysis from that comment instead.
3. Verify `deep-latency`'s "Keep it" against the current code on `origin/voice-endpoint-670` (`dashboard/mobile-backend/voice_api.js`: the `deepWaitMs`/`deepStreamMaxMs` race and `deepPending` Thread-fallback path) and note the exact file/behavior as evidence in the reply.
4. Draft the PR reply (statements only, no question-shaped prose):
   - `deep-latency`: confirmed as-built, cites the code, nothing changed.
   - `deep-tools`: states the owner gave a note but chose no option; nothing built; the note is quoted; the existing `deep-tools` Decisions block in PR #1401's body stays open and unanswered for him, with a one-line pointer to ADR 0085 (front-desk / human-readable reporting direction) as where the broader "lab assistant" idea belongs once it's concrete enough to turn into options.
   - Earlier-answers checklist: all 5 items marked kept, each with its one-line "relation only, no restated decision" reason.
   - Screenshots: states this PR has no UI/visual surface, so there is nothing to retake or pin.
   - Ends with `<!-- marvin:decisions-addressed -->`.
5. Post the comment on PR #1401 via `~/.agents/bin/gh pr comment 1401 --repo G-Eskayo/marvin --body-file -` (not raw `gh`).
6. Confirm issue #1404 closes itself as documented; take no manual close action.