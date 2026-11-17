Now I have the full picture. Here's the plan.

## North-star fit

**Reuses before adding anything new:**
- `opForHead` (`dashboard/src/lib/merge_progress.js:145`) already clears a finished-but-blocking op (`error`/`interrupted`/`reengaged`) back to `idle` once the PR's head differs from the op's recorded head. This already works correctly — the bug is that the UI's `pr.headRefOid` never gets refreshed, because nothing tells `githubState` (`electron/main/github_state.js`) that the repo changed. No change needed in `opForHead` or `MrReview.jsx`'s approve logic.
- The conditional-GET-with-ETag watcher shape (`createCheckWatcher`/`startCheckWatch`, `dashboard/webhook-server/gh_watch.js:135-218`) is reused structurally for a new, narrowly-scoped watcher (same running-guard, same Map-based ETag cache, same `onChange(repo)` callback into `githubChanged()`), rather than inventing a new polling mechanism.
- `describeApproveFailure` (`electron/main/mr_review.js:442`) — the existing fix for "Webhook call failed: 500 hid the real reason" — is mirrored for `denyMr`, which still has that exact bug today.
- `repoFromPrUrl` (`electron/main/mr_repos.js:43`) is reused; a sibling `numberFromPrUrl` is added next to it rather than re-deriving PR numbers ad hoc.
- `mergeOps` (`electron/main/merge_ops.js`) already tracks each stuck op's `head`; a new accessor is added to it rather than duplicating its state elsewhere.

**Why this is the simplest sufficient approach:** The ticket's own hypothesis (gh_watch.js's whole-repo "newest issue" identity watch may not see a bare push) is plausible but only an elegant fix *if* confirmed — and even if confirmed, patching that shared, already-fragile detector (marvin#603/#604 edge cases) to special-case PR pushes is a wider blast radius than necessary. A small watcher that polls only the handful of PRs currently showing a stuck merge op, against the one GitHub endpoint that unambiguously reflects a push (`/pulls/{number}`, whose `head.sha` is exactly what we need to compare), is correct by construction regardless of the issues-endpoint's exact `updated_at` semantics, and only costs extra GitHub calls when something is actually stuck (usually zero). This is the Colton-check form: watch the thing that's actually stuck, not the whole repo's firehose.

**Token/resource cost:** Spends a small number of extra ETag'd GitHub calls (free on a 304) only while a PR sits in `error`/`interrupted`/`reengaged`; at rest it costs nothing. Saves the owner a manual GitHub merge and saves future debugging tokens by fixing the root cause instead of adding a UI-side timeout/band-aid.

**Phone-OS direction:** A review screen that never silently strands a ready PR is a precondition for any "notify the owner, they tap Approve from anywhere" flow — this removes a case where the dashboard quietly lied about PR state.

**User capability:** Makes the owner strictly more able to trust the dashboard's Approve button; it removes a forced manual escalation to github.com, not a decision the owner should be making themselves.

## Diagnosis task (confirm before coding)

Task 1 below writes a small disposable script against a real test PR (push a commit with no comment, then poll `GET /repos/{repo}/issues?...` and compare against `GET /repos/{repo}/pulls/{number}`) to confirm whether the issues endpoint's `updated_at` reflects a bare push. The result goes in the PR description per the acceptance criteria, but the fix itself (the new head watcher in Task 3+) is correct either way, since it doesn't depend on the answer.

## Tests to write first

**`test/gh_watch.test.js`/new `test/head_watch.test.js` — `createHeadWatcher`/`createHeadProbe`/`startHeadWatch`:**
1. A 304 (head unchanged) never fires `onChange`, resends the stored etag next tick.
2. A 200 whose `head.sha` differs from the tracked PR's head fires `onChange(repo)`, once.
3. A 200 with the same head (only the etag moved) does not fire.
4. The very first probe answer already differs from the op's recorded head — fires on tick 1 (the direct "push with no comment" case: the op's head was already stale the moment it was created).
5. A force-push (head moves to a SHA never seen before) fires, same as any other head change.
6. A PR that leaves the "stuck" list between ticks (approved, cleared, or its head already updated) is forgotten — no further probes, its etag dropped.
7. A throwing/offline probe: keeps the last known etag, never fires, `tick` never rejects.
8. A non-200/304 status (403/502): ignored, state kept.
9. Two different stuck PRs are tracked independently: a change on one fires `onChange` for its repo only — "a push to a different PR: this card stays as it was."
10. `createHeadProbe`: sends `If-None-Match` conditionally, `Authorization` from `GH_TOKEN`, reads `head.sha` only on 200, and a non-JSON/odd 200 body yields `head: undefined` without throwing.
11. `startHeadWatch`: a slow tick never stacks (second concurrent `run()` is a no-op) — mirrors `startCheckWatch`'s guard.
12. `startHeadWatch` makes no probe calls while `skip()` is true (gate cooling down).

