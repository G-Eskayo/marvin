1. `merge_progress.js`: add `PING_INTERVAL_MS`, keepalive writer in `approveResponder` (streaming only), cleared on end/close/error.
2. `merge_progress.js`: add `inflightBody(inflight, url)` pure helper next to `createInflightStore`.
3. `index.js`: add `GET /inflight` route using the existing `inflight` instance + `inflightBody`.
4. `merge_ops.js`: `notice()` refreshes `lastEventAt`.
5. New `electron/main/merge_catchup.js`: extract `catchUpMerges`/single-PR catch-up (`catchUpOne`) out of `index.js` into a testable factory (`mergeOps`, `fetchProgress`, `push` injected).
6. `index.js`: wire `catchUpMerges`/`catchUpOne` from the new module in place of the inline closure.
7. `approve_stream.js`: add `STALL_MS`, injectable `checkInflight`, `onNotice` option; replace the immediate `interrupted()` resolution with an async `reconcile()` that probes `/inflight` once and resolves either `interrupted:true` (absent) or `stillRunning:true` (present); add the stall watchdog reset on every received chunk.
8. `approve_flow.js`: thread `onNotice: onSwitch` into the `send` call to `approveOnAnyMachine`; accept a new `catchUp` param; in `answered()`, branch on `result?.stillRunning` before the `interrupted` branch — no ledger conclude, call `mergeOps.notice()` + `catchUp(url)`.
9. Write/port all 23 tests above across `merge_gate_progress.test.js` (or a new file for `inflightBody`), `approve_stream.test.js`, `merge_failover.test.js` (rewriting the pinned test at line 78), `merge_ops.test.js`, a new `merge_catchup.test.js`, and `approve_flow`'s existing test file.
10. Run the full dashboard test suite (`npm test` in `dashboard/`), not just the touched files, per the full-suite-before-merge rule.
11. Pin screenshots at 900px and 1440px of a card showing the transient "Lost contact…" notice (force it via the existing `MARVIN_MR_FIXTURE`/manual trigger) on the PR.