Confirmed: still no SwiftUI/Xcode project in this repo (only the unrelated `brain-map/DesktopLive/*.swift`), and `marvin-mobile.json` still has `"dispatch": "off"`. The prior doc's claim holds. Now I have everything needed to write the revised plan.

## North-star fit

**Reuses, re-verified by reading the current code (not the prior doc's word for it):** this worktree's code is **not** the untouched baseline — it already contains an in-progress partial fix of the prior review's findings. Confirmed directly:
- `pr_images.js:282-319` `parseRange` already has the strict-digit regex + `-1`/`null` split, and `dashboard/test/pr_images.test.js:300-366` already covers it fully (tests #1–9 there are real, specific, and pass). **No work needed here.**
- `dashboard_gh_api.js:390-392` already passes `pr.files` unmodified and includes `repo` on the object given to `needsImages`, and `needsImages` (`mr_review.js:261-267`) already keys `uiPathsFor` off `pr.repo || MARVIN_REPO`. **The double-wrap and wrong-repo bugs (fix_these #2, and the latent bug the prior doc found) are already fixed in code.**
- The loader is already a single `opts.mediaLoader ?? createImageLoader(...)` built once per router (`dashboard_gh_api.js:35`), injectable by tests. **The loader-per-request bug is already fixed.**

**What is *not* fixed, confirmed by reading the actual files named in the review (not assumed from the prior doc):**
- `dashboard/test/dashboard_gh_api.test.js` still has **zero** uses of `mergeableProfilesDir`, `mediaCacheDir`, or `mediaLoader` anywhere in the file (grepped, no matches). Tests #4/#5 (lines 581–665) still hit the real `~/.agents/config/projects`. Tests #8/#9 (lines 775–823) still build the router with no loader/cache override, so `#8`/`#9` still make real HTTPS calls to `raw.githubusercontent.com` and accept `[400,404,500]`. Test #10 (line 825) is still `expect(true).toBe(true)`. Test #13 (line 871) still only asserts `router` is defined. Tests #14–28 from the original design (loader-injected 206/416/413/504/EISDIR/dedupe cases) were never written at all — the file ends at line 903, same shape the review flagged.
- `/mr/detail` (`dashboard_gh_api.js:367-415`) still has no `MARVIN_REPO`/registry check — confirmed by reading the full route body; `/mr/ticket-context`'s check two routes above it (lines 267-273) was never copied down.

So this attempt's real job is narrower than the full prior doc: **three of four production-code defects are already fixed; the test suite and the one remaining route gap are not.** I reuse the already-fixed loader-injection points (`opts.mediaLoader`, `opts.mediaCacheDir`, `opts.mergeableProfilesDir`) as the seams for every new test — no new test infrastructure, no new router shape.

**Simplest sufficient approach:** no new files, no new abstractions. Replace the vacuous/network-touching tests in place, add the missing loader-injected cases using the exact fake-loader shape (`{ load: vi.fn() }`) the design already enables, and copy the three-line registry check verbatim from `/mr/ticket-context` into `/mr/detail` (same file, same pattern, no new helper).

**Where it spends:** slightly more than the bare must-fix list — the registry-check test also needs a happy-path-with-registered-repo case so the new guard doesn't regress tests #4/#5/#7, and the loader-injected tests (#14–28) are written in full rather than stubbed, since partial coverage is exactly what caused this rejection twice.

**Token leverage:** fixing the test file once, correctly, is the one-time cost; the loader/profiles injection seams it exercises are reusable for any future route that touches `needsImages`/`mediaLoader` — no repeat cost.

**More capable, not more passive:** unchanged from the prior doc — this still only ships the backend data/media routes; Approve/Deny stays a human tap, and the phone screen itself needs a human with Xcode (see Decisions).

**If a north star argues against something:** same as before — it argues against writing SwiftUI in this headless, Xcode-less worktree a fourth time.

## Decisions
<!-- marvin:decisions -->
### swiftui_scope: This pipeline worktree can't build or verify the SwiftUI half of this ticket — how should it proceed?

Re-verified just now, unchanged: `find` across this worktree turns up `.swift` files only under the unrelated `brain-map/DesktopLive/`; there is no `.xcodeproj` anywhere. `~/.agents/config/projects/marvin-mobile.json` still has `"dispatch": "off"` and `"clone_mode": "catalog"`. The SwiftUI PR detail screen belongs in `G-Eskayo/marvin-mobile`, and this environment has no Xcode/Simulator to produce the acceptance criterion's screen recording regardless. The only comment on this issue is the automated "did not pass verification" note.

- [ ] A: This attempt ships only the mobile-backend pieces (`/mr/detail`, `/mr/media`, loader singleton — already mostly done, tests now fixed) with full tests; file a new ticket against `G-Eskayo/marvin-mobile` for the SwiftUI screen + simulator recording, built where Xcode exists
- [ ] B: Same as A, but also flip `marvin-mobile.json`'s `dispatch` to `on` first, so a future automated run can at least clone+build marvin-mobile (the simulator recording still needs a person or Xcode-capable session either way)
- [ ] C: Hold this entire ticket (no backend PR either) until the SwiftUI-side plan is settled

### media_token (text) (optional)
Note anything about where the GH token should come from on this Mac if `~/.claude/.gh-token` isn't the right source for the mobile-backend's launchd context.

## Tests I'll write first

All in `dashboard/test/dashboard_gh_api.test.js` unless noted; `pr_images.test.js`'s `parseRange` suite is already correct and untouched.

**Fix in place (currently broken/vacuous — replace, don't add alongside):**
1. **#4/#5 → real fixtures.** Both tests must pass `mergeableProfilesDir: <tmp dir>` (empty, or with one `*.json` profile) so `readUiPaths` never touches the real `~/.agents/config/projects`. #5 gets a real assertion: a profile with `evidence.ui_paths: ["src/ui.swift"]` + a PR whose `files` include `src/ui.swift` and whose body has no image → `needsImages` is `{ files: ['src/ui.swift'] }` (this is the test that would have caught the original double-wrap bug, since the old mock's shape hid it).
2. **New: two repos, two profiles.** Query `repo=A` and `repo=B`, each with its own `mergeableProfilesDir` profile (`evidence.ui_paths` differing) → `needsImages` for each is computed against the *queried* repo's own `ui_paths`, not a shared default (regression for the latent cross-repo bug the prior doc found and fixed in code — needs its own test since none exists).
3. **#8 → deterministic, no network.** Build the router with a fake `mediaLoader = { load: vi.fn().mockResolvedValue(null is never hit) }`... concretely: inject `mediaCacheDir` as an empty tmp dir and a fake loader whose `load` resolves `{ ok: true, kind: 'video', src: 'prmedia://media/<64-hex-that-does-not-exist-on-disk>' }` → route calls `mediaFileFor`, gets `null`, asserts exactly `404` with `error` containing `'not found'`. No `[400,404,500]` grab-bag.
4. **#9 → deterministic, no network.** Fake loader resolves a real video written into the injected `mediaCacheDir` (write a tiny `.mp4` fixture file by hand, no `fetchFn`) → no `Range` header → asserts exactly `200`, `Accept-Ranges: bytes`, `Content-Length` equal to the fixture's real byte length, body equals the fixture bytes.
5. **#10 → real 416.** Same fixture as #4, request with `Range: bytes=9000-9999` where the fixture is smaller → asserts exactly `416`, `Content-Range: bytes */<size>`.
6. **#13 → real stream-error path.** Cache dir contains a **directory** (not a file) at the expected cache filename for the fixture's hash (`mkdirSync` instead of `writeFileSync`) so `fs.stat` succeeds but `createReadStream(...).pipe` emits `EISDIR` — asserts the HTTP response ends/closes without throwing and without hanging the test (this is the "stale/unreadable cache entry" misuse case, done deterministically instead of racing an eviction).

**New (ticket's "How we'll try to break it" + this attempt's own gaps):**
7. 206 valid mid-range request on the injected fixture → correct `Content-Range`/`Content-Length`/byte slice (exercises the already-fixed `parseRange` end-to-end through the route, not just the pure function).
8. Suffix range `bytes=-5000` on a smaller fixture → `206` with `Content-Length` clamped to the real file size (end-to-end regression for the original #1 finding, now through the route).
9. Malformed `Range: bytes=abc-def` → ignored, falls back to full `200` (exercises `parseRange` returning `null` through the route).
10. Loader `ok:false` with reason text matching each status branch (`too large` → 413, `timed out` → 504, `not found` → 404, generic → 500) → **ticket's own "404 media" break-it case**, via the injected fake loader, no real fetch.
11. Image success via injected loader (`dataUrl` fixture) → raw decoded bytes, correct `Content-Type`, not JSON.
12. **Ticket's "a PR with 30 images" break-it case**, through the real `/mr/detail` route: a PR body with 30 `![](...)` images across several headings → `images` has all 30, in order, grouped — exercised via `exec` mock, not just `parsePrImages` directly.
13. **Ticket's "Mac unreachable" break-it case restated for this backend**: `gh pr view` rejects (network/auth failure) → `/mr/detail` returns `502`, not a hang or crash (already covered as #6, kept, re-confirmed deterministic).
14. `gh pr view` returns malformed/non-JSON stdout → clean `502`, not an uncaught exception (misuse: a real collaborator returning garbage).
15. **New must-fix regression test**: `/mr/detail?repo=some/unregistered-repo&number=1` → `400`, and the registered-repo happy path (#4/#5, now fixed) still returns `200` — proves the new `MARVIN_REPO`/registry check doesn't regress the existing passing tests (direct test for fix_these #4).
16. `POST /mr/detail` and `POST /mr/media` → router returns `false` (unhandled), consistent with every other route (misuse: wrong method).
17. Two concurrent `/mr/detail` requests for different repo/number (both using injected fixtures) resolve independently with no shared-state bleed (concurrency case from the north star's adversarial list).
18. Large/malformed input: `/mr/detail?repo=G-Eskayo/marvin&number=99999999999999999999` (digits but overflows safe integer) → handled without throwing (bad/huge input case); `/mr/media?url=` with a 10,000-character query string → `400`, not a crash (huge malformed input case).

## Task List

1. **`dashboard_gh_api.js` — add the missing registry check to `/mr/detail`** (fix_these #4): after the existing `repo`/`number` validation, add `if (repo !== MARVIN_REPO && !readRegistryData().some(b => b.repo === repo)) return 400`, copying the exact pattern already used by `/mr/ticket-context` two routes above. Write test #15 first, then the three-line change.
2. **`dashboard/test/dashboard_gh_api.test.js` — fix `/mr/detail` tests #4/#5 in place**: inject `mergeableProfilesDir` as a tmp dir in both, give #5 a real profile fixture and a real assertion on `needsImages.files`. Add the two-repo test (#2 above). Write these before touching the route further (they double as the regression guard for step 1).
3. **`dashboard_gh_api.js` / test file — fix `/mr/media` tests #8/#9/#10/#13 in place**: no production code change needed for #8/#9/#10 (already correct); write the fixture-based tests (my #3–6 above) against the existing `opts.mediaLoader`/`opts.mediaCacheDir` injection points, replacing the current real-network/vacuous versions, not adding new ones alongside them.
4. **Add the new loader-injected `/mr/media` tests** (#7–11, #16 media half, #17, #18 media half): build one small shared fixture helper inline in the test file (write a tiny real `.mp4`-shaped buffer to the injected `mediaCacheDir` at its expected hashed filename) and a `{ load: vi.fn() }` fake loader per test case — no new source file, this is test-only.
5. **Add the new `/mr/detail` tests** (#12 30-images, #14 malformed JSON, #16 detail half, #17 detail half, #18 detail half) against the real route via the `exec` mock, same style as the existing #4/#6 tests.
6. **`dashboard/mobile-backend/README.md`**: fix the `/mr/media` section header line ("images as data URLs, videos with HTTP Range support") to say raw bytes, matching the already-correct Response section two lines below; add `416` to the Errors list. One-line doc correction, no behavior change.
7. Run `dashboard/test/dashboard_gh_api.test.js` and `dashboard/test/pr_images.test.js` in full; confirm no regression in any untouched route (`/mr/list`, `/mr/ticket-context`, `/boards/load`, etc.) and that no test in the file touches a real filesystem path outside its own tmp dir or makes a real network call.
8. Post the Decisions section on the ticket/PR; do not write Swift in this worktree.