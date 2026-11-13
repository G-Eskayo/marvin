## North-star fit

**Reuses:** the existing `{destination}` templating slot already in `REVIEW_PROMPT_TEMPLATE` (`skills/architecture-review/scripts/background_architecture_review.py:168-181`) and `MD_DESTINATION`/`INBOX_DESTINATION`'s existing content — no new abstraction, just removing the hardcoded clause that duplicates what `{destination}` already says. The checked-in docstring (lines 28-32) already documents the inbox/legacy split correctly; only the prompt's opening sentence disagrees with it.

**Simplest sufficient approach:** a one-line string edit plus two test assertions. No new files, no new state, no new I/O.

**Tokens:** negligible to write; saves tokens going forward because the reviewer stops wasting part of every inbox-mode run resolving (or acting on) a contradiction, and `_import_staged()`'s habit-catching branch (line 196-212) stops silently absorbing writes to the wrong file every rotation.

**Phone-OS / capability:** doesn't touch that axis directly, but removing silent drift in the suggestions pipeline is a reliability precondition (north star 2's "nothing may break silently"). Leaves Gil more capable: he stops needing to notice or clean up `suggestions.md` drift himself.

I checked the ticket's own stated "North-star fit" against the code — it's accurate, no correction needed.

**Scope call:** the ticket's "Recurrence check" section ("add one [probe] counting 'wrote to the old suggestions.md' lines... as part of the fix") is not in "What to build" or the acceptance criteria, and the archived original ticket text describes it as a manual post-deploy watch ("watch background-review.log... to confirm it stops firing"), not new instrumentation. Building a counter/probe here would be new machinery the ticket doesn't actually require (north star 1: minimise resources) — I'm leaving it out and noting it as a follow-up observation only, not a task.

No Decisions needed — the ticket specifies the exact replacement wording and the exact test to update; nothing is open for the owner to choose.

## Tests (written first)

Per "How we'll try to break it":

1. **Exactly one write target per mode** — split into:
   - New test: render the prompt in **legacy mode** (no suggestions pile) and assert `MD_DESTINATION`'s `suggestions.md` reference is present, and the literal phrase `"only file you should write to is ~/.claude/suggestions.md"` is **absent** (the old hardcoded clause is gone even though the destination still legitimately names that file).
   - Update existing `test_inbox_mode_the_reviewer_writes_a_staging_file_that_is_added_to_the_inbox`: add assertion that `"only file you should write to is ~/.claude/suggestions.md"` is absent from the inbox-mode prompt (the existing assertion only checks for `"Append your findings to ~/.claude/suggestions.md"`, a different phrase — doesn't yet cover the ticket's literal contradiction clause).
2. **A template edit that drops `{destination}` must fail a test** — already satisfied by the positive assertions in both tests above (staging-file path / `suggestions.md` must appear in the rendered prompt); no separate test needed.
3. **Inbox-mode staging path containing spaces** — new test: point `STAGING_FILE` at a path with a space in a directory name, run in inbox mode, assert the path appears verbatim (unmangled) in the captured prompt.

**Other misuse categories** (bad/empty/huge/malformed input, dependency failures, repeats/concurrency, wrong permissions, stale state): this change only edits a literal string in a prompt template — it adds no new I/O, no new state, no new failure surface. Every one of those categories is already exercised by the existing suite against `run_review`/`main` (garbage staging file, symlinked staging file, non-zero/timeout claude exits, reruns/idempotency via content-keyed import, the old-suggestions.md habit branch). None need new coverage for this fix.

## Task List

1. Edit `REVIEW_PROMPT_TEMPLATE`'s opening sentence in `skills/architecture-review/scripts/background_architecture_review.py` (line 168): replace `"the only file you should write to is ~/.claude/suggestions.md, and you physically cannot do anything else"` with `"the only file you should write to is the one named below, and you physically cannot do anything else"`.
2. In `skills/architecture-review/scripts/tests/test_background_architecture_review.py`, update `test_inbox_mode_the_reviewer_writes_a_staging_file_that_is_added_to_the_inbox` to also assert `"only file you should write to is ~/.claude/suggestions.md"` is absent from `prompts[0]`.
3. Add a new legacy-mode test asserting the rendered prompt (pile absent, `MD_DESTINATION` path) names `suggestions.md` as the write target via the destination block, and that the old hardcoded contradiction phrase is absent.
4. Add a new test for an inbox-mode staging file path containing a space, asserting it's named correctly in the rendered prompt.
5. Run `~/.agents/venv/bin/python -m pytest skills/architecture-review/scripts/tests/test_background_architecture_review.py -v` and confirm the full suite (existing + new) passes.
6. Open the PR and `marvin-show` the diff for review.