## North-star fit

**Reuses:** three existing patterns, no new mechanism invented.
- `createChangeDetector` in `dashboard/webhook-server/gh_watch.js:28` (the ETag/identity-diff detector already powering "Triggers over polling", CONTEXT.md:879) — generalized with an `identity` param (default `newestIdentity`, zero behavior change for its one existing caller) so it can also watch a single PR's head sha, not just a repo's newest issue.
- `mergeOps` in `dashboard/electron/main/merge_ops.js` (already holds every 'reengaged' op with its stuck `head`, and already has a `mergingUrls()`-shaped accessor to copy for a new `reengagedUrls()`) and `opForHead` in `dashboard/src/lib/merge_progress.js:145` (already correctly clears a stale op to idle **once given a fresh head** — proven by existing tests in `merge_ops.test.js`, "a failure clears once a new commit is pushed"). The bug is entirely upstream of this: nothing ever hands it the fresh head.
- `startPrCheckWatch`'s exact wiring shape in `electron/main/index.js:307` (`onChange: (repo) => { githubChanged(...); mainWindow?.webContents.send('mr:refresh') }`) — copied verbatim as the new watch's `ping`, so a detected head-change reaches the card through the same refresh path every other GitHub-change trigger already uses. No new IPC message, no new renderer code.

**Diagnosis, confirmed against real data (not assumed):** pulled PR #578's actual GitHub timestamps (`gh pr view 578 --json commits,updatedAt,mergedAt`). Its fix commit `ea78a1a9` was committed at `2026-10-26T17:18:11Z`; `updatedAt` stayed `2026-10-26T17:28:55Z` — identical to `mergedAt`. **A push to a PR branch does not bump the PR/issue's `updated_at`**; GitHub only moved it when the PR merged. So `gh_watch.js`'s per-repo "newest issue identity" never changes on a bare push (same failure class as marvin#555's check-watch problem, CONTEXT.md:893: "checks starting or finishing are not issue updates, so the change-detector never sees them" — here it's heads, not checks). The MR list is never told to refresh, `pr.headRefOid` stays stale, `opForHead`'s `head !== op.head` guard never fires, and the only fallback is `githubState`'s unrelated 30-minute safety refresh (`electron/main/index.js:229`) — far short of "within one change event."

**Simplest sufficient fix:** a second, narrowly-scoped ETag poll (identical cost shape to the existing check-watch: one conditional GET per watched PR per ~20s tick, free on 304), watching only PRs currently shown as 'reengaged' in `mergeOps` — typically zero or one at a time, not every open PR. Entirely client-side (Electron main); the webhook-server's merge queue has no stale-state problem of its own (a fresh Approve always re-runs the gate from GitHub's current state), so it needs no changes.

**Spends:** one new `setInterval`-wrapping call site in `electron/main/index.js`, which `dashboard/test/polling_guard.test.js`'s enforced allowlist (marvin#556) will catch — its count for that file must go from `[1, ...]` to `[2, '...']` with a one-line reason, exactly as every other legitimate new trigger source in this codebase already does (see `webhook-server/index.js`'s count of 3). This is a required, expected edit, not a workaround.

