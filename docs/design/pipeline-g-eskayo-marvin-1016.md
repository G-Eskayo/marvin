## North-star fit

**Reuses:** `dashboard/electron/main/ticket_refs.js`'s `REF`/`parseRef`/`prTicketRefs` machinery (marvin#1004) is the only place in the codebase that already parses `owner/repo#N` correctly. `board.js`'s `dependencyRefs` (line 68-75) and `relations.js`'s `blockedByNumbers` (line 50-56) each carry their *own* copy of a cross-repo-blind regex (`(?:[\w.-]+\/[\w.-]+)?#(\d+)` with the repo group discarded) — that duplication **is** the repo-dropping bug the ticket names. The fix is to delete both copies and have them call one extended parser, the same "one parser shared by JS and Python, with shared test cases" pattern #1011 already established. Cross-repo PR resolution already has a working precedent too (`boards.js:prsOfProjects`, `index.js:boardInputs`, CONTEXT.md "Names its ticket") — reusing *that* pattern for tickets costs no new GitHub calls, since `getBoardData(repo)` is already memoized per repo (`index.js:getBoardData`, comment: "shared by the board view and the relation index: from memory until that repo changes").

**Simplest sufficient approach:** one generic relation-ref extractor (all seven words: closes, part-of, blocked-by, duplicate-of, covered-by, supersedes, related-to) in `ticket_refs.js`/`pr_ticket_check.py`, with `prTicketRefs`/`ticket_refs` kept as a thin closes/part-of-only filter over it (so the `bin/gh` "names its ticket" gate and board-column logic are untouched). `board.js`'s `dependencyRefs` becomes a filter for `blocked-by` plus the existing `## Blocked by` section-bullet scan (now also repo-aware). `relations.js` drops its private `blockedByNumbers` and calls the same function.

**Resources:** net negative new surface — deletes two buggy regexes, adds one well-tested one; the cross-repo ticket-state lookup reuses an already-warm cache (zero extra `gh` calls).

**Phone-OS fit:** a link means the same thing everywhere (north star 2) — today it silently means the wrong thing when two repos share a ticket number.

**More capable, not more passive:** this only makes the boards and Related panel *tell the truth faster*; it doesn't auto-close or auto-skip anything (that's #1017). No argument against it from north star 3.

**Machine:** no preference — pure dashboard/lib code, builds on the laptop/Mini as usual.

---

## Decisions

