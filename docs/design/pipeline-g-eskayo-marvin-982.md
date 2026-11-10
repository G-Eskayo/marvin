## North-star fit

**Reuses:** `lib/proposals.py`'s `add()` (ADR 0068) — the existing, single-owner "propose a big idea, owner decides" store that already backs the Workshop **Proposals** pile (Make a ticket / Snooze / Dismiss). `lib/marvin_session.py` already shows the convention for a caller module: a monkeypatchable `PROPOSALS_ROOT = Path.home() / ".claude" / "proposals"` constant and a plain `proposals.add(PROPOSALS_ROOT, {...})` call (`lib/marvin_session.py:49,224`). `lib/inbox.py` (ADR 0083) is the newer unification point, but per that ADR "the piles move into it one at a time; suggestions and the improvement queue go first" — commits `48e878e8`/`6846682a` on `ticket/1123-4-inbox` confirm only suggestions/improvement-queue have moved so far, not Proposals. So `lib/proposals.py` is still the current, correct target — not `lib/inbox.py`.

I also reuse `lib/box_runner.py`'s own `compare()` as the single choke point: it already writes one `"compare"` record per gate with `agree: true/false/null` and already serializes concurrent writers under `box-runs.lock`. Adding the 20-in-a-row check there (instead of a new poller or a separate streak-state file like `lib/trust_ramp.py`'s) means no new state file, no new lock, and no new scheduled job — the streak is derived by scanning the log that already exists, the same way `compare()` itself already scans `_lines()`. This matches "trigger-based, never polling" and "catch repeated mistakes: fix at the root, at the choke point."

**Simplest sufficient approach:** a pure function `agreement_streak()` over existing `compare` records (skip `agree: null`, stop at the first `agree: false`, scanning from the newest), plus one small wrapper that proposes once via `proposals.add()` and marks it done with one more log line (`{"event": "trust-proposed"}`) so a restart never re-derives state from memory — durability comes for free from the log already being the source of truth.

**Tokens:** spends a little (one new function, ~15 lines, plus tests) to avoid a recurring cost: without it, "propose after 20 clean gates" relies on Gil remembering to run `box_runner.py show` and count by hand — every week, forever. One small one-time build beats indefinite manual polling.

**Phone-OS direction:** indirect — it's gate-automation plumbing, not UI, but it's what lets the third machine (`mac-mini-2012`, the first non-macOS device) earn trust without a human watchdog, which is the pattern any future device will need.

**User capability:** leaves Gil **more capable, not more passive** — it doesn't promote the box itself (that stays "still your call," per the chosen option), it only removes the bookkeeping of noticing *when* to ask. The actual judgment (does 20 agreements justify a required runner) stays his.

**Re-reading the PR before acting:** the Decisions comment is from 2026-10-30T18:08:13Z; the PR's last two commits (2026-10-30T23:25:45Z, 2026-11-03T17:41:19Z) are both merge commits resolving `merge.js` conflicts from rebasing onto the other stacked tickets — no change to `lib/box_runner.py`'s content or the Decisions comment itself. Nothing contradicts the chosen options.

**What's actually left to do, per option:**
- **`box-runs-shown`** (chosen: "Gate log line + `box_runner.py show` only, for now... built") — already true. `show()` exists (`lib/box_runner.py`, confirmed by reading it) and is tested (`test_show_puts_disagreements_first`). Nothing to build; the reply just confirms this.
- **`box-trust`** (chosen: "After 20 gates in a row with no disagreement, propose making it a second required runner") — not built yet. This is the one piece of real work below.

## Decisions

None needed. Both questions on PR #942 are already answered by the owner, nothing in the PR contradicts them, and the one implementation choice I had to make myself (what happens if the streak later resets and climbs back to 20 after a proposal already exists) is a safe, reversible default — propose **once ever**, not once per 20-streak — stated plainly below rather than guessed silently or re-asked.

## Tests to write FIRST

In `lib/tests/test_box_runner.py`, new section after the existing "box vs Mac" tests, reusing the `log` fixture and `box_line`/`verdict` helpers already there:

