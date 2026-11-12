## North-star fit

**Reuses:** the existing `describePrState` ranking structure in `dashboard/src/lib/prState.js` — specifically the pattern already used for `GITHUB_OUTAGE` (an explicit `status === 'error' && /^CODE\b/.test(errorMessage)` branch returning a dedicated card before the generic `MIRRORED_REFUSALS` fallback) is the exact template for the new `IMAGES_STALE` branch. No new file, no new abstraction — one more branch in the same ranked `if` chain, same `base(...)` helper every other state uses.

**Simplest sufficient approach:** the bug is structural, not cosmetic. `describePrState` already re-derives six of the eight "mirrored" codes live on every render (`pr.sentBack`, `ci.state`, `pr.needsImages`, `pr.vague`/`dec.problems`, `dec.pending`, `pr.baseProblem`) — if one of those is still true, the function returns *before* reaching the `MIRRORED_REFUSALS` check at all, so hiding is already correct for them (confirmed by the existing test at `pr_state.test.js:33-37`, which asserts `ready` once each of `SENT_BACK/CI_PENDING/CI_FAILED/WRONG_BASE`'s own condition clears). The only code with **no** live re-derivation is `IMAGES_STALE`: staleness needs the same `gh api compare` the gate runs (`ui_evidence.js:140-178`), which the card deliberately never does (cost of a GitHub call per PR per render — the existing comment at `mr_review.js:271` says so explicitly). So `IMAGES_STALE` unconditionally falls through the whole chain and gets blindly hidden by the regex, landing on the default `ready` card. Fix: give `IMAGES_STALE` its own explicit branch (so it's never blindly hidden), and leave the other seven codes' behavior untouched since they're already correct by construction.

**Token/compute cost:** zero new GitHub calls, zero new config — this is a pure logic branch in a already-pure function covered by existing unit tests (`pr_state.test.js`), no network, no new dependency.

**Phone-OS direction:** neutral-to-positive — a dashboard that silently un-blocks a merge it should still be refusing is exactly the kind of "quietly wrong" failure the reliability precondition (north star 2) rules out.

**More capable or more passive:** more capable — the owner currently can't trust "Ready to merge" at face value after an images-stale refusal; this restores that trust without adding any manual step beyond what the gate's own refusal message already asks ("retake the screenshots... then approve again").

## Files read

- `dashboard/src/lib/prState.js` (full) — `describePrState`, `MIRRORED_REFUSALS`
- `dashboard/electron/main/mr_review.js` (full) — `ownBlocker`, `needsImages`, `listPipelinePrs`
- `dashboard/webhook-server/ui_evidence.js` (full) — `assertUiEvidence`, the `IMAGES_STALE` refusal
- `dashboard/webhook-server/failure.js` (full) — `refusal()`, how a code/message become the error string
- `dashboard/electron/main/mr_review.js:421-434` — `describeApproveFailure` (confirms the exact wire format: `"IMAGES_STALE at request: <message> -- needs you. <remediation>"`)
- `dashboard/src/components/MrReview.jsx:220-330` — `statusFromOp`, the merge-state effect, button rendering
- `dashboard/src/lib/merge_progress.js:145-151` — `opForHead` (confirms a new push resets `status` to `idle`, independent of this bug)
- `dashboard/electron/main/profiles.js`, `dashboard/webhook-server/merge.js:662` — where each side's UI-path list comes from
- `dashboard/webhook-server/decisions_gate.js` — confirms `DECISIONS_PENDING`/`DECISIONS_UNSTRUCTURED` share `decisions.js` with the card, same as `NO_UI_EVIDENCE`/`IMAGES_UNPINNED` share `ui_evidence.js`
- `dashboard/test/pr_state.test.js` (full) — existing regression coverage for this exact function
- `CONTEXT.md:1678-1682` — the recorded decision this ticket's fix must keep in sync (doc currently only names 4 of the 8 mirrored codes, predates `NO_UI_EVIDENCE`/`IMAGES_UNPINNED`/`IMAGES_STALE`/`DECISIONS_*` being added)
- No PR/branch exists yet for #807 (checked `gh pr list`, `git log --all --grep=807`, `git branch -a`) — the prior failed attempts left no code to inspect; only the issue comments' generic "verify timed out" / "must-fix issues" notes, with no specifics.

## Why the two cited bugs are actually one root cause

`describePrState` checks conditions in a fixed priority order and returns as soon as one applies. By the time it reaches the `MIRRORED_REFUSALS` regex check (near the bottom), every condition the function itself knows how to re-derive has already been checked and found false — otherwise it would have returned earlier. So "hide a mirrored code" is only safe for codes the function can **re-verify live**. Six of the eight can: `SENT_BACK` (ticket lookup), `CI_FAILED`/`CI_PENDING` (live `ci.state`), `WRONG_BASE` (`pr.baseProblem`), `DECISIONS_PENDING`/`DECISIONS_UNSTRUCTURED` (`summarizeDecisions`/`vagueness`, shared module with the gate), `NO_UI_EVIDENCE`/`IMAGES_UNPINNED` (`needsImages`, shared `uiFiles`/`hasImage`/`unpinnedImages` with the gate). `IMAGES_STALE` cannot — the card never calls `gh api compare`. The "only shows NO_UI_EVIDENCE/IMAGES_UNPINNED when its UI-path list matches the gate's" line in the ticket is describing the same class of risk (card's own recheck could in principle diverge from the gate's), but since both sides already read the identical `uiPathsFor`/`ui_evidence.js` logic fresh on every render, there's no separate mechanism to add for those two — the fix for `IMAGES_STALE` is the actual gap.