<!-- marvin:decisions -->
### cross_repo_depth: How deep should the "Board blockers work across repos" fix go?
- [ ] A: Shallow — fix the collision bug (a foreign `owner/repo#5` never gets confused with this board's own `#5`) and show the correct repo in the card/chip text. A foreign ticket's live open/closed state is not resolved; such a blocker never shows as cleared or as currently blocking from this alone.
- [ ] B: Deep — also resolve the foreign ticket's real open/held/not-planned state, the same way PR cross-repo linking already works (#1011): thread a cached, cross-project ticket lookup into `buildBoard` (new `issuesOfProjects`, mirroring `prsOfProjects`; zero extra GitHub calls since `getBoardData` is already memoized per repo). A card is genuinely blocked until the foreign ticket closes, not just until the fix stops colliding.

### epic_extras: Pull in the three extra robustness items `#1015` assigns to `#1016` by number but `#1016`'s own body doesn't mention?
- [ ] A: No — build exactly what `#1016`'s own "What to build" / "How we'll try to break it" say (vocabulary + cross-repo fix + docs). File a follow-up ticket for: an audit trail of added/removed links, reading GitHub's native sub-issues/"blocked by" fields, and resolving renamed/moved repos via GitHub's redirect.
- [ ] B: Yes — implement all three now as part of this ticket.

### same_ref_two_words: When one ref is named by two different new relation words in the same body (e.g. "Blocked by #5" and later "Related to #5"), which wins?
- [ ] A: Strongest wins, in this order: closes > part-of > blocked-by > duplicate-of > covered-by > supersedes > related-to (mirrors the existing "closes wins over part-of" precedent).
- [ ] B: First-written wins (order of appearance in the body), same tie-break the existing hit-sort already uses for same-relation duplicates.
<!-- /marvin:decisions -->

*(Plan below assumes 1A / 2A / 3A — the narrowest, cheapest options — and calls out anywhere a different answer changes the task list.)*

---

## Tests first

`dashboard/test/fixtures/relation_refs_cases.json` (new, same shape as `pr_ticket_refs_cases.json`), run by both a new `relationRefs` (JS) and `relation_refs` (Python) — one case per bullet:

1. **Code fences / inline code ignored** — each of the 5 words (blocked-by, duplicate-of, covered-by, supersedes, related-to) inside ``` ``` ``` and `` ` ` `` is dropped, as today.
2. **Mixed-case keyword** — `DUPLICATE OF`, `Covered By`, `SUPERSEDES`, `Related To`, `BLOCKED BY #5` all match.
3. **Same ticket number in two repos** — body `"Blocked by G-Eskayo/other#5"` on a board whose own repo also has an open `#5`: asserts the parsed ref is `{repo: 'G-Eskayo/other', number: 5}`, never collapsed into the board's own `#5`.
4. **URL ref** — `https://github.com/o/x/issues/9` after each of the 5 words.
5. **Ref to a ticket that doesn't exist** — `openDependencies`/`forTicket` on an unresolvable ref: no crash, not reported as blocking, shows `(not loaded)` in Related (existing `infoT` fallback) rather than erroring.
6. **Self-reference** — ticket `#7`'s own body says `"Blocked by #7"` (and separately `"Duplicate of #7"`): never creates a self-edge (relations.js's existing `add()` guard) and `openDependencies` never reports a ticket as blocked by itself (new guard — this is a real pre-existing gap: `openDependencies` today has no self-number filter).
7. **A cycle** — ticket A body `"Duplicate of B"`, ticket B body `"Duplicate of A"`: both directions show in each one's Related panel (`duplicate of` / `duplicated by`), no infinite loop, no dedup swallowing one side.
8. **50 refs in one body** — a `"Related to #1, #2, ... #50"` list and 50 separate `"Blocked by #N"` lines: all 50 parsed, bounded running time (regression guard against catastrophic backtracking).

Additional misuse, per the generic break-it checklist:
9. Non-string / `null` / `undefined` body for the new function (mirrors existing `prTicketRefs(null, 'o/r')` test).
10. Huge/malformed glued text: `"Unblocked by #5"`, `"depart of #7"`, `"duplicated-of #8"`, `"#5abc"` after each new word — none match (mirrors existing "closing word glued to text" / "ref glued to more text" cases).
11. Same ticket named twice the same way (`"Duplicate of #5. Duplicate of o/r#5"`) → one ref, not two.
12. Same ref named by two different new words → resolves per Decision `same_ref_two_words`.
13. One project's `getBoardData` failing while resolving cross-repo blockers doesn't take down this board's own columns (mirrors `prsOfProjects`'s existing try/catch-per-repo test) — only if Decision `cross_repo_depth` = B.
14. `board.js` existing suite: extend the `"Blocked by #n"` tests with a cross-repo variant for `deriveColumn`/`buildBoard`/`openDependencies`, and extend `needs_you.js`'s `blocksGraph` tests the same way (it shares `dependencyRefs`/`openDependencies`).
15. `relations.js`: extend the existing "`expresses blocking in both directions`" test with a cross-repo pair, plus one new test per relation word for the two-way Related wording (`duplicate of`/`duplicated by`, `covered by`/`covers`, `supersedes`/`superseded by`, `related to`/`related to`), including the ticket's own worked example ("covered by PR #8" / "covers #393" — a ref that resolves to a PR node, not a ticket node).
16. Docs: no automated test, but a manual diff check that `docs/agents/issue-tracker.md` and `CONTEXT.md` both list all seven words under "Names its ticket" / a new "Link vocabulary" entry.

