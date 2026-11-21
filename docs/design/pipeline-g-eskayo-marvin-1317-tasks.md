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