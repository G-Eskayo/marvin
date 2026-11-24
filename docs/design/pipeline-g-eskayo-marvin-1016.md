## North-star fit

- **Reuses** (no new pattern invented):
  - `relations.js`'s `tk(repo, n) = \`${repo}#${n}\`` composite-key convention — reused for board.js's open/held/not-planned sets so a cross-repo `Blocked by` can never again collide with this repo's own numbering (the exact bug named in the ticket).
  - `boards.js:prsOfProjects` (line 178) — mirrored one-for-one as `issuesOfProjects`, reading `.issues` instead of `.prs` from the *same already-cached* `getBoardData` call `index.js:boardInputs` makes today. Zero new `gh` calls.
  - `board.js:closingPrs`'s `foreign`/`prLabel` pattern (only attach `repo` to a card field when it differs from the board's own repo) — reused for `blockedBy` chip objects instead of inventing a second cross-repo-display convention.
  - `ticket_refs.js`/`pr_ticket_check.py`'s existing `PART_OF` list-regex (comma/`&`/`and`-separated refs, code-fence stripping, `owner/repo#N`-or-URL) — reused verbatim as the template for the five new keywords, rather than writing five new regex families.
- **Simplest sufficient approach**: one parser emits `{repo, number, relation}` for all 7 words, for both ticket and PR bodies; `relations.js`, `board.js`'s `dependencyRefs`, and `needs_you.js`'s `blocksGraph` all consume it instead of each hand-rolling its own "Blocked by" regex (today there are two independent, both-buggy, copies — `board.js:71` and `relations.js:53`). Collapsing them to one is the Colton check: same principle, one form.
- **Resources**: the cross-repo `Blocked by` fix costs nothing extra — it rides the cache `prsOfProjects` already warms. The parser extension is pure regex, no new I/O.
- **Capability, not passivity**: a wrongly-placed card ("blocked" when it isn't, or not-blocked when it is) currently has to be caught by Gil by hand (per #1015's motivating incidents); this makes the board tell the truth on its own.
- **Scoping call (not an owner decision, an engineering judgment within normal latitude):** cross-repo `Blocked by` only gates the column using data already in hand for *registered* boards (via `issuesOfProjects`, like PRs). A blocker in a repo with no board gets no live-state fetch — it fails safe (never silently guessed open or closed) and shows up via the Related panel only. Live-state fetching for un-registered repos, auto-closing covered tickets, and health checks on broken links are explicitly #1017's ("act on links") scope per #1015's own slice ordering, not this ticket's.
- **Wording calls made without a Decisions block:** the IN_WORD reverse-phrases for the three words the ticket doesn't spell out (`duplicate of` → `duplicated by`, `supersedes` → `superseded by`, `related to` → `related to`, symmetric) are UI microcopy, not a design fork — `covered by`/`covers` is already fixed by the ticket's own worked example.

## Tests first

All new/changed parser cases go in `dashboard/test/fixtures/pr_ticket_refs_cases.json` (run by both `ticket_refs.test.js` and `test_pr_ticket_check.py`, so one case covers both languages).

