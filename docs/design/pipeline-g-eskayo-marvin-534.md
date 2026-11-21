## North-star fit

**Reuses:** `lib/resume_check.py` `fetch()` — the one function in the codebase that asks GitHub about a ticket/PR's live `state` with a single batched GraphQL query (one `gh api graphql` call covers any number of keys), fails closed with a catchable `RuntimeError` on any gh/network/parse problem, and is already dependency-injected for tests via a `run=` callable. `lib/parked.py` `report()` is the existing caller of `fetch()` and the pattern to copy: read all records first, collect the distinct GitHub keys they reference, call `fetch()` once, then fold the answers back in. Tests reuse `test_resume_check.FakeGitHub` and `issue()`, the same helpers `test_parked.py` and `test_memory_claims.py` already import rather than re-mocking GitHub — "one parser" extends naturally to "one fake."
**Why simplest sufficient:** checking *current* `state` (OPEN/CLOSED) needs none of `resume_check`'s event history (`timelineItems`, `closedByPullRequestsReferences`) — the default `fetch()` fields already include `state`, so no new query, no `with_body=True`, no new GraphQL code. A per-ticket cache is unnecessary extra machinery: `load_all` already reads every record before computing visibility, so collecting the distinct ticket numbers across *all* `dismissed_until` proposals and calling `fetch()` once covers "N proposals, one ticket" for free, and goes further (M distinct tickets in one load also cost one call, in the same GraphQL request) — which is strictly better and adds no code over the minimum.
**Token/resource cost:** spends one short (~5s-budgeted) `gh api graphql` call per `proposals.py list`, only when at least one `dismissed_until` proposal carries a ticket — zero cost otherwise. This is exactly the kind of GitHub-call consolidation the budget incident in CONTEXT.md ("GitHub request budget", 2026-10-06) already established as policy; reusing `fetch()` instead of writing a second `gh issue view` caller keeps the account's shared hourly allowance (north star 1, north star 5) intact rather than adding a new unbounded caller.
**Phone-OS direction:** proposals that self-correct without a human re-checking GitHub by hand is a small step toward "proactive, reliable" (north star 2) — low blast radius, backend-only.
**Human experience:** Gil approves the prerequisite once and the idea comes back on its own, with a reason — exactly the north-star-3 test in the ticket. He does strictly less busywork; nothing here removes a judgment call from him (the ticket's own closing is still his decision).

One correction to the ticket's own wording: `dashboard/src/components/ProposalsSection.jsx:162` already renders `Back again: {p.returned}`. So the backend's `returned` value must **not** itself contain "Back again:" — it should be `"ticket #N closed"`, matching the existing style of the other two reasons (`"Snooze ended {date}"`, `"Backup date {date} reached"`), so the UI renders `"Back again: ticket #N closed"` without a doubled prefix. The ticket's "What to build" line describes the rendered text, not the stored field.

No dashboard/Electron changes are needed: `dashboard/electron/main/proposals.js` just shells out to `proposals.py list` with a 90s timeout, comfortably inside the ~5s GitHub budget this adds.

## Decisions

None. The one implementation choice not pinned down by the ticket — which reason wins when the ticket closed and the backup date passed the same day — has an objectively reasonable default (the more specific, ticket-named reason wins; checked first, so exactly one `returned` is ever set) and doesn't change what Gil sees in a way that needs his input.

## Tests (written first)

All in `lib/tests/test_proposals.py`, reusing `from test_resume_check import FakeGitHub, issue` (the precedent `test_parked.py` already set) so GitHub is faked at the same query-answering layer, never mocked at a level that would hide `resume_check.fetch`'s own rules.

Acceptance criteria:
1. `test_ticket_closed_returns_with_reason_naming_ticket` — `FakeGitHub({"G-Eskayo/marvin#123": issue(state="CLOSED")})`; proposal's `returned` is `"ticket #123 closed"` (rendered by the UI as "Back again: ticket #123 closed").
2. `test_ticket_open_stays_dismissed` — `issue(state="OPEN")`; `load_all` omits it.
3. `test_ticket_reopened_after_closing_stays_dismissed` — same as above by construction (we only ever read *current* `state`, never history), with a comment explaining why no event-based check is needed here (unlike `resume_check.changes_since`).
4. `test_ticket_deleted_or_missing_stays_dismissed` — `FakeGitHub({})`; GraphQL returns the node as null/errored; proposal stays dismissed, no exception.
5. `test_gh_down_leaves_backup_date_working` — `FakeGitHub(raises=FileNotFoundError("gh"))` (or `rc=1, stderr="error connecting to api.github.com"`); `load_all` before the backup date omits the proposal, after the backup date returns it with the existing backup reason; no exception anywhere.
6. `test_malformed_ticket_in_stored_record_is_ignored_not_fatal` — hand-write a `dismissed_until` record with `status.ticket` as a string, a negative number, 0, a float, and a dict/list (parametrized); `load_all` never raises and falls back to backup-date behavior for each.

"How we'll try to break it":
7. `test_ticket_closed_and_backup_date_passed_same_day_returns_once` — both conditions true on the same `today`; assert exactly one `returned` reason, naming the ticket.
8. `test_twenty_proposals_on_one_ticket_cost_one_gh_call` — 20 `dismissed_until` proposals all linking ticket 123; assert `len(gh.calls) == 1` after `load_all`.
9. `test_gh_garbage_json_is_treated_as_gh_down` — `FakeGitHub(rc=0, stdout="<html>proxy</html>")` (mirrors `resume_check`'s own "unreadable" case); same no-exception/backup-still-works assertion as case 5.
10. `test_record_with_no_ticket_key_is_unaffected` — a `snoozed`/plain `dismissed_until`-with-no-ticket record alongside ticket-linked ones; its behavior is unchanged and it contributes no key to the GraphQL call.

Extra misuse not already covered by the ticket:
11. `test_two_distinct_tickets_in_one_load_resolved_independently` — two proposals link two different tickets, one closed one open; both resolved correctly and still only one `gh.calls` entry (dedup *and* cross-ticket batching, not just same-ticket caching).
12. `test_repeated_loads_are_idempotent_and_dont_mutate_the_record` — call `load_all` twice with a closed ticket; the on-disk JSON record is byte-for-byte unchanged both times (visibility is computed, never written back — consistent with how snooze/backup returns already behave).
13. Update the existing `test_until_ticket_then_backup_date_brings_it_back` to pass `run=FakeGitHub({"G-Eskayo/marvin#123": issue(state="OPEN")})` into `load_all` — without this it would make a real, unfaked `subprocess.run` call to the live `gh` binary and the network the moment ticket-checking lands, breaking the file's "never the real network" invariant.

Not applicable here (noted, not skipped silently): wrong permissions (no new privilege boundary; the shared `~/.agents/bin/gh` gate already owns rate-limit/permission handling and isn't bypassed) and huge/malformed *input* beyond the ticket-field cases above (no new user-facing input surface is added — `load_all` takes no new untrusted argument).

## Task List

1. In `lib/proposals.py`, add `import resume_check` (same `lib/` dir, same `sys.path.insert` already in place).
2. Add `_linked_ticket(rec: dict) -> int | None`: returns the `status.ticket` value only when `rec["status"]["state"] == "dismissed_until"` and `type(ticket) is int and ticket > 0`, else `None`.
3. Add `_check_tickets(tickets: list[int], run) -> dict[int, bool]`: builds `f"{REPO}#{t}"` keys, calls `resume_check.fetch(keys, run=run, timeout=resume_check.BUDGET_S)` once, catches `RuntimeError` → returns `{}`, else returns `{t: state == "CLOSED"}` per ticket (skipping any key whose node is missing/malformed).
4. Change `_visible(rec, today, ticket_states: dict[int, bool] | None = None)`: before the existing snoozed/backup checks, if `state == "dismissed_until"` and `_linked_ticket(rec)` is in `ticket_states` as closed, return `{**rec, "returned": f"ticket #{ticket} closed"}` immediately (one reason, ticket takes priority over backup on a same-day tie). Existing backup/snooze logic and its `except (KeyError, TypeError, ValueError)` fallback stay as-is.
5. Change `load_all(root, today=None, run=subprocess.run)`: split the current single loop into (a) read+validate every file into a `records` list (unchanged error handling), (b) collect `tickets = sorted({t for rec in records if (t := _linked_ticket(rec)) is not None})`, call `_check_tickets(tickets, run)` only if `tickets` is non-empty, (c) loop `records` computing `_visible(rec, today, ticket_states)` as today, building `proposals`/`problems` the same way.
6. Leave `act()`'s existing `_visible(rec, today)` call (line 259) untouched — it doesn't need ticket-state checking (acting on a proposal only requires knowing it's currently visible, not why).
7. In `lib/tests/test_proposals.py`, add `from test_resume_check import FakeGitHub, issue` near the existing imports.
8. Update `test_until_ticket_then_backup_date_brings_it_back` to pass `run=FakeGitHub(...)` as in test 13 above.
9. Add the 12 new tests (1–12 above) in a new `# --- ticket-linked return (#534) ---` section of the file, following the file's existing fixture/style conventions (`root`, `idea()`, `TODAY`).
10. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_proposals.py -v` and confirm all pass, including the full existing suite (no regressions from the `load_all`/`_visible` signature changes).