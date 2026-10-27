# 0076 — Union merge for the synced files every machine appends to

## Status

Accepted (2026-10-26; fix approved by the owner the same day)

## Context

`code_sync.py` syncs the Claude dir ([[0022]]) by stash, pull, pop. Both Macs append to the same files, so the pop
conflicts, a stash is left behind, and `_stuck_from_previous_run()` then refuses every run until a person resolves it.
That happened three times between 2026-10-22 and 2026-10-26 and blocked sync for up to four days. The files were
`quarantine.md`, `improvement-queue.md`, the memory index `projects/*/memory/MEMORY.md` and memory notes
`projects/*/memory/*.md`; earlier ones hit `sync-log.md`. Each one was resolved the same way: each Mac added different
lines, keep both. In the sync log's own history the conflicted files in the Claude dir are exactly these
(`sync-log.md` 19 times, `quarantine.md` 8, `MEMORY.md` 3, `improvement-queue.md` 3, a memory note once). The rest
were the engine repo's machine-written files (`bench/metrics/*`, `graphify-out/*`), already handled elsewhere
(`NEVER_COMMIT`, the metrics-collision resolver). `auto-fix-log.md` is append-only too and was already union in the
dir's tracked `.gitattributes` alongside `sync-log.md` (marvin#427).

Left out on purpose: `lexicon.md` and `suggestions.md`. Both are edited and reordered in place, not only appended to,
so a conflict there is a real one.

## Decision

git's built-in `union` merge driver for those paths, written by code_sync into the clone's own
`.git/info/attributes` (a managed block) before every stash, merge or pop, in push and pull. Only a repo named
`.claude` gets it; the engine repo's files must still conflict.

`.git/info/attributes`, not a tracked `.gitattributes`:
- it is in force on a fresh machine before its first pull; a tracked file only applies once pulled, and the merge
  that brings it in doesn't use it;
- it can't conflict between machines itself;
- the rule changes when the engine changes, with nothing to commit to the owner's repo.
The dir's tracked `.gitattributes` stays as it is; the two agree.

`git stash pop` and `git merge --autostash` honour the attributes (tested on real repos).

Union can't fail, so what it gets wrong is reported, never silent. After the merge and any stash pop (never between
them, or the pop would conflict on the edit), code_sync reviews each union file both sides changed, by line counts
of base, ours, theirs and result:
- exact duplicate memory-index lines (`- [title](file.md) ...`) are removed, keeping the first, and logged;
- a line one side changed or removed that is still present (the interleave: an edit touching the other side's
  addition comes back as old line beside new line), a heading the merge doubled, or one memory linked on two
  different lines: logged once in sync-log.md and kept in `~/.claude/logs/union-merge-review.json`, shown as a yellow
  Health card (`sync:union-review`). Each item is re-checked against its file on every read, so fixing the file
  clears it. Nothing else is ever removed.

A conflict in any other file still stops for a person, exactly as before.

## Consequences

The four-day stalls stop for the files that caused them. Costs O(lines of the files both sides touched) per merge.
Known limits: a merge's review is local to the Mac that made it (the sync-log entry is synced; the Health card is not
cross-machine); a person who deliberately keeps a flagged line keeps the card yellow until they delete the review
file; `merge --autostash` inside push restores WIP without a review (that WIP is nearly always sync-log.md).
