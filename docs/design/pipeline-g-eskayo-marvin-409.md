## North-star fit

**Reuses:** `seal_beta_ingest.summarize()`'s `_stats()` output (`lag_p95`, `median_rating`, `endings`, `reports`, `os_versions`) as the only input — confirmed by reading `lib/seal_beta_ingest.py:249-273` just now, unchanged. Reuses `project_onboard._onboarding_ticket()`'s "search-by-marker, create-if-absent" idiom and its URL-parsing (`re.search(r"/issues/(\d+)\s*$", url)`), and `ticket_agents.apply_action`'s `returncode==75` → rate-limit classification idiom. Confirmed by reading `lib/seal_beta_tickets.py` just now: both of these are **already implemented** (lines 263-264, 240-243), not something this attempt needs to add. Also confirmed: `find_existing` already raises rather than swallowing errors (lines 208-221), the lock file is never unlinked (no `finally: os.unlink` in `run()`), every early-return dict already carries `"mode"` (lines 296-297, 302-303, 309-310), `detect_breaches` already type-guards malformed entries (lines 100-111), and `FakeGitHub.create` already returns a URL string, not JSON (test file line 68). **All of the prior code-review's must-fix findings except one are already fixed in this worktree.**

**The one still-wrong thing, verified directly against the ticket and ADR 0024:** the ticket's own "What" section says *"median rating ≤ 4 on a device model from ≥ 2 reports"*. The code (`lib/seal_beta_tickets.py:35,129`) still implements `median_rating < 5.0` with `THRESHOLDS["median_rating"] = 5.0` — a half-integer-off, non-equivalent condition (e.g. a device at median 4.5 wrongly breaches; the ADR's literal "≤4" would not fire on it, so this isn't just a cosmetic rename). The `reports >= MIN_REPORTS_FOR_RATING` gate is already correct. This is the exact finding the comparison flagged. Fixing it is a one-line semantic change (`<=` not `<`, `4` not `5.0`), plus syncing the three places that restate the wrong number in prose: the module docstring (line 10), the rendered issue body text (line 178), and `CONTEXT.md:1281`. `CONTEXT.md:1282` is *also* stale in a second, previously-unflagged way — it still says "Stuck endings: > 30% of conversations end abnormally", but the code (and the ticket) already correctly implement "any literal `stuck` ending." Both doc lines get corrected together since they're the same paragraph.

**Simplest sufficient approach:** no new primitives — a threshold-value fix plus a test that actually discriminates on it (existing tests use `rating=4.0`, which passes under both the buggy `<5.0` and the correct `<=4` rule, so none of them could have caught this; a value in the gap, e.g. `4.5`, is required).

**Tokens:** near-zero spend — a constant/comparator edit, three doc-text syncs, and new tests. Cheaper than a fourth failed verification round.

**Phone-OS direction:** neutral (background Mini job, as before).

**User capability:** unchanged from prior reasoning — surfaces device regressions Gil would otherwise only see by reading the dashboard by hand, without taking the close/fix judgment call away from him. More capable, not more passive: he still decides what to do about each filed ticket.

## Tests to write first

Existing coverage already in `lib/tests/test_seal_beta_tickets.py` (verified by reading the file) handles: dedup-not-duplicate on a later run, closed-issue non-reuse, propose-mode never calling `create`/`comment`, rate-limit deferral (by returncode and by message), malformed/missing `summary.json`, malformed device entries, the lock surviving a run, `mode` present on every early return, URL parsing on create, `find_existing` raising, and the `>=2 reports` gate. These don't need to be rewritten.

**Missing, and required because the ticket's own "Tests (adversarial)" section names them as acceptance criteria:**

1. `test_median_rating_at_half_point_does_not_breach_ADR_threshold` — `device_entry(rating=4.5, reports=2)`: assert **no** breach (this is the regression test for the must-fix; it fails today because `4.5 < 5.0` is true, and must pass once the threshold is `<= 4`). Pair it with `device_entry(rating=4.0, reports=2)` asserting a breach **does** fire, and `device_entry(rating=4.9, reports=2)` asserting none does — pins both the boundary and the direction.
2. `test_note_with_name_and_phone_number_never_reaches_rendered_ticket` — ticket's break-it item #2, currently absent. Build a real report via `sbi.flatten`/`sbi.summarize` (not the synthetic `device_entry()` fixture) with `note="Jane Doe, 555-123-4567"` and a rating low enough to breach; run the real `by_device` entry (which legitimately carries `"notes": [...]` with the raw text, by `seal_beta_ingest.py:296-297`'s own design) through `detect_breaches` → `render_title`/`render_body`/`render_update_comment`; assert `"Jane"`, `"Doe"`, and the phone number never appear in any rendered string. Exercising the real `summarize()` shape (not the hand-built fixture) matters: `device_entry()` always sets `"notes": []`, so it can't catch a future regression where someone absent-mindedly adds `**dev` or a `notes` passthrough into `measurements`.
3. `test_gate_refusal_on_one_breach_leaves_batch_and_proposals_consistent` — ticket's break-it item #3, currently only exercised at the single-breach `file_or_update` level, never at the `run()` batch level the gate actually protects. Build a summary with 3 breaching devices; a `FakeGitHub` subclass raises a `returncode=75` error only for the `issue create` call matching one specific device's title, succeeding normally for the other two. Assert: that breach's outcome is `"deferred"`, no issue is created for it; the other two show `"created"` with distinct real issue numbers; `PROPOSALS_PATH` (patched to `tmp_path`) parses as valid JSON afterward with all 3 proposals recorded; and a second `run()` over the same summary does not duplicate the two that already succeeded.

