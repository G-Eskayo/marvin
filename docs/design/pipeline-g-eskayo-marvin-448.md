## North-star fit

**Reuses:** `lib/ticket_policy.py`'s own `triage_verdict()` (lines 284-286) already has the exact PRD test this ticket needs — title starts with `PRD` as a whole word, or body has `## Problem Statement` / `## User Stories`. The ticket is literally "extract this into a named function and call it from a second place," which is the shared-test idea north star 4 asks for (one PRD test, not two diverging ones — mirroring how `ticket_claim.py`'s `## Parent` filter is a *different*, deliberately separate test for a different path). For the Recurrence check's probe, I reuse `lib/purpose_metrics.py`'s `_replanned_tickets()` (lines 173-194) as the template: it already walks every file in `ticket_stages.STAGES_DIR`, filters stage/status/timestamp, and returns a float within a day-window — exactly the shape needed to count "claimed"/"started" events whose `title` starts with `PRD`. The probe itself will call `ticket_policy.is_parent_prd({"title": title})` rather than re-implementing the regex a third time, so the PRD rule stays single-sourced across triage, dispatch, and the recurrence probe.

**Simplicity:** one pure-function extraction (no new logic), one new `and not` clause in an existing boolean predicate, one probe function + one `PROBES` dict entry copied from an existing pattern. No new files, no new abstractions — `_open_issues()` already fetches `title`/`body`, so no field-list change is needed (confirmed by reading `lib/ticket_pipeline.py:119-129`).

**Tokens:** negligible — a handful of lines, zero new runtime dependencies, zero model calls. This is a deterministic pure-function path (`triage_verdict`, `eligible`), the cheapest kind of fix per north star 1.

**User benefit:** this closes a real reliability gap on the unattended dispatch path (north star 2: "nothing may break silently") — today a PRD labelled ready-for-agent would be dispatched as one giant, doomed build with no human watching. Fixing it means Gil doesn't have to manually babysit the queue for mislabelled PRDs, which is capability, not passivity.

**Machine:** no machine-specific work — this runs wherever `ticket_pipeline.py`'s hourly scan runs (either Mac); nothing here is machine-bound.

**Where it disagrees with the ticket's own framing:** the "Original ticket text" (collapsed section, bottom of the issue) proposes reusing `ticket_claim.py`'s `## Parent` filter. The current (AI-retriaged) "What to build" correctly supersedes that — most ready tickets have no `## Parent` section, so that filter would stop nearly all dispatch. I'm building to the current spec, not the collapsed original.

## Files already read

- `lib/ticket_policy.py` (full file) — PRD test at lines 284-286, inside `triage_verdict()`.
- `lib/ticket_pipeline.py` lines 110-230 — `_open_issues()` (already fetches `body`), `_unclaimed_ready_tickets()` / `eligible()`.
- `lib/ticket_claim.py` lines 55-70 — the separate `## Parent` filter, confirmed untouched.
- `lib/tests/test_ticket_pipeline.py` — `_issue()` helper (line 57, no `body` param today), existing `_unclaimed_ready_tickets` tests and their `_evidence_facts`/subprocess mocking style.
- `lib/tests/test_ticket_policy.py` lines 119-128 — existing PRD triage test (`test_triage_leaves_parent_prds_and_claimed_tickets_alone`) and the `issue()` test helper it uses.
- `lib/ticket_stages.py` (full file) — confirms `record_stage(..., title=...)` on the `"claimed"/"started"` event is the existing log the probe reads; no new log needed.
- `lib/purpose_metrics.py` lines 1-60, 90-100, 156-320, 416-505 — `PROBES` dict shape, `_cut`/`_when` helpers, and `_replanned_tickets()` as the probe template; confirmed `_SAFE_NAME` naming rule and the generic `MEASURES.update({name: fn for name, ... in PROBES.items()})` plumbing.
- `lib/tests/test_purpose_metrics.py` lines 117-130, 239-256, 313-345, 418-421, 595-599 — probe registration test convention and the `_replanned_tickets` corrupt/missing-dir test style.
- `~/.agents/CONTEXT.md` (grepped) — confirms "Recurrence check" = a named probe registered in `purpose_metrics.PROBES`, never ticket text (lines 1802-1806), which is what the issue's "Probe: none yet... add one" line is asking for.
- `~/.agents/docs/north-stars.md` (full file, reproduced in the task prompt).

No open question needs the owner — the spec is unambiguous and nothing here contradicts a recorded CONTEXT.md decision. **No Decisions section.**

## Tests to write FIRST

