1. `dashboard/webhook-server/ci_status.js`: add `waitForRequiredChecks(prUrl, exec, names, opts)` plus exported `CHECKS_WAIT_TIMEOUT_MS` / `CHECKS_POLL_MS`, reusing `checkRuns()`/`MergeFailure`/`refusal()`.
2. `dashboard/test/ci_status.test.js`: tests 1–7 above, all with injected tiny `timeoutMs`/`pollMs` and a trivial `sleep`.
3. `dashboard/test/polling_guard.test.js`: add the `ALLOWLIST` entry for `ci_status.js`; confirm the allowlist test passes.
4. `dashboard/webhook-server/merge.js`: factor the pre-gate CI_FAILED block into a shared `reengageCiFailed(...)` helper (no behavior change at that call site).
5. `dashboard/webhook-server/merge.js`: wire `waitForRequiredChecks` into `mergePrUnqueued`'s `if (gate)` branch (after `postGateStatus`), injectable via `deps`; route `CI_FAILED` through the shared helper, let other codes escalate unreengaged.
6. `dashboard/test/merge.test.js`: tests 5, 8 above.
7. `dashboard/src/lib/stage_strip.js`: add `CI_TIMEOUT`/`CI_SUPERSEDED` to `REMEDIATION_BY_CODE`.
8. Run the targeted suites (`ci_status`, `polling_guard`, `merge`) then the full `vitest run` + affected `pytest` before opening the PR.