## Decisions

None — the ticket's "Fix" section and the "Images are older than the latest change" wording are explicit; no open design choice needs the owner's input.

## Tests (written first)

In `dashboard/test/pr_state.test.js`, extending the existing `describe('describePrState: ...')` blocks:

1. **IMAGES_STALE is never silently hidden** — `state({}, { status: 'error', errorMessage: 'IMAGES_STALE at request: the images were taken at abc1234, and SettingsView.swift changed after that... -- needs you. Retake...' })` → `kind: 'images-stale'`, `tone: 'blocked'`, `headline: 'Images are older than the latest change'`, `approve: 'disabled'`, `deny: 'enabled'`. (The ticket's core bug — this is the case that currently falls through to `ready`.)
2. **The gate's own detail survives** — same call: `s.detail` matches `/SettingsView\.swift/` and `/retake/i`, so the owner still sees which files and what to do, not a generic message.
3. **Regression: the other seven mirrored codes still resolve to `ready` once their own condition clears** — extend the existing loop at `pr_state.test.js:33-37` (currently `['SENT_BACK', 'CI_PENDING', 'CI_FAILED', 'WRONG_BASE']`) to also cover `['NO_UI_EVIDENCE', 'IMAGES_UNPINNED', 'DECISIONS_PENDING', 'DECISIONS_UNSTRUCTURED']` — each must still produce `kind: 'ready'` against the same `{}`-clean base PR. This is the concrete "a new push that fixes it" misuse case from the ticket, generalized to all codes that risked being over-corrected into permanently blocked.
4. **Priority: a condition that's genuinely still true wins over a stale `IMAGES_STALE` leftover** — `state({ sentBack: true }, { status: 'error', errorMessage: 'IMAGES_STALE at request: ...' })` → `kind: 'sent-back'` (not `images-stale`). Covers the "stale state"/concurrent-conditions case: an old `IMAGES_STALE` error sitting in local state while the PR has since also been sent back.
5. **Priority: `pr.needsImages` (live, still true) wins over a stale `IMAGES_STALE` leftover** — `state({ needsImages: { files: ['A.jsx'] } }, { status: 'error', errorMessage: 'IMAGES_STALE at request: ...' })` → `kind: 'needs-images'`. Confirms the new branch is inserted *after* the existing live checks, not before.
6. **Malformed/adversarial input: anchoring** — `state({}, { status: 'error', errorMessage: 'something mentions IMAGES_STALE mid-sentence, not as the code' })` → falls to the generic `kind: 'error'`, `approve: 'enabled'` (not matched as the dedicated state) — guards the `^IMAGES_STALE\b` anchor against a message that merely contains the substring.
7. **Wrong status / stale dependency value**: `state({}, { status: 'idle', errorMessage: 'IMAGES_STALE at request: ...' })` → `kind: 'ready'` (a leftover `errorMessage` string with `status !== 'error'` must never leak into a blocked state — a plausible "person's/system's mistake" if some other code path forgets to clear `errorMessage` alongside `status`).
8. **Empty/null errorMessage**: `state({}, { status: 'error', errorMessage: null })` already covered by nothing matching — confirm it still falls through to `ready` (no crash on `null` against the new regex test, same guard style as the existing `MIRRORED_REFUSALS.test(errorMessage)` which already handles `null` via `|| ''`-equivalent patterns used elsewhere in the file — verify `/^IMAGES_STALE\b/.test(errorMessage || '')` is used, not a bare `.test(errorMessage)`).

## Task List

1. In `dashboard/src/lib/prState.js`: remove `IMAGES_STALE` from the `MIRRORED_REFUSALS` regex (it's no longer blindly hidden) and update the comment above it to say it lists only codes the function re-derives live above this point.
2. Add a new explicit branch, placed between the existing `GITHUB_OUTAGE` check and the generic `MIRRORED_REFUSALS`/`error` fallback (i.e. before line ~179 in the current file): matches `/^IMAGES_STALE\b/` against `errorMessage` when `status === 'error'`, returns `base('images-stale', 'blocked', 'Images are older than the latest change', errorMessage, 'disabled', 'enabled')`. Comment explains why this one can't be verified live (needs the gate's `gh api compare`, unlike the other seven mirrored codes).
3. Write/extend the tests in `dashboard/test/pr_state.test.js` listed above (items 1–8) — run them first against the unmodified code to confirm item 1 currently fails (reproduces the bug), then make them pass with step 2's change.
4. Run the full `dashboard` test suite (`npm test` in `dashboard/`) to confirm no regression in the other `describePrState` consumers (`mr_groups.js`, `next_step.js`, `MrReview.jsx`).
5. Update `CONTEXT.md:1678-1682` ("A PR card says one thing") to name all eight mirrored-but-verifiable codes accurately (`SENT_BACK, CI_PENDING, CI_FAILED, WRONG_BASE, NO_UI_EVIDENCE, IMAGES_UNPINNED, DECISIONS_PENDING, DECISIONS_UNSTRUCTURED`) and add a line noting `IMAGES_STALE` is deliberately shown as its own blocked state ("Images are older than the latest change") because the card cannot re-verify it without the gate's GitHub comparison.
6. Manually exercise the new state in the dashboard (via the existing PR-fixture/dev-mode path already used elsewhere in this file, e.g. `index.js:1034`'s single-PR preview) to confirm the card renders correctly, then take screenshots at 900px and 1440px and pin them to the PR per acceptance criterion 2.
7. Open the PR with `Closes G-Eskayo/marvin#807`, linking the pinned screenshots.