**Deny guard** reuses `merge.js`'s existing `gh pr view --json state`/`--json baseRefName` shape (`assertTargetsBase`, `readyIfDraft`) but inverts its "a lookup hiccup never blocks" policy on purpose: the ticket's attack list requires **fail-closed** here (refuse when GitHub can't be read), the opposite of the merge-time checks' fail-open policy, because the risk is asymmetric — a missed merge-time check just fails loudly at `gh pr merge`; a missed deny-time check silently mutates a ticket that may already be done.

**Leaves Gil more capable:** he stops having to notice a stranded PR and merge it by hand on github.com, and stops needing to manually clean up mislabeled closed tickets after a stale `/deny` — both were his own manual workarounds for gaps the system should close itself (north star 3).

## Decisions

None. The ticket, CONTEXT.md's "Triggers over polling" decision, and the evidence above fully determine the approach; no open design choice needs the owner's input.

## Tests (written first)

**gh_watch.js — generalizing the detector (new, in `dashboard/test/gh_watch.test.js`)**
1. `createChangeDetector({..., identity})` with no `identity` passed still behaves exactly as today (regression guard for the one existing caller) — rerun the full existing suite unchanged.
2. A custom `identity` fn drives `onChange`: fires when the PR's head sha changes, not the issue identity.
3. `headIdentity(body)`: returns the sha for a well-formed `{head:{sha}}` pull body; returns `undefined` for a missing/malformed `head` (malformed input) — detector then "ignores and keeps last state," never crashes.
4. `createPullHeadProbe`: sends the ETag conditionally against `GET /repos/{repo}/pulls/{number}`; a 304 reads no body; a 200 extracts only `.head.sha`.
5. `createPullHeadProbe` + detector: a probe that throws (offline / rate-limited — dependency failing) is ignored, state kept, next tick still fires on a real subsequent change (mirrors the existing "ignores probe failures... still fires for a real change" tests at lines 101–121, re-run for this identity).
6. A **force-push** (sha replaced, no relation to the old one) fires `onChange` exactly like a normal push — no special-casing needed, explicit test anyway per the ticket's attack list.
7. Two watched PRs, only one's head changes (**"a push to a different PR: this card stays as it was"**) — `onChange` fires only for that key (reuses the existing "tracks each repo separately" shape, line 92, retargeted at PR-url keys).
8. A repo/PR that drops out of the watched set and comes back is treated as first-sight, not a change (reuses existing "forgets repos that left the registry" test, line 123).

**merge_ops.js (new, in `dashboard/test/merge_ops.test.js`)**
9. `reengagedUrls()` returns exactly the PR urls whose op is `state === 'reengaged'`, not `merging`/`merged`/`error`/etc., and reflects multiple independent PRs correctly (repeats/concurrency: two reengaged PRs tracked independently, same shape as the existing "tracks PRs independently" test at line 38).

**deny.js — the open-state guard (new, in `dashboard/test/deny.test.js`)**
10. `/deny` (`send_feedback`) on a PR GitHub reports as `MERGED`: refused, and `exec` is never called with `pr comment`, `issue comment`, `issue edit`, or any label/claim-release call (**"adds no label or comment anywhere"**).
11. `/deny` (`drop`) on a PR GitHub reports as `CLOSED`: same — refused, no `pr close`/`issue close`/label calls.
12. `/deny` on a PR GitHub reports as `OPEN`: proceeds exactly as today (regression guard — existing `sendFeedback`/`dropEntirely` tests must keep passing unchanged).
13. **Fail closed:** `gh pr view --json state` throws (GitHub unreachable, bad credentials, rate-limited — dependency failing): refused with a plain reason, no writes attempted — opposite of `assertNotSentBack`'s fail-open policy, explicit test to lock in which policy applies here.
14. A malformed/non-GitHub `prUrl` (bad input): still refused by the existing `assertGithubPrUrl` check, unaffected by the new guard's placement.
15. `/deny` on a PR merged **seconds ago** (stale list case from the ticket) behaves identically to test 10 — same mechanism, named explicitly to match the ticket's wording.

**mr_review.js — denyMr surfaces the real reason (new, in `dashboard/test/mr_review.test.js`)**
16. `denyMr` on a non-ok response with a JSON `{error: "..."}"` body throws an Error carrying that message, not the bare `"Webhook call failed: 500"` (mirrors `approveMr`'s existing `describeApproveFailure` fix, 2026-10-02 comment at mr_review.js:350 — the same class of bug, now in the sibling function).
17. `denyMr` falls back to `"Webhook call failed: ${status}"` when the body isn't JSON or has no `error` field (regression guard, mirrors existing approveMr fallback test at line 375).

**polling_guard.test.js — the enforced trigger-vs-poll gate (edit, required by marvin#556)**
18. Confirm the full guard suite still passes once `ALLOWLIST['electron/main/index.js']` is updated from `{interval: [1, ...]}` to `{interval: [2, '...starts the reengaged-PR head watch (marvin#678): same ETag pattern as the check watch, watching heads of PRs the gate sent back so a pushed fix clears "sent back" without the 30-min safety refresh']}` — this is the test that would have caught a previous attempt skipping this edit.

## Task List

1. `dashboard/webhook-server/gh_watch.js`: add an `identity = newestIdentity` parameter to `createChangeDetector`; thread it through to the one place it's used (the `previous.identity !== identity` comparison). Add `pullHeadEndpoint(repo, number)`, `headIdentity(body)`, and `createPullHeadProbe(env, doFetch)` (conditional GET on `/repos/{repo}/pulls/{number}`, body reduced to `{sha: json.head?.sha ?? null}`). Thread the same `identity` param (and an optional `skip`, mirroring `startCheckWatch`'s existing one) through `startChangeWatch`, default-preserving its one existing caller in `webhook-server/index.js`.
2. `dashboard/electron/main/mr_repos.js`: add `prNumberFromUrl(url)` next to the existing `repoFromPrUrl` (same regex style as merge.js's private `prNumberOf`), exported for reuse by the new probe.
3. `dashboard/electron/main/merge_ops.js`: add `reengagedUrls: () => [...ops].filter(([, o]) => o.state === 'reengaged').map(([url]) => url)` to the returned object, next to the existing `mergingUrls()`.
4. `dashboard/electron/main/index.js`: import `startChangeWatch`, `createPullHeadProbe`, `headIdentity` from `../../webhook-server/gh_watch.js` (extend the existing import line). Add `startReengagedHeadWatch()` (guarded by the existing `pullOnly` check, same as `startPrCheckWatch`): `startChangeWatch({ getRepos: () => mergeOps.reengagedUrls(), probe: createPullHeadProbe(), identity: headIdentity, skip: () => Date.now() < gateCooldownUntil(), ping: (prUrl) => { githubChanged(\`github:${repoFromPrUrl(prUrl)}\`); mainWindow?.webContents.send('mr:refresh') } })`. Call it alongside `startPrCheckWatch()` at startup.
5. `dashboard/test/polling_guard.test.js`: bump `ALLOWLIST['electron/main/index.js']`'s interval count 1 → 2 with the one-line reason above.
6. `dashboard/webhook-server/deny.js`: add `assertPrOpen(prUrl, exec)` (throws with a plain message on a non-OPEN state, and throws — fail closed — if the `gh pr view --json state` call itself fails). Call it at the top of `handleDenyRequest`, after the existing `action` validation and before dispatching to `sendFeedback`/`dropEntirely`.
7. `dashboard/electron/main/mr_review.js`: add `describeDenyFailure(status, body)` (`body?.error || \`Webhook call failed: ${status}\``, mirroring `describeApproveFailure`'s shape) and use it in `denyMr`'s non-ok branch instead of the bare status message.
8. Write all tests in the list above (items 1–18), confirm the full `dashboard` test suite (not just the new/touched files) still passes, and confirm the PR description states the diagnosis (the `updated_at`-on-push finding) per the acceptance criteria.