## North-star fit

**Reuses before adding anything:** confirmed by re-reading every file this round, not by trusting the prior doc's narrative. The full feature is already built and wired in this worktree: `needs_you.js` (`rankNeedsYou`, already covered by its own test suite), `relations_service.js`'s `overview()`/`needsYou()` (project attachment, count parity), the IPC round-trip, `saved_state.js`, and the component tree — `NeedsYouList.jsx` is already rendered unconditionally at the top of `DashboardHome.jsx:149`, above the loading gate, and `ActivityBoard.jsx` forwards `onOpenTicket` unchanged. None of that needs building. Most of the bugs the *previous* doc planned to fix are **already fixed** in the current worktree state (loading/empty fallthrough, `cleanIpcError` usage, `row.unblocks?.count` guard, `priorityPill` neutral-for-p2/p3, `applyLoadResult` replace-on-any-array, project-not-repo sort). I verified each one by reading the live file rather than re-deriving the fix.

**Simplest sufficient approach:** this round is a surgical fix of exactly what review flagged as still broken, plus a handful of still-live defects I found rereading the same files (below) — no new files, no new abstractions, no redesign.

**Where it spends/saves tokens:** the generation-counter fix is a few lines inside `ready()`, not a new caching layer. No reason to touch the ~18-minute pytest suite — nothing here touches Python; the prior attempt's comment history shows repeated 1200s timeouts, almost certainly from the merge-verification harness running the *full* suite rather than the touched vitest files — this plan explicitly scopes test runs to the touched files only.

