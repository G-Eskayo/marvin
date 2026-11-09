## North-star fit

- **Existing pattern reused:** the owner-decisions reply convention itself, documented in `docs/agents/decisions-format.md` ("After the owner answers: it is MARVIN's move") and enforced by `lib/owner_decisions.py:pr_status`/`ADDRESSED_MARKER`. No new code or abstraction — this ticket is satisfied entirely by *acting* through that existing mechanism: post one PR comment on #969 containing `<!-- marvin:decisions-addressed -->`.
- **Why simplest sufficient:** I verified (via `git diff 8d35f879 17ff3042 -- config/mac-mini-2012/build-builder-image.sh lib/vm_run.py builder/provision.sh`) that none of the PR's core feature files have changed since the decision comment (2026-10-30T23:15:52Z). The owner's chosen option — "keep the golden image in `runs/golden/`" — was already the shipped design before he even answered; the commits since then are unrelated (a stacked-branch merge of `ticket/933-gate-box-runner`/`ticket/932-box-trial`, and one single-parent CI-fix commit `ca16c1aa` for a flaky `simctl` mock in `lib/tests/test_cleanup_sweep.py`, which has nothing to do with this PR's feature). So there is nothing to build or redo — only to verify and report. Writing code here would be inventing work the ticket doesn't ask for.
- **Why the ticket still exists despite that:** `dashboard/webhook-server/decisions.js:answersAsBuilt` (the heuristic `lib/owner_decisions.py:pr_status` calls as `_as_built`) only auto-closes a Decisions comment when the ticked option's label carries a `(built)`/`(recommended, built)`/"as built" marker (`BUILT_MARK` regex, `decisions.js:121`). The PR's option text has no such marker, so the automatic short-circuit couldn't fire and the 4-hour grace (`MARVIN_DECISIONS_GRACE_HOURS`) filed this follow-up. That's a possible future improvement (tag the pre-ticked option `(built)` at PR-creation time) but it's out of scope for #989 — noting it, not building it.
- **Token/compute cost:** near-zero — a handful of `gh`/`git` read calls already done, plus one `gh pr comment` write. No test suite run needed since no source file changes.
- **User capability:** this closes the loop the owner actually asked for (`lib/owner_decisions.py`'s own purpose: "a PR whose answers sit there without a reply tells the owner nothing"). It leaves Gil able to trust that an unreplied Decisions comment really is unactioned, rather than quietly stale — the point of the mechanism, not just activity for its own sake (Watts check passes: the reply is consumed by the dashboard's `needs_you.js` ranking and by Gil reading the PR).

## Tests I will write first

None — this ticket's deliverable is a GitHub comment on PR #969, not a source-code change, so there is no code path for a pytest/dashboard test to cover. Mapping the ticket's "How we'll try to break it" list onto the actions that stand in for tests here, since there's nothing a unit test would exercise:

1. **"The notes contradict a chosen option"** → already checked: the Decisions comment's `note` field is `""` (empty) and its one answer (`golden-home`) matches the option already shown as `[x]` in the PR body. No contradiction found; if one existed, the reply would say so instead of guessing (per the ticket's own instruction) — this is a judgment call at reply-writing time, not something to encode as a test.
2. **"The PR changed since the decisions"** → already re-read: diffed `8d35f879` (pre-decision commit) against `17ff3042` (current tip) for every file the PR's "What changed" section names. No change to those files. Confirmed CI is green and the PR is `MERGEABLE`/`CLEAN` right now (it was previously parked twice for timing out, per the issue comments, but the current `statusCheckRollup` is all `SUCCESS`).
3. **Misuse cases the section didn't name, considered and ruled out as not applicable:**
   - *Bad/empty/huge/malformed input* — no form or endpoint is involved; the only "input" is the PR body/comment text I already parsed by hand.
   - *A dependency failing* — `gh` calls either succeed (giving ground truth) or fail loudly; I won't post a reply built on a failed read.
   - *Repeats/concurrency* — `lib/owner_decisions.py:_dedupe` already handles a second Mac racing to file a duplicate follow-up; posting the one reply is idempotent (a second `marvin:decisions-addressed` comment would just make `pr_status` pick the latest one — harmless, but I'll only post once).
   - *Wrong permissions/machine* — `gh` here is gated to read-only (`view`/`list`/`diff`); the write (`pr comment`) must go through `~/.agents/bin/gh`, which enforces the Decisions-format gate (`DECISIONS_NOT_ASKABLE`/`DECISIONS_UNPARSED`) — irrelevant here since my reply reports, it doesn't ask.
   - *Stale state* — re-fetched PR state live (comments, commits, CI, mergeability) rather than trusting the ticket body's snapshot.
   - *A person's mistake* — if the owner's one answer turns out ambiguous or if the PR has since been closed/merged, the reply (or the no-op) says so rather than inventing an answer.

## Decisions

None needed — the owner already answered the only open question (`golden-home`), and nothing here requires him to choose again.

## Task List

1. Post one reply comment on PR #969 (via `~/.agents/bin/gh pr comment 969 --repo G-Eskayo/marvin --body-file <tmp>`, not a heredoc substitution per the gh-body-file convention) containing:
   - `<!-- marvin:decisions-addressed -->` marker (required for `lib/owner_decisions.py` to treat it as addressed).
   - Confirmation that the `golden-home` decision ("keep the image in `runs/golden/`") is already carried out — it was the shipped design before the decision was even recorded, cited with the original commit (`8d35f879`).
   - What actually changed on the branch since the decision: the `933`/`932` stacked-branch merges and the unrelated `ca16c1aa` CI-fix commit, explicitly stating these do not touch the golden-home choice or any other PR #969 feature file.
   - The screenshots line: "not applicable — this PR has no UI change (VM build scripts and `lib/vm_run.py` only), so no screenshots were taken or need retaking."
2. Confirm after posting that `lib/owner_decisions.py pr_status` would now read `addressed_by == "reply"` for this comment (i.e. the reply's `createdAt` is after the Decisions comment and carries the marker) — a manual read-check, not a code change.
3. No further action on issue #989 itself: it is filed to close itself once PR #969 is addressed (per its own footer), so no manual close is needed — confirm it does in a later check rather than closing it by hand.