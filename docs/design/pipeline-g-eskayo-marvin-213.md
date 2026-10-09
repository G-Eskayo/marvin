## North-star fit

**Reuses before adding anything new:** the `hold` label (live, confirmed in `board.js:113`), the Done-column Archive collapsible pattern (`ProjectBoard.jsx:160-176`) for the new Backlog group, `project_tagger.py`'s exact shape (`plan`/`write_state` with atomic tmp-then-rename, a `STATE_PATH` under `~/.claude/logs/`, `check_project_tags`'s state-file-freshness check) as the template for the `revisit` agent and its Health check, `ticket_agents.py`'s existing `_act`/`AGENT_COMMENT_PREFIX`/`SKIP_LABELS`/`_skippable`/audit/propose-act machinery, `TicketAgentsPanel`'s generic `AGENT_INFO`/`ORDER` data flow, and `morning_brief.py`'s existing `_launches`/`_merged` "read a jsonl log since yesterday" pattern for the digest line. Also reuses real completed work already sitting uncommitted in this worktree: `dashboard/src/lib/revisit.js` (parser) and `board.js`/`boards.js` (per-card `revisit` field, conditional hold-comments fetch) are done and already covered by 25 passing tests — verified by reading the files and their test diffs directly, not assumed from the stale `docs/design/` note.

**Simplest sufficient approach:** no new state-file format, no new IPC bridge, no new polling loop, no new component. One more pure Python module function set mirroring an existing JS one, one more agent slotted into the existing `AGENTS` tuple, one more Health check reading one more state file, one more digest source function, one more collapsible block copy-adapted from the Archive block that already exists.

**Tokens:** spends none — every new piece is deterministic label/regex/state-file logic, no model calls, matching every other ticket agent.

**User capability:** returns Gil's own deliberate `Revisit by:` decisions to him automatically instead of a paused project quietly vanishing — more capable, not more passive.

**Correction to the ticket's stated fit (re-verified, not fixed — out of scope):** `plan_stale_claims`/`plan_refeed` check `"held" in names`, but the real label is `hold` (confirmed live). So those two agents do not actually protect an on-hold ticket's claim today, contradicting `CONTEXT.md:676,682-683`. Flagging again, not touching it — fixing it would be scope creep onto two unrelated agents.

## Current state, verified by reading every file (not reusing the stale design-doc's claims)