1. `test_agreement_streak_counts_consecutive_trues_from_the_end` — rows `[T,T,F,T,T,T]` → streak `3`.
2. `test_agreement_streak_skips_none_without_breaking_it` — a `None` (no result) in the middle of a run of trues doesn't end the streak or count toward it (matches the PR's own documented "not counted either way").
3. `test_agreement_streak_is_zero_on_an_empty_log` — empty/missing log (empty input case).
4. `test_a_corrupt_log_line_is_skipped_when_counting_the_streak` — a garbled JSON line in `box-runs.jsonl` is ignored, not crashed on (malformed input; reuses `_lines()`'s existing skip behavior).
5. `test_19_clean_gates_do_not_propose` — build 19 agreeing compare pairs; assert no file under the proposals root and no `"trust-proposed"` log line.
6. `test_the_20th_clean_gate_proposes_once` — the 20th agreeing pair creates exactly one proposal (title/problem/fix/why/north_star all present and valid per `proposals._validate`) and exactly one `"trust-proposed"` log line.
7. `test_the_21st_clean_gate_does_not_propose_again` — repeats: once proposed, further agreements don't create a second file or a second log line.
8. `test_a_disagreement_then_a_fresh_streak_of_20_does_not_re_propose_once_already_proposed` — a person's/owner's expectation check: proposing is one-shot forever, not per-streak, documented as the deliberate default above.
9. `test_proposals_add_failing_does_not_crash_compare_and_is_retried_next_time` (dependency failing) — monkeypatch `proposals.add` to raise; the 20th compare still returns its normal dict, logs an error `"trust-proposed"` line, creates no proposal file; a subsequent agreeing compare with `proposals.add` working retries and succeeds.
10. `test_an_unwritable_proposals_root_does_not_crash_compare` (wrong permissions) — `PROPOSALS_ROOT` pointed at a read-only directory; same non-crashing, retry-on-next-call behavior as #9.
11. `test_a_stale_trust_proposed_marker_from_a_restart_still_suppresses_a_new_proposal` (stale state) — pre-seed the log with a successful `"trust-proposed"` line plus ≥20 agreeing compares (simulating a process restart reading durable state fresh) and assert no new proposal is made.
12. `test_two_gates_crossing_the_threshold_at_once_propose_only_once` (concurrency) — two threads each driving the 20th-crossing `compare()` call for different shas; assert exactly one proposal file and one successful `"trust-proposed"` line (relies on the existing `box-runs.lock` serialization in `compare()`).

No new tests needed for `box-runs-shown` (already covered by `test_show_puts_disagreements_first`).

## Task List

1. In `lib/box_runner.py`: add `import proposals` (lazily, inside the new function, so a proposals-module problem can never break the gate's `submit`/`run`/`verdict` path — same defensive style already used in `submit()`).
2. Add `PROPOSALS_ROOT = Path.home() / ".claude" / "proposals"` and `TRUST_STREAK = 20` constants, following `lib/marvin_session.py`'s monkeypatchable-constant convention.
3. Add `agreement_streak(rows: list[dict] | None = None) -> int`: a pure function over `compare` records (defaults to reading `_lines()` itself), scanning newest→oldest, skipping `agree is None`, stopping at the first `agree is False`.
4. Add `_maybe_propose_trust() -> None`: checks for an existing successful `"trust-proposed"` log line (skip if found), computes `agreement_streak()`, returns early under `TRUST_STREAK`; otherwise calls `proposals.add(PROPOSALS_ROOT, {...})` with the drafted title/problem/fix/why/north_star=2/area/size/source, wrapped in `try/except Exception` that logs an error `"trust-proposed"` line on failure (so it retries later) and a plain success line on success.
5. Call `_maybe_propose_trust()` from inside `compare()`'s existing locked block, right after `_append(out)`, only when a new compare record was actually written (not on the "already compared"/`None` early-returns).
6. Write the 12 tests above in `lib/tests/test_box_runner.py` (red first), then make them pass with steps 1–5.
7. Run the full `lib/box_runner.py`-related suite (`pytest -q lib/tests/test_box_runner.py`) plus the full suite per the "full suites before a hand-merge" rule if this is hand-verified rather than going through the gate.
8. Post a reply comment on PR #942 carrying `<!-- marvin:decisions-addressed -->` that: confirms `box-runs-shown` was already built (cites `show()`); states what changed for `box-trust` (the new streak check and commit SHA); says screenshots were not retaken because there is no UI change (the Proposal, when it eventually fires, surfaces through the existing Workshop Proposals card, not a new screen); and notes that the PR's post-decision commits were re-checked and don't conflict with either chosen option.
9. Commit on branch `ticket/933-gate-box-runner` (no new PR needed — this branch *is* PR #942's branch).