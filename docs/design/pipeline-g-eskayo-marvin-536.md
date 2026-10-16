## North-star fit

**Reuses:** the existing `execWithGroupTimeout`/`withGateTimeout` cutoff machinery and the existing `GATE_INFRA` regex/classification in `failure.js` (no regex change, same design note as #190 in `CONTEXT.md:1138`). The fail-soft, injectable-`append`/`now`/`file` append-only JSONL pattern is reused verbatim from `failure_log.js`/`refusal_log.js` (both already write forever to `~/.claude/logs/pipeline-failures.jsonl` with no rotation) for the new `gate-run-durations.jsonl` — no new rotation infrastructure invented, since none exists elsewhere in this codebase either. `defaultGateContext`'s existing per-project `runTests` wrapper is extended, not duplicated, so other-project gates get the same sizing/enrichment for free.

**Simplest sufficient approach:** one new small pure-function module (`gate_durations.js`) plus three mechanical edits to `merge.js`: an optional 5th `meta` param on an existing helper, one constant replaced by a function of already-known values, and an existing-but-currently-truncated marker spliced into an existing refusal message. The ticket's own "optional" scheduling bullet (wait for a same-machine pipeline run before starting) is explicitly skipped: issue comment #1 on this ticket says #538 ("give it a suite slot, retry timeouts itself...") already owns that scheduling side and the two must be built in sequence, not in parallel — building it here would duplicate #538's work.

**Tokens:** spent on one new ~100-line module and ~30 adversarial unit tests (ADR 0063) — justified because a wrong cutoff either blocks good work (this incident: #444 refused three times for a machine problem) or never bounds a hung gate (the #147 incident already in `CONTEXT.md:1140-1147`). Saved by *not* building a new log store, a new rotation mechanism, or a parallel path for non-marvin projects.

**Phone-OS fit:** indirect — this is merge-gate reliability plumbing, tied only to north star 2's "nothing may break silently" precondition.

**More capable, not more passive:** yes. It removes a concrete, just-experienced frustration (Gil manually re-approving three times, unsure if it was his code or the Mini being busy) by making the refusal say outright "it's load" — information, not a decision taken away from him.

---

**Note on ticket structure:** issue #536 has no "How we'll try to break it" or "Attacks" section — only Problem / What to build / Acceptance criteria. The tests-first list below is therefore built from the ACs plus ADR 0063's general misuse checklist (bad/empty/huge/malformed input, dependency failure, repeats/concurrency, wrong permissions, stale state, a person's mistakes), as instructed for that gap.

**Failed-attempt feedback incorporated:** the one prior attempt (comment #2) timed out mid-run (infra, not a design flaw) but its embedded plan named two concrete defects in the discarded diff that must not recur here: (1) a `countConcurrentPytest(execSync)` call-site signature bug — `execSync`'s signature is `(command, options)`, not `execFileSync`'s `(file, args, options)`; (2) an untested path where the enrichment marker got silently dropped because the refusal message was built from `summary.comment.slice(0, 300)` rather than the full `result.reason`. Both are called out explicitly below (tests #15, #31) and designed around, not just avoided by luck.

## Tests first

1. `recordDuration` appends one JSONL line `{t, suite, ms, passed}` via injectable `append`/`now`/`file` (mirrors `failure_log.js`'s `recordFailure` contract).
2. `recordDuration` swallows a throwing `append` (fail-soft) and never throws.
3. `recentPassingDurations` returns `[]` when the log file doesn't exist.
4. `recentPassingDurations` returns `[]` on an empty file.
5. `recentPassingDurations` filters by `suite` label — `pytest` and `vitest` entries in the same file never mix.
6. `recentPassingDurations` excludes `passed: false` entries even when they're the most recent.
7. `recentPassingDurations` returns only the last 10 passing entries when more than 10 exist (most recent, not oldest).
8. `recentPassingDurations` skips a malformed/corrupt JSON line without throwing or dropping the rest of the file.
9. `recentPassingDurations` tolerates a trailing blank line and CRLF line endings (a person hand-editing the file).
10. `median([])` returns `null` (signals "no history").
11. `median` of an odd-length array returns the middle value; even-length returns the average of the two middle values.
12. `sizedTimeoutMs` returns `DEFAULT_TEST_TIMEOUT_MS` (20 min) with no history — AC1 case 2.
13. `sizedTimeoutMs` returns ≥ 27 min given a history of passing 9-minute runs — AC1 case 1 (the ticket's literal numbers).
14. `sizedTimeoutMs` never drops below the 20-min floor even when the history's median is small (e.g. 2-minute runs).
15. `sizedTimeoutMs` caps its result at `capMs` even when `3 × median` would exceed it.
16. `sizedTimeoutMs` discards non-numeric/negative/`NaN`/`Infinity` entries in the history rather than letting one poison the median — malformed-input case.
17. `countConcurrentPytest(exec)` counts matching lines from a fake exec shaped like `execFileSync`'s `(file, args, opts)` — explicit regression guard for the discarded attempt's `execSync`/`execFileSync` signature bug.
18. `countConcurrentPytest(exec)` returns `0`, not a throw, when the fake exec throws pgrep's real "no process matched" (exit 1) error.
19. `countConcurrentPytest(exec)` returns `0` (fail-soft) when exec throws an unrelated error (pgrep missing from PATH).
20. `computeGateTimeoutMs([...])` returns at least the sum of the given step cutoffs plus overhead margin.
21. `computeGateTimeoutMs([...])` caps its result at the hard ceiling constant even when the summed cutoffs exceed it — AC2.
22. `computeGateTimeoutMs([])` still returns a sane floor (empty-input case).
23. Two concurrent `recordDuration` calls (two machines finishing near-simultaneously) each produce one intact, separately-parseable line — concurrency case.
24. `recordDuration`/`recentPassingDurations` degrade to no-throw/empty-result when the log path is unwritable/unreadable (`EACCES`) — wrong-permissions case.
25. `execWithGroupTimeout`'s timeout branch, given `meta.label` plus fake `median`/`countConcurrent`, appends a duration/usual/concurrent-count marker to both the rejected error's `.message` and `.stderr`.
26. `execWithGroupTimeout`'s timeout branch with **no** `meta` (every existing call site — `sharedFiles`, `conflictsWithBase`, `merge_overlap.test.js`) produces the exact same error shape as today — explicit non-regression test.
27. `execWithGroupTimeout`'s enrichment lookup itself throwing (fake `median`/`countConcurrent` that throw) still rejects with the base timeout error, unenriched — the enrichment must never swallow the real failure.
28. `_defaultRunTests` sizes the pytest and vitest exec calls from `sizedTimeoutMs('pytest', ...)` and `sizedTimeoutMs('vitest', ...)` independently (fake `sizedTimeoutMs` returning different values per label; assert each exec call received its own 4th-arg timeout).
29. `_defaultRunTests` records a duration for pytest and for vitest separately on success, using a fake clock for elapsed ms.
30. `_defaultRunTests` records a duration with `passed: false` on a failing run, then rethrows the original error unchanged (the existing `GATE_TESTS_FAILED` path must still see the real failure).
31. `mergePrUnqueued`'s `GATE_INFRA` refusal message includes the step duration, usual duration, and concurrent-pytest count — AC3, end to end through `summarizeGateFailure`.
32. The enrichment marker survives even when the surrounding text is long enough that `summary.comment.slice(0, 300)` would truncate it first — explicit regression test for the discarded attempt's "untested enrichment-truncation path" bug; extraction must read the full `result.reason`.
33. The `GATE_INFRA` refusal still renders correctly, with no marker and no crash, for a timeout with no `meta` (e.g. another project whose `ctx.runTests` never sets a label).
34. `computeGateTimeoutMs`'s result is actually wired into `mergePrUnqueued`'s `gateTimeoutMs` default — an integration test, not just the pure function in isolation (guards "no dead unused function").
35. A caller-supplied `deps.gateTimeoutMs` (as every existing gate-timeout test already passes) still overrides the computed default exactly as before — non-regression for existing tests.
36. A full gate run whose summed sized pytest+vitest cutoffs exceed the hard ceiling is still bounded and refused as `GATE_INFRA` rather than hanging — AC2 end-to-end.
37. The full pre-existing `merge.test.js` and `merge_overlap.test.js` suites still pass unmodified, confirming no behavior change for any call site that doesn't opt into `meta`.

## Decisions

The per-step cutoff now has to grow with real run times (AC1), and the ticket says the overall gate timeout (`GATE_TIMEOUT_MS`, today a static 40-minute constant) must stay above the sum of those cutoffs — so it has to become derived rather than fixed. That only works with a hard ceiling so a single bad PR can't tie up the one-merge-at-a-time repo queue indefinitely. No record of this value being chosen earlier exists for this attempt (no PR, no decisions comment), so it's asked fresh.

## Decisions
<!-- marvin:decisions -->
### ceiling: Hard ceiling for the derived overall gate timeout (replaces the static 40-min GATE_TIMEOUT_MS)?
- [ ] A: 60 min
- [ ] B: 90 min
- [ ] C: 120 min

## Task List

1. Add `dashboard/webhook-server/gate_durations.js`: `DEFAULT_TEST_TIMEOUT_MS` (moved from `merge.js`), `GATE_TIMEOUT_CEILING_MS` (from the Decision), `recordDuration`, `recentPassingDurations`, `median`, `sizedTimeoutMs`, `countConcurrentPytest(exec)` (shaped for `execFileSync`'s real signature), `computeGateTimeoutMs`. Default log path `~/.claude/logs/gate-run-durations.jsonl`.
2. Write `dashboard/test/gate_durations.test.js` covering tests-first items 1–24.
3. In `merge.js`: import the above from `gate_durations.js`; drop the local `DEFAULT_TEST_TIMEOUT_MS` and the static `GATE_TIMEOUT_MS` constant.
4. Extend `execWithGroupTimeout` with an optional 5th `meta = {}` param (`{ label, median, countConcurrent }`, all overridable, defaulting to the real `gate_durations.js` implementations). On timeout, when `meta.label` is set, best-effort append the duration/usual/concurrent marker to both `.message` and `.stderr`, inside try/catch so a lookup failure never blocks the base timeout error.
5. Update `_defaultRunTests(cwd, exec, capMs)`: compute `sizedTimeoutMs('pytest', {capMs})` and `sizedTimeoutMs('vitest', {capMs})` separately; time each exec call with a fake-clock-friendly start/end; `recordDuration` on both the success and the catch-and-rethrow paths; pass the sized timeout + `{label}` meta into each `exec` call.
6. Apply the same wrapping to `defaultGateContext`'s `runTests`, keyed `verify:${repo}`.
7. Thread `capMs` through `rebaseAndRetest` (new optional 8th param) into its `runTests(scratchDir, exec, capMs)` call, and from `mergePrUnqueued` into both `rebaseAndRetestFn` call sites.
8. In `mergePrUnqueued`: after `ctx` is resolved, compute the real `gateTimeoutMs` default via `computeGateTimeoutMs(...)` (pytest+vitest cutoffs for marvin, `verify:${repo}` cutoff for other projects), used only when `deps.gateTimeoutMs` was not explicitly supplied (`??`).
9. In the `GATE_INFRA` branch (`merge.js:468-476`): extract the duration/usual/concurrent marker from the full, unsliced `result.reason` via regex and splice it into the refusal's `message`/`remediation`, instead of relying on `summary.comment.slice(0, 300)`.
10. Add `gate_durations.js` to `merge.test.js`'s top-level `vi.mock(...)` block with safe fake defaults, overridden per-test via `vi.mocked(...)` where a test needs specific sizing/concurrency values.
11. Add the `merge.test.js` tests from tests-first items 25–37.
12. Update `CONTEXT.md`'s "Per-command timeout + process-group kill" section (~line 1134-1138) to describe the sized-cutoff, enrichment, and derived-`GATE_TIMEOUT_MS` behavior.
13. Run the full `dashboard` vitest suite and `pytest -q` to confirm no regressions (existing passing counts unchanged) before calling this done.