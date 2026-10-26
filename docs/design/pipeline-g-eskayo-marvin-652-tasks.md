1. `lib/stale_decision_check.py`: candidate gathering — `repo_root()`, `repo_doc_candidates()`, `memory_candidates()` (wraps `project_catalog.discover_memory`), `gather_candidates()`.
2. Same file: lexical pre-filter using `project_catalog.tokens()`.
3. Same file: `classify_claim_pair()` + its Ollama prompt/parse helpers, `chat_fn`-injectable per `continuity_checker`'s pattern.
4. Same file: `find_stale_claims()` pipeline (gather → prefilter → classify → STALE-only flags), with the truncation and bounded-candidate-count guards from tests 5 and 13.
5. Same file: `format_entry()`, `existing_pending_keys()`, `append_flags()` (tmp-file-then-replace write), `check_file()` (read-and-check entry point for the hook).
6. `lib/tests/test_stale_decision_check.py`: tests 1–9, 11–13 above.
7. New PostToolUse hook script (e.g. `lib/stale_decision_check_hook.py`), modeled on `emit-resume-prompt.py` + `background_review.py`'s detached-subprocess/cooldown: filters the written path per the `hook-scope` decision, spawns `stale_decision_check.py check <path>` detached and non-blocking.
8. Test 12 (hook path filtering) against the hook script directly.
9. `lib/output_contracts.py`: add `STALE_DECISIONS` path constant and a `Contract("stale-decision-check", "~/.claude/stale-decisions.md", "handoff/self-improve session-start review or Gil", 1, lambda: suggestions_state(_read(STALE_DECISIONS)))` entry.
10. `lib/session_start_report.py`: add `check_stale_decisions()` (same inline-regex shape as `check_suggestions()`), wire it into `main()`'s `notes` tuple.
11. `docs/session-start-checklist.md`: add the new row to the table (required by its own "editing this checklist" rule).
12. `skills/handoff/SKILL.md`: one Rules-section line pointing at the new check, mirroring the existing `owner_decisions.py` rule.
13. One-off sweep: `sweep()` in `stale_decision_check.py` (memory-vs-memory, bounded pairwise prefilter, plus memory-vs-linked-project-repo-docs via `project_catalog`'s existing memory↔project linking) + `render_sweep_report()`; test 10.
14. Wire the new PostToolUse hook entry into `~/.claude/settings.json`'s `Write|Edit` block (outside this repo's git history, same as every existing hook script — `emit-resume-prompt.py`, `background_review.py`, etc. — were wired).
15. Run the full `lib/tests/` suite to confirm no regression, and run the sweep once for real to seed the queue/report with whatever it finds today (report only, per Decision `sweep-output`).