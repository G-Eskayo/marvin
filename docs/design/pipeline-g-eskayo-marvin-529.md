## North-star fit

**Reuses:** `lib/ticket_policy.py` already holds `priority_rank` (ticket_policy.py:166-171) as the home for small, pure ranking rules used by the ticket agents — `rank_by` goes right next to it, in the same module, imported the same way `ticket_agents.py` already imports it (`import ticket_policy as pol`, ticket_agents.py:31). No new file.

**Simplest sufficient approach, corrected against the code:** The ticket's "What to build" assumes all three call sites share the inline `order.index(x) if x in order else len(order)` shape. Checking the code shows that's only true for two of them:
- `lib/ticket_agents.py:426` — `APPLY_ORDER.index(a["agent"]) if a["agent"] in APPLY_ORDER else len(APPLY_ORDER)` on a tuple. Matches the ticket exactly.
- `skills/improve/scripts/improvement_sweep.py`'s `sort_key` (lines 84-89) — a hand-rolled loop over `KIND_PRIORITY` (a list) that is index-shaped once the substring-match step is separated out. Matches once rewritten.
- `skills/architecture-review/scripts/sort_suggestions.py`'s `_sort_key` (lines 72-79) — `IMPACT_RANK.get(x, 99)` / `EFFORT_RANK.get(x, 99)`, where `IMPACT_RANK`/`EFFORT_RANK` live in `lib/inbox.py:364-365` as **dicts**, not lists. Git history (`5bf1d2e0`, before the ADR-0083 inbox move) shows they were *already* dicts back then too — this was never the list+`.index()` pattern, so the ticket's fit statement is stale on this point.

Given that, `rank_by(value, order, default=None)` is written to accept either shape: a sequence ranked by `.index()`, or a mapping ranked by direct lookup — both falling back to `len(order)` when `value` is absent. This is the smaller, lower-risk change: it serves all three *named* call sites without touching `lib/inbox.py`'s `IMPACT_RANK`/`EFFORT_RANK` constants, which a 4th, unlisted call site (`inbox.suggestion_order`, inbox.py:371-376) also depends on — converting them to lists would mean fixing that site too, for no behavior gain and more blast radius. One small `isinstance(order, dict)` branch is cheap; rewriting a shared constant's type and chasing its other reader is not "the least that does the job" here.

**Tokens:** spends a little now (one helper + three call-site edits + tests) to remove three independent places that could drift on the "unknown sorts last" default — pays back on the next sweep/review/digest run that touches any of them, and on any future fourth caller.

**Phone-OS / user-capability:** no user-facing behavior changes; this is pure internal consolidation (north star 4 — tool-for-tools hygiene). Leaves the user exactly as capable; it's invisible to Gil except as fewer places to re-derive the same fix later.

**Machine:** runs wherever the ticket pipeline already runs this repo's test suite — no new infra, no machine-selection question.

No Decisions section needed — the one real design fork (dual-shape `rank_by` vs. converting `IMPACT_RANK`/`EFFORT_RANK` to lists) is a scoped engineering call justified above by git history and blast radius, not a toss-up for Gil.

## Tests (written first)

