## North-star fit

**Existing pattern reused:** none new — this plan reuses the governance pattern itself: `lib/owner_decisions.py` (marvin#607) scans for a `<!-- marvin:decisions -->` block answered-but-unactioned, and expects the response to land as a PR reply carrying `<!-- marvin:decisions-addressed -->`, per `docs/agents/decisions-format.md`. That is the only mechanism this ticket calls for; there is nothing else to build.

**Simplest sufficient approach:** verify, don't re-implement. I checked the live state of PR #1118 (`gh pr view 1118 --comments`, `git log`/`git diff` against `origin/ticket/560-auto-route-prompt-key`) rather than redoing the plan embedded in the ticket's own prior failed attempts.

**Finding — the ticket is already satisfied, upstream of this worktree:**
- PR #1118's branch (`ticket/560-auto-route-prompt-key`, tip `a0d97c92`) already contains both decided changes: a merge of `main` (`2835da31`, no conflicts, merge-base `b096519d`) followed by the keyword-first-pass + 1.5s-budget embed fast path (`a0d97c92`), diffing `lib/intent_classify.py`, `skills/route/scripts/auto_route_hook.py`, `skills/route/scripts/route.py` and their tests (814 insertions / 46 deletions total).
- `main` has had **zero** commits touching those five files since the branch's merge-base — no conflict risk, nothing stale to re-check.
- A PR comment carrying `<!-- marvin:decisions-addressed -->` is already posted, answering both questions:
  - `recall-suggestion`: "Keep suggesting `claude-recall`" — no code change needed, states why.
  - `latency`: "Only if faster first" — points at commit `a0d97c92`, with a measured before/after latency table (0.65–0.82s → 0.06s keyword / 0.2s embed) and a 46/46 agreement check against the old chromadb classifier.
  - Screenshots: explicitly addressed ("This PR has no UI... the images stand (there are none)").
- The reply reports `106 passed` across the four relevant suites plus `test_board_registry.py`.

All three acceptance criteria are already met on PR #1118 as it stands on GitHub right now. There is no implementation gap for this ticket to fill.

**Tokens:** spent only on verification (gh/git reads), zero on re-implementing already-shipped work — the cheapest correct outcome.

**User capability:** leaves the owner with one less thing to track; no behavior change for him beyond what the already-posted reply already shows.

## Risks from the ticket's "How we'll try to break it", checked

- *"The notes contradict a chosen option: say so instead of guessing."* — Checked: both decision notes were empty (`"note": ""` in the machine-readable block), so no conflict to flag; the existing reply correctly treats this as no-op for `recall-suggestion` and as a straightforward build for `latency`.
- *"The PR changed since the decisions: re-read it before acting."* — Checked directly against live GitHub state just now (not relying on the stale context embedded in earlier failed attempts). No drift: the reply's cited SHA (`a0d97c9298c9d48bb8023834a88df11b3a6c1bdc`) matches the branch tip, and `main` hasn't touched the affected files since.
- Additional misuse case not in the ticket's list but relevant here: *a prior automated run reports "mixed" or times out, then a later run on the same branch succeeds — does the ticket correctly recognize the later, successful state rather than re-acting on stale failure comments?* Checked: yes — the two prior ticket comments showing timeouts/`mixed` verdicts (12:56 UTC and earlier) predate the branch's actual completion commit and reply (11:37/18:37 UTC same day); the self-closing scan (`lib/owner_decisions.py`) just hasn't run again since. No action should be taken that contradicts this newer, successful state.

## Decisions

None. Nothing here needs the owner to choose — the owner's own prior choices are already fully carried out and replied to.

## Task List

1. No code changes — verification confirms PR #1118 already satisfies all three acceptance criteria (decisions carried out, addressed reply posted, screenshot question answered).
2. No new PR reply needed — the existing reply on PR #1118 already carries `<!-- marvin:decisions-addressed -->` and answers both questions correctly against current branch state.
3. Let `lib/owner_decisions.py`'s next scan close ticket #1143 automatically, per its own stated self-close condition ("closes itself once PR #1118 is addressed or closed") — no manual close action needed from this plan.
4. If a human wants confirmation sooner: optionally post a short ticket comment linking to the existing `decisions-addressed` reply, noting the prior "mixed"/timeout comments predate the branch's completion — but this is cosmetic, not a requirement.