## North-star fit

**Reuses:** the exact mechanism this ticket exists to drive — `lib/owner_decisions.py`'s `ADDRESSED_MARKER` (`<!-- marvin:decisions-addressed -->`) and the "owner-account reply" convention in `docs/agents/decisions-format.md` ("After the owner answers: it is MARVIN's move"). Also reuses `~/.agents/bin/gh` (the GitHub gate — [[reference-github-gate]]) to post the comment, rather than any new script. No new file, no new code.

**Simplest sufficient approach:** this ticket resolves to posting one PR comment. I confirmed by diff (`gh pr diff 969`) that the chosen option — keep the `marvin-build` golden image under `runs/golden/` (box's user, no sudo) — is already fully implemented (`lib/vm_run.py`'s `golden_path()`: images in `USER_BUILT` resolve to `RUNS_DIR/"golden"`). The three commits on the branch since the owner's decision (23:25:45 merge, a Nov-3 unrelated `simctl` test fix pulled in from the stacked base branch, and a second merge) touch none of the golden-image logic. There is nothing left to build — only to say so. Adding any script or code here would be inventing machinery for a one-off factual reply, which fails the Colton check.

**Token/cost:** trivial — one `gh pr comment` call through the existing gate. No build, no test run, no new agent.

**Phone-OS / capability fit:** this closes the exact gap marvin#607 exists to close — Gil submitted a decision 2026-10-30T23:15:52Z and, despite later commits, got no reply telling him it was carried out. Leaving it unanswered keeps him checking PRs by hand (more passive, less trusting of the dashboard). A factual reply restores that trust and lets the dashboard's "waiting on MARVIN" state clear itself — it makes Gil *more* able to rely on the system, not less.

The ticket's own "Filed by the ticket scan" framing matches the code exactly (`lib/owner_decisions.py:280-317`), so no correction needed there.

## Decisions

None needed. Nothing here requires the owner to choose anything: the only decision point (`golden-home`) was already answered by Gil and is already built. This plan only reports that fact back to him.

## Tests (verification checklist — this ticket has no code diff, so "tests" are pre/post checks, not pytest cases)

From "How we'll try to break it":
1. **"The notes contradict a chosen option: say so instead of guessing."** → Checked: the decision's `note` field is `""` (empty) in the machine-readable block on PR #969's `### Decisions from the owner` comment. Nothing to contradict. Re-verify this is still empty immediately before posting (in case of a race).
2. **"The PR changed since the decisions: re-read it before acting."** → Checked via `gh pr diff 969` against current HEAD: `golden_path()` in `lib/vm_run.py` still matches the chosen option. Re-run this diff check immediately before posting, not from memory, in case of a race with another session.

Misuse the section didn't name, applied per north-stars §Guiding principles:
3. **Stale state / race:** another MARVIN session could already have posted the addressed-reply, or PR #969 could have been merged/closed, between this plan and execution. Before posting: re-run `gh pr view 969 --repo G-Eskayo/marvin --comments` and check for an existing owner-account comment containing `ADDRESSED_MARKER`, and recheck `state`/`mergeable`. If already addressed or the PR is closed, post nothing (duplicate reply) and report that instead.
4. **Wrong-account misuse:** `addressed_by == "reply"` in `owner_decisions.py:170-172` requires the comment be authored by the *repo owner's account* (`_login(c) == owner`). Confirm `~/.agents/bin/gh auth status` is authenticated as that account before posting — a reply from a different account would silently fail to register and the follow-up ticket would never close.
5. **Self-inflicted `DECISIONS_NOT_ASKABLE`:** the reply must not open with a bare "## Decisions"/"## Open questions"/"## Choose" heading without a `<!-- marvin:decisions -->` block, or `bin/gh` refuses the comment outright. Since no new decision is needed, the reply avoids those headings entirely (uses prose/"What changed" framing instead).
6. **Marker exactness:** the posted body must contain the literal string `<!-- marvin:decisions-addressed -->` (regex match in `owner_decisions.py:170`, not a paraphrase) — verify the exact substring is present in the drafted comment before calling `gh`.
7. **Empty/malformed input to the gate:** confirm the comment body isn't empty and doesn't trip `decisions_check.gate` (no unmarked ask-heading) by drafting the body text first and checking it mentally against `docs/agents/decisions-format.md`'s rule before the `gh pr comment` call.
8. **Verify, don't assume:** after posting, re-fetch `gh pr view 969 --repo G-Eskayo/marvin --comments` and confirm the new comment is present, authored by the owner account, and contains the marker — don't just trust the `gh` exit code.
9. **Idempotency / concurrent dispatch:** if ticket #989 was independently picked up by another session and already closed (self-closing per the filing doc) before this plan's execution runs, re-check `gh issue view 989 --repo G-Eskayo/marvin` state immediately before acting; if already closed, do nothing further.

## Task List

1. Immediately before acting, re-check PR #969's state (`gh pr view 969 --repo G-Eskayo/marvin --json state,mergeable`) and comments (`gh pr view 969 --repo G-Eskayo/marvin --comments`) to confirm: no existing `ADDRESSED_MARKER` reply, PR still open, decision note still empty, and the `golden_path()` implementation still matches the chosen option (`gh pr diff 969`).
2. Confirm `gh` auth identity (`~/.agents/bin/gh auth status`) is the repo-owner account, so the reply will be recognized as an "owner-account reply" by `lib/owner_decisions.py`.
3. Draft the reply body: states (a) the chosen option (`golden-home`: keep the image in `runs/golden/`) was already carried out — it has been true since the PR's first commit, confirmed still true in `lib/vm_run.py`'s `golden_path()`; (b) no owner question was asked, so none needs answering; (c) no screenshots apply — this PR has no UI change, only the terminal "Built live on the box" output already in the PR description; (d) notes the three commits since the decision are unrelated (two merges, one unrelated `simctl` test fix pulled in from the stacked base branch) and don't touch the golden-image path. Body ends with the literal `<!-- marvin:decisions-addressed -->` marker on its own line.
4. Post the reply with `~/.agents/bin/gh pr comment 969 --repo G-Eskayo/marvin --body-file <tmpfile>` (body-file per the `gh --body-file, not heredoc-in-$()` convention — [[gh-body-file-not-heredoc-substitution]]).
5. Verify the comment landed as expected: re-fetch comments, confirm the new one is present, authored by the owner account, and contains the exact marker string.
6. Report back on ticket #989 (or let its self-closing automation handle it, per `docs/agents/decisions-format.md` — the hourly scan closes the follow-up once the PR is addressed) — no manual close needed unless the scan hasn't run; if still open after a reasonable wait, comment on #989 linking to the PR reply as confirmation.