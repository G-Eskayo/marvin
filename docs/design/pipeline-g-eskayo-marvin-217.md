## North-star fit

**Reuses, doesn't rebuild.** I re-read every touched file end-to-end rather than trusting the prior design doc's self-report, and confirmed almost all 32 of its fixes are *already present* in this worktree: `StageStrip.jsx` has no `escapeHtml`, exports `withStopPropagation`, guards `cost_usd` with `typeof`, shows the failed/blocked message panel unconditionally; `stage_strip.js` ranks the order/request insertion by stage index (not `findIndex('gate')`), threads `now` into `statusOfEvent`, has no dead `rebase` opt or `STATUS_COLORS`; `ticket_liveness.js` exists and breaks the activity.js↔mr_review.js cycle; `merge.js` already moved `shouldGateMerge` before `uiEvidence`/`decisions` and records `DRAFT_READY` as `'passed'`. This revision does **not** repeat that plan — it diagnoses why that *exact code* regressed, fixes the real defects it finds (below), and closes the two genuine gaps the last doc never actually finished.

**Simplest sufficient approach.** The regression metric (vitest: 1421→103 passed, only +1 failed; pytest: unchanged) is not the signature of a wrong assertion — losing 1318 *passing* tests while failing only one more means almost the whole `vitest run` process never got to report, which only happens from a process-level event (crash/hang/external-timeout-kill), not a logic bug in one function. So the simplest sufficient fix is not "rewrite more of stage_strip.js" (already correct) — it's find and remove whatever makes the run blow its time budget, verify by running the suite before touching feature code again, and only then layer the two remaining real gaps on top.

**Where this spends vs. saves tokens.** Most of the cost here was tracing the actual call graph instead of re-guessing: confirmed `mergePr`'s gate/rebase path is fully exec-injected (no real `child_process` spawn can leak out even when a test exercises the real `_defaultShouldGateMerge`/`rebaseAndRetest` defaults — I read `_defaultRunTests` and `rebaseAndRetest` line by line to rule that out), and confirmed the new `DRAFT_READY` tests (#26-28) are the only place in `merge.test.js` that newly exercises `shouldGateMerge`/gate logic with *unmocked* defaults, a path no pre-existing test ever took. I could not get 100% certainty without executing (Bash/node execution is denied in this planning session), so the plan's first step is a cheap, targeted diagnostic run — spending a little time there avoids a third blind guess, which is the expensive failure mode (two prior "unchanged"/"regressed" verdicts already).

**More capable, not more passive.** Unchanged from the ticket's intent: a hung or silently-conflicted PR becomes visible on the card itself. Two concrete AC/requirement gaps I found that the prior attempt missed — the hover tooltip never grew to show time/machine/cost, and `ticket_stages.js` still duplicates the stage list instead of importing it — are both small, real misses against what Gil actually asked for and against the prior doc's own stated intention; closing them is what "more capable" means here, not any new mechanism.

---

## Root cause of the regression (do this first, before any other change)

I traced every file this ticket touches and ruled out the two most dangerous-looking theories by reading the real implementations:

- **Positional-mock drift from the `merge.js` reorder** — ruled out. `grep` found zero `mockResolvedValueOnce` chains anywhere in `merge.test.js`; every exec mock routes by `args.includes(...)`, which is order-independent. The reorder changes *when* `shouldGateMerge` runs relative to `uiEvidence`/`decisions`, but since those two are globally no-op-mocked for the whole file (`vi.mock('../webhook-server/ui_evidence.js', ...)`), no pre-existing test's control flow actually changes.
- **A real subprocess/real rebase escaping the mock in the new `DRAFT_READY` tests (#26-28)** — ruled out by reading `rebaseAndRetest` and `_defaultRunTests` line by line: every `git`/`npm`/`pytest`/`vitest` call inside them goes through the *injected* `exec` parameter, which in these tests is always the test's own mock function. No real child process can be spawned from this path even though tests #26-28 don't override `shouldGateMerge`/`rebaseAndRetestFn` and so do exercise the real defaults. (The only real side effect is a harmless `mkdtemp`/`rm` temp-dir pair.)

What I *did* confirm, concretely:

1. **Stale, hand-maintained `vi.mock('../webhook-server/ticket_stages.js', ...)` factories.** `merge.test.js` (line 11), `draft.test.js`, and `decisions.test.js` all still mock this module as `{ recordStage: vi.fn() }` only. `mr_review.js` (loaded transitively by `merge.js`, which these files import) now also imports `readStages, stageKey` from that same module. `ui_evidence.test.js` was hand-patched to add `readStages` — a visible symptom that this mock shape silently goes stale every time *any* file anywhere in the graph starts consuming a new export, and nobody updates the other three copies. Today this is latent (nothing in these three files' test paths currently calls `listPipelinePrs`/`stageKey`), but it is exactly the kind of brittle-by-construction setup that turns an unrelated future change into a mass failure with no local signal — and I cannot fully rule out, without executing, that some test helper or `vi.resetModules()`/module-registry interaction in this vitest 2.1 version let one file's incomplete mock registration bleed into collection of the next.
2. **Dead import**: `mr_review.js` imports `stageKey` and never uses it.
3. **The scale mismatch itself is the strongest clue.** 1318 missing passes with only +1 failure is the fingerprint of the overall `npm test` process being killed by an external wall-clock limit before most of the ~50 test files finished, not a per-test assertion failure. That points at *aggregate* run time growing, not at one deterministic crash.

**Plan:**

- **Step 0 (diagnostic, before any feature edit):** run `vitest run test/merge.test.js` alone, then the full suite with `--reporter=verbose` and a short `--testTimeout`, capturing wall-clock per file. This pins down whether one specific file/test is slow/hanging now that didn't used to be, or whether the full-suite time simply crossed an external budget because three more real-default-exercising tests (#26-28) were added. This is cheap (minutes) and removes the guessing that burned the last two attempts.
- **Fix regardless of what Step 0 finds, because it's correct either way:** explicitly inject `shouldGateMerge: vi.fn().mockResolvedValue({ gate: false, headRefName: 'feature', body: ... })` in tests #26, #27, #28, matching every other test in the file that *does* care about gate behavior. These three tests are about `DRAFT_READY` recording, not about the gate/rebase path — they should never have been exercising `_defaultShouldGateMerge` in the first place. This also makes them deterministic and removes the only place in the file where real defaults are reached incidentally.
- **Fix the mock-drift class, not just today's instance:** convert all four `ticket_stages.js` mocks (`merge.test.js`, `draft.test.js`, `decisions.test.js`, `ui_evidence.test.js`) to:
  ```js
  vi.mock('../webhook-server/ticket_stages.js', async () => ({
    ...(await vi.importActual('../webhook-server/ticket_stages.js')),
    recordStage: vi.fn()
  }))
  ```
  Only `recordStage` has a real side effect (writing files) that tests must never trigger; everything else (`readStages`, `stageKey`, `STAGES_DIR`, `listTrackedTickets`) is pure/file-read and safe to leave real, and this can never go stale again when a new file starts consuming a new export.
- **Remove the dead `stageKey` import** from `mr_review.js`.

---

## Remaining real gaps against the ticket (not fixed by the prior attempt)

4. **"Hovering a stage shows its time, machine and cost" (Solution section, not yet done).** `StageStrip.jsx`'s button `title` attribute currently only ever shows `label` or `label: message` — never time, machine, or cost, even though `segment.cost` and `segment.events` are already computed and available. Fix: extend the tooltip string to include the latest event's machine, a relative/absolute time, and the segment's accumulated cost, e.g. `${label}${message ? ': ' + message : ''} — ${machine}, ${when}${cost ? ', $' + cost.toFixed(2) : ''}`.
5. **`ticket_stages.js`'s `VALID_STAGES` Set is still hand-duplicated** instead of built from `stage_vocabulary.js`'s `STAGE_ORDER` (the prior doc's own fix #15, never applied — confirmed `ticket_stages.js` is untouched in `git status`). Fix: `const VALID_STAGES = new Set(STAGE_ORDER)` importing from `./stage_vocabulary.js`. No `nodeIntegration` concern here since this *is* the Node-side file that already uses `fs`/`os`/`path`.
6. **Screenshots (AC "Real screenshots in the PR (#126)")**: not yet produced. After the fix lands, run the dashboard and capture: a passed strip, a failed-at-gate strip (message+remediation visible), a refused-at-order strip, and a running/stalled strip, for the PR body.
7. **Status-colors test (existing `test 24` in `stage_strip_component.test.jsx`) is missing the "unknown status falls back to pending's class" case** that the prior doc specifically called for — only the 6 known statuses are covered.

---

## Tests to write first

The ticket has no "How we'll try to break it" section (re-confirmed on this pass across all 66 comments), so this is built from the north-star's adversarial checklist, scoped to what's actually changing in this revision:

- **Each dependency failing / stale mocks (the actual regression class):** a new test that calls `mergePrUnqueued` via `mergePr` with a draft PR and *no* override for `shouldGateMerge`/`rebaseAndRetestFn`, asserting it resolves in well under a second — a direct timing regression guard for "a test accidentally exercises the real gate/rebase default path." Also: rerun `merge.test.js`, `draft.test.js`, `decisions.test.js` after the `vi.importActual` mock change and confirm every existing test in those files still passes unchanged (proves the mock swap is behavior-preserving, not just differently-shaped).
- **A person's mistake (a stale hand-written mock):** a test asserting `readStages` and `stageKey` are real, callable functions when `ticket_stages.js` is mocked via the new `vi.importActual` pattern in `merge.test.js` — this is the literal regression test for defect #1 above; reverting the mock to the old `{ recordStage: vi.fn() }` shape should make this test fail.
- **Bad/empty/malformed input:** the unknown-status-fallback case missing from `test 24` (status string `'exploded'` → same class as `pending`).
- **A person's mistake, UI-facing:** a test that the button's `title` attribute, for a segment with `events: [{machine:'mac-mini', cost_usd: 1.23, timestamp: ...}]`, contains `'mac-mini'` and `'1.23'` — the literal regression test for gap #4.
- **Stale state / drift between two sources of truth:** a test that `ticket_stages.js`'s exported stage-validation set and `stage_vocabulary.js`'s `STAGE_ORDER` are the *same reference-derived* list (e.g. `recordStage` accepts every stage in `STAGE_ORDER` and rejects one not in it), guarding gap #5 from silently re-diverging.
- **Everything already covered and still valid, kept as-is** (confirmed correct on this re-read, not touched): the full adversarial suite already in `stage_strip.test.js` (null/undefined/non-array events, 5000-event correctness, `__proto__`/`constructor`/`hasOwnProperty` stage names, determinism with pinned `now`, order/request insertion before-vs-after a recorded gate), `stage_strip_component.test.jsx`'s XSS/escaping, cost_usd malformed-input, and `withStopPropagation` tests, and `stage_strip_integration.test.js`'s real-`recordStage`-output integration tests.

Every fix above (1-7) gets a test that fails against the current worktree and passes once that fix lands, so reverting any one change in isolation breaks a specific test — including, critically, the timing-guard test for the regression itself.