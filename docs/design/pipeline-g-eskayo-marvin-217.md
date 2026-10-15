## North-star fit

**Reuses:** everything the prior attempt reused still holds — `ticket_stages.js`/`activity.js`'s stage log and `TERMINAL_STAGE_ORDER`, `card.hasTimeline`/`card.isLive` already computed by `board.js:183-184`, `mr_review.js`'s `parseTicketRef`/`ticketRef`, `post_merge_rebase.js`'s existing `REBASE_CONFLICT` write, `failure.js`'s RULES/remediation, and the codebase's own established convention of putting pure, dependency-free helpers in `dashboard/src/lib/*.js` that both the renderer **and** `electron/main` import from (confirmed precedent: `board.js`, `ticket_input.js`, `needs_you.js`, `docs_search.js`, `relations.js` already import main-process code *from* `src/lib`). No new storage, no new IPC channel, no new stage names.

**Simplest sufficient approach, corrected:** the prior attempt's shape (one pure `stage_strip.js` + one `StageStrip.jsx`, three call sites) was right; what was wrong was *where the shared constant lives*. Verified against the real import graph: `electron/main/activity.js` re-exports `TERMINAL_STAGE_ORDER` but itself imports `ticket_stages.js` (`fs`, `path`, `os`) and `dispatch_status.js` (`fs`, `path`, `os`) — both real Node built-ins. `dashboard/src/lib/stage_strip.js` importing from `../../electron/main/activity.js` therefore does pull those into the Vite renderer bundle; Vitest hid it because it runs in Node, where those imports resolve fine. Fix: move `TERMINAL_STAGE_ORDER` (and `STAGE_LABEL`) into a new **zero-import** `dashboard/src/lib/stage_names.js`, which is exactly the pattern this codebase already uses for shared pure data. `activity.js` imports from there instead of defining the array inline (and keeps re-exporting it, so nothing else that might reference `activity.js`'s export breaks).

**Token/compute cost:** no change from the prior doc's accounting — small bounded frontend/backend code, saves recurring SSH/log-archaeology time, no LLM calls on this path. The fix set below is almost entirely rearranging/guarding existing logic, not new machinery.

**Phone-OS direction:** unchanged — pure/presentational split, now with a *verified* clean boundary (the actual thing MARVIN Mobile's bundler will care about).

**More capable, not more passive:** unchanged — removes forensic log-reading, decides nothing for Gil.

**Checked against the code, two corrections to the ticket's/prior doc's own wording:**
1. The prior doc's "no new persisted display-state" correction (re: AC #1's "derived, not stored") still holds and is reused as-is.
2. AC #3 says refusals "show as a failed 'order'/'request' stage." Verified: `ticket_stages.js`'s `VALID_STAGES` has no `order` or `request` entry — `refusal()`'s `stage` argument (`'request'`, `'gate'`, `'merging'`) is a refusal-classification label, not a ticket-stage name, and `recordApproveError`/`recordRefusal` already write every request-stage refusal into the **`merging`** stage bucket (the only valid bucket available), carrying the refusal's own code/message/remediation. That is what actually ships today and what every test below targets — not a new `order` stage, which would require a VALID_STAGES schema change across every writer and isn't evidenced as needed anywhere else. Treated as descriptive language in the ticket, not a literal requirement; not raised as a Decision because there is no real alternative that fits inside this ticket's scope.

## Fixes to the five must-fix findings (verified against the real code, not assumed)

