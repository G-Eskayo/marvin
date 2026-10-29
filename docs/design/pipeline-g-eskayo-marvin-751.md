I have what I need. Here's the plan.

## North-star fit

This ticket's deliverable is almost entirely an **answer**, not new code: PR #738's branch (`feat/737-review-feedback-variations`) has had no commit since the owner's 2026-10-28T17:16:19Z Decisions comment, and the acceptance criteria are "carry out or say why" plus "answer every question." The code I read since the design was written already tells me why nothing can be carried out: issue #737 (which PR #738 is scoped under) was **reframed and paused by the owner on the same day**, 5 minutes *before* that Decisions comment ("Paused... This design is kept and will be folded in as one piece; don't merge it on its own" — PR #738 comment at 17:10:55Z). Building the trigger/variation mechanics now would directly contradict that recorded instruction, which north star 3 and the "Tests try to break it" item ("the notes contradict a chosen option: say so... instead of guessing") both argue against.

- **Reuses before adding anything:** `docs/agents/decisions-format.md`'s Decisions-section format and marvin#729's "fresh Decisions section" convention (cited by name in `docs/design/737-review-variations.md` §1) for any new owner question; `lib/owner_decisions.py`'s `ADDRESSED_MARKER` / reply convention for closing out the follow-up; the design doc itself (`docs/design/737-review-variations.md`, already drafted, "Design only: no code, nothing wired") as the place to record the refined decisions rather than opening a new doc; `dashboard/src/components/SafetyReviews.jsx:39-67` (`ReviewCard`'s `expanded`/`setExpanded` show-less/show-full toggle) as the existing collapse pattern for "Earlier versions" rows; `dashboard/src/components/Related.jsx`'s `useRelated` "derived, not stored" pattern, which is exactly how the design doc already proposes deriving Earlier Versions from PR comments; `dashboard/src/components/PrImages.jsx`'s `groupImages` for side-by-side grouped images. No new file or mechanism is needed — nothing here is "too vague" either, since real file/line references already exist for each piece.
- **Simplest sufficient approach:** don't touch any runtime code. Post one reply (answers the question, states why no option was carried out) and one small, docs-only commit on the PR branch (refines the already-written design per the owner's two refinement notes, and answers "changes" concretely) — no behavior changes, consistent with the PR's own "Design only" status and the "don't merge on its own" instruction.
- **Token cost:** cheap — no test suite, no build, one `gh` write and one doc diff. Spends tokens up front reading PR #738, issue #737, and the three dashboard components (`MrReview.jsx`, `MrDetail.jsx`, `SafetyReviews.jsx`) so the redesign answer cites real components instead of inventing new ones that would need to be reconciled later when #737 resumes.
- **User more capable or more passive:** more capable — it gives Gil a concrete, reusable design artifact (updated doc) plus closes the open loop (no more silent "waiting on MARVIN" state on a PR he already made a call on), without taking any decision off his plate that's rightfully his (new card/board tradeoffs go back to him as a Decisions section, never guessed).
- **Where a north star argues against the obvious reading of the ticket:** the ticket template says "carry out the chosen options... on the PR's branch." Here, *none* of the five chosen options (trigger/deny/store/goback/layout) should be built now — the owner's own later/adjacent decision (issue #737 reframe, logged 5 minutes earlier) overrides them. Flagging this plainly rather than building the feature and merging it, since that's what "don't merge it on its own" literally forbids.

## Decisions (to include in the reply/commit, not pre-answered)

