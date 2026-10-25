# ADR 0065: Code-sync waits on a live-edit lease before pushing

**Status:** Accepted (2026-10-09, ADR + implementation). Resolves ticket #337 (half-finished auto-commit after session crash).

## Context

On 2026-10-08, a session crashed mid-edit with three files partially modified. The next cron-triggered `code_sync.py push()` saw dirty files and committed+pushed them as-is — a half-finished, non-functional state. The owner noticed this when the auto-sync commit (5c7cf79) appeared in the log, and the commit happened to pass all tests, making it impossible to catch via a test gate. The incident represents a real risk any time a session's work is interrupted (crash, network drop, human interruption) before a handoff's own commit-on-demand finishes.

The ticket offered three options:
1. Route all interactive edits through `EnterWorktree`/`ExitWorktree` hooks for one atomic commit per session.
2. Check for live sessions actively editing the same files and defer the push until they're done.
3. Gate auto-commits on passing tests (but the actual half-finished commit in this incident passed all 1177 tests).

Option 3 is directly contradicted by the incident's own evidence; option 1 is architecturally sound but is a larger, separate ticket (needs convention-enforcement across every interactive session, not just code-sync).

## Decision

**Option 2: edit lease via existing session-work infrastructure.** Before `code_sync.push()` commits, it checks whether any live sessions (active within the last 45 minutes per `session_work.py`'s existing tracking) have recorded recent edits to the same files that are dirty in the target repo's working tree. If a match is found, `push()` defers (logs a human-readable reason, returns early, no commit).

**Why reuse session_work.py's live-session list:**
- Already built (ADR 0062), already tested, already updated on every `PostToolUse` edit regardless of launch kind.
- Already proven to detect collisions correctly (the `pre_edit()` pause mechanism uses the same logic).
- Using a new lock file would require a separate staleness constant, kept in sync, version-checked, and audited in future handoffs.
- The existing 45-minute "live" window already encodes the time-to-intervention we want ("if nobody touched it in 45 min, it's safe to commit").

**Scope: files actually dirty in this repo, not repo-id alone.** The check is keyed by repo-id + relpath (the same `file_key()` that `session_work.py` uses), but limited to files that are actually dirty in `repo`'s own `git status`. This prevents a false match where a pipeline worktree of the same repo edits a same-named file in its own tree and holds the main checkout's sync hostage. A worktree's edits never show up in another worktree's `git status`, so scoping the check to actually-dirty files is what catches the real risk (parallel work in the same checkout) without false-blocking unrelated parallel worktrees.

**Call site:** right after the existing "nothing real to commit" check (which early-returns if `real_changes` is empty), before the conflict-marker guard. No `notify()` call — this is an expected, frequent, self-resolving outcome (lease expires in ≤45 min with nobody doing anything), not a conflict; reserving notifications for genuine failures.

**Pull is unchanged.** It already stashes-and-pops rather than discarding work, and since `push()` now never ships half-finished edits, there is nothing new for `pull()` to protect against on the other machine.

## Accepted Trade-off (documented, not hidden)

Because the lease match is keyed by relpath + repo-id (not by physical worktree path), a coincidentally stale-dirty file in `~/.agents`'s own working tree that happens to share a path with something a pipeline worktree touched in the last 45 min could cause one extra deferred cycle. The deferrals never corrupt or discard anything — they simply delay a push by up to 45 minutes, and self-clear. The risk is narrow enough, and fails in the safe direction (delay, not data loss), that engineering further complexity is not warranted. If this trade-off materializes as a real friction point in practice, it will be visible in push-deferral metrics and can be addressed in a future ADR.

## Consequences

- Sessions are strictly more free to work in `~/.agents` or `~/.claude` without remembering to pause automation — the system now protects in-progress work instead of requiring manual coordination.
- Behavior is unchanged when no sessions are actively editing (the lease is None/empty, push proceeds normally).
- A session crash or network drop is no longer a vector for half-finished commits — the lease holds the push until the session's last-recorded edit goes stale, at which point the commit is defensibly complete or abandoned.
- Tests verify the lease check across all documented misuse cases: stale leases, concurrent sessions, missing/corrupt state files, unrelated files, and sibling worktrees.
