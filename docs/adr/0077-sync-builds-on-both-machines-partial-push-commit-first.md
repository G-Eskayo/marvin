# 0077 — Code sync keeps both machines building on each other: partial push, commit before merge, keep-both resolution, one alert when stuck

## Status

Accepted (2026-10-26; approved by the owner the same day). Amends [[0021]], [[0022]] and [[0076]].

## Context

Measured 2026-10-26: the laptop's synced Claude dir went four days without a successful push. Its sync log held 129
"REFUSING to run — an unresolved merge conflict", 15+ "deferring — <file> was edited N min ago by a live session" and
5 "stash(es) left over". By then 15 memories, 10 handoffs and outbox work existed only on that machine and were
flushed by hand. The chain:

1. `_live_edit_lease` deferred the **whole** push when any one changed file had a live edit. The laptop nearly always
   has a live chat, so pushes almost never happened and the pile grew.
2. `pull()` stashed the pile and popped it over the remote's changes ([[0021]]: "stash → pull → pop, not a skip").
   The bigger the pile, the likelier the pop conflicted; the leftover stash then made `_stuck_from_previous_run`
   refuse every run until a person dropped it, which agents aren't allowed to do.
3. Files edited in place conflict even with [[0076]]'s union rule: `suggestions.md` is re-sorted by a script (not
   union at all), and memory notes are rewritten, so union interleaves old and new lines.
4. A stuck sync only turned Health red. Nobody was told.

Why [[0021]] chose stash: so a dirty machine still pulls instead of skipping, without committing on pull. Nothing
recorded rules out committing first; the stash was the simplest way not to skip. Committing in the Claude dir is
already inside the scoped exception (every push commits there).

## Decision

**A. Partial push.** `push()` commits and pushes every changed file except those a live session edited within
`session_work.LIVE_S`, and those still holding conflict markers. Held files wait for the next cycle. Only when every
changed file is held does the push defer, and a deferral is neutral, not a failure. A file with conflict markers is
still refused, now per file: the rest is pushed and the entry reads `REFUSING to commit — conflict markers ...` so
Health and the alert still see it. The commit names its files explicitly (`--pathspec-from-file`, literal pathspecs),
so a held file staged by hand isn't swept in.

**B. Commit before merge, in the synced Claude dir only.** `pull()` commits local work first (the same identity,
message and `MARVIN_COMMIT_KIND=auto-sync` as push), then runs a real `git merge --ff origin/main` (`--ff` overrides
a machine's `merge.ff=only`), so union and git's 3-way merge apply. No stash, no pop. A crash between the two steps
leaves an ordinary local commit the next run merges or pushes. Whatever stays dirty (a held file, the sync log on its
own) is autostashed only when every such file is union, whose restore can't conflict; otherwise git refuses to
overwrite it and the merge waits a cycle (neutral). The sync log alone is never committed by a pull: two machines
committing each other's log entries would trade commits forever ([[0022]]). The commit is pushed by the next push.

The engine repo and the private instance keep the stash path. They are not equally safe: on main every commit there
is code, guarded by main-only commits, `NEVER_COMMIT`, the pre-push guard and the direct-commit check, and a sweep of a
session's half-done code into an auto-sync commit at session start would change what those see; a conflict there is
a real code conflict that no union or keep-both rule may settle; and their stash stays small because push runs every
30 minutes and most work there happens in worktrees. Partial push (A) and stash containment (D) apply to them too.

**C. Keep both sides of an in-place edit, in a known set.** In the synced Claude dir, a conflict confined to
`suggestions.md` and memory notes (`projects/*/memory/*.md` except `MEMORY.md`) is resolved automatically:
- a memory note: the remote version, then `## Also from <machine> (<date>)` with this machine's lines the remote
  lacks, in their order;
- `suggestions.md`: entry by entry (`## ` headings), a three-way choice per entry (a side that left an entry alone takes
  the other's version, deletion included; both changed it, or one deleted what the other edited: both kept), then
  `skills/architecture-review/scripts/sort_suggestions.py` re-sorts it if the engine has it;
- a side that deleted the file loses to the side that edited it.

Memory notes leave the union rule (the index, `MEMORY.md`, stays union): git's 3-way merge now merges their
non-overlapping edits cleanly, and only real overlaps reach this resolver. Each resolution is logged and shown as an
`auto-resolved` item on [[0076]]'s `sync:union-review` card (same review file), open while its marked section is still
in the note, or, for `suggestions.md`, until the file is edited. A conflict in any other file, or in this set beside
any other file, aborts the merge and stops for a person exactly as before. Never in the engine repo.

**D. One alert when stuck, and leftover stashes HEAD already has are dropped.**
- A repo whose push or pull has been failing (any `_log` failure, or a crash) for 30 minutes sends one notification
  through the existing `notify()`, and one "back in sync" when every failing action has run healthy again. Episodes
  are per repo, kept in `~/.claude/logs/code-sync-stuck.json` (per machine, never synced). Neutral runs (a deferral,
  a branch checked out) neither open nor close one. The per-run failure banners are gone: they fired every cycle and
  were ignored. The push-guard refusal ([[0071]]) keeps its own banner.
- Before refusing on a leftover stash, code sync drops each stash whose every file (working tree, index and untracked
  parts) has exactly HEAD's content, and logs the stash's sha (still recoverable with `git stash apply <sha>` until
  git's gc). A stash with anything HEAD lacks is kept, the run refuses, and the stuck alert tells the owner.

The pull-only mirror ([[0069]]) is unchanged.

## Consequences

The four-day stall can't recur from a live chat, a growing stash, or an in-place edit both machines made. Cost: the
partial push adds one session-state read per push (as before) and the resolver is O(lines of the conflicted files).
Known limits: a file under a live edit for days that the remote also changes makes the Claude dir's merge wait until
the session goes quiet (`LIVE_S`); the keep-both note can grow one marked section per resolution until a person
tidies it (the card stays yellow until then); the "applies as a no-op" proof for a stash was not built, only "every
file equals HEAD", so a stash HEAD contains in a later, larger form is kept and alerted, never dropped.