In `lib/tests/test_ticket_policy.py` (new `rank_by` unit tests, next to the existing `priority_rank` tests):
1. `test_rank_by_returns_the_value_s_position_in_a_sequence` — value present in a tuple/list → its index.
2. `test_rank_by_missing_value_gets_the_default` — value absent, default supplied → that default.
3. `test_rank_by_defaults_to_len_order_when_no_default_given` — ticket's stated default behavior.
4. `test_rank_by_none_value_is_unknown_not_an_error` — `rank_by(None, order)` returns the default, raises nothing (ticket's explicit break-it case).
5. `test_rank_by_duplicate_entries_in_a_sequence_use_the_first_position` — `["a","b","a"]`, rank of `"a"` is 0 (ticket's explicit break-it case).
6. `test_rank_by_empty_order_returns_a_default_for_everything_no_exception` — `rank_by("x", [])` and `rank_by("x", {})` don't raise.
7. `test_rank_by_looks_up_a_dict_order_by_key_not_position` — covers `IMPACT_RANK`/`EFFORT_RANK`'s actual shape, confirms it isn't trying `.index()` on a dict.
8. `test_rank_by_dict_order_missing_key_gets_the_default` — dict counterpart of #2.

In `skills/architecture-review/scripts/tests/test_sort_suggestions.py` (alongside the existing `_sort_key` test):
9. `test_unknown_impact_value_sorts_below_every_known_impact` — an entry with `**Impact**: made-up-value` sorts after one with a real impact.
10. `test_unknown_effort_value_sorts_below_every_known_effort` — same for Effort.
11. `test_missing_impact_or_effort_field_is_treated_as_unknown_not_an_error` — no `**Impact**:`/`**Effort**:` line at all (the `""` lookup case) doesn't raise and sorts last.

In `skills/improve/scripts/tests/test_improvement_sweep.py` (new tests for `top_issues`/`sort_key`, none exist today):
12. `test_top_issues_orders_entries_by_kind_priority_logic_first` — mixed `[STYLE]`/`[LOGIC]`/`[NAMING]` documents come back in `KIND_PRIORITY` order.
13. `test_top_issues_treats_an_unrecognized_kind_tag_as_lowest_priority` — a `[WEIRDKIND]` entry sorts after every recognized kind.
14. `test_top_issues_with_no_kind_tag_at_all_does_not_raise` — empty/malformed `document` string (ticket's "bad/malformed input" case the section didn't spell out itself).

In `lib/tests/test_ticket_agents.py` (integration, proving the real call site's order is unchanged):
15. `test_apply_order_runs_stale_claims_before_triage_and_prioritize_regardless_of_discovery_order` — a snapshot mixing a releasable stale claim (fixture shape from `test_a_stale_claim_with_no_work_in_flight_is_released_with_an_explanation`, line 111) with a `needs-triage` ticket and a plain prioritize-eligible ticket (reusing `snapshot()`/`run()`, lines 189-195); asserts `audit.jsonl`'s applied-row order matches `APPLY_ORDER`, not issue-list order.

Not applicable here, noted rather than skipped silently: `rank_by` is a pure, stateless, no-I/O function, so "each dependency failing," "concurrency/repeats," "wrong permissions/machine," and "stale state" from the north-stars' break-it list don't apply to it directly — those are already covered at the caller level (e.g. `gh` failing is `test_a_failing_gh_call_is_recorded_and_does_not_stop_the_rest`, unaffected by this change) and don't need new tests for this ticket.

## Task List

1. Add `rank_by(value, order, default=None)` to `lib/ticket_policy.py`, next to `priority_rank` — `order.index(value)`/fallback for a sequence, `order.get(value, default)` for a dict, default `len(order)` either way, first-match-wins on duplicates (free from `list.index()`).
2. Write the `rank_by` unit tests (items 1-8 above) in `lib/tests/test_ticket_policy.py`; confirm they fail against `main` (no `rank_by` exists yet) before step 1 lands, then pass after.
3. In `lib/ticket_agents.py:426`, replace the inline `APPLY_ORDER.index(...) if ... else len(APPLY_ORDER)` with `pol.rank_by(a["agent"], APPLY_ORDER)`.
4. In `skills/architecture-review/scripts/sort_suggestions.py`: add `from ticket_policy import rank_by` (lib already on `sys.path` via the existing `inbox` import at line 25-26); replace the two `IMPACT_RANK.get(...)`/`EFFORT_RANK.get(...)` lines (72-79) with `rank_by(..., IMPACT_RANK)` / `rank_by(..., EFFORT_RANK)`.
5. Add tests 9-11 to `skills/architecture-review/scripts/tests/test_sort_suggestions.py`.
6. In `skills/improve/scripts/improvement_sweep.py`: add `from ticket_policy import rank_by` (lib already on `sys.path`, line 25); rewrite `sort_key` (84-89) to find the first present `kind` via the existing substring loop, then return `rank_by(found, KIND_PRIORITY)` instead of the raw loop index.
7. Add tests 12-14 to `skills/improve/scripts/tests/test_improvement_sweep.py`.
8. Add integration test 15 to `lib/tests/test_ticket_agents.py`.
9. Run the full suite for the three touched modules plus `ticket_policy`'s own tests (`lib/tests/test_ticket_policy.py`, `lib/tests/test_ticket_agents.py`, `lib/tests/test_ticket_agents_revisit.py`, `lib/tests/test_ticket_policy_revisit.py`, `skills/architecture-review/scripts/tests/test_sort_suggestions.py`, `skills/improve/scripts/tests/test_improvement_sweep.py`) and confirm everything passes with unchanged sort orders (acceptance criterion 2).
10. Grep the three touched files (and `lib/inbox.py`, to confirm it's untouched) for any remaining inline `.index(...) if ... else len(...)` ranking to verify acceptance criterion 1 is actually satisfied, not just believed.