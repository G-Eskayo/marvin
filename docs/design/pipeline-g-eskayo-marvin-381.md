## North-star fit

- **Reuses before adding anything new:** The backend half of this ticket is already built and working in this worktree — `/mr/detail` (`dashboard/mobile-backend/dashboard_gh_api.js:225`, reusing `parsePrImages`/`listPipelinePrs`) and `/mr/media` (`dashboard/mobile-backend/mr_media.js`, reusing `createImageLoader`/`mediaFileFor` from `dashboard/electron/main/pr_images.js`) are both present and wired into `index.js:65`. Review did **not** flag `/mr/detail` or its test file. This plan touches only the four locations review actually found broken: `mr_media.js`, its test, and the README section describing it — nothing is rebuilt from scratch.
- **Simplest sufficient approach:** three of the four fixes are small, local corrections (clamp a byte offset, swap `.pipe()` for `stream/promises` `pipeline()`, rewrite one paragraph of prose) — not new abstractions. The fourth (the vacuous `cacheDir` test) is fixed by **removing** complexity, not adding it: the current test file's `vi.mock('../electron/main/pr_images.js', ...)` mocks `mediaFileFor` for every test, which is why nobody could write a real isolation test — `mediaFileFor` is a pure, deterministic `existsSync` lookup, so dropping the mock and running it for real (with correctly-named 64-hex-id cache files) is simpler than keeping the mock and bolting on more fake plumbing. This directly reuses the already-reviewed `mediaFileFor` contract instead of re-deriving a fake one.
- **Where it spends/saves tokens:** fixing the four named findings in place, instead of re-deriving the route, is the cheap path — a third pass that re-litigates already-accepted design (DI for `cacheDir`/`loader`, the `/mr/detail` route, the overall Range/206/416 shape) would waste tokens relitigating settled ground. One new, small DI seam (`createReadStream`) is added only because it's the only way to deterministically test the fd-leak finding — no test, no seam.
- **Phone-OS direction:** unchanged — real seekable video/image streaming over Tailscale is still direct progress on "reachable from anywhere."
- **More capable, not more passive:** unchanged — this exists so Gil can actually see evidence before approving from his phone (#374's hard rule). A route whose README lies about its own behavior, or that leaks file descriptors every time a scrubbing player aborts a range request, erodes exactly the trust this ticket is meant to build.
- **Carried-over correction:** the SwiftUI half is still unbuildable here — no `marvin-mobile` checkout exists in this sandbox (verified: `~/Developer/marvin-mobile` not found). The Decision below is unchanged from the prior attempt for that reason, not because it was ignored.

## Why the current code still fails review (read from the actual files, not the old design doc)

The worktree's `mr_media.js` already has `{ cacheDir, loader }` injection, Range parsing, and `206`/`416` support — the *first* review's findings are fixed. The second review found four more, all confirmed by reading the current code:

1. **`mr_media.js:93`** — `start >= fileSize || end >= fileSize || start > end` rejects any `end` past EOF with `416`, instead of clamping `end` to `fileSize - 1` and serving `206` (RFC 7233). A player that requests `bytes=0-999999` on a 1000-byte file gets a bogus `416` instead of the whole file.
2. **`mr_media.js:111,133`** — `stream.pipe(res)` has no listener for `res` closing early. When a client (AVPlayer scrubbing) aborts mid-range-request, nothing calls `stream.destroy()`; the fd leaks until GC. (The existing `stream.on('error', ...)` handler is a different, already-fixed path — it only covers the source stream erroring, not the destination closing first.)
3. **`README.md:152`** — "Omitting the Range header or providing an out-of-bounds/malformed range triggers a `416`" is self-contradicting: the sentence above it (and the code) says omitting Range returns a full `200`.
4. **`mr_media.test.js:419-430`** — `'uses provided cacheDir and loader when options supplied'` only asserts `200`; it never proves `cacheDir` was actually read from. This is possible to fix properly now because the whole file forces `mediaFileFor` through a `vi.mock`, so no test can exercise the real cache-lookup contract.

## Tests to write first

All still run against a **fake `loader`** (`{ load: vi.fn(...) }`) and a **temp `cacheDir`** — never real network, never real `HOME`. The only structural test-file change: drop `vi.mock('../electron/main/pr_images.js', ...)` entirely. It's unnecessary — passing an explicit `loader` already bypasses `createImageLoader` (the one real network dependency); `mediaFileFor` is pure and safe to run for real against a temp dir, and running it for real is what fixes finding #4.

**New/changed tests (the four fixes):**
1. `Range: bytes=0-999999` on a 1000-byte cached file → `206`, `Content-Range: bytes 0-999/1000`, `Content-Length: 1000`, body = full 1000 bytes. *(regression test for finding #1 — end-byte clamping)*
2. `Range: bytes=999-999999` (start valid, end past EOF) → `206`, `Content-Range: bytes 999-999/1000`, `Content-Length: 1`. *(boundary case of the same clamp)*
3. Client aborts mid-stream on a `Range` request: open the request, read the first chunk, then destroy the client socket; assert the injected `createReadStream`'s returned stream had `.destroy()` called, and that the server stays up and serves a *subsequent* unrelated request correctly afterward. *(regression test for finding #2 — requires adding an optional `createReadStream` param to `createMrMediaRouter`, defaulting to the real `fs.createReadStream`, so the test can inject a spyable stream; this is the only new DI seam this round, matching the existing `cacheDir`/`loader` pattern.)*
4. README: no code test (it's prose) — fixed directly, verified by re-reading the file after editing (see Task List).
5. Replace the vacuous test with a real **cacheDir-isolation** test: write a real cache file (named with a real `sha256` hex id, matching `hashOf`'s contract) into `cacheDirA` only; build `routerA` with `cacheDir: cacheDirA` and `routerB` with `cacheDir: cacheDirB` (both unmocked `mediaFileFor`); same fake `loader` returning `src: 'prmedia://media/<id>'` for both; assert `routerA` serves `200`/`206` and `routerB` returns the real "video file not found in cache" `502`. *(fixes finding #4, and also finally exercises the real `src.split('/').pop()` → `mediaFileFor` contract that was previously only ever mocked.)*

**Carried-over / already-present tests kept as-is** (confirmed present and correctly assertive): missing url (400), empty url (400), image success (200 + content-type + length), invalid image data format (502), video no-Range (200 + Accept-Ranges), Range 0-99 (206), out-of-range start≥fileSize (416), malformed Range (416), video-not-in-cache (502), unknown kind (502), loader error "only https" (400), loader 404 reason (404), generic loader error (502), loader throws (502), unmatched route (404 via parent), open-ended Range `bytes=500-` (206).

**Additional misuse coverage this round adds** (ticket's break-it list + general misuse categories, checked against current tests):
6. Loader resolves `{ ok:false, reason: 'not a valid address' }` → `400`. *(malformed-URL branch exists in route code at the `'not a valid'` check but had no direct test — cheap, closes a real gap.)*
7. Loader resolves `{ ok:false, reason: 'too large (20 MB)' }` → `502`. *(ticket's explicit "large GIFs on cellular" break-it case, now tested with the loader's real reason string instead of a generic stand-in.)*
8. Two concurrent requests against the same cached video with different `Range` headers (`bytes=0-99` and `bytes=500-599`) both resolve independently with the correct byte ranges and `Content-Length`. *(repeats/concurrency — AVPlayer issues overlapping range requests while scrubbing; nothing in the current suite exercises two simultaneous requests at all.)*
9. "PR with 30 images" and "Mac unreachable" are explicitly **not** retested here: the former is `parsePrImages`'s `MAX_ITEMS` cap (`pr_images.js:23`), exercised by `/mr/detail`'s own untouched tests; the latter is a Tailscale-reachability concern with no code path inside this route to test. Noted so the plan doesn't silently drop them.

Each new/changed test asserts the exact thing its name claims (status code, specific header value, or specific call having happened) — no `expect([...]).toContain(status)` ranges, per the finding-#4 lesson.

## Decisions
<!-- marvin:decisions -->
### scope: Where should the SwiftUI half of this ticket happen?
- [ ] A: Ship backend-only in this PR (the four fixes above to `mr_media.js`/README/tests, plus the already-written, review-clean `/mr/detail` route); file a sibling ready-for-agent ticket in `G-Eskayo/marvin-mobile` for the SwiftUI screen, picked up once that repo gets an agent execution profile
- [ ] B: Build the SwiftUI screen now too, in a separate session/worktree that actually has `marvin-mobile` checked out, accepting the risk of coding against issue #3's MR Review tab without having read it first
- [ ] C: Something else (note below)

## Task List

1. `dashboard/mobile-backend/mr_media.js`:
   - Fix Range-end clamping: compute `end = rangeMatch[2] ? parseInt(rangeMatch[2], 10) : fileSize - 1`; return `416` only when `start >= fileSize || start > end`; then clamp `end = Math.min(end, fileSize - 1)` before computing `length`/headers/stream. Leave the malformed-Range → `416` and no-Range → `200` behaviors exactly as they are now (already correct, already tested).
   - Add an optional `createReadStream` param to `createMrMediaRouter` (default: real `fs.createReadStream`), and replace both `stream.pipe(res)` + manual `stream.on('error', ...)` blocks with `await pipeline(stream, res)` from `node:stream/promises`, wrapped in try/catch that only writes a `502` if `!res.headersSent`.
2. `dashboard/test/mr_media.test.js`:
   - Remove the `vi.mock('../electron/main/pr_images.js', ...)` block; import the real `mediaFileFor` (and `hashOf`'s equivalent via `crypto.createHash('sha256')`) to build real, correctly-named cache files in temp dirs.
   - Add tests 1-3, 5-8 from above; keep all carried-over tests; delete the vacuous `'uses provided cacheDir and loader when options supplied'` test (replaced by test 5).
3. `dashboard/mobile-backend/README.md` (`/mr/media` section, "Range semantics" paragraph): split the self-contradicting sentence into two correct ones — omitting `Range` → full `200`; an out-of-bounds-after-clamping or malformed `Range` → `416` with `Content-Range: bytes */<size>`.
4. Run `npm test` (vitest) for `dashboard/test/mr_media.test.js` and `dashboard/test/dashboard_gh_api.test.js` to confirm no regression in the untouched `/mr/detail` tests, and run the full suite once to check the baseline `pytest`/`vitest` failure counts haven't moved beyond the pre-existing baseline (2 pytest failures, 0 vitest failures, unrelated to this ticket).
5. Resolve the Decision above before opening/updating the PR:
   - If **A**: file the sibling `marvin-mobile` SwiftUI ticket (grouped grid, GIF `UIViewRepresentable`, `VideoPlayer`, full-screen swipe viewer, Approve/Deny honoring `needsImages`) and stop here for this PR.
   - If **B**: in a session with `marvin-mobile` checked out, read the existing MR Review tab/approve-deny screen (issue #3) in full before writing anything, then build the PR detail screen against `/mr/detail` and `/mr/media`, with its own tests.
6. Capture the simulator screen recording of clarity-captions #99 with GIFs animating (acceptance criterion) — only reachable once a working SwiftUI screen exists, i.e. after step 5 resolves to B or the sibling ticket lands.