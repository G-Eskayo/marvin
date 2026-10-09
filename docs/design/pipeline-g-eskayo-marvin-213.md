## North-star fit

**Reuses:** the `hold` label already exists and is live on 20 tickets today (description already says *"Paused on purpose; carries a 'Revisit by:' line; never blocks others"* — the convention was named before this ticket). Reuses: the Done-column Archive pattern (`Column` component, `dashboard/electron/main/board.js:141-193`) for the new Backlog group; the `ticket_agents.py`/`ticket_policy.py` five-agent/pure-rules split; the existing `githubState.get('board', repo, fetchBoardData)` cache + webhook invalidation (`index.js:123`) for the one new GitHub call the board needs; `gh issue list --json number,comments` (confirmed by a live call against this repo to return full comment bodies, not just a count) so fetching every held ticket's comments costs **one extra call per repo**, not one per ticket; `TicketAgentsPanel`'s `AGENT_INFO`/`ORDER` (data flow is already generic — `groupProposals` needs no change); `check_project_tags`'s state-file-freshness pattern for the new Health check; the `human_task.js`-style shared pure parser convention (`dashboard/src/lib/`) for a `revisit.js` mirroring `ticket_policy.py`, per that file's own note to "keep the two in step."
**Simplest sufficient approach:** no new state file, no new IPC bridge, no new polling loop — one more field in an existing parallel fetch, one more optional param on a pure `buildBoard`, one more collapsible block copy-pasted from the Archive block, one more pure Python module function reusing the existing `_act`/audit/propose-act machinery.
**Tokens:** spends none — this is deterministic parsing and label/comment ops, no model calls, same as the other four ticket agents.
**User capability:** this returns Gil's own deliberate decisions (his `Revisit by:` lines) back to him, rather than deciding anything on his behalf — strictly reclaiming work he already did (pausing a ticket) that currently vanishes. Net: more capable, not more passive.

**Correction to the ticket's own stated fit:** none stated explicitly, but the ticket's wording implies a greenfield label/convention ("every hold carries..."). In reality the `hold` label, its description, and 20 already-held tickets predate this ticket — this is wiring existing intent through, not introducing a new one.

**Critical finding from the denial history:** PR #362 (the prior attempt, still open, state `CONFLICTING`) implemented the backend correctly but **never touched any frontend file** — the board UI acceptance criterion (AC1, the actual headline ask) was skipped entirely. It also repeatedly conflicted with `main` because `lib/morning_brief.py`'s `default_sources`/`_SOURCE_NAMES`/`## Overnight` dict literals were touched by *both* that PR and PR #341 (`auto_merge`, ADR 0064) at the same lines. Main now has `auto_merge` merged in. This attempt must (a) build the board UI, and (b) add the `revisited` source *additively* next to the already-merged `auto_merge` entries, not by re-deriving the old diff.

**Terminology check:** the ticket repeatedly says "the `hold` label" — confirmed correct (`gh label list` shows `hold`, not `held`). Note for awareness only (out of scope here, not touching it): `ticket_agents.py`'s `plan_stale_claims`/`plan_refeed` check literal `"held"`, which is not a real label on this repo — those two agents currently do **not** actually protect `hold`-labelled tickets' claims as CONTEXT.md claims they do. Pre-existing bug, unrelated to #213's scope; flagging rather than fixing silently.

## Files to touch

**Backend (Python, `lib/`)**
- `lib/ticket_policy.py` — add `parse_revisit_comment(comment) -> dict|None`, `latest_revisit(comments) -> dict|None`, `is_revisit_due(revisit, now, open_numbers=None) -> bool`. Pure, no I/O.
- `lib/ticket_agents.py` — add `AGENTS` entry `"revisit"`; `plan_revisit(repo, issues, comments_by_number, open_numbers, now)`; `collect_hold_comments(repo, gh)`; `write_revisit_state(no_revisit, path, ts)`; wire into `run()` (new `revisit_state_path` param, called only when `modes["revisit"] != "off"`, needs `comments_by_number` passed from `collect()`/`main()` via one new `gh issue list --repo X --state open --label hold --json number,comments` call per repo).
- `lib/health_checks.py` — add `check_hold_revisit()` (state file `~/.claude/logs/hold-revisit-state.json`, same shape/staleness pattern as `check_project_tags`), appended to `run_all()`.
- `config/ticket_agents.json` — add `"revisit"` to `_readme` text; leave `"agents"` block alone (no override = inherits `auto`/`act_after`, i.e. starts in propose like the others did at rollout).
- `CONTEXT.md` — in "### Ticket agents and the completed record", "Four ticket agents" → "Five ticket agents", add a `5. **revisit**` bullet documenting the `Revisit by: YYYY-MM-DD [— condition]` convention (date-only, date+text, or date+`#N` ref).