Misuse not named in the ticket's own list, required by the north star's adversarial bar (checked against current code — all already pass, kept as regression anchors rather than new work):
4. Confirm (don't rewrite) `test_9_malformed_device_entry_skipped`, `test_13_malformed_summary_with_missing_by_device`, `test_7_no_lock_cleanup`, `test_8_early_returns_include_mode`, `test_two_overlapping_runs_do_not_double_file`, `test_max_tickets_per_run` still pass after the threshold edit — they exercise dependency failure isolation, repeats/concurrency, and huge/malformed input, and none of them touch `median_rating`, so they shouldn't change behavior.

**Verify-fails check:** test 1 is confirmed to fail against the code currently in this worktree (median=4.5 wrongly breaches today) and to pass only once `THRESHOLDS["median_rating"]` becomes `4` and the comparator becomes `<=`. Tests 2 and 3 are new coverage for already-passing-by-construction behavior (they should pass immediately once added, proving the invariant rather than driving a code change) — written first regardless, since "test try to break it" requires covering misuse the ticket names even when the current code happens to already be safe against it.

## Decisions
<!-- marvin:decisions -->
### label: What label should a filed beta-alert ticket carry on clarity-captions?
- [ ] A: `ready-for-human` (reuses the existing label; means the body must also carry the `## Your task` four-field section from `docs/agents/human-task-template.md`, or triage flips it back to `needs-info` on this and every future update)
- [ ] B: A new dedicated label (e.g. `beta-alert`), created on first use like `ready-for-human` was in `project_onboard.py`, excluded from any automated triage/pipeline logic that might otherwise try to "implement" it
- [ ] C: No label at all — rely on the title/body shape alone to keep it out of the implementation pipeline

### resolve: When a later run shows the threshold no longer crossed, what happens to the open ticket?
- [ ] A: Nothing automatic — it stays open until Gil closes it by hand
- [ ] B: The job posts a comment noting it's no longer breaching (as of which build), but never closes it itself
- [ ] C: The job closes it automatically with a comment citing the build that fixed it

(Both carried forward unanswered from the prior design doc — the code already has `TODO (Decision: ...)` markers at `render_body()` and `file_or_update()` referencing them. Neither is required by this ticket's own acceptance criteria, so they don't block merging the threshold fix; they stay open questions for the PR.)

## Task List

1. `lib/seal_beta_tickets.py:35` — change `THRESHOLDS["median_rating"]` from `5.0` to `4`.
2. `lib/seal_beta_tickets.py:129` — change the comparator from `median_rating < THRESHOLDS["median_rating"]` to `median_rating <= THRESHOLDS["median_rating"]`.
3. `lib/seal_beta_tickets.py:10` — fix the module docstring's threshold line to read "Poor rating: `median_rating` ≤ 4 (on 1-10 scale), AND ≥ 2 reports".
4. `lib/seal_beta_tickets.py:178` — fix the rendered issue-body threshold text from `(threshold: <{THRESHOLDS['median_rating']}, min {MIN_REPORTS_FOR_RATING} reports)` to read `≤{THRESHOLDS['median_rating']}`.
5. `CONTEXT.md:1281-1282` — fix "Poor rating: `median_rating` < 5.0 (on 1–10 scale)" to "≤ 4 (on 1–10 scale), from ≥ 2 reports", and fix "Stuck endings: > 30% of conversations end abnormally (not `userStop`)" to "any literal `stuck` ending" so the doc matches the already-correct code.
6. `lib/tests/test_seal_beta_tickets.py` — add test 1 (`test_median_rating_at_half_point_does_not_breach_ADR_threshold`, with the 4.0/4.5/4.9 trio), test 2 (`test_note_with_name_and_phone_number_never_reaches_rendered_ticket`, built off real `sbi.flatten`/`sbi.summarize`), and test 3 (`test_gate_refusal_on_one_breach_leaves_batch_and_proposals_consistent`, at the `run()` batch level with patched `PROPOSALS_PATH`).
7. Run `~/.agents/venv/bin/python -m pytest lib/tests/test_seal_beta_tickets.py lib/tests/test_seal_beta_ingest.py -v`; confirm test 1 fails before step 1-2 land and passes after, and tests 2-3 pass outright (they're proving an existing invariant, not driving a new fix).
8. Leave the two `Decisions` blocks in `docs/design/pipeline-g-eskayo-marvin-409.md` unresolved for the PR; don't touch `render_body()`'s label/resolve `TODO`s until Gil answers them.