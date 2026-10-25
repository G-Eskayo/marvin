## North-star fit

Reuses, unchanged: `parsePrImages`/`createImageLoader`/`mediaFileFor`/`sniffMime` in `dashboard/electron/main/pr_images.js` (allowlist, size caps, mem/disk cache, credential handling — read again just now, still correct); the router pattern and all three routes already implemented in `dashboard/mobile-backend/dashboard_gh_api.js` (`GET /mr/:owner/:name/:number`, `GET /mr/media`, `GET /mr/media/stream/:id`); the `opts.fetchFn` DI hook already wired into `createImageLoader(...)` at `dashboard_gh_api.js:35,41` (the prior plan's item 1 is already done — no new plumbing needed). This revision adds nothing new: it is a surgical bug-fix pass on code that is already sitting uncommitted in this worktree (confirmed via `git diff`, which shows the whole `/mr/*` block as the only uncommitted change against `c0ef48c`).

Simplest sufficient approach: the regex bug is one line (`dashboard_gh_api.js:485`), verified by hand-tracing it — `^bytes=(-?\d+)-(\d*)$` against `bytes=-500` lets the greedy `-?\d+` consume `-500` entirely, leaving no `-` for the literal separator, so the match fails outright and the suffix branch at line 499 (`firstNum < 0`) is genuinely dead code. The two test fixes are deletions/rewrites of ~15 lines each, not new scaffolding.

Token spend: cheapest possible revision — no new files, no new abstractions, three located defects plus the tests that would have caught them. Skips a fourth rejection round by also closing the gap the review's **notes** section pointed at (tests that don't isolate `mediaCacheDir`, a positive-registry-path test that accidentally uses `MARVIN_REPO` and therefore never registry-checks, and the stream not being destroyed cleanly on client abort) — these aren't must-fix, but they sit on the exact lines I'm already touching, so fixing them now is strictly cheaper than a fifth round over the same file.

Capability: this is the difference between "the phone can request a video range" and "the phone can actually scrub/seek a recording" — Safari/AVPlayer send suffix ranges (`bytes=-500`) routinely when seeking near the end of a clip; today that silently degrades to a full-file 200, which is a worse experience than failing loudly. Fixing it is what makes Gil's phone screen-recording review flow (the acceptance criterion) actually work on a real device, not just in a mocked test.

**Scope correction (reconfirmed, unchanged from the prior two attempts):** `dashboard_gh_api.js` lives in `G-Eskayo/marvin`; the SwiftUI PR detail screen belongs in `G-Eskayo/marvin-mobile`, not checked out here. Re-verified `~/.agents/config/projects/marvin-mobile.json`: `"dispatch": "off"` still holds, and `gh pr list --repo G-Eskayo/marvin --search 381` returns nothing — no PR exists yet, and both issue comments are only automated rejection notices, no owner answer on record. This plan again covers **only the backend half**, Option A, and carries the Decisions section forward unanswered.

## Decisions
<!-- marvin:decisions -->
### scope: How should #381's cross-repo split be handled?
- [ ] A: Split now — land the mobile-backend routes from this worktree against #381, then relabel #381 `project:marvin-mobile` and open a new linked ticket in `G-Eskayo/marvin-mobile` for the SwiftUI screen once that repo's dispatch is turned on
- [ ] B: Same split, but keep #381 open (not closed) until the SwiftUI ticket also lands, so the acceptance criteria aren't marked done early
- [ ] C: Hold all of #381 (including the backend routes) until `marvin-mobile` dispatch is turned on, then do both halves together as one coordinated pair of PRs
- [ ] D: Something else (note below)

### dispatch: Turn on dispatch for G-Eskayo/marvin-mobile now? (optional)
- [ ] Yes, flip `config/projects/marvin-mobile.json` `dispatch` to on as part of this work
- [ ] No, leave it off — flip it separately, outside this ticket

