## North-star fit

**Reuses:** `opForHead`/`createMergeOps.get` in `dashboard/electron/main/merge_ops.js` (already correct and already tested, `dashboard/test/merge_ops.test.js:64-99`) and the existing "card subscribes; it does not poll" source-wiring test pattern in `dashboard/test/merge_progress_view.test.jsx:99-108`. For deny, reuses `approveMr`/`describeApproveFailure`'s "parse the JSON failure body" pattern (`dashboard/electron/main/mr_review.js:442-472`) and the `PROBES` dict pattern in `lib/purpose_metrics.py:442-475`. Nothing new is invented at the architecture level — this is a wiring fix, not a new mechanism.

**Diagnosis (supersedes the ticket's "likely cause"):** I reproduced this by reading, not guessing. `gh_watch.js`'s change detector already fires correctly on a push with no comment (`dashboard/test/gh_watch.test.js:41-48`, "fires when the newest issue was updated, even under the same etag") — that hypothesis is wrong, no change needed there. The real bug: `dashboard/electron/main/mr_review.js`'s `listPipelinePrs` (line 416) exposes a PR's head commit to the renderer as `headSha`, added by #938 (`20b06563`) — before that commit, the card had **no head field at all**. But `dashboard/src/components/MrReview.jsx`'s `ApproveDenyActions` and `PrQueueLine` have read `pr.headRefOid` since `d49cf2df` (2026-10-21), which predates `headSha`'s existence. `pr.headRefOid` is `undefined` on every real card, always has been. `opForHead(op, head)` (`dashboard/src/lib/merge_progress.js:149`) only clears to idle when `head && op.head && head !== op.head` — with `head` permanently `undefined`, that condition can never be true, so a `reengaged`/`error` status can never clear itself, exactly matching #578's symptom. This is deterministic, not timing-dependent, which fits "stayed stuck until Gil manually merged" better than a probe-polling race would.

**Simplest sufficient fix:** change 6 call sites in one file (`MrReview.jsx`) from `pr.headRefOid` to `pr.headSha` — the field the data layer already correctly produces and that `MockupLauncher.jsx:22` already reads correctly. No renaming elsewhere, no new fields, no touching `gh_watch.js` or `merge_ops.js` (both already correct and tested).

**Tokens/cost:** spends a little now (one diagnose-first read) to save a lot later — this bug has presumably caused every "fix pushed, Approve still missing" incident, not just #578, so it's a compounding fix, not a one-off.

**Human experience:** removes a dead end that forced Gil to merge by hand on github.com. More capable, not more passive — restores a button that should have just worked.

**Decisions:** none needed. The ticket's own ambiguity (which of two hypotheses was the real cause) is resolved by evidence above, not by owner choice. Status codes for the new `/deny` refusal (409 "not open", 502 "could not confirm state") are plain implementation detail, not a product choice.

---

## Tests first

1. **Regression/wiring guard** (new `describe` block in `merge_progress_view.test.jsx`, mirroring the existing "does not poll" source-check): assert `ApproveDenyActions` and `PrQueueLine`'s source reads `pr.headSha`, never `pr.headRefOid`.
2. **End-to-end proof, stuck→clears on push**: build a card via `listPipelinePrs` for a PR at `headRefOid: 'sha-old'`, record a failed/reengaged op at that head (`mergeOps.fail`/an equivalent start+fail), then rebuild the card at `headRefOid: 'sha-new'` (simulating the push) and assert `mergeOps.get(url, now, card2.headSha).state === 'idle'`.
3. **A push with no comment or label change**: two successive `listPipelinePrs` builds, only `headRefOid` differs — assert the card's `headSha` differs too (the data layer carries it with nothing else changing). Pairs with test 1 of `gh_watch.test.js` already covering detection.
4. **A force-push**: same as 2/3 — any differing sha clears, not just a descendant commit (string inequality, already how `opForHead` works; add an explicit case so it's not implicit).
5. **A push while the card is unmounted, then remount**: a fresh `mergeOps.get(url, now, newHead)` call (simulating mount-time read with no events received while away) returns idle — no reliance on having "seen" the push live.
6. **A push to a different PR leaves this card alone**: already covered by `merge_ops.test.js:38` ("tracks PRs independently"); add one explicit case at the card level (two PRs, only one's `headRefOid` changes) if not already implied.
7. **`/deny` on a PR merged seconds ago (stale list)**: `handleDenyRequest` fetches live state via `gh pr view <url> --json state` before dispatching; `state !== 'OPEN'` → refusal, zero exec calls to comment/close/label/release.
8. **`/deny` on an already-closed PR**: same path, message says "closed" not "merged".
9. **`/deny` when GitHub can't be reached to read state**: the state-check `exec` call throws → refuse (fail closed), distinguishable from the existing 500 "action itself failed" path. Update `deny.test.js`'s existing 3 passing-path tests to mock the new `gh pr view --json state` call (`state: 'OPEN'`); split the current "returns 500 on dispatch failure" test into (a) state-check failure → new 502-ish fail-closed response, (b) state OPEN but the actual comment/close call fails → existing 500 behavior, unchanged.
10. **Bad/malformed `prUrl`** reaching the new state check: reuse `assertGithubPrUrl`, refuse before any `exec` call (extends the existing "rejects a non-GitHub URL" coverage to `handleDenyRequest` itself, which currently only validates inside `sendFeedback`/`dropEntirely`, after dispatch).
11. **The refusal message actually reaches the owner**: extend `mr_review.test.js`'s `denyMr` tests — a 409 response with JSON body `{error: 'This PR is already merged.'}` must make `denyMr` throw *that* message, not the generic `Webhook call failed: 409` (mirrors `approveMr`'s existing body-parsing test at `mr_review.test.js:375-378`); keep a fallback test for a non-JSON failure body.
12. **Recurrence probe** (`lib/purpose_metrics.py`): a unit test for the new `_stuck_approve_after_push`-style measure function with a synthetic log fixture — a PR logged as approve-failed at head A, never later logged as merged, now open at head B ≠ A within the window, counts 1; a PR that later merged, or whose head never changed, counts 0.

No mocks substitute for GitHub's real state rules in test 9/10 — `assertGithubPrUrl` and the `exec` rejection path are exercised exactly as the real `gh` CLI would behave (non-zero exit → rejected promise), not a stubbed-out success.

---

## Task List

1. **Fix the field mismatch** in `dashboard/src/components/MrReview.jsx`: change all 6 uses of `pr.headRefOid` (lines 255, 257, 261, 267, 512, 516) to `pr.headSha`.
2. **Write test 1** (source-wiring guard) in `dashboard/test/merge_progress_view.test.jsx`.
3. **Write tests 2–6** (push clears stuck Approve, force-push, remount, independent-PR isolation) in `dashboard/test/merge_ops.test.js` and/or `dashboard/test/mr_review.test.js`, using real `listPipelinePrs` output rather than hand-rolled fixtures that assume the fixed field name.
4. **Add the live-state guard to `handleDenyRequest`** in `dashboard/webhook-server/deny.js`: a small `fetchPrState(prUrl, exec)` helper using `gh pr view <url> --json state` (no `--repo`, matching existing call shape); validate the URL first (`assertGithubPrUrl`), then check state before dispatching `send_feedback`/`drop`; refuse non-OPEN with "already merged"/"closed"; refuse (fail closed) if the state check itself throws, with a distinct status/message from the existing 500 dispatch-failure path.
5. **Update `denyMr`** in `dashboard/electron/main/mr_review.js` to parse the failure body's `error` field (mirroring `approveMr`/`describeApproveFailure`) instead of always throwing the bare `Webhook call failed: ${status}`, so the new refusal text reaches `DenyModal`.
6. **Update/add `deny.test.js` cases** per tests 7–10 (mock `pr view --json state` on the 3 existing passing-path tests; split the 500 test into state-check-failure vs. dispatch-failure).
7. **Update/add `mr_review.test.js` cases for `denyMr`** per test 11.
8. **Add the recurrence probe**: a `_stuck_approve_after_push` entry in `lib/purpose_metrics.py`'s `PROBES` dict, backed by a function reading `~/.claude/logs/dashboard-webhook-error.log`/`.log` (reusing `merge_history.js`'s `APPROVE_FAILED`-style parsing as the source of a PR's last-known failed head) cross-checked against each candidate PR's live `state`/`headRefOid`; target limit 0; write test 12.
9. **Write the PR description's diagnosis section**, stating the confirmed root cause (the `headRefOid`/`headSha` naming mismatch, not the change-detector) per AC3, with the specific commits (`d49cf2df`, `20b06563`) as evidence.
10. **Run the full dashboard test suite** (not just the touched files) before opening the PR, per "full suites before a hand-merge."