**From "How we'll try to break it":**
1. Each of the 5 new words inside a code fence / inline backtick — ignored, as today.
2. A mixed-case keyword for each new word (`DUPLICATE OF #5`, `Covered By: #9`, `SuperSedes #3`, `related TO #4`, `blocked BY #2`).
3. The same ticket number in two repos: a body with `Related to #5` and `Related to o/x#5` on one ticket in repo `o/r` must resolve to two distinct targets, never merged into one; `board.js`'s cross-repo `Blocked by o/x#7` must not be satisfied by repo `o/r`'s own open `#7`.
4. A URL ref for each new word.
5. A ref to a ticket that doesn't exist: relation index still builds the edge; `infoT` falls back to `(not loaded)` without throwing.
6. A self-reference (`#16` says `Duplicate of #16`) — dropped, no edge (exercises `add()`'s existing `from.key===to.key` guard against the new kinds).
7. A cycle (`A` "Duplicate of" `B`, `B` "Duplicate of" `A`) — two distinct edges built without recursion; `around()` on either returns the other correctly ("duplicate of" / "duplicated by"), no infinite loop, no dedup into one edge.
8. 50 refs in one body (`Related to #1, #2, ... #50`) — all 50 parsed, none dropped or truncated.

**Misuse the section didn't name:**
9. Bad/empty/huge/malformed input: null/undefined body for each new word (parity with existing `prTicketRefs(null, …)` coverage); a ref glued to more text (`Supersedes #5abc`, `Covered by #6-x`) is not a ref; a glued false-keyword (`outcovers #5`, `depart of #7`, `superseded of #8`) matches nothing (word-boundary parity with existing `part of the #5 rewrite` case); a 500-ref body doesn't hang (perf smoke test, no catastrophic backtracking).
10. Each dependency failing: in `issuesOfProjects`, one registered repo's `getData` rejecting drops only that repo's cross-repo issue data (same try/catch isolation `prsOfProjects` already has for PRs) — board still renders using what loaded.
11. Repeats: the same ref named by two different words on one ticket (`Duplicate of #5` and `Related to #5`) — exactly one relation survives per the existing `closes`-wins-else-first-write-wins rule in `put()`; documented, not silently arbitrary.
12. Wrong permissions / stale state: N/A — no filesystem/permission-sensitive code is touched, and relations are still derived live from text on every read (no new cache to go stale). Noted, not tested.
13. A person's mistake: a ref with no slash where one was meant (`ownerrepo#5`) doesn't match the repo-qualified form and isn't silently treated as cross-repo; a keyword with no ref after it (`Supersedes nothing yet`) yields no ref.

**Board-specific (the `dependencyRefs` bug and its fix):**
14. `dependencyRefs` on a body with `Blocked by G-Eskayo/other#5` returns `{repo: 'G-Eskayo/other', number: 5}` — not bare `5`, and not matched against this repo's own `#5`.
15. `buildBoard`/`deriveColumn`: a cross-repo blocker confirmed open via `crossRepoIssues` → column `blocked`, reason names the foreign repo; the same ref with no cross-repo data available → NOT blocked (fails safe, never guesses).
16. `ticketLinked`/`closingPrs` regression: a PR body with only `Related to #9` (no `Closes`/`Part of`) must not move ticket `#9` to review — the broadened shared parser must not leak new relation words into PR-closing logic.
17. `blocksGraph` (needs_you.js, documented single-repo contract): a same-numbered ticket in another repo must not appear as a blocker/dependent of this repo's tickets.

## Decisions

None needed — the one place real ambiguity existed (the `covers`/`covered by` direction) is pinned by the ticket's own worked example, and the rest are implementation calls within normal latitude (see North-star fit).

## Task List

1. Extend the shared parser (`dashboard/electron/main/ticket_refs.js`, `lib/pr_ticket_check.py`) with `blocked-by`, `duplicate-of`, `covered-by`, `supersedes`, `related-to` keyword regexes (same list-ref, code-fence-stripped, `owner/repo#N`-or-URL shape as `PART_OF`/`CLOSES`). Narrow `ticketLinked`/its Python equivalent to only ever return `closes`/`part-of`.
2. Add the new fixture cases (test list above) to `dashboard/test/fixtures/pr_ticket_refs_cases.json`; confirm both `ticket_refs.test.js` and `test_pr_ticket_check.py` pick them up.
3. `relations.js`: replace `blockedByNumbers()` and the ad hoc PR-only `prTicketRefs()` call with one shared-parser pass over every ticket and PR body, emitting edges for all 7 relation kinds (repo always resolved, never dropped). Extend `OUT_WORD`/`IN_WORD` with `duplicate-of`/`covered-by`/`supersedes`/`related-to`. Add/port the self-reference and cycle tests.
4. `board.js`: rewrite `dependencyRefs()` on the shared parser filtered to `blocked-by`, returning `{repo, number}` (repo omitted when it's the issue's own, mirroring `closingPrs`'s `foreign` pattern). Change `openDependencies`/`deriveColumn`/`deriveColumnCore`/`buildBoard` to work against composite-key `openKeys`/`heldKeys`/`notPlannedKeys` Sets (own-repo issues plus an optional `crossRepoIssues` param), threading the issue's own `repo`. Update `board.test.js` call sites from bare-number Sets to composite keys.
5. `boards.js`: add `issuesOfProjects(repos, getData, except)` beside `prsOfProjects` (same shape, reads `.issues`); thread its result through `loadBoard` as `otherIssues` → `buildBoard`'s `crossRepoIssues`.
6. `index.js`: add `issuesOfProjects(...)` to the existing `Promise.all` in `boardInputs()`, alongside `prsOfProjects(...)`.
7. `needs_you.js`: update `blocksGraph` to use the new `dependencyRefs` shape, only counting a dependency when its resolved repo matches the function's own `repo` argument (keeps its documented single-repo scope correct instead of leaking cross-repo matches).
8. `ProjectBoard.jsx`: minimal update to the `card.blockedBy` chip to show the foreign repo (same convention `PrChip`/`prLabel` already use) when a blocker object carries one.
9. Write/port the remaining tests from the list above (perf/50-refs, partial-fetch-failure isolation, `ticketLinked` regression, board blocked/not-blocked cross-repo cases).
10. Docs: update `docs/agents/issue-tracker.md` (new bullet listing all 7 link words and direction) and `CONTEXT.md` ("Names its ticket" paragraph and the "Blocked" column rule) to describe the full vocabulary and the cross-repo fix.