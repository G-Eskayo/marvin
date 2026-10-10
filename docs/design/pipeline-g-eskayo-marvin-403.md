## North-star fit

Unchanged from the prior attempt on the content question, but the mechanical diagnosis needs one more correction, now visible in the live worktree state. This remains a "no code changes" review ticket — the issue body says so explicitly ("## The review (no code changes)") — so one markdown file is still the right-sized deliverable: no new abstraction, no merge decided in advance, reusing the existing Decisions format (`docs/agents/decisions-format.md`), the outbox-vs-plans memory rule, and the catalog/relations machinery already shipped for Docs/Files. Token spend is re-verification (cheap) plus git mechanics (cheap), not code — correct, since a wrong merge call costs more to unwind than a careful review costs now. It leaves Gil more capable: a real Decisions block with three concretely-described options, not a decision made for him.

**What's actually new in this pass, verified directly against the live worktree (not re-guessed):**

- `docs/plans/docs-vs-files-review.md` **already exists, untracked, and its content is correct.** I read it in full this pass. It has all four required sections, and the Decisions block matches `docs/agents/decisions-format.md` byte-for-byte (`<!-- marvin:decisions -->`, `### merge: <question>`, three `- [ ]` options, no pre-ticked boxes, one required question). I re-checked its two load-bearing citations against current code and both are still accurate, but the file paths in the doc are abbreviated — the real paths are `dashboard/src/App.jsx` (labels `'Docs'`/`'Files'` confirmed at lines 17–18) and `dashboard/electron/main/outbox.js` (`detectKind`, confirmed at lines 134–150, recognizing only `.md`→markdown and `.json`→json-or-text, falling back to `text` for everything else, including images/PDFs). **Correction to apply:** fix those two citations to include the `dashboard/` prefix the repo actually uses.
- `git branch --show-current` shows this worktree is **already on `pipeline/g-eskayo/marvin#403`** — it is not detached HEAD, and no new branch needs creating. `git log` on it has no ticket-specific commit; HEAD sits at the same auto-sync commits as `main`. So the deliverable file has never been staged or committed, confirming (again) that content isn't the problem — committing is.
- **New finding this pass, not in the prior doc:** two more untracked files, `docs/design/pipeline-g-eskayo-marvin-403.md` (51 lines) and `-tasks.md` (6 lines), have a **later** mtime (15:11:05) than the review doc itself (15:03:22). These are this planning step's own captured output from the *previous* iteration — i.e. a build/execution stage did write the deliverable content correctly, and then a second planning pass ran and got captured to disk, and **still nothing was ever committed.** Three iterations in a row have independently reached "content is correct" and then stalled before `git add`. That is a strong signal the prior plan's git-mechanics steps were placed last in a task list, after several verification steps — plausible failure mode: an execution agent that treats a long list as advisory and stops once it judges the content "already fine" never reaches the commit/push/PR items at the end. This revision fixes that by putting the git mechanics **first**, as the only required actions, with verification as a precondition check rather than the lead items.
- Also worth stating plainly: the automated comparison's `vitest_passed`/`pytest_passed`/`tests_failed` metrics being bit-identical to baseline every iteration is **not evidence against this plan** — this ticket intentionally makes zero code changes, so no test count can ever move. The actual completion criterion, per the issue's own "Done when," is "the review doc is in a PR, and the PR's Decisions section asks Gil to pick an option." No PR has ever been opened in three iterations. That is the one fact this revision must fix.

## Tests first (adapted — #403 has no "How we'll try to break it" section, confirmed again)

