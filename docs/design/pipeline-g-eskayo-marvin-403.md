## North-star fit

- **Reuses before adding anything new:** the prior analysis (`docs/plans/docs-vs-files-review.md`, already on disk, untracked) is still factually correct against current code — re-verified fresh below. The Decisions grammar (`dashboard/webhook-server/decisions.js`) and the GitHub gate (`~/.agents/bin/gh`, [[reference-github-gate]]) are existing mechanisms this plan uses as-is. Nothing new is added — the fix is entirely in how the task list is executed, not in more analysis.
- **Simplest sufficient approach:** still one markdown file + a PR description. No new machinery.
- **Where it spends/saves tokens:** this revision explicitly moves the cheapest, highest-signal check (can this session actually commit/push/open a PR?) to the very first task, before any content re-verification work. That ordering is the token-saving move: if attempt 3 is going to stall at the same point as attempts 1 and 2, it should stall for ~0 tokens, not after re-reading six files again.
- **User capability:** unchanged from the ticket's own framing — Gil gets one grounded choice via buttons once this actually reaches a PR.

## Why this keeps coming back "unchanged" — a different diagnosis than last time

Fresh verification of the actual worktree (not the stale plan) shows:

- `docs/plans/docs-vs-files-review.md` exists, is fully written, and **already contains** the one revision the last design doc called for (the `files_search.js` footnote in §2). So whatever executed the previous plan's task list did perform the content edit.
- `git status` shows this file (and the two `docs/design/pipeline-g-eskayo-marvin-403*.md` planning artifacts) as **untracked**. `git log` / branch tracking shows this branch is still exactly `origin/main` — **zero commits ahead**, same as last time.
- `gh pr list --search 403` (plain, allowed `gh`) returns nothing. No PR exists, same as last time.

So the previous attempt's diagnosis ("it never ran commit/push/PR, add explicit steps for that") was the right category of fix but evidently **did not change the outcome** — the content got revised exactly as instructed, and the process still stopped at the identical point: file written, nothing committed. Two different task lists, two identical stalls at the same seam. Per [[feedback-catch-repeated-mistakes]], a mistake recurring unchanged despite a targeted fix means the fix targeted the wrong layer — the task list was never the bottleneck.

The likely actual bottleneck, based on direct evidence from *this* planning session: every `git`/`gh` invocation I attempted outside the small explicitly-granted read-only set (`git log/diff/show/blame`, `gh view/list/diff`) was hard-denied by the sandbox — including a plain read command routed through the `~/.agents/bin/gh` wrapper (`gh pr list --head ...`). That's a permission-allowlist denial, not a judgment call, and it fired even for a read. One repo fact cuts the other way, though: this same pipeline *did* successfully create and merge a PR for a different ticket (`efe95c3`, PR #398 from `pipeline/g-eskayo/marvin#380`) — so the write path isn't categorically broken for this repo. That means either (a) the build stage for a **docs-only, zero-code-diff** ticket like #403 is hitting a narrower or different permission profile than code-changing tickets get, or (b) something about this specific branch/PR path for #403 is failing silently in a way that two content-focused retries never surfaced because neither retry actually checked git exit codes — it just assumed the task list's prose would be followed through.

I can't confirm the exact mechanism from a read-only planning seat. What I can do is stop assuming the next attempt's git/gh calls will succeed just because they're written down, and instead make the task list self-diagnosing: probe the write path first, cheaply, and fail loud with the exact error if it's blocked — rather than silently producing a third identical stall that only an external metrics tool notices, cycles later.

## Facts re-verified fresh