**Backend (Node, `dashboard/electron/main/`)**
- `dashboard/src/lib/revisit.js` *(new)* — `parseRevisitComment`/`latestRevisit`, a JS mirror of the two Python parse functions (not the due-check — the board only displays, it doesn't decide due-ness).
- `dashboard/electron/main/boards.js` — `fetchBoardData` gets a 4th parallel call: `gh issue list --repo X --state open --label hold --limit 1000 --json number,comments`, folded into the existing `Promise.all`, passed through as `holdComments: {number: [comments]}`.
- `dashboard/electron/main/board.js` — `buildBoard({..., holdComments = {}})`; for each card where `d.held`, attach `card.revisit = latestRevisit(holdComments[issue.number] || [])`.

**Frontend (React)**
- `dashboard/src/components/ProjectBoard.jsx` — in `Column`, add a `showHold`/count block in the **Backlog** column (`column.id === 'backlog'`), identical pattern to the Done/Archive block: collapsible, `▸ On hold · N`, each row showing `#number title` plus its revisit line (`Revisit by: 2026-11-01 — condition`, or a flagged "no revisit line set" when `card.revisit` is `null`). Needs `column.cards` partitioned into `heldCards`/`openCards` (held cards currently render inline with everything else in Backlog; they move into the new group instead).
- `dashboard/src/components/TicketAgentsPanel.jsx` — add `revisit` to `AGENT_INFO` and `ORDER`. No other change needed; `groupProposals`/`readTicketAgents` are already generic per-agent.

**Docs**
- CONTEXT.md as above (this *is* the "ticket states" documentation location — there's no separate ticket-states doc).

## Tests to write first

**`lib/tests/test_ticket_policy.py` — parsing (pure, mirrors the 3 functions above)**
1. `Revisit by: 2026-11-01` → date-only parses, `condition: None`, `ref: None`.
2. `Revisit by: 2026-11-01 — when clarity-captions ships` → date + condition, no ref.
3. `Revisit by: 2026-11-01 - after Terry's review` (hyphen, not em-dash) → same parse.
4. `Revisit by: 2026-11-01 — when #42 ships` → `ref: 42`.
5. Ref at the very start of the condition (`— #17 is done`) → `ref: 17`.
6. No matching line at all → `None`.
7. Empty / missing `body` key → `None` (bad/malformed input).
8. Malformed date (`next month`, `2026-13-45`, `2026-11` incomplete) → `None`, not a crash.
9. `"let me revisit this later"` (word "revisit" present, wrong prefix) → `None` — not a false positive.
10. Case-insensitive prefix (`REVISIT BY:`) → parses.
11. Multiple matching comments → newest by `createdAt` wins, **not** list order (person's mistake: pastes an old one back at the top).
12. Mixed matching/non-matching comments → non-matching ones skipped.
13. No comments at all / empty list → `None`.
14. A huge comment list (200+) → still finds the right one, no slowdown/crash (misuse: huge input).
15. One comment with a malformed `createdAt` → doesn't crash; the other, valid one is still found and used (dependency partially failing: GitHub's own timestamp field unparseable).
16. `is_revisit_due`: date in the past → due; date is exactly today → due (boundary); date in the future → not due.
17. `is_revisit_due` with a `ref` to a ticket **not** in `open_numbers` (closed) → due regardless of date, even when the date is far in the future (condition satisfied overrides the date).
18. `is_revisit_due` with `ref` **in** `open_numbers` (still open) → not due on that basis even past its date... actually per the ticket, the date is an independent trigger too — so: not due *by the ref*, but still check whether the date alone makes it due (test both independently: ref-still-open+date-future → not due; ref-still-open+date-past → due by date).
19. `is_revisit_due(None, ...)` → never due (defends every caller against a missing-comment ticket).

**`lib/tests/test_ticket_agents.py` — `plan_revisit` (dependency: GitHub comments as the real collaborator shape, not a mock that hides its rules)**
20. Past due date → emits `remove_label hold` + `add_label needs-triage` + a comment naming the date.
21. Ref'd condition ticket now closed, date still in the future → still due (comment-closure overrides date).
22. Ref'd condition ticket still open → not due, no action, even if the text also contains a plausible-looking date.
23. `hold` with no `Revisit by:` line at all → no action (this is what feeds the Health check, not a revisit).
24. `pinned` + `hold` together → never touched (respects `pinned`, per the ticket's explicit requirement).
25. Two different due holds in one pass → each gets its own distinct comment body (misuse: a shared/templated comment string leaking ticket A's reason onto ticket B).
26. The agent comment is prefixed with `AGENT_COMMENT_PREFIX` and names the actual due date/reason (consistency with the other four agents' comments).
27. Same ticket number, two different repos → each repo's revisit is evaluated independently (repeats/wrong-scope misuse: a cross-repo number collision must not leak state).
28. A ticket with `hold` but also `claimed:*` and no comments fetched for it (because `collect_hold_comments` only fetched tickets currently labelled `hold`, and labels changed between fetch and plan) → doesn't crash, just no-ops (stale-state misuse).
29. `collect_hold_comments`: `gh` raising (rate limit, network, repo deleted) → returns `{}`, never raises (dependency failure must not take down the whole hourly pass, matching every other `_gh`/`gh` wrapper's `except Exception` convention in this file).
30. `write_revisit_state`: unwritable path (permissions) → silently no-ops, doesn't crash the run (matches `_write`'s existing convention).
31. `run()`: with `modes["revisit"] == "off"`, `plan_revisit` is never called and no `revisit` proposals appear (off-switch misuse check, same as the other agents already get tested).
32. `run()` with `modes["revisit"] == "propose"` (its start state): proposals recorded, **no** `gh` label/comment calls actually made (concurrency/safety: someone else edits the ticket in the meantime — propose mode must guarantee zero writes).

**`lib/tests/test_health_checks.py` — `check_hold_revisit` (mirrors `check_project_tags`'s 4 cases)**
33. State file missing → yellow, "has not run yet" (first-run / dependency-never-ran case).
34. State file stale (> `HOLD_REVISIT_STALE_HOURS`) → yellow.
35. State file fresh, `no_revisit` empty → green.
36. State file fresh, `no_revisit` non-empty → yellow/red with the ticket numbers+titles named (never a bare count — matches the "avoid bare numeric IDs" convention already used by `check_project_tags`).
37. Corrupt/malformed JSON in the state file → yellow "not run yet", not a crash (malformed-input misuse).

**`dashboard/test/board.test.js` — `buildBoard`/`deriveColumn` with `holdComments`**
38. A held card with a parseable `Revisit by:` comment → `card.revisit` is the parsed `{date, condition, ref}`.
39. A held card with **no** matching comment → `card.revisit` is `null` (feeds the frontend's own "no revisit line" flag).
40. `holdComments` omitted entirely (default `{}`, back-compat with every existing `buildBoard` test) → no crash, `card.revisit` is `null` for held cards.
41. A held card whose `holdComments[number]` entry has a malformed `createdAt` → doesn't crash (same malformed-dependency-data case as the Python side, proving the two parsers "stay in step" per `ticket_policy.py`'s own comment).
42. Two held cards in the same `buildBoard` call → each gets its own `revisit`, no cross-contamination (mirrors Python test #25/#27).

**`dashboard/test/revisit.test.js` *(new)*** — same date-only/date+condition/em-dash-vs-hyphen/case-insensitive/malformed/huge-list/newest-wins cases as the Python `parse_revisit_comment`/`latest_revisit` tests (1-15 above), run against the JS port, so a future change to one side without the other is caught by a failing test on both sides rather than silent drift.

**Frontend render (lightweight, no new RTL harness exists for `ProjectBoard` per the exploration — if one is added, these three; otherwise cover via `board.test.js`'s data-shape assertions plus a manual run-the-app check):**
43. Manual/dev-server check: Backlog shows "On hold · N" collapsed by default (not a dozen "On hold" cards dumped inline, which is today's behavior and is what the ticket is fixing); expanding shows each card's revisit line or a flagged "no revisit line" state; a `hold`+`pinned` card is still shown (display, not agent action, so `pinned` doesn't hide it).

**Verify-fails-without-fix guard:** for every one of the above, confirm against the actual prior (missing) behavior before writing the fix — e.g. #38-42 currently fail outright since `holdComments` doesn't exist on `buildBoard` yet; #20-32 fail since `plan_revisit` doesn't exist; #33-37 fail since `check_hold_revisit` doesn't exist. That absence *is* the red step.