**User capability:** unchanged and correct — this surfaces real invisible work (Seal Speak #406/#408/#410-style tickets) so Gil can act on it himself; nothing here does anything *for* him.

**Correction to the previous doc's framing:** it claimed `relations_service.js`'s `invalidate()`-during-build-race was fixed by the generation counter already in the file. It wasn't — `built = await buildInFlight` at line 60 is unconditional and overwrites the generation check that ran inside `.then()`, so the dead-code finding from review is accurate. I'm not repeating that mistake: the fix below actually closes the race, and the test is a real race, not a same-order call sequence that already passed before the fix existed.

## Files read (current state, this session)

`relations_service.js`, `relations_service.test.js`, `needs_you.js`, `needs_you_view.js`, `needs_you_view.test.js`, `NeedsYouList.jsx`, `needs_you_list_render.test.jsx`, `DashboardHome.jsx`, `ActivityBoard.jsx`, `saved_state.js`, `docs/agents/decisions-format.md`, and `ProjectBoard.jsx` (for the pill-casing precedent below).

## Must-fix items from review, and the real fix for each

1. **`relations_service.js:60` — stale in-flight build gets cached anyway.** `built = await buildInFlight` always commits whatever `buildInFlight` resolves to, so the `result.generation === generation` check inside `.then()` is dead code: the caller overwrites `built` unconditionally one line later. Fix: track which generation an in-flight build was started for; only **join** an in-flight build if it matches the current generation (otherwise start a fresh one); and after awaiting, only commit the result (`built = result`) if its generation still matches — if not, recurse into `ready()` to get a build that does. Concretely:
   ```js
   async function ready() {
     if (!built || built.generation !== generation || now() - built.at > ttlMs) {
       if (!buildInFlight || buildInFlight.generation !== generation) {
         const startedFor = generation
         const p = build().then(result => {
           if (buildInFlight === p) buildInFlight = null
           return result
         }).catch(err => { if (buildInFlight === p) buildInFlight = null; throw err })
         p.generation = startedFor
         buildInFlight = p
       }
       const result = await buildInFlight
       if (result.generation !== generation) return ready() // invalidated while we were waiting
       built = result
     }
     return built
   }
   ```
   This removes the now-pointless commit check from inside `build()`'s own `.then()` — the join/recurse logic replaces it, so there's exactly one place that decides freshness.

2. **`relations_service.test.js:118` — doesn't exercise the race.** Rewrite so `invalidate()` fires *while* the first `getBoardData` is still pending (not after it resolves), using a controllable promise:
   ```js
   it('invalidate() during an in-flight build() does not let the stale result get served or cached', async () => {
     let release
     let calls = 0
     const getBoardData = vi.fn(async () => {
       calls += 1
       if (calls === 1) await new Promise(r => { release = r })
       return { issues: [issue(1)], prs: [] }
     })
     const s = make({ getBoardData })
     const first = s.forTicket('G-Eskayo/marvin', 1) // build #1 starts, blocks inside getBoardData
     await Promise.resolve() // let the microtask queue reach the pending await
     s.invalidate()
     release()
     await first
     await s.forTicket('G-Eskayo/marvin', 1) // must not reuse build #1's stale result
     expect(getBoardData).toHaveBeenCalledTimes(2)
   })
   ```
   This fails against the current code (build #1's result gets cached at line 60 regardless of the invalidate) and passes once fix #1 lands.

3. **`relations_service.test.js:133` — test name claims coverage it doesn't have.** `needsYou()` always computes `unblocks` itself (via `transitiveUnblocks` in `needs_you.js`); there is no code path where a row from this function is missing `unblocks`, so "defends against missing unblocks" is not a real scenario at this layer (it *is* real at the `sortRows`/`NeedsYouList` layer, which already has that coverage in `needs_you_view.test.js:21`). Replace the mislabeled test with one that actually exercises what the `Map` optimization could get wrong — cross-repo key collisions:
   ```js
   it('needsYou() attaches each row to its own ticket, not a same-numbered ticket in another repo', async () => {
     const s = createRelationsService({
       getRepos: () => ['G-Eskayo/marvin', 'G-Eskayo/other'],
       getBoardData: async (repo) => ({
         issues: [issue(2, { labels: [{ name: 'ready-for-human' }, { name: repo.endsWith('other') ? 'project:other-proj' : 'project:marvin-proj' }] })],
         prs: []
       }),
       getDocs: async () => [], getProjects: () => projects
     })
     const rows = await s.needsYou()
     const marvinRow = rows.find(r => r.repo === 'G-Eskayo/marvin')
     const otherRow = rows.find(r => r.repo === 'G-Eskayo/other')
     expect(marvinRow.project).toBe('marvin-proj')
     expect(otherRow.project).toBe('other-proj')
   })
   ```
   This genuinely fails if the `repo#number` keying in the `Map` were ever collapsed to a bare `number` key.

## Other defects found rereading the code (not in the official 3, still real, cheap to fix now rather than draw another review round)

4. **`NeedsYouList.jsx:148,158` — Prev/Next clamp against raw `currentPage`, not `paginated.currentPage`.** If a background refresh shrinks the list, raw state can sit one page past what's displayed (e.g. raw=3 while displayed/clamped="2 of 2"); clicking Prev computes from the raw value and lands back on the same displayed page — looks like Prev does nothing. Fix: base both button handlers on `paginated.currentPage`, not the closure's `p`.
5. **`relations_service.js` — a bare `project:` label produces `project: ''`.** The component falls back to the repo name via `||` (line 116), but `sortRows`'s `'project'` branch uses `?? a.repo`, and `''` is not nullish, so these rows sort first under an empty key instead of grouping with their repo. Fix: in `needsYou()`, treat an empty `projectId` the same as a missing one (`projectId || projectIdOf(row.repo)`).
6. **`needs_you_view.js:25` (`priority` sort) — `parseInt(priority[1])` has no `NaN` guard.** Every row from `rankNeedsYou` is already constrained to `p0`–`p3` or `null`, but `sortRows` is an exported pure function and a stale/cached row could carry a malformed string. Default `NaN` to `99` (same pattern already used for missing priority).
7. **`NeedsYouList.jsx:107` — `row.repo.split('/')` throws on a cached row with no `repo`.** The PR already guards the equivalent case for `unblocks` (`row.unblocks?.count`) but not for `repo`. Fix: `row.repo?.split('/')[1] || row.repo || ''`.
8. **`kindLabel` casing — resolved, not a Decision.** The prior review flagged this as ambiguous ("needs answer"/"needs you" vs. "Needs answer"/"Needs you"). I checked the codebase instead of guessing: `ProjectBoard.jsx:104` already renders a literal lowercase `needs you` pill for `card.owner === 'human'`. That's the established convention this exact feature should match, and it's also the literal casing Gil used in his 2026-10-13 comment. Fix `kindLabel` to return lowercase `'needs answer'` / `'needs you'`, and update `needs_you_view.test.js:81` to match. No owner input needed — this is a bug fix against an existing in-repo precedent, not a new design choice.

## Decisions

None. Every open question in the issue was answered by Gil on 2026-10-13 (rows-per-page, empty state, pill colors/wording, sort options, saved-state behavior), and the one new ambiguity review raised (`kindLabel` casing) resolves against existing code (`ProjectBoard.jsx:104`) rather than needing a choice.

## Tests written first

**`relations_service.test.js`** (only `getBoardData` mocked, everything downstream real):
1. Real in-flight race: `invalidate()` fires while `build()` is still pending → the next call does not serve or cache the stale result (replaces the current test at line 118; see fix #2 above).
2. Cross-repo key-safety: two repos each with a ticket numbered `#2` → each row's `project` matches its own repo's label (replaces the current test at line 133; see fix #3 above).
3. A ticket with a bare `project:` label (empty id) falls back to `projectIdOf(repo)`, not `''` (new — proves fix #5).
4. *(Keep as-is, already correct)* string-vs-object label handling (line 144), concurrent-call dedup (line 96), one-repo-failure isolation (line 42), count parity (line 88).

**`needs_you_view.js`** (pure module, no mocks):
5. `sortRows(..., 'priority')` with a malformed priority string (e.g. `'xyz'`) does not throw and does not let `NaN` corrupt ordering — sorts as if unprioritized (new — proves fix #6).
6. `paginate(rows, page, 5)` with `page = 0`, a negative page, `NaN`, and a page past the last page all clamp into `[1, totalPages]` (new — this exact case isn't in the current suite, only in-range pages are).
7. `kindLabel('needs-info')` → `'needs answer'`, `kindLabel('ready-for-human')` → `'needs you'`, unrecognized → `'needs you'` (updated — current test asserts the wrong, capitalized strings; this one fails against the current code and passes after fix #8).
8. *(Keep as-is, already correct and already real)* `sortRows` by unblocks/age/project, `paginate` basic slicing, `priorityPill` colors, `applyLoadResult`, sort-preference read/write including a storage that throws.

**`needs_you_list_render.test.jsx`** (`renderToStaticMarkup`, using the `globalThis.window = {...}` idiom already established in `decisions_view.test.jsx:74`, reset between tests):
9. A saved payload with `value: []` seeded into `globalThis.window.localStorage` before mount renders "Nothing needs you" with no loading text — the literal empty-state acceptance screenshot case, not currently covered (today's render tests only check the *first-mount* loading state, never the distinguishable empty-after-load state).
10. A saved row missing `repo` entirely renders without throwing (new — proves fix #7).
11. A saved row with `kind: 'needs-info'` renders the lowercase text `needs answer` (updated — proves fix #8 at the component level too).
12. *(Keep as-is)* header/sort-control structure, styling, first-mount loading text.

**Explicitly not tested, and why (unchanged from the known gap):** the Prev/Next click handlers (fix #4) and the real `window.api.activity.needsYou()` fetch path live inside event handlers/`useEffect`, which `renderToStaticMarkup` never executes. Fix #4 is a one-line change to which value the handler reads (`paginated.currentPage` vs. local `p`) — it has no pure-function equivalent to push the fix into, unlike the earlier pagination-clamp bug which was fully absorbed into `paginate()` itself. It's covered by the required manual/screenshot verification in "Done when," not by vitest.

## Task List

1. `dashboard/electron/main/relations_service.js`: replace the `ready()`/`buildInFlight` logic with the generation-tracked join-or-rebuild version (fix #1); make `needsYou()` fall back to `projectIdOf(repo)` when the `project:` label yields an empty string (fix #5).
2. `dashboard/test/relations_service.test.js`: replace the test at line 118 with the real in-flight-race test (test 1); replace the test at line 133 with the cross-repo key-safety test (test 2); add the bare-`project:`-label test (test 3).
3. `dashboard/src/lib/needs_you_view.js`: guard the `priority` sort branch against a non-`p[0-3]` string (fix #6); change `kindLabel` to return lowercase `'needs answer'` / `'needs you'` (fix #8).
4. `dashboard/test/needs_you_view.test.js`: add the malformed-priority test (test 5) and the full pagination-clamp test (test 6); update the `kindLabel` test to the lowercase strings (test 7).
5. `dashboard/src/components/NeedsYouList.jsx`: base both Prev/Next handlers on `paginated.currentPage` instead of the local `currentPage` closure value (fix #4); guard `row.repo?.split('/')[1] || row.repo || ''` (fix #7).
6. `dashboard/test/needs_you_list_render.test.jsx`: add the empty-after-load test seeded via `globalThis.window` (test 9); add the missing-`repo` render test (test 10); add the lowercase-`kindLabel` render test (test 11); reset `globalThis.window` between tests that set it.
7. Re-verify (read, no edit) that `DashboardHome.jsx` and `ActivityBoard.jsx` still need no changes after steps 3–6 — they're already correct.
8. Run only the touched vitest files (`relations_service.test.js`, `needs_you_view.test.js`, `needs_you_list_render.test.jsx`) plus `npm run build` for a bundle sanity check. Do not run the full pytest suite — nothing in this change touches Python, and the prior attempt's repeated 1200s timeouts strongly suggest the full suite, not these targeted tests, was what blew the budget.
9. Screenshots for the PR per "Done when": list populated (lowercase pill wording, project chip, neutral P2/P3 pill visible), list empty showing "Nothing needs you", and a ticket opened from a row landing on its `HumanTaskPanel` — captured via Electron CDP attach against the running dashboard, per the hard screenshot rule for any look change.