- `CONTEXT.md:375–382` (Files tab, in design) and `:417–425` (Docs tab, built) — still describe the split as drafted. Unchanged.
- `dashboard/electron/main/files_search.js` — confirmed via grep: referenced only by `dashboard/electron/main/index.js` and its own test (`dashboard/test/files_search.test.js`), not by `FilesExplorer.jsx` or `outbox.js`. It's the Docs-tab "Where things are" Spotlight search (`CONTEXT.md:589`), not Files-tab search. The on-disk doc's footnote already states this correctly.
- `dashboard/src` grep for `track|localStorage|analytics|logEvent`: only literal hit is the CSS class `tracking-wide` (and `UsageView.jsx`'s unrelated token-usage-limit prose). No UI telemetry exists — "usage frequency unknown" still holds.
- `dashboard/webhook-server/decisions.js` parser re-checked line-by-line (`QUESTION_RE`, `OPTION_RE`, `ID_RE`): the drafted block below (`### merge: Docs vs Files — which option?`, id `merge`, 4 options) matches every regex. Still valid, single-choice, required by default.
- `#402` re-read fresh: still open, `needs-info`, diagnosed root cause in `outbox.js`/`FilesExplorer.jsx`, still the dependency the Connections note should name.
- No diff exists between this branch and `main`; no PR for #403 exists under either plain `gh` or the wrapper's read form; the branch `pipeline/g-eskayo/marvin#403` already exists and tracks `origin/main` with zero local commits — reuse it, don't recreate it.

## Verification checks (process tests, since this is a doc-only deliverable with no app code)

1. **The exact failure that has now happened twice:** work stalls after the local file write, never committed/pushed/PR'd — with no error visible anywhere because nothing checked for one. Guard: every git/gh write call in the task list below is followed by an explicit exit-code/output check; if any fails, STOP and report the exact command and error as the task's result — do not proceed, and do not report the ticket done.
2. **Permission/tooling block on the write path** (the new hypothesis this revision adds): reproduced directly in this planning session for a *read* call through `~/.agents/bin/gh`. Guard: task list's first step is a cheap, reversible probe of the actual write path *before* spending tokens on content re-verification — see Task List step 1.
3. **Malformed Decisions block:** missing marker, bad id casing, fewer than 2 options. Guard: after PR creation, fetch the live PR body (`gh pr view --json body`) and re-check it against the real parser regexes on the *fetched* text, not the drafted text.
4. **Empty/placeholder PR body:** a PR created with a template default instead of the intended body. Guard: same fetch-and-check as #3 — non-empty, contains the literal `<!-- marvin:decisions -->` marker.
5. **Dependency failing:** `gh` write calls must go through `~/.agents/bin/gh` ([[reference-github-gate]]) for its cooldown/budget floor. Guard: use the wrapper for writes, check its exit code, don't loop/retry around a cooldown — treat a cooldown response as a real blocker to report, not something to spin on.
6. **Repeats / idempotency:** a third run must not create a duplicate branch or PR. Guard: `gh pr list --repo G-Eskayo/marvin --search "403" --state all` (plain, confirmed allowed) before creating anything; if a PR already exists by the time this runs, update it instead.
7. **Concurrency:** another session could be mid-edit on the same branch. Guard: re-run `git status`/`git log` immediately before committing, not from this plan's snapshot.
8. **Wrong permissions / wrong target:** guard against pushing to `main` or hitting branch protection — push only the existing feature branch, confirm `git branch --show-current` first.
9. **Stale state:** `#402`'s body could have changed. Guard: re-fetch `#402` immediately before finalizing the Connections note.
10. **Scope creep:** the PR diff must contain exactly one new file, `docs/plans/docs-vs-files-review.md` — not the `docs/design/pipeline-g-eskayo-marvin-403*.md` planning artifacts, and no edits to `App.jsx`/`DocsExplorer.jsx`/`FilesExplorer.jsx`/`outbox.js`/`docs_service.js`. Guard: `git status`/`git diff --stat` before pushing must show exactly that one path staged.
11. **Reader's mistake:** Gil could read an open PR and expect the chosen option already built. Guard: PR body states plainly that building the chosen option is a separate follow-up ticket.
12. **Third-strike escalation (new):** if this attempt *also* stalls at local-write with no commit, that is no longer a content or task-list-wording problem — two prior attempts with increasingly explicit instructions already ruled that out. Guard: if step 1's probe fails, or any later git/gh write call fails, the task's final output must say so in plain terms (which exact command, which exact error) so a human session can fix the permission/tooling gap directly, instead of a fourth autonomous retry re-deriving the same correct content a third time.

## Decisions

None needed from the owner at planning stage — unchanged from the prior plan, and still correct: the one owner choice (which of A/B/C to build) belongs in the PR's own Decisions section, per the ticket's design.

```markdown
## Decisions
<!-- marvin:decisions -->
### merge: Docs vs Files — which option?
- [ ] A: Keep both tabs, rename Files so it stops reading as a synonym of Docs
- [ ] B: Merge into one tab, with Projects and Outbox as sidebar sources
- [ ] C: Fold the outbox into Docs as a pseudo-project, like the master doc (recommended)
- [ ] other: Something else (say what in the note)
```

## Task List

1. **Permission probe (do this before anything else, before re-reading any content):** on the current branch, run `git commit --allow-empty -m "probe: confirm write access for #403"`, check its exit code, then `git push -u origin pipeline/g-eskayo/marvin#403` and check its exit code. If both succeed, immediately `git reset --soft HEAD~1` to undo the empty local commit (origin now has it; this just confirms local write capability — leaving a stray empty commit on origin is harmless and will be superseded by the real commit in step 5) — actually: if push succeeded, don't try to un-push; just proceed, the real commit in step 5 will follow it normally. If either command fails or is denied, STOP here and report the exact command and error as the task's complete output — do not attempt the remaining steps, and do not report the ticket done.
2. Re-verify the facts in "Facts re-verified fresh" above one more time immediately before finalizing (CONTEXT.md line ranges, `files_search.js` scope, `#402` body) — not from this plan's snapshot.
3. Confirm `docs/plans/docs-vs-files-review.md` still matches those facts. It already does (verified above, including the `files_search.js` footnote) — do not rewrite it.
4. `git add docs/plans/docs-vs-files-review.md` only — not the `docs/design/pipeline-g-eskayo-marvin-403*.md` planning artifacts (scope-creep guard, check 10).
5. `git commit` with a message referencing #403; check exit code; if non-zero, STOP and report the error.
6. **Idempotency guard:** `gh pr list --repo G-Eskayo/marvin --search "403" --state all` (plain `gh`, confirmed working) — only proceed to push/create if nothing already exists; if a PR now exists, update it instead of creating a second one.
7. `git push -u origin pipeline/g-eskayo/marvin#403`; check exit code; if non-zero, STOP and report the exact error (don't assume step 1's probe guarantees this one still works — re-check it live).
8. `~/.agents/bin/gh pr create --repo G-Eskayo/marvin` with a short summary plus the exact Decisions block above, referencing #403 and #402; check exit code and capture the returned PR number; if it fails, STOP and report the exact error.
9. **Completion guard:** `gh pr view <num> --json body` and re-check the fetched body against the real parser rules (marker present, id `merge` matches `ID_RE`, 4 options match `OPTION_RE`).
10. `git status` and `git diff main...HEAD --stat` — confirm a clean tree and exactly one changed file before reporting the ticket done.
11. Do not touch `App.jsx`, `DocsExplorer.jsx`, `FilesExplorer.jsx`, `outbox.js`, or `docs_service.js` in this PR — building the chosen option is a follow-up ticket, filed only after Gil answers.
12. If step 1 or any later git/gh step failed and this task list stopped early: that is the complete, correct output for this attempt — a clear "blocked at <step>, error: <text>" report, not a silent re-run of steps 2-4 dressed up as progress.