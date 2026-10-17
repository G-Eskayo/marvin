## North-star fit

**Reuses:** the append-only, fail-soft JSONL log pattern already used three times in this exact directory (`failure_log.js`, `refusal_log.js`, `merge_history.js` — injectable `append`/`now`/`file`, `mkdirSync` + `appendFileSync`, swallow write errors). `gate_durations.js` is a new file (unavoidable — no existing module tracks per-step test durations; `ticket_stages.js` records one coarse "gate" event per *ticket*, not per pytest/vitest *step*, and is keyed by ticket number, so parsing it for "last 10 passing pytest runs across all PRs" would mean scanning every ticket's stage file and reconstructing a wrong-shaped signal — more code and more coupling than a purpose-built log). `execWithGroupTimeout`'s existing `(cmd, args, opts, timeoutMs)` signature is extended, not replaced, so every untouched call site (`sharedFiles`, `conflictsWithBase`, `isBehindMain`, `merge_overlap.test.js`) is byte-for-byte unaffected.

**Simplest sufficient approach:** `GATE_TIMEOUT_MS` stops being a static guess and becomes `computeGateTimeoutMs()` = sum of the per-step sized cutoffs + a small fixed overhead for git plumbing, capped at one named ceiling. That single arithmetic relationship is what makes "cutoff grows with real history" and "the overall timeout always exceeds the sum of the step cutoffs" true *by construction*, instead of two independently-tuned constants that can drift apart (which is exactly how the original bug happened: a fixed 20-min constant stopped matching a suite that grew to 9.4 min idle / 20+ min loaded). No queuing, no slot, no waiting-on-other-jobs logic is added — that's `#538`, filed separately and explicitly flagged "build in sequence, not in parallel" with this ticket.

**Tokens:** spends a small, bounded amount — one new ~80-line module, a handful of call-site edits in `merge.js`, no new runtime dependencies, no network calls (the concurrency check is a single local `pgrep`). Saves tokens/time repeatedly going forward: Gil previously burned three real Approve clicks (and a human noticing the pattern) on the same mis-sized constant; a self-sizing cutoff plus an informative refusal removes that whole class of "approve again and hope" cycles.

**More capable, not more passive:** when a timeout does fire, Gil gets the actual cause on the first read (step's duration vs. its usual, and how many other pytest runs were competing for the machine) instead of a opaque "didn't finish in time," so he can act correctly (wait vs. actually investigate) without re-deriving it himself.

One correctness gap I found while reading the code that the ticket doesn't mention: `dashboard/electron/main/merge_ops.js`'s `maxMergingMs` (45 min) is an independent client-side "give up and allow a new Approve" watchdog. Once `GATE_TIMEOUT_MS` can legitimately grow past 45 min, that watchdog would fire *while the backend gate is still validly running*, and `start()` would let a second Approve launch a concurrent merge attempt on the same PR. I'm folding a fix for that into this plan (bump its default above the new ceiling, pin the relationship with a test) rather than deferring it, since shipping this ticket without it would introduce exactly the kind of latent concurrency bug the "tests try to break it" standard exists to catch.

## Decisions

<!-- marvin:decisions -->
### ceiling: Hard ceiling for the gate's overall timeout (`GATE_TIMEOUT_CEILING_MS`)?
- [ ] A: 60 min — tightest; at 3× today's idle pytest baseline (9.4 min ≈ 28 min) this leaves little room before the suite's continued growth reproduces today's problem again
- [ ] B: 90 min — the value referenced by this ticket's own earlier (failed) automated attempt; comfortable headroom above today's 3×-median figure
- [ ] C: 120 min — most headroom, but means a stuck-but-"passing" gate could legitimately run Gil out to 2 hours before being flagged as machine trouble

## Tests (written first)

`dashboard/test/gate_durations.test.js` (new):
1. `median([])` → `null`; odd-length and even-length arrays average correctly.
2. `recentPassingDurations`: with no log file at all, returns `[]` (feeds the "no history → 20 min" case).
3. Only `passed: true` entries for the matching `step` count; `passed: false` entries and malformed/corrupt JSON lines in the file are skipped, not thrown on.
4. A different step's entries (`vitest` vs `pytest`) never pollute each other's history.
5. Only the most recent N (10) entries are used, not an arbitrary 10.
6. `recordDuration` appends a well-formed line; an append failure (simulated disk-full/read-only `append`) is swallowed — fails soft like `failure_log.js`.
7. `recordDuration` records whatever `ms` it's given, including an outlier (hours-long but passing run) — the clamping, if any, happens at sizing time, not recording time.
8. `sizedTimeoutMs('pytest', …)` with a history of nine-minute (540,000 ms) passing runs returns ≥ 27 min — acceptance criterion #1.
9. `sizedTimeoutMs` with no history returns exactly the 20-minute floor — acceptance criterion #1.
10. `sizedTimeoutMs` respects `capMs`: 3×median above the cap is clamped to the cap.
11. A single pathological outlier among otherwise-fast passing runs does not blow the median-derived cutoff past its cap (outlier resistance + hard-cap backstop together).
12. `sizedStepTimeouts`/`computeGateTimeoutMs`: with heavy history on *both* `pytest` and `vitest` (each pinned at its per-step cap), the sum of the two returned step cutoffs is strictly less than `computeGateTimeoutMs`'s result — direct test of acceptance criterion #2.
13. `computeGateTimeoutMs` never exceeds `GATE_TIMEOUT_CEILING_MS` regardless of how extreme the fed-in history is.
14. `computeGateTimeoutMs` with no history for any step returns a small, sane value (two floors + overhead), not the ceiling.
15. `computeGateTimeoutMs` generalizes to a single-step list (`['verify:repo']`) for non-marvin projects, independent of the two-step marvin case.
16. `countConcurrentPytest`: a fake exec returning a normal `pgrep -fc pytest` count is parsed correctly.
17. `countConcurrentPytest`: pgrep's "no matches" shape (non-zero exit, empty/`0` stdout surfaced via the error object) resolves to `0`, not a thrown error or `NaN`.
18. `countConcurrentPytest`: the fake exec rejects outright (`pgrep` missing on this machine) — resolves to a safe default, never throws.
19. `countConcurrentPytest`: garbage/non-numeric stdout resolves to a safe default, not `NaN`.
20. Two near-simultaneous `recordDuration` calls for the same step (simulating the Mini's actual contention — gate + pipeline + main-health all finishing around the same moment) both land intact in the log; neither line is lost or corrupted.
21. `recentPassingDurations` fails soft to `[]` when the log path is unreadable (points at a directory, or a permissions error) — the "wrong permissions" case.

`dashboard/test/merge.test.js` (extended):
22. `execWithGroupTimeout` timeout with `meta.label`/`usualMs`/a working `countConcurrent`: the rejected error's **both** `.message` and `.stderr` contain the label, usual duration, and concurrent count — acceptance criterion #3, and specifically covers the real bug in `testOutputOf()` where `.message` is dropped whenever `.stdout` is non-empty.
23. `execWithGroupTimeout` timeout with no `meta` argument (today's call sites: `sharedFiles`, `conflictsWithBase`, `isBehindMain`, raw git/gh calls): the rejection message is unchanged from current behavior — regression guard for `merge_overlap.test.js`.
24. `execWithGroupTimeout` timeout where `meta.countConcurrent` itself throws: the base timeout rejection still happens promptly and isn't swallowed or delayed — a failing dependency must never mask the real failure.
25. `execWithGroupTimeout` on a command that fails fast (non-zero exit, not a timeout): `meta.countConcurrent` is never invoked at all.
26. `_defaultRunTests`: the pytest step's exec call uses a timeoutMs sized from `pytest` history, not the flat 20-minute default, when history exists.
27. `_defaultRunTests`: the vitest step is sized independently — different cutoffs when the two steps' histories differ, proving they aren't pooled.
28. `_defaultRunTests`: both steps call `recordDuration` with `passed: true` on success and `passed: false` on failure, so a failing-but-slow run never inflates the "passing" median used for sizing — covers the "a person's mistake" (a slow, flaky PR) case.
29. `defaultGateContext`'s `runTests` for a non-marvin project is sized/recorded under its own `verify:<repo>` key; two different projects' histories never cross-contaminate.
30. GATE_INFRA refusal: when the underlying error carries the enrichment, the thrown `MergeFailure`'s message deterministically contains the usual duration and concurrent count via explicit extraction — not by lucky inclusion inside `summary.comment.slice(0, 300)`.
31. GATE_INFRA refusal: when the error carries **no** enrichment (e.g. the overall gate ceiling fired rather than a per-step timeout), the refusal message still reads cleanly — no crash, no leftover placeholder text, from a non-matching extraction.
32. End-to-end: with pytest+vitest history that sizes `computeGateTimeoutMs()` to e.g. ~50 minutes, a gate run that takes 35 minutes — which the *old* static 40-minute `GATE_TIMEOUT_MS` would still have allowed, so pick a figure that actually distinguishes old vs. new, e.g. 45 minutes — completes successfully instead of being cut off, proving the reported bug is actually fixed.

`dashboard/test/merge_ops.test.js` (extended):
33. `maxMergingMs`'s default is strictly greater than `GATE_TIMEOUT_CEILING_MS` — pins the two constants together so a future change to either can't silently reopen the "watchdog fires while gate is still legitimately running → duplicate Approve" bug.

All of the above use fake clocks (injected `now`), fake `exec`/`append`/`countConcurrent` functions, and tiny real-ms values for the existing real-timer-based `execWithGroupTimeout` tests (matching that file's existing convention) — nothing invokes the real pytest/vitest suite.

## Task List

1. Add `dashboard/webhook-server/gate_durations.js`: `DEFAULT_TEST_TIMEOUT_MS` (moved from `merge.js`, unchanged value/meaning), `GATE_TIMEOUT_CEILING_MS` (per the Decision), `GATE_OVERHEAD_MS` (5 min, documented as a generous fixed allowance for git fetch/worktree/rebase/push), `recordDuration`, `recentPassingDurations`, `median`, `sizedTimeoutMs`, `sizedStepTimeouts`, `computeGateTimeoutMs`, `countConcurrentPytest`. Default log path `~/.claude/logs/gate-run-durations.jsonl`, following the `failure_log.js`/`refusal_log.js` fail-soft JSONL convention exactly (injectable `append`/`now`/`file`/`exec`).
2. Write `dashboard/test/gate_durations.test.js` (tests-first items 1–21).
3. In `merge.js`: import the above from `gate_durations.js`; remove the local `DEFAULT_TEST_TIMEOUT_MS` and the static `export const GATE_TIMEOUT_MS`.
4. Extend `execWithGroupTimeout` with an optional 5th `meta` param (`{ label, usualMs, countConcurrent }`, all optional). On timeout, when `meta?.label` is set, best-effort append a single-line, regex-extractable enrichment to **both** `error.message` and `error.stderr` inside a try/catch (a `countConcurrent` failure must never block or delay the base rejection). No parameter, no behavior change, for every existing call site.
5. Update `_defaultRunTests(cwd, exec)`: compute `const { pytest, vitest } = sizedStepTimeouts(['pytest', 'vitest'])` once; call the pytest exec with `timeoutMs = pytest` and `meta = { label: 'pytest', usualMs: median(recentPassingDurations('pytest')), countConcurrent: countConcurrentPytest }`; likewise for vitest. Wrap each call to `recordDuration({ step, ms: elapsed, passed })` on both the success and the catch-and-rethrow paths (`npm install` stays unsized/unrecorded — it isn't a test step).
6. Apply the same timing/sizing/recording wrapper to `defaultGateContext`'s `runTests`, keyed `verify:${repo}` (a single-element `sizedStepTimeouts([\`verify:${repo}\`])`).
7. In `mergePrUnqueued`: stop defaulting `gateTimeoutMs` in the top-level `deps` destructure; resolve it lazily, right before the `withGateTimeout(...)` call (where `ctx`/`repo` are known), as `deps.gateTimeoutMs ?? computeGateTimeoutMs(ctx ? [\`verify:${repo}\`] : ['pytest', 'vitest'])`, so the same per-step sizes used for the actual exec calls are what the overall ceiling is built from.
8. In the GATE_INFRA branch (`merge.js` ~516–525): extract the enrichment marker from `result.reason` (the full, unsliced text) via regex and splice the step's usual duration + concurrent-pytest count explicitly into the refusal's `message`, instead of relying on `summary.comment.slice(0, 300)` to happen to contain it. Handle the no-match case cleanly.
9. In `dashboard/electron/main/merge_ops.js`: bump `maxMergingMs`'s default so it's always comfortably above `GATE_TIMEOUT_CEILING_MS` (import the constant rather than hardcoding a number that can drift).
10. Add the `merge.test.js` tests (items 22–32) and the `merge_ops.test.js` test (item 33).
11. Update `CONTEXT.md`'s "Per-command timeout + process-group kill" / "Hardening after the red-main incident" sections (~lines 1134–1146) to describe the sized, history-driven cutoff, the enriched GATE_INFRA message, and the derived `GATE_TIMEOUT_MS` — no new ADR; this is a parameterization of already-documented behavior, not a new architectural decision.
12. Run the full `dashboard` vitest suite and `pytest -q` to confirm no regressions, before calling this done.