## North-star fit

**Reuses:** the whole feature is an extension of #1011's pattern, not a new mechanism:
- `dashboard/electron/main/ticket_refs.js` `prTicketRefs`/Python's `lib/pr_ticket_check.py` `ticket_refs` — the regex table gets 5 more keyword entries (`blocked by`, `duplicate of`, `covered by`, `supersedes`, `related to`), reusing the exact `PART_OF` regex shape (`\bKEYWORD:?\s+(REF(?:\s*(?:,|&|\band\b)\s*REF)*)`) and the existing `REF` token (already handles `owner/repo#N` and GitHub URLs) and `stripCode`. One parser, one shared cases file, as today.
- `dashboard/electron/main/relations.js` `buildRelationIndex`'s `OUT_WORD`/`IN_WORD` maps get 5 more entries — the Related panel, `linkify`, and the self-reference guard (`from.key===to.key`) in `add()` need no changes; they already generalize over any relation kind.
- Cross-repo "read once, reuse the cache" — `dashboard/electron/main/boards.js` `prsOfProjects` (added in #1011) is the exact pattern for the one genuinely new piece: knowing whether a cross-repo blocker is still open. A sibling helper reads the same already-warm `getBoardData` cache (already fetched once per registered repo for `otherPrs`), so this costs zero extra GitHub calls, not a new poller.

**Simplest sufficient approach:** no new stored link table (#1015's "connect them relationally, not another button" still holds) and no new parser file. `Related.jsx` needs zero changes — it already renders whatever `relation` string it's given. The one real UI touch is `ProjectBoard.jsx`'s blocked-by rendering, because the bug fix genuinely changes what `card.blockedBy` means (same-repo-only plain numbers was always wrong once a cross-repo ref matched the wrong ticket by number).

**Resources:** this stays regex + existing-cache work, no new background jobs, no new GitHub calls when the registry is warm (which it always is during normal dashboard use).

**Phone-OS direction:** boards that tell the truth across repos is a reliability precondition (north star 2) for anything that later *acts* on these links (#1017) — a prerequisite, not itself phone-OS-shaped.

**More capable, not more passive:** this removes a specific way the dashboard lies to Gil (a same-numbered ticket in another repo silently "blocking" or silently not blocking); it doesn't take any decision away from him — #1017 is where MARVIN starts acting on these links.

## Scope note: what #1016's own body asks for vs. #1015's larger list

#1015 (the parent) tags several bigger robustness items as "(#1016)": reading GitHub's native sub-issue/blocked-by fields, an audit trail of added/removed links, and resolving renamed/redirected repos. **None of these appear in #1016's own "What to build" or "How we'll try to break it."** I'm treating #1016's own issue text as authoritative for this attempt (two prior automated attempts already failed review once scoped broadly or narrowly — I have no specifics on which), and raising the mismatch as a Decision below rather than guessing either way.

## Tests first

**Shared parser (`ticket_refs.js` / `pr_ticket_check.py`, via the one shared `pr_ticket_refs_cases.json`):**
1. Each new keyword, bare: `Duplicate of #5`, `Covered by #5`, `Supersedes #5`, `Related to #5`, `Blocked by #5` → correct relation.
2. Each new keyword, colon form (`Covered by: #5`) and list form (`Related to #1, #2 and o/x#3`).
3. Mixed case: `DUPLICATE OF #5`, `Covered BY #5`.
4. Cross-repo qualified ref (`Duplicate of G-Eskayo/other#5`) and by URL (`Supersedes https://github.com/o/x/issues/9`).
5. Same ticket number in two different repos stays two distinct refs (`Related to #5` and `Related to o/x#5` in one body → both kept).
6. A keyword glued to other text is not a match: `Unrelated to #5`, `Encovered by #6`, `misrepresents #7` (word-boundary false positives), mirroring the existing `Encloses #5` case.
7. `related to the #5 rewrite` (no ref immediately after the keyword) → no match, mirroring the existing `part of the #5 rewrite` case.
8. Inside a code fence / inline code → ignored, for every new keyword (mirrors the existing fenced-`Closes` case).
9. A ref glued to more text (`Covered by #5abc`) → not a ref.
10. 50 distinct refs in one body (`Related to #1, #2, ... #50`) → all 50 parsed, none dropped.
11. **Regression guard:** `refusal()` (Python) and `ticketLinked` (JS) still treat a body that *only* says `Related to #5` / `Duplicate of #5` / `Covered by #5` / `Supersedes #5` as **naming no ticket** — `PR_NAMES_NO_TICKET` still fires, and `closingPrs` still does not put the card in review. This is the easiest place for this change to regress #1004's gate, since the new relations go through the same function.
12. `Blocked by` keeps its `##\s*Blocked by\s*\n` section form (bulleted `- #N`) working, now also capturing a qualified ref in a bullet (`- o/x#5`), and still ignoring a `None` section.

**`dependencyRefs` / `openDependencies` / `deriveColumn` (`board.js`):**
13. A ticket in repo A says `Blocked by owner/B#7`; repo B's #7 is open and repo A's own #7 is closed → the card blocks on B's #7, not on its own closed #7 (the exact bug: "reads as this repo's #5").
14. The same cross-repo blocker, now closed in repo B → card is not blocked.
15. A cross-repo blocker whose repo isn't known/registered (can't be verified) → fails open (not blocking), never crashes.
16. `card.blockedBy` for a mixed same-repo + cross-repo case lists both, cross-repo entries carrying their repo.
17. Existing same-repo cases (held, not-planned, section form, "None") keep behaving exactly as today — full regression pass on all of `board.test.js`'s current blocked-by assertions after the shape change.
18. A self-reference (`Blocked by #16` inside ticket #16's own body) never blocks or appears as a dependency.

**`buildRelationIndex` (`relations.js`):**
19. A ticket's `Duplicate of #6` produces `duplicate of` on the ticket and `duplicated by` on #6 (both directions, like the existing `blocked by`/`blocks` test).
20. A PR's `Covered by #8` on ticket #393's body (or a PR body naming `Covers`/`Covered by`, per the ticket's own example) shows as "covered by PR #8" on the ticket and "covers #393" on the PR, in the Related panel's data.
21. A cycle — ticket A says `Duplicate of B`, ticket B says `Duplicate of A` — produces two directed edges and both render in `forTicket`; no infinite loop, no dedup that drops one direction.
22. A ref to a ticket number that was never loaded still renders with `title: '(not loaded)'`, `state: 'UNKNOWN'` (reuses existing `infoT` fallback) rather than throwing.
23. `extractRefs`-driven plain `mentions` edges and the new keyword relations never double up for the same pair (a ticket that says `Duplicate of #6` doesn't also get a separate `mentions #6` edge) — mirrors the existing closes-vs-mentions precedence test.
24. **Regression guard:** `relations_service.js`'s `LINKED` set (`closes`/`part of`) is unchanged — a `related to` or `covered by` PR→ticket edge must not satisfy `parity()`'s "has an open PR" check, so parity still flags a ticket with only a `Related to` PR as having no closing/part-of PR.

**Misuse the ticket's list didn't name, per the testing rule:**
25. Bad/malformed input: `null`/`undefined` body for every new keyword (mirrors existing `prTicketRefs(null, 'o/r')` case).
26. Huge input: a body with thousands of unrelated `#N` characters and one real `Covered by #5` buried in the middle doesn't time out or misparse (regex, not recursive — a basic perf sanity check, not a hard budget).
27. Wrong permissions / stale state: a cross-repo blocker lookup against a repo whose `getBoardData` call rejects (network/auth failure) degrades to "unverified → not blocking" for that one repo only, same as `prsOfProjects`'s existing per-repo try/catch — other repos' boards still build.
28. Concurrency: two boards (own + foreign, in `loadBoard`) built from the same warm cross-repo issue-state map in one pass don't refetch per card.
29. A person's mistake: `Blocked by #16` where #16 doesn't exist in any registered repo at all → same "(not loaded)"/unverified-not-blocking behavior as case 15/22, no crash.

## Decisions
<!-- marvin:decisions -->
### cross_repo_verify: Should "Board blockers then work across repos" mean MARVIN actually checks whether the cross-repo blocker is still open (not just stops matching the wrong same-numbered ticket)?
- [ ] A: Yes — add the cross-repo open/held/not-planned lookup (reusing the already-warm `getBoardData` cache via a `prsOfProjects`-style helper), so a genuinely-open cross-repo blocker really blocks the card, and a closed one really doesn't.
- [ ] B: No — just stop the false match (never compare a qualified ref's number against this repo's own open-ticket set); leave actually resolving a cross-repo blocker's state to #1017 ("act on links"), and for now a cross-repo `Blocked by` never blocks the card (shown in Related, but ignored for column placement).

### held_notplanned_cross_repo: A cross-repo blocker that is itself on hold or was closed "not planned" in its own repo — exempt it from blocking (like same-repo ones already are), or treat it as a plain open/closed check only, for this ticket?
- [ ] A: Exempt it too (fetch its hold/not-planned state the same way, from the same cached data) — full parity with same-repo behaviour.
- [ ] B: Plain open/closed only for now; a held or dropped cross-repo blocker still shows as blocking until #1017. (optional)

### parent_ticket_items: #1015 tags "GitHub's own links count too" (native sub-issue/blocked-by fields), "an audit trail" (log added/removed links, "link removed by…"), and "renamed/moved repos resolve instead of reporting broken" as owned by #1016, but none of them are in #1016's own "What to build" or acceptance criteria.
- [ ] A: Out of scope for this PR — #1016 ships only what its own body asks for; file a follow-up ticket for these three items (or fold them into #1017/#1018 where #1015 already lists related work).
- [ ] B: In scope now — implement all three alongside the vocabulary extension in this PR.
- [ ] C: In scope now, but only some of them (note which in a comment after merge).
<!-- /marvin:decisions -->

## Task List

1. **Shared parser — add the 5 new relations.** `dashboard/electron/main/ticket_refs.js`: add `BLOCKED_BY`, `DUPLICATE_OF`, `COVERED_BY`, `SUPERSEDES`, `RELATED_TO` regexes (same shape as `PART_OF`, list-capable), fold their hits into `prTicketRefs`'s existing `hits`/`found` merge loop. Mirror exactly in `lib/pr_ticket_check.py`'s `_PART_OF`-style constants and `ticket_refs()`.
2. **Fixture cases.** Extend `dashboard/test/fixtures/pr_ticket_refs_cases.json` with cases 1–10 above (shared by both languages' tests automatically).
3. **Narrow the two consumers that must not see the new relations.** `ticket_refs.js`'s `ticketLinked` and `pr_ticket_check.py`'s `refusal()`: filter to `relation ∈ {closes, part-of}` explicitly (test 11).
4. **`board.js` — fix `dependencyRefs`.** Return `[{repo, number}]` (repo `null` = own repo), keep the `## Blocked by` section form but capture an optional `owner/repo` prefix per bullet. Update `openDependencies`, `deriveColumn`'s held/dropped notes, and the `reason` string builder to handle both same-repo and cross-repo entries (render foreign ones as `owner/repo#N`, like `prLabel` already does for cross-repo PRs).
5. **Cross-repo open/held/not-planned lookup**, per the `cross_repo_verify` decision: add a `boards.js` helper mirroring `prsOfProjects` (reads the same warm `getBoardData` cache for every other registered repo, classifies each issue OPEN/held/not-planned). Thread it into `index.js`'s `boardInputs` (alongside `otherPrs`) and into `loadBoard`'s `buildBoard` calls; in `relations_service.js`'s `build()`, compute the same three sets locally from the `tickets` array it already loads (no new fetch needed there).
6. **`board.js` card shape + `ProjectBoard.jsx`.** Update `card.blockedBy` to carry `{repo, number}` entries (repo `null` for same-repo, to stay close to today's shape); update `ProjectBoard.jsx`'s blocked-by render (around line 140) to show `owner/repo#N` for foreign entries, bare `#N` for same-repo ones.
7. **`relations.js` — wire the new relations into the index.** Replace the ad hoc `blockedByNumbers` with the shared parser's `blocked-by` output (fixing relations.js's own copy of the repo-dropping bug as a side effect); run the shared parser over ticket bodies too (not just PR bodies) so `duplicate-of`/`covered-by`/`supersedes`/`related-to` show up from tickets; add the 5 new entries to `OUT_WORD`/`IN_WORD`.
8. **Tests.** `dashboard/test/ticket_refs.test.js`, `lib/tests/test_pr_ticket_check.py` (cases 1–11, 25–27 via direct unit tests beyond the shared fixture), `dashboard/test/board.test.js` (13–18, 29), `dashboard/test/relations.test.js` (19–23), `dashboard/test/relations_service.test.js` (24, 28).
9. **Docs.** `docs/agents/issue-tracker.md`: expand "A PR names its ticket" into the full 7-word vocabulary (noting which words are PR-facing vs. ticket-facing, and that `bin/gh`'s `PR_NAMES_NO_TICKET` gate only honours Closes/Part of). `CONTEXT.md`: update the "Blocked" column bullet (~line 844) to say cross-repo blockers are resolved, not just matched by number, and extend the "Names its ticket" bullet (~lines 868–877) and the "Relationships are derived from text" bullet (~lines 1073–1085) with the 5 new relations and their Related-panel words.
10. Apply whichever options the Decisions above resolve to before closing out scope (particularly `cross_repo_verify`, since it changes step 5's size).