**`lib/tests/test_ticket_policy.py` — `is_parent_prd()` directly:**
1. Body `None` / key missing, and title missing → `False`, no crash.
2. Body is a normal ticket that happens to quote `"## User Stories"` mid-paragraph (not a real heading) → `True` (the rule matches anywhere in the body by design; held back is safer than dispatched — pin this).
3. Title `"PRDs are slow to load"` → `False` (word boundary; `D`→`s` has none).
4. Title `"PRD review of X"` → `True` (whole word at the start, rest of title ignored).
5. Title `"prd: something"` (lowercase) → `True` (case-insensitive).
6. Existing `test_triage_leaves_parent_prds_and_claimed_tickets_alone` (line 123) must pass **unchanged** — pins acceptance criterion 1 ("existing triage tests pass unchanged").
7. *Not applicable, noted rather than padded:* no I/O dependency, no concurrency, no permissions, no stale state — `is_parent_prd` is a pure function on a dict, same risk profile as the code it's extracted from. Malformed non-string `title`/`body` (e.g. an int) isn't newly hardened against: that's pre-existing `triage_verdict` behavior ("no behaviour change" is an explicit acceptance criterion), not something to fix here.
8. *Attacks: N/A.* Issue title/body is attacker-reachable text, but it only feeds a read-only regex match — never shell, SQL, or template interpolation — so no injection class applies.

**`lib/tests/test_ticket_pipeline.py` — dispatch integration:**
9. Add `body=""` param to `_issue()` helper (line 57-59) — default keeps all 36 existing call sites unaffected.
10. A `ready-for-agent`, unclaimed, unblocked ticket titled `"PRD: Something"` → excluded from `_unclaimed_ready_tickets()` (acceptance criterion 2a).
11. A `ready-for-agent` ticket whose `body` contains `"## User Stories"` → excluded (acceptance criterion 2b).
12. A `ready-for-agent` ticket with **no** `## Parent` section and no PRD markers → still appears in the result (acceptance criterion 3 — the regression guard that this fix does *not* resurrect the `## Parent` filter here).
13. *Not applicable, noted:* combinatorial interaction with the other `eligible()` predicates (claimed/held/blocked) isn't separately tested — `is_parent_prd` is one more independent `and` term over an already-tested pure boolean function; no new combinatorial risk.

**`lib/tests/test_purpose_metrics.py` — the recurrence probe:**
14. A ticket-stages file with a `"claimed"/"started"` event, `title` starting with `"PRD"`, inside the 7-day window → probe counts 1.
15. A `"claimed"/"started"` event with a non-PRD title → not counted.
16. An otherwise-matching event older than the window → not counted.
17. Corrupt JSON file, a file holding a non-list, and a file with `None`/non-dict entries in its list (mirrors `_replanned_tickets`'s own fixture at test_purpose_metrics.py:251-253) → skipped, no crash.
18. Missing/nonexistent stages dir → `0.0`, no crash.
19. `PROBES["prd-dispatched"]` is registered with a `0.0` threshold and mentions `#448` (mirrors `test_sync_probe_is_registered_with_a_zero_threshold`, line 313). The existing generic `test_every_probe_is_also_a_measure_that_can_run_on_the_other_mac` (line 127) covers `MEASURES` plumbing automatically once the entry is added — no separate test needed for that.

## Task List

1. `lib/ticket_policy.py`: extract the PRD check (lines 284-286) into `is_parent_prd(issue: dict) -> bool`; call it from `triage_verdict()` in place of the inline regex (no behaviour change).
2. `lib/tests/test_ticket_policy.py`: add the `is_parent_prd()` unit tests (items 1-5 above); confirm the existing PRD triage test still passes untouched.
3. `lib/ticket_pipeline.py`: in `_unclaimed_ready_tickets()`'s `eligible()` (lines 143-147), add `and not ticket_policy.is_parent_prd(i)`; update the function's docstring (line 133) to list "not a parent PRD" among the selection criteria.
4. `lib/tests/test_ticket_pipeline.py`: add `body=""` to the `_issue()` helper; add the three dispatch-exclusion tests (items 10-12 above).
5. `lib/purpose_metrics.py`: add `_prd_dispatches(stages_dir=None, days=PROBE_WINDOW_DAYS, now=None) -> float`, modeled on `_replanned_tickets()`, walking `ticket_stages.STAGES_DIR`, counting `"claimed"/"started"` events in-window whose `title` satisfies `ticket_policy.is_parent_prd({"title": title})`; register it in `PROBES` as `"prd-dispatched"` with threshold `0.0` and a description citing `#448`.
6. `lib/tests/test_purpose_metrics.py`: add the probe tests (items 14-19 above), reusing the `_stages()`-style fixture already in the file.
7. Run the full existing `test_ticket_policy.py`, `test_ticket_pipeline.py`, and `test_purpose_metrics.py` suites to confirm no regression, then the targeted new tests.