## North-star fit

**Reuses:** the existing single-cascade pattern in `describeState()` (`dashboard/src/lib/prState.js`) — one ranked list of conditions, first match wins, so only one headline/button-set is ever shown (file header comment, lines 1–8). No new rendering mechanism: `MrReview.jsx` already treats `view.kind`/`view.tone`/`view.approve`/`view.deny` generically (`data-state={view.kind}`, `TONE[view.tone]`, `approve !== 'hidden'`), so adding new `kind` values needs zero changes there or in `mr_review.js`. The only file that changes is `prState.js`.

**Simplest sufficient approach:** the bug is structural, not cosmetic. By the time `describeState` reaches the `status === 'error'` check (prState.js:174), every earlier branch (`sentBack`, `ci.state`, `pr.needsImages`, `decisions`, `pr.baseProblem`) has already run and *not* matched — meaning, for any code in `MIRRORED_REFUSALS`, the card's own fresh check never currently shows an equivalent condition at exactly that point. For `SENT_BACK`/`CI_PENDING`/`CI_FAILED`/`WRONG_BASE`/`DECISIONS_PENDING`/`DECISIONS_UNSTRUCTURED` that's fine: those fresh checks read GitHub-sourced fields (labels, check runs, base ref, decisions parsed from the live body) that the gate reads too, so "not matching anymore" genuinely means "fixed since the refusal" — confirmed by the existing test at `dashboard/test/pr_state.test.js:33-37`, which is correct today and must keep passing.

For `NO_UI_EVIDENCE` / `IMAGES_UNPINNED` / `IMAGES_STALE`, that assumption is false. `needsImages()` (`mr_review.js:264-274`) runs on a local heuristic (`uiPathsFor(repo)`, only when `pr.files` is present) that can disagree with the gate's own `uiFiles()` call in `webhook-server/ui_evidence.js`, and it never checks staleness at all — the comment at `mr_review.js:271` says so explicitly ("Staleness needs GitHub calls, so only the gate checks it"). `opForHead` (`src/lib/merge_progress.js`) already guarantees a displayed refusal belongs to the PR's *current* head commit, so when one of these three codes reaches `MIRRORED_REFUSALS` with nothing else blocking, it isn't stale — it's a live refusal the card simply can't reproduce. Hiding it is the bug (#807's title). The fix: carve these three codes out of `MIRRORED_REFUSALS` and give them their own blocked state, shown as the gate reported it, instead of assuming the card already said the same thing.

**Tokens:** small, surgical diff in one file (~20 lines), no new dependency, no new GitHub calls, no architecture change.

**Phone-OS direction:** neutral — this is dashboard-UI correctness, not reach/linkability.

**More capable or passive:** more capable — the owner stops seeing a false "Ready to merge" and gets the actual reason Approve would fail again, so he isn't surprised by a second refusal or, worse, doesn't notice and leaves it sitting as "Ready" indefinitely.

## Decisions

<!-- marvin:decisions -->
### scope: Apply "show instead of hide" to all seven MIRRORED_REFUSALS codes, or only the three image codes?
- [ ] A: Only NO_UI_EVIDENCE, IMAGES_UNPINNED, IMAGES_STALE (the three where the card's own check can genuinely diverge from the gate's). SENT_BACK/CI_PENDING/CI_FAILED/WRONG_BASE/DECISIONS_PENDING/DECISIONS_UNSTRUCTURED keep today's behavior (hidden once the GitHub-sourced fresh check disagrees), matching the existing test at `dashboard/test/pr_state.test.js:33-37`.
- [ ] B: All seven codes — remove the whole `MIRRORED_REFUSALS` hiding mechanism and always show a mirrored refusal as blocked whenever reached, even for the GitHub-sourced codes. This requires rewriting the existing test (lines 33-37) to expect a blocked state instead of `ready`, and removes the "stale error auto-clears once GitHub-sourced state changes" behavior the file header currently documents as intentional.

I'm proceeding on **A** as the default (it fixes exactly what #807 reports and evidences, and preserves a passing, intentional test), but this is a real behavior-change decision, not a guess, so it's listed for Gil to confirm or override.

## Tests (written first)

In `dashboard/test/pr_state.test.js`, extending the existing `describePrState` suite:

1. **(Ticket's own break-it case) Refusal, then a new push that fixes it:** a PR with an `IMAGES_STALE` refusal and `status: 'error'` renders blocked; the same PR with `status: 'idle', errorMessage: null` (what `opForHead` produces once `pr.headRefOid` changes) renders `ready`. Models the full sequence, not just the end state.
2. **The core bug, one case per code:** for each of `NO_UI_EVIDENCE`, `IMAGES_UNPINNED`, `IMAGES_STALE`, a PR with no other blocker (`ready` baseline) and `status: 'error', errorMessage: '<CODE> at request: ...'` must render `kind !== 'ready'` and `approve !== 'enabled'` (currently it renders `ready` with `approve: 'enabled'` — this is the reported defect, reproduced).
3. **`IMAGES_STALE` gets the named state:** same setup, asserts `kind: 'images-stale'`, `headline: 'Images are older than the latest change'`, `detail` containing the gate's own message, `approve: 'hidden'`.
4. **`NO_UI_EVIDENCE`/`IMAGES_UNPINNED` fall back to the existing "Needs images" presentation:** `kind: 'needs-images'`, `approve: 'hidden'`, `deny: 'enabled'`, `detail` containing the gate's message.
5. **Regression lock — the four GitHub-sourced codes still resolve to `ready` once their fresh check is clean:** keep the existing test (`SENT_BACK`, `CI_PENDING`, `CI_FAILED`, `WRONG_BASE`) passing unchanged; add `DECISIONS_PENDING` and `DECISIONS_UNSTRUCTURED` to that same loop (they're in `MIRRORED_REFUSALS` but weren't covered by the existing test).
6. **Priority: a real, independent blocker still wins over a leftover image refusal.** `conflicts: true` (or `checks.state: 'failing'`) together with `errorMessage: 'IMAGES_STALE at request: ...'` → `kind` is `conflict` (or `checks-failed`), not `images-stale`. Confirms the new checks are inserted without jumping the existing cascade's priority order.
7. **An unmirrored, genuinely novel error still shows as a real failure.** Existing `MERGE_REFUSED` test must keep passing unchanged (`kind: 'error', approve: 'enabled'`).
8. **Malformed/empty input:** `status: 'error', errorMessage: null` and `status: 'error', errorMessage: ''` must not throw and must fall through to whatever the rest of the cascade says (no crash from `.test()` on a falsy value inside the new code paths).
9. **Near-miss code name (person's/gate's typo) must not false-match:** `errorMessage: 'IMAGES_STALENESS at request: ...'` (not a real code) must NOT be treated as `images-stale` — it's unmirrored, so it falls through to the generic `error` kind. Guards the `\b`-bounded regex against accidental over-matching.
10. **`GITHUB_OUTAGE` is unaffected:** keep the existing outage test passing — confirms the new checks sit after it in the cascade, not before.

No dependency/mocking concerns here: `describePrState` is a pure function over plain objects, so these are direct, unmocked unit tests — nothing to fake that could hide real gate behavior.

## Task List

1. In `dashboard/src/lib/prState.js`, shrink `MIRRORED_REFUSALS` to just `SENT_BACK|CI_PENDING|CI_FAILED|WRONG_BASE|DECISIONS_PENDING|DECISIONS_UNSTRUCTURED`, and add two new regexes: `IMAGES_STALE_REFUSAL = /^IMAGES_STALE\b/` and `IMAGE_EVIDENCE_REFUSAL = /^(NO_UI_EVIDENCE|IMAGES_UNPINNED)\b/`. Update the file-header/inline comment to explain why these three are excluded (card's own check can diverge from the gate's; staleness isn't computed client-side at all).
2. In `describeState()`, right after the existing `GITHUB_OUTAGE` check (around line 174-177) and before the generic non-mirrored `status === 'error'` block (line 179), insert:
   - `if (status === 'error' && IMAGES_STALE_REFUSAL.test(errorMessage || ''))` → `base('images-stale', 'blocked', 'Images are older than the latest change', errorMessage, 'hidden', 'enabled')`.
   - `if (status === 'error' && IMAGE_EVIDENCE_REFUSAL.test(errorMessage || ''))` → `base('needs-images', 'blocked', 'Needs images', errorMessage, 'hidden', 'enabled')`.
3. Write/run the ten tests above in `dashboard/test/pr_state.test.js` against the change; confirm the full dashboard test suite still passes (`npm test` in `dashboard/`), not just this file, per the "run ALL suites" rule for anything touching shared state logic.
4. Take screenshots of a card in the new "Images are older than the latest change" state (and, if the "Needs images" fallback path renders visibly differently in context, that one too) at 900px and 1440px, pin them to the PR's commit, per acceptance criterion 2.
5. Open the PR with the Decisions section above (scope A vs B) carried over verbatim, and reference marvin#807 and marvin#743.