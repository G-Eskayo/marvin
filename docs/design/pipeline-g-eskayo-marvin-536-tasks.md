1. `dashboard/webhook-server/merge.js:290` — fix `defaultGateContext`'s `runTests` call from `run(VENV_PYTHON, [...], timeoutMs, { ... })` to `run(VENV_PYTHON, [...], {}, timeoutMs, { ... })`. `[FIX-1]`
2. `dashboard/webhook-server/merge.js:42-65` (`execWithGroupTimeout`) — append the `[usual: ...; concurrent: ...]` enrichment to `error.stderr` as well as `error.message` (e.g. build `enrichment` once, assign `Object.assign(new Error(msg), { stdout, stderr: stderr + enrichment })`); capture and clear the inner 2s fallback timer in a `finally`. `[FIX-5, plus the bundled timer-leak cleanup]`
3. `dashboard/webhook-server/gate_durations.js` — no source change (confirmed already correct); only `dashboard/test/gate_durations.test.js` changes:
   a. Fix the mislabeled `countConcurrentPytest` test (line 279) to assert `toBe(0)` with an accurate name.
   b. Add the concurrent-write regression test.
4. `dashboard/test/merge.test.js`:
   a. Fix the `gate_durations.js` mock (lines 25-33) to default `recordDuration`/`recentPassingDurations` to a scratch temp file rather than the real log path. `[FIX-2]`
   b. Extend the `defaultGateContext` test (line 820-827) with the positional-args assertions. `[FIX-1 regression]`
   c. Rewrite the two vacuous-assertion tests at lines 1198 and 1211. `[FIX-4]`
   d. Rewrite the toothless enrichment-extraction test at line 1300 and extend the one at line 1396. `[FIX-3]`
   e. Rewrite the toothless `'gate timeout lazy computation'` test at line 1276. `[FIX-3]`
   f. Simplify the `vi.spyOn`-based wiring test at line 1353, dropping the unused variables. `[FIX-1, related]`
   g. Add the stderr-enrichment-survives test and the uncleared-timer test from tests-first items 9-10. `[FIX-5]`
5. `dashboard/electron/main/merge_ops.js`, `dashboard/test/merge_ops.test.js`, `CONTEXT.md` — confirmed no changes needed; re-verified by reading all three in full against the fixed code's behavior (none of the fixes above change any externally-visible timing value or documented behavior).
6. Run `npx vitest run test/gate_durations.test.js test/merge.test.js test/merge_ops.test.js` from `dashboard/` to confirm everything passes. Do **not** run the full vitest suite or `pytest -q` — no Python file is touched by this ticket, and running the full suites is the specific trap that produced two of the four prior denials on this issue.