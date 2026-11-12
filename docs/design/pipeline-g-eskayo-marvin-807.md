## North-star fit

- **Reuses:** `describeState`'s existing `base()` helper, kind/tone/approve/deny vocabulary, and early-return ordering in `dashboard/src/lib/prState.js`; the already-shared `webhook-server/decisions.js` module (confirms `DECISIONS_PENDING`/`DECISIONS_UNSTRUCTURED` are genuinely self-verifying, unlike the image codes); and the existing SHA-keyed staleness clearing in `electron/main/merge_ops.js` (marvin#559, already tested in `merge_ops.test.js:71-83`) — that mechanism, not `prState.js`, is what already handles the ticket's one listed "how we'll break it" case ("Refusal, then a new push that fixes it"), and this fix doesn't touch it. `MrReview.jsx`'s generic `view.kind/tone/approve/deny` rendering (already data-driven) needs no changes — no new component logic.
- **Why simplest sufficient:** CONTEXT.md's own recorded decision (line 1681) names exactly four codes as safe to auto-clear: `SENT_BACK, CI_PENDING, CI_FAILED, WRONG_BASE`. The code's `MIRRORED_REFUSALS` regex had silently grown to include two more (`DECISIONS_PENDING`, `DECISIONS_UNSTRUCTURED` — verified still safe, same shared `decisions.js` on both sides) and three that are *not* safe (`NO_UI_EVIDENCE`, `IMAGES_UNPINNED`, `IMAGES_STALE` — the dashboard's own `needsImages()` in `mr_review.js:264-274` depends on a caller-supplied per-project path list that can diverge from the gate's (`ui_evidence.js`'s `assertUiEvidence`, called from `merge.js:661`'s project-specific-paths addition — tracked unresolved in #743), and never computes staleness at all ("Staleness needs GitHub calls, so only the gate checks it", `mr_review.js:271`)). Rather than building a generic "replay every native check" framework, this narrows the safe-to-hide set back to what's actually self-verifying and adds two small dedicated branches for the three that aren't — the smallest change that matches the documented invariant.
- **Token/cost:** one surgical diff to `prState.js` (~15 lines) + its test file + one CONTEXT.md paragraph. No new files, no new dependencies.
- **Leaves Gil more capable, not more passive:** stops the dashboard from silently clearing to "Ready to merge" / Approve-enabled after a real, still-live gate refusal it can't independently verify — it now fails closed and shows the gate's own message, so he isn't misled into clicking Approve on something that will just be refused again.
- Runs via the normal Vitest suite (`dashboard/test`), no specific machine.

## Tests first (dashboard/test/pr_state.test.js)

Covering the ticket's "How we'll try to break it" item plus the misuse cases it didn't spell out:

1. **The ticket's own case — already covered, confirm no regression:** a `CI_FAILED`/`SENT_BACK`/etc. refusal, then the underlying state clears (existing `'and once that state clears, the stale refusal does not come back'` test) — keep passing unchanged; this is genuinely handled upstream in `merge_ops.js` for the SHA-level case, and in `prState.js` for the same-render case. Extend that test's loop to also cover `DECISIONS_PENDING`/`DECISIONS_UNSTRUCTURED` (newly confirmed safe), locking in that the narrowed regex still clears them.
2. **`NO_UI_EVIDENCE` reaching the card with no native `needsImages`** (list mismatch or already-fixed-elsewhere): `status: 'error', errorMessage: 'NO_UI_EVIDENCE at ui_evidence: ...'` on an otherwise-clean `pr` → must NOT become `kind: 'ready'`; must be `kind: 'needs-images', tone: 'blocked', approve: 'disabled', deny: 'enabled'`, `detail` containing the gate's own message.
3. Same for **`IMAGES_UNPINNED`**.
4. **`IMAGES_STALE`** (never computed natively at all): `status: 'error', errorMessage: 'IMAGES_STALE at ...'` → `kind: 'images-stale', headline: 'Images are older than the latest change', tone: 'blocked', approve: 'disabled', deny: 'enabled'`.
5. **Precedence / no double-render:** when `pr.needsImages` IS truthy (native check agrees) and `status === 'error'` carries `NO_UI_EVIDENCE`/`IMAGES_UNPINNED` too — the native `'needs-images'` branch (approve `'hidden'`) must win; the new fallback branch must never override an already-correct native state.
6. **Malformed input — anchoring guard:** an `errorMessage` that merely *mentions* `IMAGES_STALE`/`NO_UI_EVIDENCE` without it being the leading code (e.g. `'MERGE_REFUSED at merging: see IMAGES_STALE docs'`) must NOT trigger the new branches — falls through to generic `'error'`, approve enabled.
7. **Empty/missing input:** `status: 'error', errorMessage: null` and `errorMessage: ''` must not throw and must fall through to `'ready'` (or whatever the clean `pr` otherwise shows) — no crash, no stuck blocked state from nothing.
8. **A person's mistake / combined state — draft interaction:** a draft PR (`isDraft: true`) hit with `IMAGES_STALE` → `describePrState`'s draft wrapper still forces `approve: 'hidden'` (not `'disabled'`), consistent with existing draft handling, so the new state doesn't leak a clickable-looking Approve on a draft.
9. **Repeat/idempotence (cheap, pure-function sanity):** calling `describePrState` twice with identical input yields identical output (guards against any accidental hidden mutation when I touch the regex/branches).

## Decisions

None — the acceptance criteria already specify the exact behavior (blocked, Approve disabled) and the exact new headline text ("Images are older than the latest change"), so there's nothing left for Gil to choose.

## Task List

1. In `dashboard/src/lib/prState.js`: narrow `MIRRORED_REFUSALS` to `SENT_BACK|CI_PENDING|CI_FAILED|WRONG_BASE|DECISIONS_PENDING|DECISIONS_UNSTRUCTURED` (confirmed self-verifying — derived straight from the same `pr` data / shared `decisions.js` the gate uses, no duplicate list).
2. Add two dedicated branches in `describeState`, placed right after the existing `GITHUB_OUTAGE` check and before the generic `MIRRORED_REFUSALS`/`'error'` fallback:
   - `NO_UI_EVIDENCE`/`IMAGES_UNPINNED` → `kind: 'needs-images', tone: 'blocked', headline: 'Needs images', detail: errorMessage, approve: 'disabled', deny: 'enabled'`.
   - `IMAGES_STALE` → `kind: 'images-stale', tone: 'blocked', headline: 'Images are older than the latest change', detail: errorMessage, approve: 'disabled', deny: 'enabled'`.
3. Update the file's top comment (lines 10-11) to state the narrower, accurate scope of what's safe to auto-clear vs. the three codes that are always shown.
4. Write the tests above in `dashboard/test/pr_state.test.js` (TDD: write and watch them fail against current code first).
5. Implement steps 1-2, make the new/extended tests pass, run the full `dashboard` test suite (not just this file) to confirm no regression elsewhere (e.g. `mr_review.test.js`, `merge_ops.test.js`).
6. Update `CONTEXT.md:1681` to match the corrected, documented set of auto-cleared codes and mention the new `needs-images`/`images-stale` blocked fallback.
7. Run the dashboard locally, drive a PR card into each of the three new states (can be done by stubbing/mocking the approve webhook response rather than needing a real gate refusal), and capture screenshots at 900px and 1440px; pin them to the PR per `docs/agents/showing-things.md`.
8. Open the PR, citing #807 and noting #743 as the still-open root-cause ticket for the dashboard/gate UI-path-list duplication this fix works around rather than resolves.