The card/board redesign answer surfaces real open tradeoffs; these go on the PR as a fresh `## Decisions` section (replacing the already-answered one in the PR body — `decisions.js`'s `sectionRange` reads only the **first** `<!-- marvin:decisions -->` marker, so a second section lower down would never be parsed; the existing answers stay on record in the already-posted "Decisions from the owner" comment, so nothing is lost by replacing the body section):

```markdown
## Decisions
<!-- marvin:decisions -->
### card-density: How much should a card on the MR board show at a glance?
- [ ] Keep today's inline metrics table on every card (no change)
- [ ] Collapse the metrics table to a one-line summary on the card; full table only in the detail view (recommended — most decluttering)

### board-ownership: Should the board badge whose turn it is (you vs. MARVIN), reusing `owner_decisions.py`'s signal?
- [ ] Yes, add a small "waiting on: you / MARVIN" badge per card, derived from the same check that files these follow-up tickets (recommended)
- [ ] No, leave that only in the dashboard's existing ranked attention list

### variations-scope: Should "Earlier versions" (collapsed, side-by-side only when directly related) also show in the board/list view, or only in the per-PR detail view?
- [ ] Detail view only, as the existing mock-up shows (recommended — keeps the board itself uncluttered)
- [ ] Also a one-line "N earlier versions" hint on the board card
```

## Tests (written/verified first, mapped to the ticket's break-it list)

1. **"The notes contradict a chosen option: say so in the reply instead of guessing."** — Before writing the reply, re-confirm via `gh pr view 738 --comments` (already done) that the 17:10:55Z "Paused" comment predates the 17:16:19Z Decisions comment and is from the owner's account; the reply must state this explicitly as the reason no option is built, not silently comply or silently skip.
2. **"The PR changed since the decisions: re-read it before acting."** — Re-run `gh pr view 738` and `gh pr diff 738` immediately before posting, to catch any commit/comment added after this plan was written; abort the stale plan and re-plan if the branch or body changed.
3. **Reply-closes-the-loop check (misuse: a reply that doesn't actually register as "addressed").** After posting, run `lib/owner_decisions.py waiting --json` (or re-derive `pr_status()` for PR #738) and confirm `addressed_by == "reply"` — i.e., the posted comment is authored by the same account as the owner's Decisions comment and contains the literal `<!-- marvin:decisions-addressed -->` marker. A comment from a different account, or missing the marker, proves nothing per the module's own docstring and must be caught before considering the ticket done.
4. **Decisions-format validity (misuse: owner can't act because the new block is "too vague").** Validate the new `## Decisions` block I add against `dashboard/webhook-server/decisions.js`'s rules by hand: each `### id:` is lowercase/`-`/`_`, unique, not reused from the old section; each required question has ≥2 `- [ ]` options; no prose question outside the block. Confirms the dashboard will render buttons, not "Too vague: needs options."
5. **Doc-edit scope check (misuse: sneaking in behavior under cover of "docs only").** Diff the commit before pushing and confirm it only touches `docs/design/737-review-variations.md` (prose), never `lib/`, `dashboard/src/`, or `dashboard/electron/` — since the PR is explicitly paused, any runtime file touched here would be a defect, not a fix.
6. **Repeats/concurrency (misuse: two agents acting on the same follow-up).** Before filing/commenting, check `gh issue list --label owner-decisions --state open` isn't already being worked by another run (this ticket, #751, and #750 for PR #740 are siblings — don't cross-touch #740). `owner_decisions.py`'s own `_dedupe` already handles duplicate *follow-up tickets*; this check is for duplicate *replies* on the same PR, which that module doesn't dedupe.
7. **Wrong-account / permissions (misuse: reply posted by a bot identity GitHub doesn't recognize as the owner).** Post via `bin/gh` only (reference-github-gate pattern), never a raw `curl`/other token, so the comment is attributed consistently with every other MARVIN write and the `_login(c) == owner` check in `pr_status` passes.
8. **Empty/malformed input (misuse: the owner's dictated note is themselves ambiguous, e.g. "um... I think I would prefer subagents... Or if that's not the case, we need to do a cue").** Treat the `trigger` note's ambiguity honestly in the reply — restate the two readings (subagents-per-ticket vs. a queue) and say which the existing design already gives him (subagent per follow-up ticket, already true today via the ticket pipeline) rather than picking silently.

## Task List

1. Fetch PR #738's current head and comments one more time immediately before writing (re-read-before-acting check, item 2 above); confirm nothing changed since this plan was drafted.
2. On a worktree of `feat/737-review-feedback-variations`, edit `docs/design/737-review-variations.md`:
   - Update the `Status:` line to note the design is paused and folded into #737, decisions recorded for later.
   - Refine §2 "Where the list lives" with the owner's `store` note (collapsible, don't clutter the PR).
   - Refine §3 "The mock-up" layout description per the owner's `layout` note: side-by-side only for directly-related images; otherwise collapsed at the bottom; current round stays first/foremost.
   - Add a new §4 "Redesigning the PR/MR card and board" answering `changes`, naming the real components it would touch (`dashboard/src/components/MrReview.jsx`'s `PrCard`/`OpenPrs`, `MrDetail.jsx`'s `Section`/`PrImages`, the `ReviewCard` collapse pattern from `SafetyReviews.jsx`) and the three open tradeoffs as Decisions (see above) — design only, no code.
3. Commit that doc-only change on the PR branch (satisfies "carried out where you can"; also registers as the "commit after the decisions comment" signal `owner_decisions.py` checks for) and push without force.
4. Append the fresh `## Decisions` section (card-density / board-ownership / variations-scope) to PR #738's body, replacing the now-answered section, per `docs/agents/decisions-format.md`.
5. Post the reply comment on PR #738 containing `<!-- marvin:decisions-addressed -->` that: states plainly why none of the five original chosen options are being built now (paused per the owner's own comment + issue #737's reframe); answers `changes` concretely (summary + link to new §4); surfaces the restated `trigger` note ambiguity and names which reading today's design already satisfies; points to the new Decisions section for the three new open questions.
6. Verify via `lib/owner_decisions.py waiting` (or equivalent `pr_status` check) that PR #738 no longer shows as waiting on MARVIN.
7. Leave issue #751 to close itself per its own "closes itself once PR #738 is addressed or closed" footer (`owner_decisions.sync`) — do not manually close it.