**`test/merge_ops.test.js` — `mergeOps.stuckHeads()`:**
13. An op in `reengaged` with a head → returned as `{repo, number, head}`.
14. Ops in `merging`, `queued`, `waiting-memory`, `merged`, or absent (`idle`) → excluded.
15. `error` and `interrupted` states → included.
16. A URL that doesn't parse to a repo/number → skipped, not thrown.
17. No ops → `[]`.

**`test/deny.test.js` — `handleDenyRequest` open-state guard:**
18. PR state `MERGED` → 409, `{done:false, error: '<url> is already merged.'}`; no `pr comment`/`issue edit`/`pr close` calls made.
19. PR state `CLOSED` → refusal naming "closed", same no-side-effects guarantee.
20. PR state `OPEN` → existing `send_feedback`/`drop` behavior unchanged (update the two existing happy-path tests' `exec` mocks to answer the new `gh pr view <url> --json state` call).
21. The state-check `exec` call rejects (GitHub unreachable) → fails closed: refuses (503) with a plain "could not confirm ... refusing to deny" message, no side-effect calls attempted.
22. The state-check returns unparsable JSON → treated the same as unreachable (fail closed), not a crash.
23. `action: 'unknown'` still short-circuits to 400 before any `gh` call (regression — guard sits inside the dispatch, after action validation).
24. A real failure in `sendFeedback`/`dropEntirely` *after* the state check passes still returns 500 with the existing error shape (guard doesn't swallow genuine failures).

**`test/mr_review.test.js` — `denyMr` / new `describeDenyFailure`:**
25. `describeDenyFailure(status, {error: 'already merged'})` → `'already merged'`.
26. `describeDenyFailure(status, null)` / body without `.error` → falls back to `'Webhook call failed: <status>'`.
27. `denyMr` on a non-ok response with a JSON `{error: '...'}` body throws an Error with that exact message (not `'Webhook call failed: 409'`).
28. `denyMr` on a non-ok response with no/unparsable body still throws the generic fallback (regression, no crash).

## Decisions
None — the design choices above (targeted head-watcher vs. patching the generic issue watcher; 409 vs 503 for the two refusal cases) are implementation judgment calls, not product choices for the owner.

## Task List

1. **Diagnose (live, before coding):** confirm whether a bare push to a PR branch (no comment, no label) changes what `GET /repos/{repo}/issues?state=all&sort=updated&direction=desc&per_page=1` returns as the newest issue, using a disposable test PR. Write the finding into the eventual PR description.
2. Add `numberFromPrUrl(url)` next to `repoFromPrUrl` in `dashboard/electron/main/mr_repos.js`.
3. Add `pullEndpoint`, `createHeadWatcher`, `createHeadProbe`, `startHeadWatch` to `dashboard/webhook-server/gh_watch.js`, modeled on `createCheckWatcher`/`createCheckProbe`/`startCheckWatch`. Write tests 1–12.
4. Add `stuckHeads()` to `createMergeOps` in `dashboard/electron/main/merge_ops.js` (filters `error`/`interrupted`/`reengaged` ops with a recorded head, maps to `{repo, number, head}` via `repoFromPrUrl`/`numberFromPrUrl`). Write tests 13–17.
5. Wire `startStuckHeadWatch()` in `dashboard/electron/main/index.js` next to `startPrCheckWatch()`: `getPrs: () => mergeOps.stuckHeads()`, `probe: createHeadProbe()`, `onChange: (repo) => { githubChanged(\`github:${repo}\`); mainWindow?.webContents.send('mr:refresh') }`, `skip: () => Date.now() < gateCooldownUntil()`; guarded by the same `pullOnly` early-return as `startPrCheckWatch`.
6. Add the open-state guard to `handleDenyRequest` in `dashboard/webhook-server/deny.js`: read `gh pr view <prUrl> --json state` before dispatching to `sendFeedback`/`dropEntirely`; refuse with 409 (`not OPEN`) or 503 (unreadable/unparsable, fail closed), touching no labels or comments. Write tests 18–24, updating the two happy-path tests' exec mocks.
7. Add `describeDenyFailure(status, body)` to `dashboard/electron/main/mr_review.js` (mirrors `describeApproveFailure`) and use it in `denyMr`'s non-ok branch instead of the bare `Webhook call failed: ${status}`. Write tests 25–28.
8. Run the dashboard test suite (`dashboard`'s vitest) and confirm all new and existing tests pass.
9. Write the PR description with the diagnosis finding from Task 1, naming #678's acceptance criteria explicitly.