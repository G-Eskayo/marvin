## North-star fit

**Reuses:** the existing fail-soft injectable-JSONL logging convention (`failure_log.js`/`refusal_log.js`: `append`/`now`/`file` params, `~/.claude/logs/*.jsonl`), the existing async `exec(cmd, args, opts)` abstraction already used everywhere in `merge.js` (no new sync `execSync`/`execFileSync` path), and the existing `GATE_INFRA` regex/`summarizeGateFailure` pipeline unchanged. Nothing new is introduced where an existing primitive already does the job.

**Simplest sufficient approach:** one new small module (`gate_durations.js`) holding pure, fakeable functions (median/sizing/logging/concurrency-count), wired into the two places that already run tests (`_defaultRunTests`, `defaultGateContext.runTests`) via one extra optional parameter on `execWithGroupTimeout`. No new service, no polling, no new file format.

**Ticket's stated fit doesn't fully hold up:** the ticket says "the stage files already have timestamps," implying durations could be read off `ticket_stages.js`. I read it (`dashboard/webhook-server/ticket_stages.js`): it records one `gate` stage per *ticket*, started/passed/failed, with no pytest/vitest split, and it's keyed by ticket (many tickets have none, e.g. manually-authored PRs). It cannot cheaply answer "the last 10 passing **pytest** runs across all gates on this machine." A small dedicated log (same shape as the two logs already in this directory) is the correct level, not a stretch of an existing file — this is a correction, not a reuse opportunity missed.

**Tokens:** spent on one new ~70-line module + tests; saved by not touching the Python side, CI, or the pipeline's own timeout machinery at all — this is a JS-only, webhook-server-local fix.

