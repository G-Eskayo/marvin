## North-star fit

Reuses `prFetchBanner` (`dashboard/src/lib/pr_fetch_status.js:28`) — the function #422 already built to turn `{errors, projects, lastGoodAt, source}` into a tone + sentence, already wired into `MrReview.jsx`'s list banner and already covering exactly the "all fail → red tone" / "some fail → amber tone with names" / "none fail → null" cases this ticket asks for, including the mini/pull-only path (`miniBanner`). It's also already tested end-to-end for rate-limit and all-13-projects-down scenarios in `dashboard/test/error_log.test.jsx:77-96`. The only missing piece is that the tab-dot computation (`mr:reviewStatus` in `index.js:1154` → `computeReviewStatus` in `mr_seen.js:33`) never sees the module-level `prFetch` (`index.js:284`) that already tracks those errors — it's already exposed to the renderer under a different channel, `mr:listStatus` (`index.js:1027`), just not folded into the dot.

Simplest sufficient fix: pass `prFetch` through the existing `mr:reviewStatus` response, and add one new pure helper, `reviewDotStatus`, beside `prFetchBanner` in the same file, that maps a banner's tone onto the dot color/title. No new IPC channel, no new state, no changes to `computeReviewStatus` or `mr_seen.js` at all (keeps `mr_repos.test.js`/`mr_seen.test.js`'s existing 2-arg contract intact, and the mobile-backend's own `computeReviewStatus(prKeys, seenNumbers)` call in `dashboard_gh_api.js` untouched — out of this ticket's cited scope). Token cost: one extra field on an existing IPC response plus ~15 lines of pure, fully unit-testable logic; no extra round trips, no polling added. Leaves Gil strictly more informed (a grey dot now means "go check your network/gh auth," not "nothing to do") without adding any new interaction he has to perform.

## Tests to write first

In a new `dashboard/test/review_dot.test.jsx` (or appended to `pr_fetch_status`'s existing test block in `error_log.test.jsx` — will decide at write time by what's less disruptive to that file's focus) for the new pure `reviewDotStatus({ status, fetch }, now)`:

Ticket's "How we'll try to break it":
1. `gh` not installed — simulate via an error message that matches none of `prFetchBanner`'s `CAUSES` regexes (e.g. `spawn gh ENOENT`) on every repo → tone stays `'red'` regardless of message content → dot `'grey'`.
2. Rate-limited mid-fetch — one repo errors with `'API rate limit exceeded'` while others still have cached PRs (`0 < errors.length < projects`) → tone `'amber'` → dot unchanged (colour from the rest), note mentions the failing repo and "GitHub rate limit".

Misuse the section didn't list, covering the mandated categories:
3. Empty/undefined input: `reviewDotStatus()` and `reviewDotStatus({})` don't throw; return `{ dot: undefined, note: null }` (mirrors the real pre-first-load render in `App.jsx`).
4. Malformed `fetch` (missing `errors`/`projects` entirely) — same as above via `prFetchBanner`'s own defaults; must not throw.
5. Empty registry: `projects: 0, errors: []` → no false "all failed" (guards the `projects > 0` condition already in `prFetchBanner`, re-verified at this call site).
6. Every dependency failing: `errors.length === projects` (direct-GitHub path) → `{ dot: 'grey', note: "Couldn't reach GitHub" }`.
7. Pull-only node, healthy (`source.from === 'mini'`, tone `'info'`) → dot/note **unchanged** — an informational banner must never be mistaken for a failure (this is the one case a naive "banner ? note it : don't" implementation gets wrong).
8. Pull-only node, Mini itself unreachable (tone `'red'`, `state: 'missing'`) → `dot: 'grey'`, but `note` is the Mini-specific sentence (`source.text`), not the literal "Couldn't reach GitHub" — accuracy matters since on that node type GitHub was never contacted directly.
9. Pull-only node, Mini stale (tone `'amber'`) → dot unchanged, note is the feed's own stale-age text.
10. None fail (`errors: []`, direct path) → `{ dot: status, note: null }` exactly reproduces today's behavior — regression guard for AC3.
11. Repeats/concurrency: not separately tested — `reviewDotStatus` is a pure function with no internal state, so repeated/concurrent calls can't interact; a dedicated test would have no failure mode to catch.

No new test for the `mr:reviewStatus` IPC handler itself: the only change there is forwarding the already-produced, already-tested `prFetch` object (no new branching), consistent with how this codebase tests other handlers (through their underlying pure functions, not through `ipcMain.handle` plumbing).

## Decisions

None — the existing `prFetchBanner`/`prFetch` machinery already answers every open question (what counts as "all failed," what text to show, how the mini path differs); nothing here needs Gil to choose between options.

## Task List

1. `dashboard/electron/main/index.js:1154` — in the `mr:reviewStatus` handler, add `fetch: prFetch` to the returned object (no other change).
2. `dashboard/src/lib/pr_fetch_status.js` — add `export function reviewDotStatus({ status, fetch } = {}, now = Date.now())`: compute `const banner = fetch ? prFetchBanner(fetch, now) : null`; if no banner or `banner.tone === 'info'`, return `{ dot: status, note: null }`; if `banner.tone === 'red'`, return `{ dot: 'grey', note: fetch?.source?.from === 'mini' ? banner.text : "Couldn't reach GitHub" }`; else (`'amber'`) return `{ dot: status, note: banner.text }`.
3. Write the tests above for `reviewDotStatus` (TDD — before wiring it into `App.jsx`).
4. `dashboard/src/App.jsx` — import `reviewDotStatus` from `./lib/pr_fetch_status.js`; add `grey: 'bg-neutral-500'` to `DOT_COLOR`; in the tab-render loop, compute `const { dot: mrDot, note: mrNote } = reviewDotStatus(reviewStatus)` and use `mrDot`/composed title (`mrNote` alone when `mrDot === 'grey'`, else `` `${STATUS_LABEL[mrDot]}${mrNote ? ` — ${mrNote}` : ''}` ``) only for `tab.id === 'mr-review'`, leaving the `health` tab branch untouched.
5. Run the dashboard test suite (`dashboard`'s vitest) to confirm no regression in `mr_seen.test.js`, `mr_repos.test.js`, `error_log.test.jsx`.
6. Manually verify in the running app (no network / `gh` revoked) that the dot goes grey with the right tooltip, and with one project's `gh` artificially failing that the dot keeps its colour and gains the note; capture screenshots at 900px and 1440px per the acceptance criteria and pin them on the PR via `marvin-show`.