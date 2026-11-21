Everything checks out. Here's the plan.

## North-star fit

This reuses two existing patterns rather than inventing anything: `lib/ticket_policy.py:is_parent_prd` (already the single source of truth for "what counts as a PRD" — `\s*PRD\b` title match, already fully tested in `lib/tests/test_ticket_policy.py`) and `tests/test_skill_doc_links.py`'s pattern of asserting on literal `SKILL.md` prose content with a regex, which is the right shape for a doc-only test. The convention itself already exists in the wild (PRD issues #1164, #1146, #152 all titled `PRD: <name>` with `enhancement` + `project:*` + `priority:*`), and `triage`'s `is_parent_prd` already skips PRDs (CONTEXT.md:1133) — this ticket just writes that convention down so an agent doesn't have to re-derive it per run, which is exactly north star 4 (tool for tools: one written convention instead of a guess) and the "research efficiency" principle (start from what's already known). It's the simplest sufficient approach: two short sentences added to two docs, no code change, no new file. Token cost: near-zero to apply, and it saves tokens on every future `to-prd` run that would otherwise guess at labelling. It leaves the user more capable — it removes an ambiguity that previously risked a human or `triage` run misclassifying a spec as actionable work, not through automation, but through a known-good answer.

One discrepancy worth flagging, not blocking this ticket: issue #1146, cited in the ticket as "no triage-role label," actually still carries `needs-triage` today. That's the exact failure mode this ticket exists to prevent, but it's a mislabeling of an existing issue, not a doc defect — out of scope here (fixing it is a one-label `gh issue edit`, not a doc change, and the ticket's own scope is docs-only).

## Tests

The ticket's "How we'll try to break it" section says `Docs-only: exempt`. That's correct for behavior — there's no runtime code path to attack (no input parsing, no external surface, no dependency to fail). But acceptance criterion 3 ("the prefix written in the skill matches the regex in `lib/ticket_policy.py`") is a concrete, checkable claim, and leaving it unchecked means future drift (e.g. if `is_parent_prd`'s regex ever changes) would silently desync the doc from the code it's describing. Following `tests/test_skill_doc_links.py`'s exact pattern, I'll add one test, written first:

1. `tests/test_to_prd_skill_prd_label.py::test_to_prd_skill_names_prd_prefix_and_labels` — reads `skills/to-prd/SKILL.md`, asserts step 3's text contains the literal `PRD: ` title instruction and names `enhancement`, a project label, and a priority label, and asserts it does NOT also hand-apply any of the five canonical triage-role labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`).
2. `tests/test_to_prd_skill_prd_label.py::test_to_prd_skill_prefix_matches_ticket_policy_regex` — extracts the sample title the skill instructs (`PRD: <name>`, with a concrete substitution e.g. `PRD: Example feature`) and asserts `lib.ticket_policy.is_parent_prd({"title": ...})` returns `True` for it, directly enforcing acceptance criterion 3 against the real regex rather than a copy of it.
3. `tests/test_triage_labels_doc_prd_exception.py::test_consumer_rules_state_prd_exception` — reads `docs/agents/triage-labels.md`'s Consumer rules section and asserts it states a parent PRD (title `PRD: ...`) carries no triage-role label.

No misuse cases beyond this apply (bad/empty/huge/malformed input, dependency failure, concurrency, stale state, wrong permissions are all meaningless for a static doc-string assertion) — the only thing that can "misuse" this change is the doc and the code drifting apart, which test 2 directly guards.

No Decisions section is needed: every instruction in "What to build" is fully concrete (exact sentence, exact line, exact prefix already verified against both the regex and the live convention), with no owner choice left open.

## Task List

1. Write the three tests above (`tests/test_to_prd_skill_prd_label.py`, `tests/test_triage_labels_doc_prd_exception.py`), confirm they fail against current doc content.
2. Edit `skills/to-prd/SKILL.md` step 3: after `...not ready-for-agent — a PRD is a spec, not a single unit of work)`, add the sentence specified in the ticket — title it `PRD: <name>`, apply `enhancement` + project label + priority label, apply none of the five triage-role labels, note the `PRD:` prefix is how triage knows to leave it alone.
3. Edit `docs/agents/triage-labels.md`'s Consumer rules bullet list: add one line stating a parent PRD (title `PRD: ...`) carries no triage-role label.
4. Run the new tests plus the existing `lib/tests/test_ticket_policy.py` suite (unchanged, just confirming no regression) and `tests/test_skill_doc_links.py` to confirm nothing else that greps `SKILL.md` content broke.
5. Re-read both edited files in full to confirm the acceptance criteria are satisfied verbatim (prefix present, labels named, no triage-role label stated, prefix matches `lib/ticket_policy.py`'s regex).