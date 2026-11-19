## North-star fit

**Reuses:** the existing `tests/test_skill_doc_links.py` pattern (file-content assertions over skill markdown, `Path(__file__).resolve().parents[1] / "skills" / ... `) — the established way this repo tests doc/skill files — rather than inventing a new doc-lint mechanism. Also reuses the citation style already used in `skills/to-issues/SKILL.md` (`docs/north-stars.md`) for pointing at the north star/ADR instead of restating it, and the existing `mocking.md` ChromaDB `tmp_path` example as the anchor for the new temp-HOME rule.

**Why simplest sufficient:** ~15–20 lines changed across 4 existing files (`skills/tdd/SKILL.md`, `mocking.md`, `tests.md`) plus one small new test file following an established pattern. No new skill, no new doc, no abstraction — exactly what `docs/adr/0063-tests-try-to-break-it-enforced-at-every-gate.md` and `lib/ticket_policy.py`/`lib/commit_check.py` already enforce; this ticket only makes the skill doc stop contradicting them.

**Tokens:** spends a small, one-time editing cost; saves recurring cost on every future ticket that touches tests, since `skills/tdd/SKILL.md` is always-on and currently points every dev-work agent at the wrong bar ("not every possible edge case" vs. ADR 0063's "every feasible way to misuse it"), which the ticket says is already causing send-backs/reruns (north star 1).

**Phone-OS direction:** neutral — this is a process-consistency fix, not a feature.

**User capability:** more capable — agents (and the humans reading their output) get one consistent, correctly-cited test bar instead of two contradictory ones, closing a gap that otherwise relies on a reviewer catching it by memory.

**Confirmed:** the ticket's own claim that the merge gate/commit check criteria live in a separate file is correct — `lib/ticket_policy.py:300` ("ADR 0063 gate 1 (#335): a build ticket says how we'll try to break it... Research and decision tickets are exempt") and `lib/commit_check.py` (`# ADR 0063 gate 4`) both enforce the rule stated once in `docs/north-stars.md` / `docs/adr/0063-...md`. `SKILL.md` should point there, not restate it — matches the ticket's instruction exactly.

No CONTEXT.md decision or prior ADR covers `skills/tdd/` docs or a "logs-wipe" incident by name; no prior PR/comments exist for #631 (checked `gh issue view 631 --comments` — empty, and `gh pr list --search 631` — no match). Nothing to reconcile.

## Tests to write first

Ticket's "How we'll try to break it" section states: **"Docs-only: exempt"** — matching ADR 0063 gate 1 (research/docs tickets are exempt) and ADR 0063's own consequence line ("Docs- or config-only changes pass the commit check with a stated reason"). This change touches only three markdown files with no executable behavior, so there are no misuse/adversarial/dependency-failure cases to simulate (no input parsing, no outward-facing surface, no state, no concurrency — the files are static prose read by an LLM at skill-load time).

What *is* verifiable mechanically, and what I'll write first (reusing the `test_skill_doc_links.py` pattern, one assertion per acceptance criterion, in a new `tests/test_tdd_skill_break_it_standard.py`):

1. `test_skill_md_no_longer_limits_edge_cases` — `skills/tdd/SKILL.md` content does **not** contain "not every possible edge case".
2. `test_skill_md_cites_adr_0063` — `skills/tdd/SKILL.md` content contains a reference to `docs/north-stars.md` (or ADR 0063) in place of the restated rule.
3. `test_checklist_has_break_it_item` — the "Checklist Per Cycle" block in `SKILL.md` contains a break-it-cases line (empty/malformed/huge input, dependency failure, repeats/wrong order, stale state).
4. `test_checklist_has_outward_facing_item` — the same checklist block contains an adversarial/outward-facing-input line (injection, traversal, oversized payload, secrets in logs, fail closed).
5. `test_mocking_md_states_temp_home_rule` — `mocking.md` contains the temp-HOME rule (never point tests at the real `~/.claude`/`~/.agents`; use `tmp_path`/temp HOME) and still contains the existing ChromaDB `tmp_path` example (regression check: didn't delete the anchor it's "next to").
6. `test_mocking_md_cites_logs_wipe_incident` — `mocking.md` references the 2026-10-09 logs-wipe incident as the rule's justification.
7. `test_tests_md_has_failure_path_example` — `tests.md` contains a second "Good" example whose test name/body demonstrates a failure path (malformed/empty input rejected without raising), plus the sentence that failure paths count as behavior.
8. `test_mock_boundary_rule_unchanged` — `mocking.md`'s "Mock at the true external boundary only" sentence is still present verbatim (regression guard: ticket explicitly says leave it unchanged).

This set covers every acceptance-criterion box in the ticket one-for-one, plus a "didn't break what was already there" regression case for each file touched (#5, #8) — the misuse case a purely additive-editing task can actually have: an edit accidentally deleting or garbling the adjacent content it was told to leave alone.

## Decisions

None. The ticket is fully specified: exact line to replace, exact two checklist items, exact file/placement for the temp-HOME rule and its citation, exact file/placement for the failure-path example, and an explicit instruction to leave one sentence unchanged. Nothing here requires an owner choice.

## Task List

1. Write `tests/test_tdd_skill_break_it_standard.py` with the 8 failing tests above (RED), following `tests/test_skill_doc_links.py`'s `Path(__file__).resolve().parents[1]` pattern.
2. Edit `skills/tdd/SKILL.md` line 62: replace "Focus testing effort on critical paths and complex logic, not every possible edge case." with wording that prioritizes by risk but requires break-it cases for every behavior, citing `docs/north-stars.md` (ADR 0063) instead of restating it. (Satisfies tests 1–2.)
3. Edit `skills/tdd/SKILL.md` "Checklist Per Cycle" (~line 103–111): add one line for break-it cases (empty/malformed/huge input, a dependency failing, repeats/wrong order, stale state) and one line for outward-facing adversarial cases (injection, traversal, oversized payload, secrets in logs, fail closed). (Satisfies tests 3–4.)
4. Edit `skills/tdd/mocking.md`: add the temp-HOME rule next to the existing ChromaDB `tmp_path` example, citing the 2026-10-09 logs-wipe incident; leave "Mock at the true external boundary only" untouched. (Satisfies tests 5, 6, 8.)
5. Edit `skills/tdd/tests.md`: add a second "Good" example demonstrating a failure path (malformed/empty input rejected without raising) plus one sentence stating failure paths are behavior too. (Satisfies test 7.)
6. Run the new test file and confirm all 8 pass (GREEN); run the full `tests/` suite to confirm no existing test (e.g. `test_skill_doc_links.py`) regressed.
7. Commit with a stated reason per ADR 0063 gate 4 (docs-only change), referencing #631.