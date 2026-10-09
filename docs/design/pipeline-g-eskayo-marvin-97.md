## North-star fit

**Reuses:** Same base as the prior attempt — PR #357's design, the existing `rebaseAndRetest`/`execWithCodeReviewDefaults` real-git-fixture test idiom already in `dashboard/test/merge.test.js`, and the already-merged #91/#96 gates (`gate` stage + `assertCodeReviewClean`) that the versioning step slots in after for free. The `merge.js`, `ticket_stages.js`/`.py`, and `activity.js` diffs already sitting uncommitted in this worktree are correct as-is and need no changes — verified by reading them against the current code, not assumed.

**Simplest sufficient approach:** no new abstractions. The only material change from the last attempt is fixing a **test-harness bug**, not the implementation. No new worktree helper, no new retry framework beyond what's already there.

**Where the regression actually came from (root-caused, not assumed):** `dashboard/test/changelog.test.js` currently has two mock-exec helpers with the wrong arity:
```js
// test 'bumps version correctly from existing VERSION file' (line ~159)
const mockGh = vi.fn(async (cmd, args) => { ...; return realExec(cmd, args) })
// test 'fails after bounded retry attempts on persistent push failure' (line ~291)
const flakyExec = vi.fn(async (cmd, args) => { ...; return realExec(cmd, args) })
```
Both drop the third `opts` argument. `applyVersionBump` always calls `exec(cmd, args, { cwd: ... })` — every one of those calls passes through these two helpers as `exec('git', [...], {cwd: repoPath|currentWorktreePath})`, but because the helper's signature is `(cmd, args)`, the `{cwd}` option is silently discarded and `realExec(cmd, args)` runs in `process.cwd()` instead. `process.cwd()` during a vitest run is inside **this real pipeline repo**, not the test's isolated bare-repo fixture. So these two tests actually execute `git worktree add --detach <tmp> origin/main`, `git config user.email/name`, `git fetch origin main`, and `git push origin HEAD:main` against the **real marvin checkout** — including a real `git fetch origin main` against GitHub, which has no reason to resolve quickly (or at all) in a sandboxed test run. That is consistent with exactly what the metrics show: 88 vitest tests passed (whatever ran before the hang), 1 failed (the hung/timed-out test), and ~1026 tests that never got a chance to run because the whole `vitest run` process stalled or was killed on a wall-clock budget. Four of the six mock-exec helpers in the same file already use the correct `(cmd, args, ...rest) => ...(cmd, args, ...rest)` forwarding pattern (matching `execWithCodeReviewDefaults` in `merge.test.js:52-61`, the file's own established convention) — only these two deviate.

**Tokens:** this is a one-file, localized fix (test harness only) plus one new defensive test, versus re-deriving or rebuilding the whole design again — the cheapest path that still eliminates the actual defect rather than retrying blind.

**Phone-OS / capability:** unchanged from before — pure infra bookkeeping, not user-facing, leaves Gil more able to trust `main` at a glance without added manual work.

**Ticket's own stated fit:** none stated in the ticket body; ADR 0028 confirms this is deliberately **one combined MARVIN-wide version** (not per-project), which is why `applyVersionBump` is correctly gated by `!ctx` (marvin's own repo only) in the existing `merge.js` diff — other projects (clarity-captions, etc.) live in separate clones and have no root `VERSION`/`CHANGELOG.md` to bump.

---

## What's already correct (verified by reading, kept unchanged)

- `dashboard/webhook-server/changelog.js` — `bumpType`, `bumpVersion`, `formatChangelogEntry`, idempotency guard (checks `prUrl` already in `CHANGELOG.md` before doing any work), and the fetch→re-read→write→commit→push retry loop (bounded at 3 attempts, retries only on `non-fast-forward` stderr).
- `dashboard/webhook-server/merge.js` — `applyVersionBump` wired in right after `stage('merging', 'passed', '')`, guarded by `if (!ctx && ticketNumber !== null)`, failure recorded via `recordFailureFn` with `stage: 'versioning'` but not `reengage()`'d (merge already happened; this is post-merge bookkeeping). This structurally satisfies AC3 (same step as #91, no separate trigger) and AC4 (anything that fails the `gate` or code-review gate throws before this line is ever reached).
- `dashboard/webhook-server/ticket_stages.js`, `lib/ticket_stages.py` — `'versioning'` added to `VALID_STAGES` alongside the pre-existing `'mutation'` entry, untouched otherwise.
- `dashboard/electron/main/activity.js` — `'versioning'` added to `TERMINAL_STAGE_ORDER` between `'merging'` and `'rebuilding'`.
- `dashboard/test/merge.test.js` — mocks `changelog.js` at module level (`vi.mock('../webhook-server/changelog.js', ...)`) so merge tests never touch real git for versioning; the one updated stage-sequence assertion (line 199) is correct, and the other marvin-repo stage-sequence test and the clarity-captions-project test (line 935, `ctx` truthy → `!ctx` false → versioning correctly never fires) don't need updating — confirmed by tracing which tests exercise the `!ctx` branch.

