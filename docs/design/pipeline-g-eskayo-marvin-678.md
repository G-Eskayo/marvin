## North-star fit

- **Reuses before adding anything new:**
  - `createCheckWatcher` / `startCheckWatch` (`dashboard/webhook-server/gh_watch.js:135-218`) — the ETag-conditional-GET watcher pattern (watch a small candidate set, free 304s, swallow-and-retry on error). The fix extends this *pattern* with a second, narrowly-scoped watcher for stuck PRs' head SHA, rather than widening the generic "newest issue" change detector that marvin#603 already hardened and that `CONTEXT.md` ("Triggers over polling") documents as *not* seeing non-issue-field changes (it already needed the separate check-watch for exactly this reason — checks starting/finishing aren't issue updates either).
  - `opForHead` (`dashboard/src/lib/merge_progress.js:145-151`) and `mr:mergeEvent` (`dashboard/electron/main/index.js`, consumed by `ApproveDenyActions`'s effect at `MrReview.jsx:235-261`) — the client already resets a stuck op to idle the moment it sees a merge op whose `head` is older than the PR's current head. No new client-side state machine; the gap is only that nothing currently *tells* it the head changed when there's no comment/label.
  - `viewPrState` (`dashboard/electron/main/index.js:114`, used by `mergeOps.githubChanged`) — the exact `gh pr view <url> --json state` read, reused in shape for the deny guard.
  - `startPrCheckWatch`'s `if (pullOnly) return` guard (`index.js:308`) — the new head-watch is skipped on the Mini for the same reason (read-only, no merge UI there).
- **Simplest sufficient approach:** a targeted watch over *only* PRs with a currently-stuck merge op (reengaged/error/interrupted) — typically zero — instead of touching the general change detector that every other trigger depends on.
- **Cost:** one extra ETag-conditional GET per ~20s per currently-stuck PR (usually none running); same free-304 property as the existing two watchers. No new polling loop class, no new storage.
- **Leaves the user more capable:** removes the exact manual workaround from 2026-10-26 (merging on github.com by hand) and the false `needs-reengagement` labelling of closed tickets — neither was a judgment call worth making by hand.
- **Where it runs:** the electron main process already holding `mergeOps` (whichever Mac has the dashboard open), and the existing `webhook-server` process for `/deny` — no new host.

No Decisions needed — the ticket fully specifies the fix (file names, functions, and both acceptance criteria); nothing here is a product choice for the owner to pick between.

## Tests to write first

In `dashboard/test/gh_watch.test.js` (new watcher, mirroring `check_watch.test.js`'s structure):
1. A stuck PR (reengaged/error/interrupted) gets a plain push (new head, no comment/label) → the watcher's next tick sees a different `head.sha` and fires `onChange(url)`.
2. A force-push → same (new SHA either way, no special-casing needed).
3. A push to a *different* PR → only that PR's entry changes; an unrelated stuck PR's candidate stays untouched (no false reset).
4. GitHub unreachable / rate-limited mid-tick → the tick swallows the error for that PR, keeps the last-known ETag, and retries next tick; never throws, never fires a spurious `onChange`.
5. Two ticks race on the same PR (a second push lands before the first GET resolves) → no duplicate `onChange` for a SHA that's already been reported.
6. A PR whose op is `queued` or `waiting-memory` (not stuck-on-head, per `opForHead`'s own exception list) is **not** in the candidate set — a push must not cancel a real in-flight approval.
7. A PR removed from GitHub (404) while still tracked → treated like "can't confirm," left alone, not thrown.

In `dashboard/test/merge_ops.test.js`:
8. `stuckOps()` (or equivalent) returns exactly the ops in `reengaged`/`error`/`interrupted`, with their recorded `head`; excludes `idle`/`merging`/`merged`/`queued`/`waiting-memory`.
9. Resetting a stuck op on a confirmed new head clears it to idle and the reset is reflected by `get(url, now, newHead)`.

In `dashboard/test/mr_actions.test.js` or `merge_progress_view.test.jsx` (confirms the already-existing client path really closes the loop once the main process pushes the event — covers the card-unmounted/remounted case):
10. Card unmounted while a PR is `reengaged`, main process resets the op and pushes `mr:mergeEvent`, card remounts later → `mergeState` read on mount already reflects idle (no missed event, no manual refresh) — this is the existing `useEffect`'s "pushed-before-mount-read-resolves" guard (`MrReview.jsx:257-259`); add the regression test if none covers it today.

In `dashboard/test/deny.test.js` (extend the existing suite — every current mock must additionally answer `gh pr view ... --json state`):
11. `/deny` on a PR GitHub reports as `MERGED` → refused (409-style `{done:false, error}`), **no** `gh pr comment`, `issue comment`, `issue edit`, or `pr close` call at all.
12. `/deny` on a PR reported `CLOSED` → same refusal, same "touches nothing" assertion.
13. `/deny` on a PR that merged *seconds* before the request (simulating a stale dashboard list) → same refusal; the guard reads live GitHub state, not the stale payload the renderer sent.
14. `gh pr view --json state` fails (offline/rate-limited) → refuse (fail closed) via the existing `catch` → 500 path, with the real error in the message; still no label/comment/close call.
15. `gh pr view --json state` returns malformed JSON → same fail-closed refusal, not a crash.
16. A non-GitHub `pr_url` is still rejected by `assertGithubPrUrl` *before* the new state check ever calls `gh` (extend the existing "rejects a non-GitHub URL without calling exec" test to assert zero calls, not just zero comments).
17. Two back-to-back `/deny` calls on an already-merged PR are both refused identically and idempotently (no duplicate labels/comments — trivially true since nothing is written).
18. `/deny` on a genuinely `OPEN` PR still works exactly as today (the existing `send_feedback`/`drop` tests, now passing through the new guard) — regression coverage, not new behavior.

## Task List

1. Diagnose and record in the PR description: confirm whether a bare push (no comment/label) to a PR branch is seen by the generic change detector (`createChangeDetector`'s newest-issue identity) within one ~20s tick, and confirm that `opForHead` + the renderer's `useEffect` would already resolve the stuck card *if* `pr.headRefOid` refreshed — isolating the gap to "nothing currently triggers that refresh for a push with no issue/label/comment change."
2. Add `createHeadWatcher` / `startHeadWatch` to `dashboard/webhook-server/gh_watch.js`: ETag-conditional `GET /repos/{repo}/pulls/{number}`, watching only `head.sha` for a given candidate list, modeled on `createCheckWatcher`/`startCheckWatch`. Tests 1–7.
3. Add a `stuckOps()`-style accessor to `createMergeOps` (`dashboard/electron/main/merge_ops.js`) returning `{url, repo, number, head}` for ops in `reengaged`/`error`/`interrupted`, plus a reset method that clears a stuck op to idle on a confirmed new head. Tests 8–9.
4. Wire `startStuckPrHeadWatch()` in `dashboard/electron/main/index.js`, parallel to `startPrCheckWatch()` (same `if (pullOnly) return` guard): feed it `mergeOps.stuckOps()`, and on change, reset the op, call `githubChanged(repo)` (so the list itself also picks up the new `headRefOid`), and push `mr:mergeEvent` for that `url` with idle state over the existing channel. Test 10.
5. Fold in the ticket's required recurrence-check probe: expose a small count (stuck ops whose GitHub head no longer matches their recorded head) from the new watcher, surfaced the same way existing `dashboard/scripts/*_evidence.mjs` probes are (e.g. alongside `merge_motion_evidence.mjs`), so the 2026-11-26 check-on date has something to read.
6. Add `currentPrState(prUrl, exec)` to `dashboard/webhook-server/deny.js` (same `gh pr view <url> --json state` shape as `viewPrState`, `index.js:114`), and call it in `handleDenyRequest` right after `assertGithubPrUrl` and before dispatching to `sendFeedback`/`dropEntirely`; return a refusal (`{status: 409, body: {done:false, error: '...already merged/closed...'}}`) for any non-`OPEN` state. Leave GitHub-unreachable/malformed-JSON to the existing `catch` → 500 path (already fail-closed). Tests 11–17.
7. Update every existing mock `exec` in `dashboard/test/deny.test.js` to answer the new `gh pr view ... --json state` call (default `OPEN`) so current passing tests keep passing. Test 18.
8. Write the diagnosis finding (step 1) into the PR description per acceptance criterion 3.
9. Run the full dashboard test suite (and the Rules check) locally before handing off, per the project's "a hand-merge skips the gate" lesson — this PR still goes through the normal merge gate, but the suite should be green before requesting it.