This plan proceeds as if **A** is chosen. If **C** instead: the bug fixes below still land (they're fixes to existing code, not new scope) but the PR stays unmerged until the SwiftUI half can pair with it.

## Tests to write first

All in `dashboard/test/dashboard_gh_api.test.js`, against `dashboard/mobile-backend/dashboard_gh_api.js` and the real `pr_images.js` collaborator (only `fetchFn` is faked — never mock `createImageLoader`/`parsePrImages` themselves, or the allowlist/cache/dedup logic they enforce would be invisible to the test). Every new test passes an explicit tmp `mediaCacheDir` (closes the review's isolation note).

**Direct regression tests for the 3 must-fix findings:**

1. **Suffix range, the exact named bug**: pre-seed a cached file, `Range: bytes=-500` → 206, `Content-Range: bytes <size-500>-<size-1>/<size>`, body is exactly the trailing 500 bytes. This is the test that would have caught the dead suffix branch.
2. **Both-empty range is malformed, not a crash**: `Range: bytes=-` → falls back to a full 200 response that actually completes (asserts `'end'` fires, body length === file size). Covers the "reject when both empty" instruction explicitly.
3. **Truly malformed Range** (non-numeric, e.g. `bytes=garbage`, and a multi-range header `bytes=0-10,20-30`) → same clean full-200 fallback, not a hang.
4. **Rewritten "caches image data correctly"** (fixes must-fix #2): inject `fetchFn` returning real PNG bytes for an allowed host (`raw.githubusercontent.com`); first `GET /mr/media?url=...` calls `fetchFn` once, returns the bytes with `Content-Type: image/png`, writes a cache entry to `cacheDir`; a second identical request does **not** call `fetchFn` again (exercises the `mem` cache, not just the allowlist). Test is renamed to match what it now does.
5. **Rewritten "returns 404 for unallowed hosts"** (fixes must-fix #3): keep the disallowed-host behavior but rename it to `"rejects media from an unallowed host (HTTP 200, ok:false)"` so the name matches the 200/`ok:false` contract instead of implying a literal 404.

**Range correctness, beyond the regression case:**

6. Open-ended (`bytes=10-`) and explicit (`bytes=10-19`) ranges return correct 206 bytes at the right offset (content-correctness, not just headers).
7. Over-sized explicit range (`bytes=0-999999999` on a ≤1 KB file) clamps to `size-1`, not truncated/oversized.
8. Unsatisfiable range (`bytes=500-600` on a 100-byte file) → 416, `Content-Range: bytes */100`.
9. Reversed range, a person's mistake (`bytes=19-10`) → 416, not a negative-length read.
10. Oversized suffix (`bytes=-999999` on a small file) → clamps to the whole file, not negative `start`.
11. No-Range baseline unchanged: full-file 200 with `Accept-Ranges: bytes` and correct `Content-Length`.

**Stale state / dependency failure (misuse the ticket didn't name but the north star requires):**

12. File deleted between `mediaFileFor` lookup and `statP` → clean `{ok:false, reason}` at 500, never an unhandled rejection or hang.
13. File deleted mid-stream after a 206 is already written → the existing `stream.on('error', () => res.destroy())` must fire without an uncaught exception (guard with a `process.once('uncaughtException', fail)` listener) and the test server must still answer a follow-up request afterward, proving the process survived.

**Ticket's own named break cases:**

14. Large media over cap: `fetchFn` reports `content-length` over the cap → `{ok:false, reason:'too large (...)'}` at HTTP 200.
15. 404 upstream ("Mac unreachable" / GitHub 404 reframed server-side): `fetchFn` resolves 404 → `{ok:false, reason:'not found (404)...'}`.
16. Dependency failing: `gh pr view` exec rejects (ENOENT/network) → clean `{ok:false, reason: err.message}` at 200, never a 500/unhandled rejection.
17. PR with 30 images: a `gh pr view` body with 30 distinct image refs → `/mr/:owner/:name/:number` returns all 30, in document order.

**Concurrency, permissions, and the remaining misuse list:**

18. Concurrent dedup: two simultaneous `GET /mr/media?url=...` for the same URL, with a `fetchFn` that counts calls and resolves after a delay, result in exactly one `fetchFn` call (the loader's `inflight` map) and two identical successful responses.
19. Positive registry-path regression (fixes the review note that the existing "registered" test accidentally uses `MARVIN_REPO` and skips the check): register a genuinely different repo (not `G-Eskayo/marvin`) and confirm `/mr/<that-repo>/123` passes the `registry.some(...)` branch instead of short-circuiting on the `repo !== MARVIN_REPO` check.
20. Bad/empty input: missing `url` → 400; unregistered repo → 400 `"not registered"`; empty PR body → `images: []`; stream ids too short/long/non-hex → fall through to 404 without matching the route.
21. Token never leaves the Mac: set `GH_TOKEN` to a known fake value for the test only (saved/restored in `beforeEach`/`afterEach` so it can't leak into other tests), assert the fake `fetchFn` *received* the `Authorization` header for an allowed host, and assert the client-facing response body/headers from both `/mr/media` and the stream route never contain that value.

## Task List

1. Fix the Range regex at `dashboard_gh_api.js:485` from `^bytes=(-?\d+)-(\d*)$` to `^bytes=(\d*)-(\d*)$`, treat `match[1] === ''` as a suffix range (`bytes=-N`), and treat `match[1] === '' && match[2] === ''` as malformed (falls through to the existing full-file fallback) — the fix behind tests 1–3, 9, 10.
2. While touching that block, swap the three `createReadStream(...).pipe(res)` call sites for `stream.pipeline(createReadStream(...), res, () => {})`-style handling so the read stream and its fd are always closed on client abort or error, instead of relying on only a `res.destroy()` side effect — closes the review's stream-cleanup note at the same cost as the regex edit, with test 13 covering it.
3. Rewrite the "caches image data correctly" test to exercise `fetchFn` injection and actual cache-hit behavior (test 4); rename and correct the "returns 404 for unallowed hosts" test to match its real 200/`ok:false` contract (test 5).
4. Add the regression and range-correctness tests (1–3, 6–11) against a pre-seeded cached file written directly into a tmp `mediaCacheDir` via `writeFileSync`.
5. Add the stale-state tests (12, 13), using the `process.once('uncaughtException', ...)` guard pattern to prove the process survives a mid-stream file deletion.
6. Add the ticket's own named break-case tests (14–17) using the existing `fetchFn`/`exec` injection points — no new DI needed.
7. Add the concurrency test (18) and the registry-path regression test (19), the latter using a repo distinct from `MARVIN_REPO` to actually exercise the `registry.some(...)` branch.
8. Add the remaining input-validation and token-leak tests (20, 21), with explicit save/restore of `process.env.GH_TOKEN` around test 21 so it can't bleed into other tests in the same process.
9. Give every new/modified test its own explicit tmp `mediaCacheDir` (via the existing `withTempDirs` helper) so none touch the real `~/.claude/mobile-pr-media-cache`.
10. Run the full `dashboard` vitest suite to confirm no regression in the other `/mr/*`, `/boards/*`, `/relations/*`, `/activity/*`, `/queue` routes already in this file.
11. Comment on G-Eskayo/marvin#381 with what shipped (backend routes only, now bug-fixed and test-covered), carry the unanswered Decisions section into the PR per `docs/agents/decisions-format.md`, and do not claim the acceptance criteria fully met — the simulator-recording criterion needs the `marvin-mobile` SwiftUI half, which this worktree cannot build.