No such section and no Attacks list exist in the issue body (unlike #402). Adversarial checks on the doc-as-deliverable and the commit mechanics, each a concrete way this still fails a person or the pipeline:

1. **Re-verify facts haven't drifted since drafting, with corrected paths** — `dashboard/src/App.jsx:17-18` still `label: 'Docs'` / `label: 'Files'`; `dashboard/electron/main/outbox.js`'s `detectKind` still only recognizes `.md`/`.json`, falling back to `text`. Confirmed this pass. Fix the doc's citations to use the real `dashboard/`-prefixed paths before committing.
2. **Decisions section fails the structured parser** — diff against `docs/agents/decisions-format.md` line-by-line (marker present, `### <id>: <question>` form, ≥2 `- [ ]` options, none pre-ticked, no stray prose question elsewhere). Confirmed passing.
3. **Usage-frequency fabrication** — doc must say "unknown, no tab-usage telemetry exists," never invent a number. Confirmed both tab sections say this.
4. **Options don't name what Gil sees on screen** — each option needs a "What you see on screen" subsection. Confirmed present in all three.
5. **#402 dependency silently dropped** — each option states its consequence for #402. Confirmed present ("Implications for #402" in all three).
6. **Recommendation contradicts its own evidence** — recommending Option A while describing why B/C are riskier is internally consistent; confirmed.
7. **Doc touches code** — `git status --porcelain` immediately before staging must show it touches only `docs/plans/docs-vs-files-review.md`; `git diff --stat` after staging must show exactly one file. This is the step that silently never happened in three iterations — now explicit and first, not buried.
8. **Pipeline scratch files leak into the commit** — `docs/design/pipeline-g-eskayo-marvin-403.md` and `-tasks.md` are this planning step's own captured output, not the ticket's deliverable, and must be excluded by staging the review doc by its explicit filename, never `git add -A`/`git add .`.
9. **Wrong branch / stale assumption** — the prior plan assumed a new branch needed creating; it doesn't. Current worktree is already on `pipeline/g-eskayo/marvin#403`, confirmed this pass. Committing directly to it is correct; creating a second branch would be the actual new mistake to avoid here.
10. **Race with another session** — re-run `gh pr list --repo G-Eskayo/marvin --head "pipeline/g-eskayo/marvin#403" --state all` immediately before opening a PR (confirmed empty this pass, but shared worktree, other sessions can act between planning and execution).
11. **PR opens without the Decisions section actually in its body** — the block must be pasted verbatim into the PR description (not left only in the file), since the dashboard's merge gate (`decisions_gate.js`) reads the PR description, not the file, per `docs/agents/decisions-format.md`.
12. **Execution stalls again after verification, never reaching the commit** — the actual repeat failure mode across all three iterations. Mitigated structurally below by making the git commands the first, mandatory, unconditional steps of the Task List rather than steps 3-7 of 7.

## Decisions

No new decision for me to make — the ticket's own "Options" list is the single decision the owner must answer. It is already present in the existing draft, format-verified against `docs/agents/decisions-format.md`:

```markdown
## Decisions
<!-- marvin:decisions -->
### merge: Keep Docs and Files as two tabs, or merge them?
- [ ] A: Keep both, rename so they no longer read as synonyms
- [ ] B: Merge into one tab with sources (Projects, Outbox, Plans) in its sidebar
- [ ] C: Fold the outbox into Docs as a pseudo-project, like the master doc
```

## Task List

1. **Fix the two citation paths** in `docs/plans/docs-vs-files-review.md` (lines 27 and the App.jsx references near line 73-74) to read `dashboard/src/App.jsx:17-18` and `dashboard/electron/main/outbox.js` (`detectKind`, ~lines 134-150) instead of the bare paths — the only content edit this revision makes.
2. **Stage only the review doc by explicit name**: `git add docs/plans/docs-vs-files-review.md` — never `-A`/`.`. Confirm with `git status --porcelain` immediately after that `docs/design/pipeline-g-eskayo-marvin-403.md` and `-tasks.md` remain untracked/unstaged.
3. **Commit directly to the current branch** (`pipeline/g-eskayo/marvin#403` — already checked out, do not create a new one) with a message describing the review, not a feature.
4. **Re-check for a race**: `gh pr list --repo G-Eskayo/marvin --head "pipeline/g-eskayo/marvin#403" --state all` must still be empty.
5. **Push the branch and open the PR**, pasting the Decisions block verbatim into the PR body text (not just relying on the file) so the merge gate's `decisions_gate.js` reads it correctly.
6. **Confirm via `gh pr view`** that the opened PR shows the Decisions section and that `git diff main --stat` for the branch shows exactly one file changed, two lines, in `docs/plans/`.
7. *(Only after 1-6 succeed)* re-run the 12-point adversarial check above against the committed version as a final sanity pass — this is confirmation, not a gate that should block steps 1-6, since steps 1-6 are the fix for the actual repeated failure.