---

## Task List

1. Add `dashboard/test/fixtures/relation_refs_cases.json` with the cases above (closes/part-of cases are *not* duplicated here — they stay owned by `pr_ticket_refs_cases.json`).
2. `dashboard/electron/main/ticket_refs.js`: add `BLOCKED_BY`, `DUPLICATE_OF`, `COVERED_BY`, `SUPERSEDES`, `RELATED_TO` regexes (same `REF`/list-separator construction as `CLOSES`/`PART_OF`); add `relationRefs(body, repo)` returning all seven kinds with the priority order from Decision `same_ref_two_words`; redefine `prTicketRefs` as a closes/part-of filter over it (output unchanged, existing tests stay green).
3. `lib/pr_ticket_check.py`: mirror step 2 (`relation_refs`, `ticket_refs` redefined as a filter) so the two parsers can't drift; run `relation_refs_cases.json` from both `dashboard/test/ticket_refs.test.js` (new describe block) and `lib/tests/test_pr_ticket_check.py` (new test).
4. `dashboard/electron/main/board.js`: rewrite `dependencyRefs(issue, repo)` to combine `relationRefs(issue.body, repo).filter(blocked-by)` with the (now repo-aware) `## Blocked by` section-bullet scan; drop the self-reference guard into `openDependencies`; update `blockedBy`/`heldDependencies`/`notPlannedDependencies` card fields and the `reason` text to carry `{repo, number}` and render foreign refs as `repo#n` (same convention as `prLabel`'s foreign-PR chip).
5. If Decision `cross_repo_depth` = B: add `issuesOfProjects(repos, getData, except)` to `boards.js` (mirrors `prsOfProjects` exactly); thread `otherTickets` through `loadBoard` → `buildBoard` the same way `otherPrs` already flows; wire it in `index.js:boardInputs` and `relations_service.js:build()` (which already has all-repo tickets in hand — just needs to pass them in); leave mobile-backend's `/boards/load` as-is (it already omits `otherPrs` too — pre-existing gap, out of scope here).
6. `dashboard/electron/main/relations.js`: delete `blockedByNumbers`; wire `relationRefs` into both the ticket loop and the PR loop for all 5 non-closes/part-of words, resolving each ref's node type (ticket vs PR) by checking `ticketNodes`/`prNodes` before defaulting to ticket; add `OUT_WORD`/`IN_WORD` entries for `duplicate-of`, `covered-by`, `supersedes`, `related-to`; fix the `mentions`-vs-`blocked-by` dedup check (line 104) to compare resolved `repo#number` keys instead of bare numbers.
7. `dashboard/electron/main/needs_you.js`: update `blocksGraph` to build repo-qualified keys from the full (already-cross-repo) `tickets` list instead of grouping by repo first, so a cross-repo "Blocked by" is no longer silently dropped there either.
8. Update `dashboard/test/board.test.js`, `relations.test.js`, `relations_service.test.js`, `boards.test.js`, and any `needs_you` tests for the new shapes/behaviors (steps 4-7).
9. `dashboard/src/components/ProjectBoard.jsx`: render a foreign `blockedBy` entry as `⛔ repo#n` (reuse the existing foreign-PR-chip convention) instead of assuming same-repo.
10. Document the full vocabulary (`Closes`, `Part of`, `Blocked by`, `Duplicate of`, `Covered by`, `Supersedes`, `Related to`) in `docs/agents/issue-tracker.md` and CONTEXT.md's "Names its ticket" entry, including the two-way Related wording table and the cross-repo form for every word.
11. If Decision `epic_extras` = B: scope and implement the audit trail, GitHub-native sub-issues/"blocked by" fields, and repo-redirect resolution as additional tasks (not detailed above — would need its own design pass).