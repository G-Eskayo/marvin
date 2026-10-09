## North-star fit

- **Reuses before adding anything new:** every data shape this ticket needs already exists as a pure, Electron-free function — `loadBoard`/`fetchBoardData`/`getEvidence` (boards.js), `listPipelinePrs`/`fetchTicketContext`/`sentBackKeys` (mr_review.js), `listOpenPrsAcrossRepos`/`prListArgs`/`canMergeFromDashboard` (mr_repos.js), `computeReviewStatus`/`readSeenNumbers` (mr_seen.js), `createRelationsService` (relations_service.js), `getReworkStatus` (rework.js), `getQueue` (queue.js), `readMergeableRepos` (profiles.js), `createGithubState` (github_state.js). I verified none of these import `electron` — `dashboard_api.js` already proves this pattern works (it imports straight from `electron/main/*.js`). Nothing new is invented; this ticket is genuinely "thin adapters," as it says.
- **Simplest sufficient shape:** one new router file (`dashboard_gh_api.js`) for the GitHub-backed routes, mirroring the existing one-file-per-concern layout (`chat_api.js`, `actions_api.js`, `offline_batch_api.js`...), plus two small additions to the existing `dashboard_api.js` (`/activity/timeline`, title-backfill on `/activity`). I deliberately did **not** fold the new routes into `dashboard_api.js` itself — see "Scope conflict" below.
- **Where it spends tokens (GitHub calls, not model tokens):** reuses the shared `createGithubState()` cache verbatim for the two GitHub-heavy routes (`/boards/load`, `/mr/list`), protecting the shared `gh` gate ([[reference-github-gate]]) from a second uncoordinated poller — the cheaper-looking "skip caching" option was rejected because it risks tripping the shared cooldown that other machines/processes also depend on.
- **More capable, not more passive:** the phone gains real parity with the desktop's board/MR/relations views instead of a stub, and the standing "never a bare number" rule ([[feedback-avoid-bare-numeric-ids]]) gets enforced at the one place it was still leaking through to the phone.
- **Ticket's own stated fit:** the ticket doesn't state one explicitly (no "If the ticket states a fit" text present) — nothing to correct there.

## Important finding: a scope conflict with ticket #156