**User impact:** directly fixes a real incident (3 good merges refused under load on 2026-10-15) and makes the next one self-diagnosing (the refusal will say *why*, instead of Gil having to dig through ticket-stage timestamps by hand as happened on #444). More capable, not more passive — it removes a false "your code is broken" signal, it doesn't remove a judgment call from him.

## What's already there vs. what's missing

Confirmed by reading the worktree: `gate_durations.js` / `dashboard/test/gate_durations.test.js` do **not** exist (`wc -l` fails on both) and `git status` is clean — no leftover diff from a previous attempt in *this* worktree to discard. This is a clean build from the current `merge.js` (610 lines, read in full), `merge_ops.js`, `failure_log.js`, `refusal_log.js`, `ticket_stages.js`, `failure.js` (relevant sections), `merge.test.js` (all call sites of `execWithGroupTimeout`, `_defaultRunTests`, `gateTimeoutMs`), and `CONTEXT.md`'s two relevant sections.

## Tests to write first

No "How we'll try to break it" section exists on this ticket (confirmed via `gh issue view 536 --json body`) — all of the below are derived from the acceptance criteria plus the standard adversarial checklist, since the section is simply absent rather than incomplete.

**`gate_durations.test.js`** (new):
1. No history → `sizedTimeoutMs` returns `DEFAULT_TEST_TIMEOUT_MS` (20 min). (AC1)
2. History median 9 min → returns exactly 27 min (`3×9`), satisfying "at least 27 min". (AC1)
3. Only the last 10 passing runs count — an 11th+ older run falling out of the window must not affect the median.
4. A `passed:false` entry (a timeout or a real failure) is excluded from "usual" duration — noise from bad runs must not widen future tolerance.
5. One corrupted entry claiming e.g. `ms: 10_000_000_000` still yields a `sizedTimeoutMs` ≤ its `capMs` — huge/malformed input never produces an unbounded cutoff.
6. `median()` unit cases: empty array, odd length, even length, non-numeric/NaN entries filtered.
7. `recordDuration` is fail-soft: `append` throwing (disk full/permission denied) must not throw or block the caller.
8. `recordDuration` → `recentPassingDurations` round-trips through a **real temp file**, not a mock — catches a JSONL shape mismatch a mock would hide.
9. `recentPassingDurations` skips a malformed/truncated JSONL line (a concurrent writer caught mid-write) instead of crashing.
10. `recentPassingDurations` on a missing/empty file returns `[]` (no history yet).
11. `sizedStepTimeouts` for 1, 2 and 5 steps: sum of all step cutoffs + `GATE_OVERHEAD_MS` is always `≤ capMs`, by construction. (AC2)
12. `computeGateTimeoutMs(['pytest','vitest'])` with extreme historical durations still stays `≤ GATE_TIMEOUT_CEILING_MS` — unbounded growth under sustained load is a defect, not just a style nit.
13. `computeGateTimeoutMs` honors an explicit `capMs` override.
14. `countConcurrentPytest`: `pgrep` finds 3 → returns `3`.
15. `countConcurrentPytest`: `pgrep -fc` exits 1 with stdout `"0"` (its real "no match" behavior) → returns `0`, not `null`/thrown.
16. `countConcurrentPytest`: exec throws with unparseable stdout (`pgrep: command not found`) → returns `null` ("unknown"), never throws.
17. `recordDuration` called with a missing/wrong-typed field (a person's mistake) fails soft and does not write a line another reader can't parse.
18. Two `recordDuration` calls back-to-back (simulating two concurrent gates) both land as separate valid lines — no lost/clobbered write.
19. `GATE_TIMEOUT_CEILING_MS`/`GATE_OVERHEAD_MS` are exported with their documented values (drift guard).

**`merge.test.js`** (extend):
20. `execWithGroupTimeout` with no `meta` — timeout message byte-identical to today (regression guard for every non-gate caller, e.g. `sharedFiles`, `conflictsWithBase`, `isBehindMain`).
21. `meta = { label:'pytest', usualMs, countConcurrent }` — on timeout, both `.message` and `.stderr` carry `[usual: 9 min; concurrent pytest: 2]`.
22. `meta.usualMs = null` (no history) → enrichment says "no history yet", not "NaN min".
23. `meta.countConcurrent` **never resolves** → rejection still happens within a small bounded extra delay — a hung dependency must never block the base timeout.
24. `meta.countConcurrent` throws/rejects → enrichment falls back to "concurrent pytest: unknown", rejection still happens.
25. `_defaultRunTests` sizes the pytest and vitest exec calls from `sizedStepTimeouts(['pytest','vitest'])` (mocked `gate_durations.js`).
26. `_defaultRunTests` records a passing duration for each of pytest and vitest on success.
27. `_defaultRunTests` records a **failing** duration for whichever step's exec rejects, and still rethrows the original error unchanged (existing failure-text parsing must not regress).
28. `npm install` is never sized or recorded (it isn't a test step) — scope-boundary guard.
29. `defaultGateContext.runTests` wraps its single `verify:${repo}` call with the same timing/sizing/recording and its own `meta.label`.
30. Two different projects' `verify:${repo}` histories never mix (repo-keyed, not globally pooled).
31. `mergePrUnqueued` resolves `gateTimeoutMs` via `computeGateTimeoutMs(['pytest','vitest'])` for marvin's own gate when `deps.gateTimeoutMs` is omitted.
32. `mergePrUnqueued` resolves it via `computeGateTimeoutMs([\`verify:${repo}\`])` for another project when omitted.
33. The two **existing** tests passing an explicit `deps.gateTimeoutMs` (30, 5000) still pass unmodified — explicit override always wins, never recomputed.
34. GATE_INFRA refusal message includes step duration, usual duration, and concurrent count when the enrichment marker is present in `result.reason`. (AC3)
35. GATE_INFRA refusal falls back to today's `slice(0,300)` behavior when no marker is present (covers the existing fake-`rebaseAndRetestFn` test at line 951).
36. The marker extraction only fires for `GATE_INFRA`, not `GATE_TESTS_FAILED` — a failing test whose own output coincidentally contains `[usual: ...]`-shaped text must not be misread as the enrichment.
37. A huge/garbage `result.reason` doesn't crash or blow up the regex extraction (bounded, single-line pattern; no ReDoS).

**`merge_ops.test.js`** (extend):
38. `createMergeOps()`'s default `maxMergingMs` is strictly greater than the imported `GATE_TIMEOUT_CEILING_MS` — the UI must never say "gave up" while a legitimately-sized gate is still inside its own ceiling.

All of the above use fake clocks (`now`/`sleep` injection, already the file's convention) and fake `exec`; nothing here spawns a real `pytest`/`vitest`/`pgrep`. (AC4) Test 8 is the one exception by design — it hits the real filesystem on purpose, per "test against the real collaborator where a mock could hide its rules" (a JSONL append/read mismatch is exactly the kind of thing a mock hides).

## Decisions

<!-- marvin:decisions -->
### gate_ceiling: What should the hard ceiling on the overall gate timeout (`GATE_TIMEOUT_CEILING_MS`) be?
- [ ] A: 60 minutes
- [ ] B: 90 minutes
- [ ] C: 120 minutes

### pipeline_wait: Build the optional "wait up to N minutes for a same-machine pipeline verification run to finish before starting" feature? (optional)
- [ ] Build it now
- [ ] Skip for this ticket (my read: the sizing fix alone already resolves the reported incident — cutoffs grow with real load instead of staying fixed at 20 min — and this feature needs a new cross-process "is a verification run active on this machine right now" signal that doesn't exist yet; better scoped as its own ticket once #538's scheduling changes land)

## Task List

1. Add `dashboard/webhook-server/gate_durations.js`: `DEFAULT_TEST_TIMEOUT_MS` (moved from `merge.js`), `GATE_TIMEOUT_CEILING_MS`, `GATE_OVERHEAD_MS` (5 min), `recordDuration`, `recentPassingDurations`, `median`, `sizedTimeoutMs`, `sizedStepTimeouts`, `computeGateTimeoutMs`, `countConcurrentPytest`. Default log path `~/.claude/logs/gate-run-durations.jsonl`, fail-soft, injectable `append`/`now`/`file`/`read`, matching `failure_log.js`'s convention exactly.
2. Write `dashboard/test/gate_durations.test.js` covering tests-first items 1–19.
3. In `merge.js`: import the above from `gate_durations.js`; drop the local `DEFAULT_TEST_TIMEOUT_MS` and the static `export const GATE_TIMEOUT_MS`.
4. Extend `execWithGroupTimeout` with an optional 5th `meta` param (`{ label, usualMs, countConcurrent }`). On timeout, when `meta?.label` is set: race `meta.countConcurrent()` against a short internal bound so it can never delay the base rejection; append a single-line `[usual: N min; concurrent pytest: M]` (or "no history yet" / "unknown" for missing data) to both `error.message` and `error.stderr` inside a try/catch. No parameter → byte-identical behavior to today.
5. Update `_defaultRunTests`: compute `sizedStepTimeouts(['pytest','vitest'])` once; pass the sized timeout + `meta` (`label`, `usualMs` from `median(recentPassingDurations(step))`, `countConcurrent`) into each exec call; wrap each with start/end timing and `recordDuration` on both the success and the catch-and-rethrow paths. `npm install` stays unsized/unrecorded.
6. Apply the same wrapper to `defaultGateContext`'s `runTests`, keyed `verify:${repo}`.
7. In `mergePrUnqueued`: stop defaulting `gateTimeoutMs` at the top-level `deps` destructure; resolve it as `deps.gateTimeoutMs ?? computeGateTimeoutMs(ctx ? [\`verify:${repo}\`] : ['pytest','vitest'])` right before the `withGateTimeout(...)` call, where `ctx`/`repo` are known.
8. In the `GATE_INFRA` branch (`merge.js:468-476`): extract the `[usual: ...; concurrent pytest: ...]` marker from the full, unsliced `result.reason` via a bounded regex and splice it into the refusal's `message`, only when `summary.code === 'GATE_INFRA'`; fall back to today's `slice(0,300)` when no marker matches.
9. In `dashboard/electron/main/merge_ops.js`: import `GATE_TIMEOUT_CEILING_MS` from `gate_durations.js` and set `maxMergingMs`'s default comfortably above it, instead of a hardcoded `45 * 60_000`.
10. Add the `merge.test.js` tests from items 20–37, and the `merge_ops.test.js` test from item 38.
11. Update `CONTEXT.md`'s "Per-command timeout + process-group kill" and "Hardening after the red-main incident" sections (~lines 1134–1146) to describe the sized, history-driven per-step cutoff, the enriched `GATE_INFRA` message, and the derived (ceiling-capped) `GATE_TIMEOUT_MS`/`maxMergingMs` relationship — a parameterization of already-documented behavior, no new ADR needed.
12. Run the full `dashboard` vitest suite and `pytest -q` to confirm no regressions before calling this done.