## North-star fit

**Reuses before adding anything new:**
- `auto_fix.py`'s existing `load_queue()` / `mark_items()` (lines 185–224) — the new "drop existing VERBOSITY items" step is one small function built entirely on these two primitives, not a new queue reader/writer.
- `inbox.py`'s existing `QUEUE_MARK_STATES` mark-parsing convention (`lib/inbox.py:453`) — extended with one tuple (`("dropped", "dropped")`) rather than inventing a new status mechanism. `inbox.act()`'s already-proven "custom state + note" pattern (used today for `suggestions`' `declined` state) is the direct precedent.
- `improvement_sweep.py`'s existing `top_issues()` anti-pattern filter (line 82) — extended with an explicit kind-exclusion, not a new filtering stage.

**Why this is the simplest sufficient approach:** the owner's decision (`t1123-verbosity`, already `[x]`) is "drop it" — not "rename it" or "hide it" — so the fix is deletion, not reclassification: the four AST/regex checks in `qa_scan.py` that currently tag `verbosity` (the `== True/False` check, `len(...) == 0` check, `not not` check, and the filler-word-in-comment check) are removed outright rather than kept-but-filtered, since dead detection code that nothing ever surfaces is waste nobody asked to maintain (Colton/Watts checks). I read the ticket's "(filler word)" parenthetical and "Where it lives → qa_scan.py (filler-word comment checks)" as descriptive, not scope-limiting: the Task line ("the scanners stop emitting **them**") and the owner's literal choice ("Drop it … about 67 low-value items") are about the whole VERBOSITY category, and three of the four checks aren't comment-related at all, so narrowing to just the comment check would leave VERBOSITY items still flowing from the other three. I'm flagging this interpretive call plainly rather than silently narrowing it — it isn't a product choice that needs a button-press, since the ticket and the owner's answer already settled "category, not subset."

**Where it saves:** fewer detection passes per scan (less CPU/tokens per handoff), a smaller queue (fewer entries to carry into the daily digest's LLM prompt → fewer tokens on every digest call), no PR churn on 67 low-value items.

**More capable, not more passive:** removes noise from Gil's queue/digest so his attention goes to LOGIC/NAMING/KISS findings that actually matter, directly serving north star 3.

Two implementation calls I'm making without a Decisions block (neither is a product choice — both follow mechanically from already-settled design):
1. The "existing VERBOSITY items get marked dropped" step runs automatically inside `auto_fix.py`'s existing daily job (same place `refresh_pr_marks` already runs), not a one-off migration script — it degenerates to a cheap no-op once nothing is left to drop, which is simpler than adding a run-once sentinel.
2. The daily digest filters out VERBOSITY items by kind directly (in addition to the drop-marking), so "gone from the digest" holds even on the day something is queued and the day it's marked dropped haven't yet both happened.

## Tests to write first

**`skills/qa-agent/scripts/tests/test_qa.py`** (new — no existing coverage of these checks):
1. A file whose comments are packed with filler words (`just`, `simply`, `basically`, …) → `analyze_comment_quality`/`analyze_quality`/`scan()` produce **zero** issues tagged `verbosity`/`[VERBOSITY]`.
2. A file with `if flag == True:`, `if len(x) == 0:`, `not not x` → same: no `verbosity`-kind issues from any of these, confirming all four sources are gone, not just the comment one.
3. The same fixture still produces its *other* findings unchanged: a generic parameter name (naming), `== None` (style/PEP8), a bare `# TODO` (comment) — "other categories unchanged."
4. `qa_scan.scan(tmp_project)` end-to-end on a project full of filler words: no entry's `document` contains `[VERBOSITY]` (the literal acceptance-criterion scenario, at the scan layer).

**`skills/improve/scripts/tests/test_improvement_sweep.py`** (new):
5. `top_issues()` given only `[VERBOSITY]`-tagged anti-pattern entries returns `[]` (defense-in-depth at the sweep layer, independent of where the entries came from).
6. `top_issues()` given a mix of `[VERBOSITY]` and `[NAMING]`/`[LOGIC]` entries returns only the non-VERBOSITY ones, and never degrades to including VERBOSITY just because fewer than 5 other findings exist.

**`skills/improve/scripts/tests/test_auto_fix.py`** (update existing + new):
7. Update the `QUEUE` fixture to drop its `[VERBOSITY]` line (2 items, not 3) and every hardcoded `3`-count assertion in the file (`test_items_are_marked_in_pr...`, `test_a_pr_closed_unmerged...`, `test_the_log_keeps_the_line...`, `test_a_fix_that_breaks_a_test...`, `test_a_fixer_that_changes_nothing...`) to `2`.
8. `af.SCOPE` no longer contains `"VERBOSITY"`; `_in_scope()` returns `False` for a `VERBOSITY` item even when unmarked.
9. `pr_body()` / `FIX_PROMPT_TEMPLATE` output never contains the literal string `VERBOSITY` ("summary line no longer names VERBOSITY").
10. **Mixed-kind drop** (markdown mode): a queue with one unmarked `[VERBOSITY]` line and one unmarked `[NAMING]` line → `drop_kind("VERBOSITY", reason, today)` marks only the VERBOSITY line (`— auto-fix: dropped <today>, ticket #1317: …`); NAMING line untouched.
11. **Mixed-kind drop** (inbox-pile mode, fixture mirroring `test_improvement_sweep.py`'s `piled`): same scenario via `inbox.list_items` — VERBOSITY item's `status.state == "dropped"` with a note containing `"#1317"`; NAMING item stays `"open"`.
12. **Old-format / nothing-lost**: a pre-mark-convention `[VERBOSITY]` bullet (no `— auto-fix:` suffix) plus a fully untyped old bullet (no `[KIND]` tag at all) in the same file → after `drop_kind`, the VERBOSITY bullet is dropped, the untyped bullet is byte-for-byte unchanged (not corrupted, not lost).
13. **Stale state**: a `[VERBOSITY]` item already marked `in PR #42` is *not* re-marked dropped (don't clobber in-flight state).
14. **Idempotency**: calling `drop_kind` twice — the second call marks nothing new and the file/pile is unchanged.
15. **Empty/missing queue**: `drop_kind` on an empty or missing queue does nothing and doesn't raise.
16. Existing `test_a_huge_queue_is_parsed_quickly_and_only_a_capped_batch_is_taken` re-verified to still pass with `drop_kind` now running unconditionally on every `run()` call (performance check — adjust if the extra full-queue pass regresses it).

**`lib/tests/test_inbox.py`** (new):
17. `inbox.queue_status("dropped 2026-11-20, ticket #1317: …")` → `{"state": "dropped", "note": "...", "on": "2026-11-20"}`.

**`skills/improve/scripts/tests/test_daily_digest.py`** (new, alongside existing inbox tests at line 466+):
18. A pile with a `[VERBOSITY]` item mixed with `[NAMING]`/`[KISS]` items → `improvement_queue_summary()`'s output never contains `VERBOSITY`, and the "`X of Y`" count excludes the VERBOSITY item from `Y`.
19. Same scenario in legacy-markdown (pre-import) mode → the raw-dump output still contains the `**[NAMING]**`/`**[KISS]**` lines verbatim (preserving `test_queue_summary_reads_the_inbox_once_the_pile_exists`'s existing contract) but the `**[VERBOSITY]**` line is filtered out before the last-20-lines dump.
20. Re-run the two existing tests at lines 466 and 481 unchanged, to confirm no regression.

## Task List

1. `skills/qa-agent/scripts/qa_scan.py`: remove the `verbosity`-tagged branches from `QualityVisitor.visit_Compare` (`== True/False`, `len(...) == 0`), delete `visit_UnaryOp` entirely (`not not` check), delete the filler-word block and `_FILLER_RE` in `analyze_comment_quality`, and drop the now-unreachable `"verbosity"` key from `quality_kind_to_tags` in `scan()`.
2. `skills/improve/scripts/improvement_sweep.py`: remove `"verbosity"` from `KIND_PRIORITY`; add an explicit kind-exclusion in `top_issues()` so a `[VERBOSITY]`-tagged anti-pattern entry is never selected regardless of origin.
3. `lib/inbox.py`: add `("dropped", "dropped")` to `QUEUE_MARK_STATES`.
4. `skills/improve/scripts/auto_fix.py`: 
   - `SCOPE = ("NAMING", "KISS")`, drop `"VERBOSITY"` from `DIFF_CAP`.
   - Remove the VERBOSITY bullet from `FIX_PROMPT_TEMPLATE`'s "How to fix each kind" and from `pr_body()`'s "Size caps" line.
   - Add `DROP_REASON` constant and `drop_kind(kind, reason, today=None)` (built on `load_queue`/`mark_items`), skipping already-marked items.
   - Call `drop_kind("VERBOSITY", DROP_REASON, today)` unconditionally at the top of `_run_locked()`.
   - Update the module docstring (steps list, the mark-format example, the "NAMING, VERBOSITY and KISS" line) to match.
5. `skills/improve/scripts/daily_digest.py`: filter VERBOSITY out of `improvement_queue_summary()` for both the inbox-pile branch (by `fields.kind`) and the legacy-markdown branch (by line pattern), preserving each branch's existing output format.
6. Update docs to match code: `skills/improve/SKILL.md` (priority-order sentence), `skills/audit/SKILL.md` (auto_fix scope description), `CONTEXT.md` line 131 (auto-fix scope description).
7. Write/update all tests listed above (qa_scan, improvement_sweep, auto_fix, inbox, daily_digest).
8. Run the full affected suites (`skills/qa-agent`, `skills/improve`, `lib/tests/test_inbox.py`) and confirm no other test outside this list references `VERBOSITY`/`verbosity` in a way that now fails.