`dashboard/test/dashboard_api_scope.test.js` (added for ticket #156, "Mobile backend: read-only Dashboard API") contains:
- `it('blocks /boards/load (out of scope)', ...)` — asserts `createDashboardApiRouter()` 404s `/boards/load`.
- `it('does not import profiles module', ...)` / `'does not import dispatch_status write path'` — source-text regex guards on `dashboard_api.js`.

#156 explicitly scoped *out* `boards/load` and profile/dispatch reachability. #272 (this ticket, parent PRD #152) explicitly scopes `boards/load` *in*, and `/mr/list`'s parity requires `canMerge`, which needs `readMergeableRepos` (profiles.js, read-only). This is legitimate, approved scope growth, not a mistake — but I'm resolving it without touching either guard test: **the new routes live in a separate router file**, so `dashboard_api.js`'s own router still correctly 404s `/boards/load` in isolation (that test keeps passing, unmodified, and stays true — that file still doesn't handle it), and `dashboard_api.js` still never imports `profiles`. Zero existing tests change. This is the surgical option, not a workaround.

## Files to touch

### 1. New: `dashboard/mobile-backend/dashboard_gh_api.js`

`createDashboardGhApiRouter(opts)` returning a router function, same calling convention as `dashboard_api.js`. Module-level singleton `const githubState = createGithubState()` (own in-memory cache, separate process from Electron — consistent with github_state.js's own documented "one copy per process" model) and a shared helper:

```js
const getBoardData = (repo, gh) => githubState.get('board', repo, () => fetchBoardData(repo, gh))
```

reused by `/boards/load`, `/mr/list`'s sentBack/closed checks, *and* the relations service's `getBoardData`, exactly mirroring desktop's wiring (so a board just loaded on the phone also warms `/activity/overview` seconds later).

Injectable opts (all default to the real path/module, mirroring `dashboard_api.js`'s pattern): `exec`, `registryPath`, `catalogDir`, `masterDocPath`, `deviceId`, `mergeableProfilesDir` (→ `profiles.PROFILES_DIR`), `mobileSeenPath` (→ new `~/.claude/mobile-mr-seen.json`, deliberately separate from the desktop's Electron-`userData` seen file — "seen" is explicitly documented in `mr_seen.js` as per-viewer by design, and the phone is a different viewer), `mrWebhookUrl` (passed down from `index.js`'s already-computed `MR_WEBHOOK_URL`), `rework: {run}`/`queue: {run}` passthroughs for test injection.

Routes:

- **`GET /boards/load?repo=`** — 400 if `repo` missing; 400 `No board registered for <repo>` if not in `readRegistry()` (mirrors `assertRegistered`'s message, as a proper HTTP error instead of an uncaught throw); else `loadBoard(repo, { gh, registryRepos: readRegistry(), data: await getBoardData(repo, gh), evidence: await getEvidence(repo) })`. Omits desktop's `reconciler.observe(...)` call — that's Electron UI-reconciliation telemetry, not part of the returned data; documented, not silently dropped.

- **`GET /mr/list`** — `listOpenPrs = () => listOpenPrsAcrossRepos(readRegistry().map(b=>b.repo), repo => githubState.get('prs', repo, () => gh(prListArgs(repo))))`; `sentBackTickets`/`closedTickets` built from `getBoardData` per repo (shared helper above, so no double fetch); `reworkStatus = getReworkStatus` (its own 60s cache, used as-is — no extra wrapper, since it already self-protects); `canMerge = repo => canMergeFromDashboard(repo, readMergeableRepos(mergeableProfilesDir))`; `rebaseStatus`/`autoMergeShadow` = plain `fetch` to `${mrWebhookUrl.replace(/\/approve$/, '/rebase-status'|'/auto-merge-shadow')}` with a 3s timeout (`listPipelinePrs` already try/catches these — no extra wrapping needed). Omits `stackRetarget.check(prs)` (Electron-side safety-net side effect, not returned data; documented).

- **`GET /mr/review-status`** — light PR list across repos (`prListArgs(repo, {light:true})`), `listPipelinePrs(...)` with no options (defaults), `computeReviewStatus(keys, normalizeSeen(readSeenNumbers(mobileSeenPath)))`, returns `{status, openCount}`. Documented limitation: no `POST` mark-seen endpoint exists yet on mobile (out of scope for #272), so this will read "red" whenever any pipeline PR is open until that's added later — correct per the per-viewer design, not a bug.

- **`GET /mr/ticket-context?ref=&repo=`** — 400 if `ref` missing; defaults `repo` to `MARVIN_REPO`; 400 if `repo` not `MARVIN_REPO` and not registered; `fetchTicketContext(ref, (n) => ghIssueView(n, repo))` where `ghIssueView` is the same `gh issue view <n> --repo <repo> --json number,title,body` shape already used elsewhere in this codebase.

- **`GET /activity/overview`** — module-scope `relations = createRelationsService({ getRepos, getBoardData, getDocs, getProjects, getStages: defaultStagesFor, getLive: defaultLiveNumbers, recheck: () => {} })` (no-op `recheck` is safe: only `relations.parity()` ever calls it, and parity isn't exposed here). `getDocs` replicates desktop exactly: `docsService.localDocs()` merged with `loadIndex().docs` (docs_search.js, pure local-file read) for repos without a local clone. Calls `relations.overview()`.

- **`GET /relations/ticket?repo=&number=`** — 400 if either missing; `relations.forTicket(repo, Number(number))`. No registry check (desktop doesn't gate this either — unknown repo/ticket degrades to `state: 'UNKNOWN'`/`'(not loaded)'`, not an error; matched faithfully).

- **`GET /relations/context?project=`** — 400 if missing; `relations.context(project)`. Same no-registry-check faithfulness.

- **`GET /queue`** — `getQueue()` direct (own 60s cache already in queue.js); `{ ok: true, data }` = exactly `{queue, running, error}`.

### 2. Edit: `dashboard/mobile-backend/dashboard_api.js`

- Import `getTicketTimeline` alongside `listTicketActivity` (already imported from the same `activity.js`).
- Add **`GET /activity/timeline?repo=&number=`** — 400 if `number` missing (`repo` optional, null → marvin, matching `getTicketTimeline`'s own default); returns `getTicketTimeline(Number(number), stagesDir, repo || null)`.
- **Title backfill on `GET /activity`**: after `listTicketActivity(...)`, collect rows with `title === null`, group by `repo`, and for each repo do `gh issue view <number> --repo <repo> --json title` per missing number (same call shape as the existing `/boards/ticket` route, reusing the already-injected `exec`), in parallel, each wrapped in its own try/catch so one bad lookup never drops the rest (matches the codebase-wide "one failure must not hide the others" pattern in boards.js/mr_review.js). On success, fill `row.title`; on failure, leave it `null` (documented: best-effort join against a possible GitHub outage, not a hard guarantee — the existing, still-valid `activity.js` test "reports title: null when no event has one" is about the shared function's contract and is *not* touched; the join happens one layer up, in the HTTP route only).

### 3. Edit: `dashboard/mobile-backend/index.js`

- Import and construct `dashboardGhApiRouter = createDashboardGhApiRouter({ mrWebhookUrl: MR_WEBHOOK_URL })` (reusing the `MR_WEBHOOK_URL` already computed on lines 29-31 — no new env-var derivation).
- Add `handled = await dashboardGhApiRouter(req, res); if (handled) return` into the existing router chain, in the same position as the other `*ApiRouter`s — i.e. *after* the `allowed` check. This is how "sits behind the device gate" is satisfied: by placement in the already-gated chain, the same way every existing route satisfies it today (there's no existing test that exercises the full gated chain for any route, since `index.js` self-starts a real Tailscale-bound listener at import time — I won't add one either; it'd require live Tailscale, which the existing suite also avoids).

### 4. Edit: `dashboard/mobile-backend/README.md`

Add entries for all 8 new/changed routes to the existing "Contract: Read-only Dashboard API" section, in the same `### GET /path` + **Query parameters** + **Response** style already used, including the documented limitations (mobile's independent seen-state file, best-effort title backfill, omitted Electron-only side effects).

## Tests to write first

No "How we'll try to break it" section exists on this ticket, so this list is derived from north-star guiding principles (bad/empty/huge/malformed input; each dependency failing; repeats/concurrency; wrong permissions; stale state; a person's mistakes), applied per route. New file `dashboard/test/dashboard_gh_api.test.js` (HTTP-level, same `startTestServer`/`makeRequest` helpers as `dashboard_api_parity.test.js`, faking only `exec`/`run`/`fetch` — never the pure logic modules) unless noted:

**Cross-cutting / scope regression**
1. `dashboard_api_scope.test.js`'s existing 6 assertions still pass unmodified (run as-is, no edits) — confirms the new router didn't leak into the old one.
2. New: `createDashboardGhApiRouter()`'s source does not import `dispatch_status`'s write path or `portfolio` (same spirit as the old guard, scoped to the new file, so the *write*-adjacent surfaces #156 cared about stay provably unreachable even as reads expand).

**`GET /boards/load`**
3. Missing `repo` → 400, no `exec` call made.
4. `repo` not in registry → 400 `No board registered for ...`, no `exec` call made (wrong input never reaches `gh`).
5. Registered repo, `gh pr/issue list` all succeed → 200 with the same shape `loadBoard` produces (columns, otherProjects, fetchedAt).
6. `gh` throws (dependency failure) on the issue list → request fails loud (surfaces, doesn't silently return an empty board) — matches `loadBoard`'s own `throw`.
7. Two concurrent `/boards/load?repo=X` requests within the cache TTL → underlying `exec` called once (githubState dedup), not twice — a correctness assertion, not just an optimization check (proves no response can be wrong because it raced a second in-flight fetch).
8. Huge/malformed `repo` value (e.g. `repo=../../etc`, repo containing `#`/`&`/newlines) → either 400 (treated as "not registered") or safely passed through `URL`'s query decoding without ever reaching a shell — no injection into the `gh` argv (since `execFile` with an argv array, not a shell string, is already injection-safe by construction; test asserts the argv array passed to the faked `exec`, confirming no string concatenation was introduced).

**`GET /mr/list`**
9. No PRs anywhere → 200, `data: []`.
10. One repo's `gh pr list` fails, another succeeds → the failing repo's PRs are simply absent, the other repo's still show (never a total failure) — mirrors `listOpenPrsAcrossRepos`'s own per-repo try/catch.
11. `canMerge` is true for `G-Eskayo/marvin` even with an empty/missing profiles dir (marvin's gate is built-in, not profile-gated).
12. `canMerge` is true for another repo only when its profile sets `merge_from_dashboard: true` (temp profiles dir with a malformed profile JSON alongside a good one → malformed one is skipped, good one still works — "one broken profile must not hide the others").
13. `rebaseStatus`/`autoMergeShadow` fetch times out or 500s → PR rows still return with `rebase: null`/`autoMerge: null`, not an error (best-effort fields degrade, not propagate).
14. A PR whose linked ticket carries `needs-reengagement` → `sentBack: true`; a PR's board data fetch for sentBack/closed reuses the *same* cached board fetch as a concurrent `/boards/load` for that repo (one `exec` call, not two) — proves the shared `getBoardData` helper is actually shared, not duplicated per route.

**`GET /mr/review-status`**
15. No open PRs → `{status: 'green', openCount: 0}`.
16. Open PRs, mobile seen-file absent → `{status: 'red', ...}` (never crashes on a missing file).
17. Open PRs, mobile seen-file present but malformed JSON → still `'red'`, not a 500 (mirrors `readSeenNumbers`'s own try/catch).

**`GET /mr/ticket-context`**
18. Missing `ref` → 400.
19. `repo` not `MARVIN_REPO` and not registered → 400.
20. `gh issue view` fails for the ticket itself → `{ticket: null, parent: null}`, 200 (never throws — mirrors `fetchTicketContext`'s own try/catch).
21. Ticket exists, has a `## Parent` reference, but the parent lookup fails → `{ticket: {...}, parent: null}` (one failing fetch doesn't null out the one that succeeded).
22. A person's mistake: `ref` is a non-numeric string (e.g. `ref=abc` or a full URL instead of a number) → passed through as-is to `gh issue view <ref>`, which will itself fail cleanly → `{ticket: null, parent: null}`, not a crash.

**`GET /activity/overview`, `/relations/ticket`, `/relations/context`**
23. Empty registry (no boards at all) → `/activity/overview` returns `{}`, not an error.
24. `/relations/ticket` for a ticket/repo that exists in no board's data → `state: 'UNKNOWN'`, `title: '(not loaded)'`, not 404/500 (degrades, matches desktop).
25. `/relations/ticket` missing `number` → 400; non-numeric `number` (e.g. `number=abc`) → `Number('abc')` is `NaN`; assert this returns the graceful "not loaded" shape rather than crashing deep in `relations.js`'s string-key building.
26. `/relations/context` missing `project` → 400.
27. One repo's board-data fetch fails while building the relations index → that repo's tickets/PRs are just absent from the index, overview/ticket/context still answer for every other repo (relations_service.js's own per-repo try/catch).
28. `loadIndex()` file absent/corrupt (docs index never built yet) → `getDocs` still resolves (falls back to `EMPTY`), overview/context still answer.

**`GET /queue`**
29. `run` throws → `{queue: [], running: [], error: '<message>'}`, 200 — never an empty-queue-looking success.
30. Two calls within 60s → `run` invoked once (existing cache, re-asserted at the HTTP layer this time, not just the unit level already covered by `queue.test.js`).

**`GET /activity/timeline`**
31. Missing `number` → 400.
32. Unknown/untracked ticket → `[]`, 200 (matches `getTicketTimeline`'s existing contract, no change needed there — just wiring it up).
33. `#13` in `clarity-captions` vs `#13` in `marvin` return different timelines when `repo` differs (regression guard for marvin#127's exact bug class, applied to this new route).

**`GET /activity` title backfill**
34. A row with `title: null` and a successful `gh issue view --json title` → row comes back with the real title filled in, other fields unchanged.
35. A row with `title: null` whose `gh issue view` fails → row still comes back with `title: null` (soft-fails, doesn't drop the row or 500 the whole list).
36. Two null-titled rows in the *same* repo → exactly two `gh issue view` calls (one per missing ticket), not one-per-row-regardless — and zero calls for rows that already have a title (no wasted lookups).
37. Every row already has a title → zero extra `gh` calls at all (regression guard: this change must not add a tax to the common case).
38. Existing `activity.test.js` "reports title: null when no event has one" still passes unmodified — confirms the backfill lives in the HTTP route, not in `listTicketActivity`'s own contract.

**Device gate / wiring (code-review level, not new runtime tests — matches how the rest of the suite already treats `index.js`)**
39. Manual check (not a test, documented in the PR): `dashboard_gh_api_router` is wired into `index.js`'s chain strictly after the `allowed` check, same position as the other routers — grep/diff-reviewable, consistent with how every other route's gating is currently verified in this codebase (no existing route has a live-gate integration test either).