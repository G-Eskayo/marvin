## North-star fit

**Reuses:** `parseTicketRef(body)` (`dashboard/electron/main/mr_review.js:152`) — already computed per-PR as `ticketRef` at `mr_review.js:364` and already used to derive `sentBack`/`ticketClosed`/`rework` (`mr_review.js:407-410`). The fix wires the existing `ticketNumber` field (`mr_review.js:411`) to that same value instead of a second, narrower parse (`evidence?.ticketRef`) that only exists for schema PRs. No new function, no new field, no new file.

**Simplest sufficient approach:** one-line change at the single place `ticketNumber` is computed, plus widening `parseTicketRef`'s existing regex capture (adding an optional second `repo` arg, default `null` so every other call site — `board.js`, `post_merge_rebase.js`, `merge.js`, `refusal_log.js`, `approve_guard.js` — is byte-for-byte unaffected) to stop a cross-repo `Closes` line from being silently paired with the wrong repo. Every downstream symptom (Deny not retagging, Drop leaving the ticket open, Requirements/Design/stage-strip showing "Not available") shares this one root cause — `MrDetail.jsx`, `mr_actions.js`, `deny.js` all already branch correctly on `ticketNumber`/`pr.ticketNumber` and need no changes, confirmed by reading `mr_actions.js:74-96`, `deny.js:60-80`, and their existing passing tests (`dashboard/test/mr_actions.test.js:209-238`, `dashboard/test/deny.test.js`).

**Tokens:** spends none beyond this; saves future ones — any PR lacking the evidence schema (today all 7 open marvin PRs, per the issue) stops silently losing its ticket link, so the owner stops having to manually chase "Not available" ticket context.

**User capability:** more capable — Deny/Drop start acting on the real ticket instead of doing nothing, and Requirements/Design/stage-strip become visible for every PR, not just schema-conforming ones (mirrors the "every open PR shows" fix already made for `hasSchema` itself, `mr_review.js:206-216`).

**Repo-owner convention check:** `docs/agents/issue-tracker.md` documents `Closes owner/repo#N` as a *legitimate* cross-repo pattern (a private-instance PR closing a public-engine ticket). I'm not rejecting that pattern in general — `parseTicketRef` without a `repo` arg still resolves it everywhere it already did. But `ticketNumber` is consumed downstream *only* ever paired with `pr.repo` (`ticketContext(pr.ticketNumber, pr.repo)` → `ghIssueView(n, repo)` at `index.js:1180-1183`; `activity.timeline(pr.ticketNumber, pr.repo)`; `denied()` → `gh issue ... --repo <pr.repo>`). A bare number can't carry "which repo" on its own, so if the `Closes` line names a *different* repo than `pr.repo`, setting `ticketNumber` anyway would retag/close/display the wrong issue number in the wrong repo — worse than today's "Not available." I'm treating that as a correctness call, not an owner decision: when the `Closes` line's explicit prefix doesn't match `pr.repo`, `ticketNumber` stays `null` for *this PR's own* ticket-detail/Deny/Drop purposes (full cross-repo ticket resolution is a separate, bigger feature, consistent with ADR 0024's "adaptive, deferred" posture).

## Decisions

None — ticket is concrete; the cross-repo handling above is a correctness fix, not a design preference.

## Tests first