This worktree is fresh off current `main` (967730c, already past the auto-merge-shadow-mode merge that caused PR #362's repeated conflicts). Checked each file by reading it directly:

| Piece | State |
|---|---|
| `dashboard/src/lib/revisit.js` (`parseRevisitComment`/`latestRevisit`) | **Done**, 17 tests in `dashboard/test/revisit.test.js`, uncommitted |
| `dashboard/electron/main/board.js` (`holdComments` param, per-card `revisit`, `card.held`) | **Done**, tests in `board.test.js`, uncommitted |
| `dashboard/electron/main/boards.js` (conditional, independently-caught hold-comments fetch) | **Done** — already has the fix for the exact regression (unconditional 4th `gh` call) that got a prior attempt denied; 4 tests in `boards.test.js`, uncommitted |
| `dashboard/src/components/ProjectBoard.jsx` | **Missing** — no partition of Backlog cards by `card.held`, no "On hold · N" group (AC1) |
| `dashboard/src/components/TicketAgentsPanel.jsx` | **Missing** — `AGENT_INFO`/`ORDER` has only 4 agents, no `revisit` (part of AC3) |
| `lib/ticket_policy.py` | **Missing entirely** — no `parse_revisit_comment`/`latest_revisit`/`is_revisit_due` (grepped, zero matches) |
| `lib/ticket_agents.py` | **Missing** — `AGENTS` tuple has 5 entries, none is `revisit`; no `plan_revisit`/`collect_hold_comments`/`write_revisit_state` |
| `lib/health_checks.py` | **Missing** — no `check_hold_revisit` |
| `lib/morning_brief.py` | **Missing** — no `_revisited` source, nothing in `render()`'s Overnight block |
| `config/ticket_agents.json` | **Missing** — `_readme` doesn't mention `revisit` |
| `CONTEXT.md:658-685` | **Missing** — says "Four ticket agents", no `revisit` bullet, no `Revisit by:` convention documented |
| `lib/tests/test_ticket_policy.py`, `test_ticket_agents.py` | No `revisit`-related tests yet (grepped) |

A separate, already-raised PR #362 (branch `pipeline/g-eskayo/marvin#213`) implements the backend differently and has conflicted with `main` in `lib/morning_brief.py` 6 times, hit the 2-attempt refeed cap, and is now `ready-for-human` — it's a dead end I won't touch or reuse code from. Building fresh in this already-current worktree is what avoids repeating that failure, per the prior design note's own diagnosis.

## Implementation plan

**Backend — `lib/ticket_policy.py`** (append, mirror `revisit.js` line for line so "keep the two in step" holds): `parse_revisit_comment(comment_body) -> {"date", "condition"} | None` (same regex: `Revisit by:\s*(\d{4}-\d{2}-\d{2})\s*(?:[—-]\s*(.+))?`, case-insensitive, validated with `datetime.fromisoformat`), `latest_revisit(comments) -> dict | None` (newest valid `createdAt` wins, invalid dates deprioritized exactly as the JS does), `is_revisit_due(revisit, now, ref_issue_state) -> bool` (date passed, OR its `#N` condition ref is a closed issue — ref state passed in, this module stays pure/no GitHub).

**Backend — `lib/ticket_agents.py`**: add `"revisit"` to `AGENTS`. `collect_hold_comments(repo, held_numbers, gh) -> dict[int, list]` — one `gh issue list --label hold --json number,comments` call, `{}` on any exception (mirrors `project_tagger`/`boards.js`'s already-proven pattern). `plan_revisit(repo, issues, hold_comments, now)` — for each `hold`-labelled, non-`pinned` issue: parse its latest revisit comment, skip silently if none (that's Health's job, not this agent's), skip if not due, else `remove_label("hold")` + `add_label("needs-triage")` + an `AGENT_COMMENT_PREFIX` comment saying why (date passed / `#N` closed). `write_revisit_state(no_revisit_line, path, now)` — same atomic tmp-then-rename as `project_tagger.write_state`. Wire into `run()`: alongside `prioritize`/`triage`/`project_tag` (not gated behind `executable`, since it only touches labels/comments, never claims or execution).

**Backend — `lib/health_checks.py`**: `check_hold_revisit(path=HOLD_REVISIT_PATH, now=None)`, same shape as `check_project_tags` — state file missing/stale → yellow "not run yet"/"stale"; fresh + empty list → green; fresh + N tickets with no `Revisit by:` line → yellow, named (truncated at 5, same as `check_project_tags`). Wired into `run_all()`.

**Backend — `lib/morning_brief.py`**: `_revisited(now)` reads `ticket_agents.AUDIT_PATH`, filters `agent=="revisit" and op=="remove_label" and arg=="hold" and status=="applied"` within the last day (mirrors `_launches`'s per-line try/except). Added **additively** to `default_sources`/`_SOURCE_NAMES` **after** `auto_merge`, not interleaved — the one thing that actually ends the repeated `morning_brief.py` conflict history. Rendered in `## Overnight` as `- Returned from hold: {_ref(t)}`.

**Config/docs**: `config/ticket_agents.json` — append a `revisit` sentence to `_readme` only; `agents` block untouched (same `auto`/`act_after` bootstrap every other agent went through, starts in propose). `CONTEXT.md:666-679` — "Four" → "Five ticket agents", add a numbered `revisit` bullet, and document the `Revisit by: YYYY-MM-DD [— condition]` convention (date-only / date+text / date+`#N` ref) next to the existing agent list.

**Frontend — `TicketAgentsPanel.jsx`**: add `revisit` to `AGENT_INFO` and `ORDER` (pure data, zero logic change — `groupProposals`/`readTicketAgents` are already generic).

**Frontend — `ProjectBoard.jsx`** (AC1, the one true gap in the UI): in `Column`, for `column.id === 'backlog'` only, partition `column.cards` into open vs. `card.held` (field already exists, from `board.js:174` — no new label-string check needed). Render open cards as today; render held cards inside a collapsed-by-default block copied from the Archive pattern (`▸ On hold · N`), each row showing `#number title` plus `card.revisit` as `Revisit by: {date}{condition ? ' — ' + condition : ''}`, or a visibly flagged "no revisit line set" when `card.revisit` is `null`. A `hold`+`pinned` card still renders (pinned only blocks agents, never visibility).

## Tests to write first

The issue's body has **no** "How we'll try to break it" section (confirmed — fetched the raw body directly, nothing was truncated). Deriving the adversarial set from the north-star testing standard instead.

**Already written and passing — verified by reading, no changes:** `revisit.js`'s 17 cases (date-only/condition/hyphen-vs-dash/ref-extraction/case-insensitive/no-match/malformed-date/missing-body/trim/newest-wins/skip-non-matching/empty/all-malformed/malformed-createdAt/non-array/huge-list/condition-in-latest); `board.js`'s 5 (held-with-comment/no-match/omitted-holdComments/non-held-card/two-held-cards-independent); `boards.js`'s 4 (fetches-when-held/skips-when-not-held/gh-throws-returns-empty/malformed-JSON-returns-empty — this last pair is the exact "dependency failing" and "malformed input" cases for that path).

**New — `lib/tests/test_ticket_policy.py`** (Python port of the same 17 JS cases, so a future one-sided edit fails a test on both sides): all of the above, plus `is_revisit_due`: past-date, today (boundary), future-date, ref-open (not due despite future date), ref-closed (due despite future date), date-past-with-no-ref (due regardless), no revisit line at all → `False` (never guesses).

**New — `lib/tests/test_ticket_agents.py`**: `plan_revisit` — past-due held ticket acts; future-due doesn't; ref-closed acts; ref-open doesn't; held-with-no-`Revisit by:`-comment → no action (person's mistake, not a crash); `pinned`+held+objectively-due → never touched; two held tickets same run → independent, no cross-contamination; multiple revisit comments on one ticket → latest wins at the integration level. `collect_hold_comments` — **gh raises** (network/rate-limit/repo-gone) → `{}`, never propagates; malformed JSON → `{}`; called once per repo, not once per held ticket; zero held tickets in a repo → gh never called (same regression-guard shape already proven in JS, ported since it's a separate implementation). `write_revisit_state` — creates the file correctly; **unwritable path** (parent can't be created) → no-ops, doesn't crash the run; called twice back-to-back (two hourly passes) → clean overwrite via tmp-then-rename, never a half-written file. `run()` wiring — `"revisit"` respects `mode: "off"` (zero gh calls, zero actions); propose mode → proposals recorded, zero actual GitHub writes (mock `gh` asserted never called mutating); act mode → `apply_action` called with `remove_label("hold")`, `add_label("needs-triage")`, and a comment, all landing in the audit log like every other agent's.

**New — `lib/tests/test_health_checks.py`**: `check_hold_revisit` — state file missing → yellow "not run yet"; stale (> hourly cadence) → yellow; fresh + empty → green; fresh + N named tickets → yellow, truncated detail for a large N (50+, doesn't blow up the string); malformed JSON in the state file → yellow, doesn't crash `run_all()`.

**New — `lib/tests/test_morning_brief.py`** (or appended to the existing suite): `_revisited` — included within last day; excluded if older; audit log missing/empty/one malformed line → `[]`, doesn't raise (mirrors `_launches`'s per-line skip). `render()` — no revisited tickets → Overnight unchanged (regression guard on existing tests); with revisited tickets → `Returned from hold:` line appears **after** the existing `auto_merge`/`merged` lines, never interleaved — this is the direct regression guard against PR #362's exact conflict history.

**Manual (no RTL harness exists for `ProjectBoard` today, consistent with the rest of this component — not building one just for this):** dev-server check once built — Backlog shows "On hold · N" collapsed by default; expanding shows each held card's revisit line or the flagged "no revisit line set" state; a `hold`+`pinned` card is still visible, just unactioned.

**Verify-fails-without-fix guard:** every backend test above targets a function/state file that does not exist yet in this worktree, so it fails outright (not merely "doesn't change behavior") until the corresponding code is written — satisfying "verify fails when code changes without a test changing" by construction, since there's no pre-existing passing baseline to accidentally leave untouched.