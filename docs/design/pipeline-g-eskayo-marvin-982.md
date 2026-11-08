## North-star fit

**Reused patterns:**
- `lib/box_runner.py:compare()` — already the single place a box/Mac pair's agreement is decided and appended to `~/.claude/logs/box-runs.jsonl` under its own `fcntl` lock (`compare()`, `_lines()`, `_append()`). The streak check below is computed by scanning this same append-only log inside that same lock — no second state file (unlike `lib/trust_ramp.py`'s separate `trust-ramp.json`), because the log is already the one source of truth for every compare outcome and is already atomic.
- `lib/proposals.py:add()` (ADR 0068) — the existing, owner-approved channel for "big idea, still your call" items that show up in MR Review → Proposals. This is exactly what the `box-trust` decision asked for ("propose... still your call"), so the new code calls `add()` directly instead of inventing a second notification path.
- `lib/trust_ramp.py` was read as a precedent for "N-in-a-row, reset on a bad event" but **not** reused structurally — it needs a separate state file because it tracks many independent repos/authors; box-trust only tracks one thing (the box vs. the Mac), so deriving the streak from the existing log on each `compare()` call is simpler and adds zero new storage.

**Simplest sufficient approach:** no new file, no new service, no model call. One pure function reads the tail of the log that already exists; one call to `proposals.add()` fires once per clean 20-run streak, guarded by a `propose` marker already written to the same log under the same lock `compare()` already holds — so two gates finishing at once still can't double-propose.

**Tokens:** spends a few bytes once per 20-gate streak (one local JSON file, no `gh`, no LLM call); saves Gil from manually tallying `box_runner.py show` to notice the streak.

**Phone-OS direction:** negligible — internal merge-gate tooling, not phone-reachable.

**User capability:** leaves Gil more capable, not more passive — it surfaces the evidence and drafts the ask, but the actual promotion decision stays a Proposal he acts on (ticket / snooze / dismiss), per his own "still your call" answer. This matches north star 3's "coach, don't take over" when the decision is explicitly reserved as the human's.

**Decision 1 check (`box-runs-shown`):** the chosen option text itself says "(built: no UI change without your approval)". I verified this against the branch: `merge.js`'s `makeBoxRunner().submit()` already emits the gate log line (`mac-mini-2012 runs it too (extra runner, not the verdict): <sha>`) and `box_runner.py show` already exists. **No action needed** — already satisfied by the PR as it stands.

**Decision 2 (`box-trust`)** is the only one requiring new code: track the box/Mac agreement streak and, once it reaches 20 in a row with no disagreement, open a Proposal (never auto-promote).

No Decisions section is needed in this plan or the reply — neither chosen option leaves anything for the owner to choose again; the `box-trust` mechanism's own output *is* a Proposal, which is the owner's existing "still your call" lever.

## Tests to write first (`lib/tests/test_box_runner.py`)

Mirroring the PR's own "tests try to break it" structure, against the real log file and the real `proposals.py` (not a mock, except for `add` where I need to force a failure):

1. `test_streak_counts_consecutive_agreements_most_recent_first` — N trailing `agree: True` compares → streak N.
2. `test_streak_resets_on_a_disagreement` — an `agree: False` anywhere stops the count at that point.
3. `test_streak_skips_no_result_compares_without_breaking_it` — `agree: None` rows (box offline/timeout/error) are invisible to the streak, consistent with `compare()`'s existing "not counted either way" rule — not a new rule, a reuse of the existing convention (`compare()`/`show()`).
4. `test_19_agreements_do_not_propose` — `check_trust_proposal()` returns `None`, nothing written.
5. `test_the_20th_agreement_proposes_once` — a `propose` record and a file under a tmp `proposals` root appear.
6. `test_a_streak_past_20_does_not_propose_again` — streaks of 21, 22… after the first proposal don't call `add` again.
7. `test_a_reset_then_a_new_streak_of_20_proposes_again` — disagreement zeroes it, a fresh run of 20 proposes a second time (not a one-shot lifetime flag).
8. `test_a_proposal_failure_is_logged_not_raised` — `add` raises (`ProposalError`, a locked/unwritable dir) → swallowed, an `event: propose, outcome: error` record is written, `compare()` still returns normally (never breaks the gate, same guarantee as `submit()`).
9. `test_propose_is_called_from_compare_when_a_result_lands` — integration: real `box`/`mac` events through `compare()` itself (not calling `check_trust_proposal` directly) drive the streak to 20 and a proposal file lands.
10. `test_concurrent_compares_do_not_double_propose` — two threads hit `compare()` for two different shas that each complete the 20th agreement at once, both contending the same `box-runs.lock`; assert exactly one proposal file exists afterward.
11. `test_malformed_log_lines_dont_crash_the_streak_count` — a garbage line mixed into the log (already tolerated by `_lines()`) doesn't crash `check_trust_proposal`.
12. `test_proposal_fields_fit_proposals_py_limits` — `propose_trust()`'s dict validates against `proposals._validate` (title ≤140, problem/fix/why ≤600, a real `north_star` in 1–4) so `add()` can never reject it at the one streak that matters.
13. `test_empty_log_has_zero_streak_and_proposes_nothing` — no crash on a fresh/missing log.

Misuse the ticket's bullets didn't name but north star 1 ("tests try to break it") requires: #8 (dependency failure — `proposals.add`), #10 (concurrency/repeats), #11 (malformed state), #13 (empty state). Stale state and wrong permissions are already covered by `proposals.py`'s own tests (symlink refusal, >256 KB refusal, corrupt JSON) — not re-tested here, since that's `add()`'s own contract, not `box_runner.py`'s.

## Task List

1. On `ticket/933-gate-box-runner` (fetch, create a local tracking branch): write the tests above in `lib/tests/test_box_runner.py`, confirm they fail (functions don't exist yet).
2. In `lib/box_runner.py`: add `import proposals` (after the existing `task_dispatch` import pattern), `TRUST_NEEDED = 20`, and `_agreement_streak()`, `_streak_already_proposed()`, `propose_trust()`, `check_trust_proposal()` as designed above.
3. Call `check_trust_proposal()` from inside `compare()`'s existing locked block, right after `_append(out)`, before the lock releases — no new call sites, no change to `run()`/`verdict()`/`merge.js`.
4. Run the new tests plus the full existing `test_box_runner.py` (36 tests) to confirm no regression, then the full Python suite scoped to affected tests per `lib/affected_tests.py`.
5. Commit on `ticket/933-gate-box-runner` and push (so it lands inside PR #942, not a new PR — the code it extends only exists on this branch).
6. Post a reply comment on PR #942 via `~/.agents/bin/gh` carrying `<!-- marvin:decisions-addressed -->`, stating: `box-runs-shown` needed no change (already built, cited above); `box-trust` is now implemented at commit `<sha>` — streak tracked in the existing `box-runs.jsonl`, a Proposal opens once 20 clean gates land in a row, nothing auto-promotes; no screenshots retaken (backend-only change, no UI).
7. Let issue #982 close itself per its own filer (`lib/owner_decisions.py`) once the addressed reply lands — no manual close.