All in `dashboard/test/mr_review.test.js` (existing `describe('parseTicketRef', ...)` and `describe('listPipelinePrs', ...)` blocks) and `dashboard/test/deny.test.js` (verify, don't re-add — already covers ticketNumber-truthy paths).

1. **AC1 core — `listPipelinePrs`:** a non-schema PR body with `Closes #70` → `ticketNumber === 70`, numeric. (Replaces the now-wrong assertion at `mr_review.test.js:257` which currently expects `null` for `NON_SCHEMA_BODY`, whose body literally contains `Closes #70` — that assertion encodes today's bug.)
2. **Regression — schema PR unaffected:** `PIPELINE_BODY` (`Closes G-Eskayo/marvin#42`) still yields `ticketNumber === 42` (existing test at `mr_review.test.js:270-278`, must keep passing unchanged).
3. **No ticket reference:** body with no `Closes`/`Fixes`/`Resolves` → `ticketNumber === null` (existing test at `mr_review.test.js:280-287`, must keep passing unchanged).
4. **Attack — cross-repo Closes:** PR's own `repo` is e.g. `G-Eskayo/clarity-captions`, body says `Closes G-Eskayo/marvin#42` → `ticketNumber === null` (not `42`): must not misattribute another repo's ticket number to this PR's repo.
5. **Attack — two Closes lines, first cross-repo then same-repo:** body has `Closes other/repo#1\n\nCloses #70` for a PR in the default repo → `ticketNumber === 70` (falls through to the matching one, doesn't just bail on the first non-matching line).
6. **Attack — two Closes lines, both same-repo:** `Closes #11\n\nCloses #22` → deterministic, picks `11` (first), no throw — document the "first wins" choice in the test name.
7. **`parseTicketRef` own unit tests (no `repo` arg) stay green:** `'Closes #11'` → `'11'`; `'Fixes G-Eskayo/marvin#42'` → `'42'` (existing, `mr_review.test.js:191-197`) — proves the added optional `repo` param is fully backward-compatible for every other call site that doesn't pass it.
8. **`parseTicketRef('Fixes owner/repo#42', 'owner/repo')` (repo matches):** → `'42'` — same-repo explicit prefix still resolves when repo is supplied.
9. **Scope guard — "Part of #N" never sets `ticketNumber`:** body with only `Part of #70` (no Closes/Fixes/Resolves) → `ticketNumber === null`. Locks in that we didn't accidentally widen matching to a relationship that must never trigger Deny/Drop's close-the-ticket behavior.
10. **Malformed/edge input, no throw:** empty string body, `null`/`undefined` body (already guarded by `pr.body || ''` at `mr_review.js:364` — assert explicitly), and a `Closes #` with a very long digit run (e.g. 20 digits) — `Number()` conversion doesn't throw, returns a (possibly imprecise but non-throwing) number.
11. **Case-insensitivity preserved:** `'closes #70'` / `'FIXES #70'` still match (regex already has the `i` flag — regression-guard it explicitly since the regex is being edited).

Out of scope for new tests (unchanged dependencies, no new I/O introduced by this fix): `sentBackTickets`/`rebaseStatus`/`closedTickets` failure-injection tests already exist and don't touch this code path; `deny.js`'s ticketNumber-truthy/falsy branches are already fully covered and untouched by this fix.

## Task List

1. In `dashboard/electron/main/mr_review.js`, widen `parseTicketRef(body)` → `parseTicketRef(body, repo = null)`: capture the optional `owner/repo` prefix in its own group; when `repo` is supplied and the captured prefix exists and doesn't case-insensitively match it, skip that match and continue scanning (switch the regex to global and loop) rather than returning early — so a later, same-repo `Closes` line can still win.
2. At `mr_review.js:364`, pass the PR's own repo into that call: `const ticketRef = parseTicketRef(pr.body || '', pr.repo || MARVIN_REPO)`.
3. At `mr_review.js:411`, replace `ticketNumber: evidence?.ticketRef ? Number(evidence.ticketRef) : null,` with `ticketNumber: ticketRef !== null ? Number(ticketRef) : null,` (reusing the same `ticketRef` already in scope, now repo-aware).
4. Update the stale assertion at `mr_review.test.js:257` (expects `null` for `NON_SCHEMA_BODY`) to expect `70`, and add the new tests listed above (items 1, 4-11) to the existing `describe('parseTicketRef', ...)` and `describe('listPipelinePrs', ...)` blocks.
5. Run the dashboard's full Vitest suite (not just this file) — full-suite-before-hand-merge convention — and confirm no other test asserts the old `evidence?.ticketRef`-only behavior.
6. Manually verify end-to-end against a real or seeded non-schema PR with `Closes #N`: Deny → ticket gets `needs-reengagement` + comment; Drop → ticket closes; MrDetail shows Requirements/Design and the stage strip instead of "Not available."
7. Capture before/after screenshots at 900px and 1440px of an affected PR's detail view (Requirements/Design sections + stage strip appearing) using the `run` skill to drive the dashboard headlessly, and pin them to the PR per the repo's screenshot/image-hosting rule (`docs/agents/showing-things.md`, `pr-images-private-repo-raw-host.md`).
8. Open the PR with `Closes #806`, named per the repo's "every PR names its ticket" convention.