## Fix (the only change needed)

In `dashboard/test/changelog.test.js`, replace the two broken two-argument mock-exec closures with the file's own existing `(cmd, args, ...rest) => realExec(cmd, args, ...rest)` pattern (already used correctly by the other four helpers in this same file), so every fallthrough call keeps its `{cwd}` and genuinely only ever touches the fixture's bare-repo clone, never the real checkout.

Additionally, tighten `applyVersionBump` itself in one small way while here: drop the dead pre-loop `currentVersion`/`newVersion` computation (its result is never used — the loop always recomputes from a fresh read) and move the `git fetch origin main` to the top of each attempt, *before* `git worktree add`, so the worktree is created from the fetch that was just done rather than one fetch behind. This is a real ordering bug (currently self-heals only via the non-fast-forward retry) and removing the dead code is in scope of "simplest sufficient," not a new feature.

## Tests to write first

No "How we'll try to break it" section exists on this ticket, so the adversarial list below is built from the north-star's general "tests try to break it" principle, applied to this feature:

**Harness self-defense (new, targets this exact regression so it can't silently reappear):**
- A test that spies on the `exec` arg actually received by `realExec`/`execFileSync` for every `git` subcommand `applyVersionBump` issues (worktree add, config, fetch, add, commit, push) and asserts each one carries a `cwd` pointing at the fixture's `repoDir`/worktree path — never `undefined`, never the ambient process cwd. This is the test whose absence let the arity bug ship; it must fail against the two broken helpers and pass once they're fixed, satisfying "verify fails when code changes without a test changing."

**Bad / empty / malformed input (carried over, still valid, already written):**
- `bumpType`: undefined/empty/only-enhancement/only-breaking-change/both-present labels.
- `bumpVersion`: malformed version strings (`"1.2"`, `"1.2.3.4"`, `"a.b.c"`, trailing newline), invalid bump type.
- `formatChangelogEntry`: embedded newlines (rejected), brackets/backticks in title (preserved, not escaped away).
- Real fixture: `CHANGELOG.md` heading not followed by exactly `\n\n` → entry still inserted correctly, not silently dropped.
- Real fixture: corrupted/non-semver `VERSION` file → fails cleanly, no partial commit.

**Each dependency failing:**
- `gh issue view` rejects → `applyVersionBump` throws, `merge.js` catches it: stage sequence ends `versioning:failed`, but `mergePr`'s overall result is still `{ merged: true, ... }` — merge isn't undone by bookkeeping failing.
- `ticketNumber === null` → `applyVersionBump` never called, `versioning` stage never recorded (not recorded as a failure either).
- `git worktree add` fails → cleanup doesn't throw on an unestablished worktree, no unhandled rejection escapes.

**Repeats, concurrency, wrong order (the headline case):**
- Push rejected once (real non-fast-forward via a second local pusher, not a mocked string) then succeeds → retried, re-reads fresh `VERSION`/`CHANGELOG.md` from the new tip, not the stale first read.
- Push rejected on every attempt → bounded retry gives up cleanly, no hang.
- Two sequential `applyVersionBump` calls for two different tickets against the same fixture → second starts from the first's committed state.
- Same PR URL called twice (crash-and-retry simulation) → idempotency guard skips the second call.

**Wrong permissions / person's mistakes:**
- Push rejected with a real branch-protection-style rejection → fails within the bounded retry count, not forever.
- Both `enhancement` and `breaking-change` applied by a human → `breaking-change` wins.

**Integration ordering (AC3/AC4), in `merge.test.js`:**
- Clean gated marvin merge: stage order `..., merging:passed, versioning:started, versioning:passed, rebuilding:started, done:passed` (already present, line 199) — additionally assert `applyVersionBump` was called with the right `{ticketNumber, prUrl}`, not just that the stage strings appeared.
- A PR blocked by the `gate` or code-review gate: `applyVersionBump`/the `versioning` stage never appears at all — the direct AC4 test, must spy on the real exported `applyVersionBump` mock so a future reordering in `merge.js` is caught, not just stage-name strings.
- A clarity-captions-style project merge (`ctx` truthy): `versioning` stage never fires, VERSION/CHANGELOG untouched (already covered correctly by the existing line-935 test; add an explicit assertion that `applyVersionBump` was never called, not just that recordStageFn's array matches).

This is ready to implement directly from here — the design is sound, the only code change needed is the two-line arity fix (plus the dead-code trim) in `changelog.js`/`changelog.test.js`.