1. **Renderer pulls Node builtins (`stage_strip.js:1`).** Confirmed via the import chain above. Fix: new `dashboard/src/lib/stage_names.js` (exports `TERMINAL_STAGE_ORDER`, `STAGE_LABEL`, no imports at all); `stage_strip.js` and `StageStrip.jsx` import from there; `activity.js` imports from there and re-exports for compatibility.
2. **`ticketNumber` vs `ticketRef` (`MrReview.jsx:405`, `MrDetail.jsx:152`).** Confirmed via `mr_review.js:350-353`: `ticketRef` comes from `parseTicketRef(pr.body)` (any `Closes/Fixes/Resolves #N`, unconditional) while `ticketNumber` is only set when the PR carries the evidence schema (`evidence?.ticketRef`). Fix: both effects key on `pr.ticketRef` (a string digit, same as `activity:timeline`'s other callers already pass — `window.api.activity.timeline(ticketRef, repo)` works identically, confirmed against `ipcMain.handle('activity:timeline', ...)` → `getTicketTimeline(number, ...)` → `readStages(ticketNumber, ...)`, which only ever does string/template-literal file-name building, no numeric coercion that would reject a string).
3. **`Remediation: undefined` guard (`merge.js:536`).** Verified `classifyFailure` always returns a non-undefined `remediation` (explicit fallback string at `failure.js:76`), so this exact literal isn't reachable *today* — but the review is right that there's no guard, and a future RULES entry missing a `remediation` key, or any other `failure`-shaped object lacking one, would produce it silently. Fix: extract the guard refusal_log.js already has (`remediation ? `${reason}\n\nRemediation: ${remediation}` : reason`) into one shared helper in `failure.js` and use it from **both** `merge.js:536` and `refusal_log.js:38`, so there is one guarded code path instead of two (one guarded, one not).
4. **False "stalled" on every passed stage (`stage_strip.js:26-28`).** Confirmed: the current code computes `liveStatus` inside the per-stage `.map()`, so it runs for every stage in the strip, not just the in-flight one. Fix: compute the single globally-most-recent-timestamped stage once, and additionally require `event.status === 'started'` (a stage that already reports `passed`/`failed` is finished regardless of `isLiveNow` — it should never show "running" or "stalled"). Only that one stage, if it's still `started`, gets `liveStatus`; every other stage gets `null`.
5. **Nested `<button>` (`ProjectBoard.jsx:111`).** Confirmed `Card`'s root is a native `<button>` and `StageStrip.jsx` renders native `<button>` pills inside it — invalid DOM, and `Tag`/`PrChip` in the same file already establish the correct pattern (`<span role="button" tabIndex={0}>` + `e.stopPropagation()`). Fix: `StageStrip.jsx`'s pills switch to that exact pattern.

## Other defects fixed in the same pass (pulled from the review's `notes`, directly tied to correctness, cheap)

- **No cancellation guard on the three new effects** (`ProjectBoard.jsx` Card, `MrReview.jsx` PrCard, `MrDetail.jsx`'s new timeline effect) — `MrDetail`'s own pre-existing ticket-context effect already uses a `cancelled` flag; match it, plus reset `events` to `[]` when the key changes (matters concretely for `MrDetail`, which is reused across different `pr` props without remounting).
- **`needsRebase` missing the `stage === 'gate'` check** — add it; a `merging: failed` detail that happens to start with `REBASE_CONFLICT` must not get the ⚠ icon.
- **`extractRemediation` drops everything after the `Remediation:` line** — join the remainder instead of taking one line, so multi-line remediation text survives.
- **Duplicate `STAGE_LABEL`** (`StageStrip.jsx` vs the lib) — both now import the single copy from `stage_names.js`.
- **N IPC calls for liveness** — `ProjectBoard`'s `Card` already has `card.isLive` for free from `board.js:184`; wire it straight into `deriveStageStrip`'s `isLiveNow` instead of leaving it unwired (the prior attempt never passed `isLiveNow` at all, so its strip could never show "running"). For `MrReview`/`MrDetail`, hoist **one** `window.api.activity.list()` call into `OpenPrs.reload()` (alongside the existing `mr.list()`/`parity()` calls), build a `key → isLiveNow` map, and attach `isLiveNow` onto each PR object once — `PrCard` and `MrDetail` then just read `pr.isLiveNow`, no per-card IPC call added.
- **Tasks doc overclaimed finished/passing tests that don't exist** — the rewritten tasks doc will not claim anything not actually in the diff.
- **Locale-dependent test** (`toMatch(/Oct/)`) — replaced with a locale-independent assertion.
- **CONTEXT.md's wrong claim** ("without `isLiveNow`, age-based stall detection still applies") — corrected to state the real, intentional behavior: no `stalled`/`running` label without `isLiveNow`, by design (otherwise normal CI-wait time would misreport as "stalled").

Scope boundary (not a defect): `TicketDrilldown` keeps its existing vertical `PipelineHistory` only; the compact `StageStrip` is not duplicated there — it exists to put pipeline visibility where there currently is none (collapsed board card, MR Review card), not to decorate a view that already shows the same facts in more detail.

## Decisions

<!-- marvin:decisions -->
### stall-thresholds: How long with no new stage event before the current stage shows "stalled" (amber) instead of "running"?
- [ ] A: One flat threshold for every stage — 10 minutes
- [ ] B: Per-stage thresholds — 10 min for claimed/planning/executing/verifying/merging/versioning/rebuilding/done, 25 min for gate specifically (gate's own test run can legitimately take up to `DEFAULT_TEST_TIMEOUT_MS` = 20 min before merge.js kills it, plus rebase overhead)
- [ ] C: Defer — ship with option A's flat 10 minutes for now, revisit with real data once the strip has been live for a week

## Tests (written first)

`dashboard/test/stage_strip.test.js` (rewrite/extend the existing file — pure logic, against the real `ticket_stages.js`/`failure.js` shapes, never a hand-rolled mock of them):

1. Empty events array → `[]`, no crash.
2. Canonical-order rendering regardless of file order (existing test, keep).
3. Latest-event-wins per stage on duplicates (existing test, keep).
4. Remediation line extracted and split off (existing test, keep) — **extended**: a detail with `Remediation:` followed by multiple lines keeps all of them, not just the first.
5. No `Remediation:` line → detail unchanged, `remediation: null` (existing test, keep).
6. `needsRebase` true only for `stage: 'gate', status: 'failed'` with a `REBASE_CONFLICT` prefix (existing test, keep).
7. `needsRebase` false for a `gate: failed` detail that doesn't start with `REBASE_CONFLICT` (existing test, keep).
8. **New:** a `merging: failed` event whose detail happens to start with `REBASE_CONFLICT` → `needsRebase` is `false` (the stage-gated fix — this is the exact must-fix regression test).
9. `isLiveNow: true`, one `started` event, age under threshold → `liveStatus: 'running'` (existing, keep).
10. `isLiveNow: true`, one `started` event, age over threshold → `liveStatus: 'stalled'` (existing, keep).
11. `isLiveNow: false` → `liveStatus: null` regardless of age (existing, keep).
12. **New (the must-fix regression test):** multiple stages present (`claimed: passed` at t0, `gate: passed` at t1, `executing: started` at t2, the most recent), `isLiveNow: true`, t2 within threshold → only `executing` gets `liveStatus: 'running'`; `claimed` and `gate` both get `liveStatus: null` (not `'stalled'`).
13. **New:** same shape, but the most-recent-timestamp event's own `status` is `'passed'` (not `'started'`) — `liveStatus: null` even though `isLiveNow: true` (a stage that already finished is never "running").
14. `when`/`money` fields present (existing, keep — rewritten to not assert `/Oct/`; assert a non-empty string and that it round-trips through `Date.parse`, so it isn't locale-dependent).
15. `formatMoney` zero/small-amount formatting (existing tests, keep).
16. Out-of-canonical-order events still render in canonical order (existing test, keep).
17. Unknown/future stage name is ignored, doesn't crash, doesn't drop other stages (existing test, keep).
18. Malformed detail: `null`, empty string, and a 10,000-character detail — never throws, detail shown bounded.
19. 500+ events for one ticket — derivation stays O(events), no visible hang (perf smoke).
20. **New (regression for finding #1):** read `dashboard/src/lib/stage_strip.js`'s own source text and assert it contains no `from '../../electron` import — the exact mistake, caught statically since Vitest running in Node can't catch it behaviorally.

`dashboard/test/stage_strip_view.test.jsx` (rewrite the pill markup assertions for the non-button fix):

21. Renders a pill per stage with its label (existing, keep).
22. Status icon ✓/✗ present (existing, keep).
23. `title` attribute present per pill (existing, keep).
24. ⚠ for `needsRebase` (existing, keep).
25. **New (must-fix regression test):** every pill is **not** a `<button>` element (query for `button` tags inside the rendered strip and assert zero), and each pill's `onClick` calls `stopPropagation` — render the strip inside a mock `<button>` wrapper (mirroring `ProjectBoard.jsx`'s real nesting) with an `onClick` spy on the wrapper, click a pill, and assert the wrapper's click handler was **not** called.

`dashboard/test/merge.test.js` (new cases, against the real `classifyFailure`/`RULES`, not a stub):

26. A classified failure with a real RULES match (e.g. `BRANCH_PROTECTION`) → the stage-log detail passed to `recordStageFn` contains the code+message and a `Remediation:` line matching `failure.js`'s real RULES text for that code.
27. **New (must-fix regression test):** inject a `classifyFailure`-shaped failure object with `remediation: undefined` (simulating a future RULES/path gap) → the stage-log detail never contains the literal string `"Remediation: undefined"`; it omits the `Remediation:` line instead.
28. `readyIfDraft` actually flipping a draft → `merging: started` detail says `"draft marked ready"`; a non-draft PR → detail stays `''` (regression for the already-correct `draftWasMarkedReady` wiring — confirm it still holds after the shared-helper refactor).

`dashboard/test/refusal_log.test.js` (new cases):

29. `recordRefusal` with a `remediation` string → detail is `refused ${reason}\n\nRemediation: ${remediation}` (existing behavior, now routed through the shared helper — regression test that the refactor didn't change it).
30. `recordRefusal` with no `remediation` (the `OUT_OF_ORDER`/`WRONG_BASE` shape from `pr_order.js`'s `refused()`) → detail stays `refused ${reason}`, no `Remediation:` line, no `"undefined"` anywhere.
31. Existing `recordApproveError`/`writeStage` gating tests must still pass unchanged.

`dashboard/test/pr_state.test.js` or a new `dashboard/test/mr_review_strip.test.jsx` (render, real `pr` shapes):

32. A PR with a `Closes #N` reference but **no** evidence schema (`ticketRef` set, `ticketNumber` null) → the timeline fetch still fires on `pr.ticketRef` (regression test for the ticketRef/ticketNumber must-fix).
33. `window.api.activity.timeline` rejecting (simulated IPC failure) → the card still renders title/Approve/Deny; the strip section is simply absent; no unhandled rejection.
34. Two different repos' PRs both referencing ticket `#158` → each fetches/renders its own timeline (`${repo}#${number}` key), never mixed.
35. **New (cancellation regression):** `MrDetail` rendered with PR A, then re-rendered with PR B before PR A's `activity.timeline` promise resolves → PR A's late-arriving events never appear under PR B (assert via a deferred promise the test resolves after the re-render).
36. `isLiveNow` reaching `PrCard`/`MrDetail` via the hoisted `activity.list()` map (not a per-card IPC call) — assert `window.api.activity.list` is called once per `OpenPrs.reload()`, not once per `PrCard`.

`dashboard/test/board.test.js` (new case):

37. `Card` passes `card.isLive` through to `deriveStageStrip`'s `isLiveNow` (regression for "ProjectBoard never wired isLiveNow at all").

## Task List

1. Create `dashboard/src/lib/stage_names.js`: `TERMINAL_STAGE_ORDER` (the 9 real stage names, matching `activity.js`'s current list exactly) and `STAGE_LABEL`, zero imports.
2. Update `dashboard/electron/main/activity.js`: import `TERMINAL_STAGE_ORDER` from `../../src/lib/stage_names.js` instead of defining it inline; keep the existing `export { TERMINAL_STAGE_ORDER }` for compatibility.
3. `failure.js`: add a small guarded helper (e.g. `appendRemediation(reason, remediation)`) mirroring `refusal_log.js`'s existing ternary; export it.
4. `merge.js:536`: use the shared helper instead of the unguarded template string.
5. `refusal_log.js:38`: switch to the same shared helper (removes the now-duplicated inline guard).
6. Write/extend `dashboard/test/stage_strip.test.js` (tests 1-20) and `dashboard/test/stage_strip_view.test.jsx` (tests 21-25) against the not-yet-fixed `stage_strip.js`/`StageStrip.jsx` (red).
7. Rewrite `dashboard/src/lib/stage_strip.js`: import `TERMINAL_STAGE_ORDER` from `./stage_names.js`; fix `needsRebase` to require `stage === 'gate'`; fix `liveStatus` to apply only to the single most-recently-timestamped stage, and only when that stage's own `status === 'started'`; fix `extractRemediation` to keep everything after the `Remediation:` marker, not just one line.
8. Rewrite `dashboard/src/components/StageStrip.jsx`: import `STAGE_LABEL` from `stage_names.js` (drop the local duplicate); change pills from `<button>` to `<span role="button" tabIndex={0}>` with `e.stopPropagation()` on click/keydown, matching `Tag`/`PrChip`'s existing convention in `ProjectBoard.jsx`.
9. Write `merge.test.js` cases 26-28 and `refusal_log.test.js` cases 29-31 against the step 3-5 changes (red before, green after).
10. `ProjectBoard.jsx`'s `Card`: pass `isLiveNow: card.isLive` into `deriveStageStrip`; add a `cancelled` guard + `setEvents([])` reset on the timeline effect.
11. `MrReview.jsx`'s `OpenPrs.reload()` (and `reloadKeepSelected()`): add `window.api.activity.list()` alongside the existing `mr.list()`/`parity()` calls, build a `key → isLiveNow` map, attach `isLiveNow` onto each PR object once. `PrCard`: fetch on `pr.ticketRef` (not `pr.ticketNumber`), pass `pr.isLiveNow` into `deriveStageStrip`, add cancellation guard + reset.
12. `MrDetail.jsx`: fetch on `pr.ticketRef`, pass `pr.isLiveNow`, add cancellation guard + reset (same pattern as its existing ticket-context effect).
13. Write/extend the render-level tests (32-37) against steps 10-12.
14. Run the full suite (`npx vitest run`) and fix anything that regresses in `activity.test.js`/`board.test.js` from the `stage_names.js` extraction.
15. Rewrite `CONTEXT.md`'s "Pipeline visibility — stage strip" entry to match what's actually implemented (drop the false "age-based stall detection still applies without isLiveNow" claim; record the refusal-stage-name correction and the resolved stall-threshold decision).
16. Rewrite `docs/design/pipeline-g-eskayo-marvin-217-tasks.md` to list only what's actually done/tested — no overclaiming.
17. Real screenshots (AC #5): the strip in a passing state and a failed/needs-rebase state, on both an MR Review card and a board ticket card; attach to the PR.