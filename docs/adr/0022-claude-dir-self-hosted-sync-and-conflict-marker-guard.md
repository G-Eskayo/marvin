# 0022 — ~/.claude sync: self-hosted git remote, and a conflict-marker propagation guard

## Status

Accepted (2026-07-12)

## Context

[[0021]] built bidirectional git sync for `~/.agents` (skill code), with a GitHub remote. The
same drift problem exists for `~/.claude` (CLAUDE.md, memory, commands, handoffs, shared
backlogs) — it was never synced by any mechanism at all, and MacBook Pro's copy had drifted
significantly (a stale `CLAUDE.md` missing 4+ session-start checks, discovered and one-time
reconciled while building 0021).

**Remote choice.** Asked directly, Gil's answer was unambiguous: "always go with the more secure
approach when it comes to sensitive information." `~/.claude` holds more sensitive content than
`~/.agents` (personal memory, `.claude.json` session/auth tokens) and had no existing remote at
all. Decision: no third-party remote. Reused `code_sync.py`'s exact push/pull/stash/merge logic
unchanged (it's just git commands, indifferent to remote type) but pointed it at a bare repo
self-hosted on Mac Mini (`~/.claude-sync.git`), reached over Tailscale/SSH — the same mechanism
git itself used before hosted services existed, no third party ever touches this content.

**Scope.** `~/.claude` mixes genuinely shared content with a large volume of machine-specific and
sensitive runtime state (93MB of raw per-session `.jsonl` transcripts, `.claude.json`, ChromaDB
binaries, per-machine identity files). A wholesale `git add -A` would have been actively
dangerous. Built a default-deny `.gitignore` (allow-list the ~15 genuinely shared paths, e.g.
`CLAUDE.md`, `lexicon.md`, `memory/`, `commands/`, `handoffs/`, explicit backlogs) rather than
trying to enumerate every dangerous file — verified exhaustively with `git add --dry-run -A` and
`git check-ignore -v` against every known-sensitive path (`.claude.json`, `machine-profile.json`,
`resume/master.md` — the standing "master resume never goes to git" rule — `history.jsonl`,
`chroma/`, and anything `cross_machine_merge.py` already owns) before ever running a real `git
add` against this repo.

**First real merge, first real divergence.** MacBook Pro's `~/.claude` had never been a git repo;
joining it required an actual merge (`--allow-unrelated-histories`), not a clean clone. This
surfaced genuine, non-trivial divergence: MacBook's `commands/*.md` were symlinks straight to each
skill's `SKILL.md` (an older convention, no `$ARGUMENTS` templating), while Mac Mini's were proper
wrapper files — resolved in Mac Mini's favor (strictly more functional, matches every command
built this session). `quarantine.md` and an early `sync-log.md` held genuinely unique, unreviewed
entries on both sides (real safety-monitor flags from 2026-07-04 through 07-06 that only existed
on MacBook) — merged by concatenation, not picked one side, since discarding either would have
lost real unreviewed content.

## Decision

`~/.claude` syncs the same way `~/.agents` does ([[0021]]), through the same `code_sync.py`,
parameterized to accept a repo path instead of hardcoding `~/.agents`. Its remote is a
self-hosted bare repo on Mac Mini over SSH, not GitHub. Its scope is allow-listed via
`.gitignore`, not inferred. Both `push`/`pull` hooks (handoff-triggered push, `SessionStart`
pull, daily cron backstop) fire for both repos from the same wiring.

**A real bug found in production, not in review**: `push()` wrote its `sync-log.md` entry *after*
committing, meaning the log's own last line was always fresh uncommitted content by the time the
next `pull()` ran — nearly every push/pull cycle produced an avoidable stash-pop conflict on
`sync-log.md` alone, purely from the log describing itself. Worse, once *any* stash-pop conflict
left literal `<<<<<<<`/`=======`/`>>>>>>>` markers sitting in a working-tree file (from either
machine, at any point), `push()` had no check for this — the *next* automated push (including the
daily 22:00 cron backstop, which kept firing unattended across two real days while other work was
happening) would `git add -A` and commit the markers as if they were legitimate file content, and
push that corruption to the shared remote. The other machine would then pull it, and if it also
auto-pushed, could commit its own broken "resolution" on top. This is exactly what happened:
`lexicon.md`, `MEMORY.md`, `improvement-queue.md`, `settings.json`, and `sync-log.md` itself all
ended up with literal conflict markers baked into *committed* history across several autonomous
cycles before being caught by a manual comprehensive `git ls-files | grep` scan — `git status`
alone did not reveal it, since committed markers register as clean relative to `HEAD`.

Fixed two ways: (1) `push()` now writes its log entry *before* committing, so it's swept into the
same commit instead of trailing as fresh dirty state; (2) `push()` now scans every changed file
for literal conflict-marker lines before committing anything, and refuses (logs the refusal,
notifies, does not commit) if any are found — verified with a deliberate test (planted a fake
marker, confirmed refusal, confirmed `HEAD` unchanged). Historical corruption was repaired by
reconstructing `sync-log.md` from every reachable version across git history on both machines
(deduplicating by timestamp+header, keeping the most complete copy of each entry, discarding
literal marker lines) rather than continuing to hand-patch individual conflicts — the hand-patch
approach had itself proven unreliable (a `git checkout --theirs` invocation silently failed to
resolve several "add/add" conflicts during the original merge, with no error output flagging the
failure, which is the root reason corrupted content ever got committed in the first place).

## Consequences

`~/.claude` now has the same durable sync mechanism `~/.agents` does, with a stronger security
posture (no third party) appropriate to more sensitive content. The conflict-marker guard is a
real, general robustness improvement to `code_sync.py` itself — it protects both repos, not just
`~/.claude`, and specifically protects against corruption propagating through *unattended*
autonomous cycles, which is the scenario where a human would be least likely to notice quickly.

Known residual gap, accepted rather than fixed: `pull()`'s own log write still happens after the
fact (only `push()` was restructured), so a small amount of harmless local-only log noise can sit
uncommitted on a machine between real pushes — self-resolving whenever real work next triggers a
push, never causes a conflict on its own since `push()` filters `sync-log.md`-only diffs out of
its "is there real work to do" check. Also unresolved: `git checkout --theirs`'s silent failure
mode on "add/add" conflicts was never root-caused (worked reliably for "distinct type" conflicts
via a different code path); future manual conflict resolution should prefer the "extract clean
content directly via `git show <verified-clean-commit>:<path>`" pattern over `--theirs`, and
always finish with a repo-wide `git ls-files | grep conflict-marker` scan rather than trusting
`git status` alone, since committed marker corruption is invisible to it.