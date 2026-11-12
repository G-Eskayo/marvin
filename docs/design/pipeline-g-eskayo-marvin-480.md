## North-star fit

Reuses two existing patterns, no new infrastructure:
- **Guard-test pattern** (`lib/tests/test_no_hardcoded_home.py`): a small pytest module that reads real repo files via `Path.read_text()` and asserts a textual invariant across files, with the `REPO = Path(__file__).resolve().parents[2]` convention. The new drift check follows this shape exactly — same directory, same style — rather than inventing a "skill-lint" framework.
- **`_sort_key()`** in `skills/architecture-review/scripts/sort_suggestions.py:57-72` — reused as the system under test for the "missing Priority sorts as 0" case, not reimplemented.

North star 4 (tool for tools): fixes a doc-drift bug between two skills that both write to the same shared backlog, so they can't diverge again. North star 1: this is a two-line prose edit plus two small test files — no new scripts, no new scope. Effort stays "low" as the ticket states; cost is a few hundred tokens to read and edit 1 file + add ~2 test files, which is proportionate to a P1 reliability bug with a known concrete fix already spelled out in the ticket. Leaves the user more capable: audit-generated findings will now sort correctly without Gil having to notice and hand-fix a missing Priority field.

No contradiction with recorded decisions: architecture-review/SKILL.md's "Entry format:" block (lines 38-52) is the canonical format; nothing here changes it, only audit's paraphrase of it.

## Tests (written first)

From "How we'll try to break it" plus the acceptance criteria's own test requirement — new file `lib/tests/test_audit_entry_format_sync.py`:

1. `test_audit_dispatch_prompt_names_every_architecture_review_entry_field` — parse the field names (`Priority`, `Status`, `Impact`, `Effort`, `Why`, `What`, `How`, `Added`) out of architecture-review/SKILL.md's real "Entry format:" fenced block, assert every one of them appears (as `**Field**`) in audit/SKILL.md's real dispatch-prompt text. This is the live regression test — it fails today (no `**Priority**`, no `**Added**`) and must pass after the edit.
2. `test_drift_check_detects_a_field_missing_from_audits_prompt` — the ticket's "Attacks" case: take the real field list, append a fixture field (`"Owner"`) that was never added to audit's prompt, run the same missing-field check, assert it reports exactly `["Owner"]` as missing (non-empty) — proving the check actually catches drift instead of vacuously passing.
3. `test_audit_dispatch_prompt_no_longer_uses_the_stale_dated_header` — asserts `"## [date] [title]"` is absent from audit's dispatch prompt and `"[Title]"` is present, directly encoding acceptance criterion 1.

New file `skills/architecture-review/scripts/tests/test_sort_suggestions.py` (no test currently exists for this script):

4. `test_missing_priority_field_sorts_below_every_real_priority` — builds two fixture blocks (`**Priority**: 1` vs. no Priority line at all), calls `_sort_key()` on each, asserts the no-Priority block's key sorts *after* (worse than) the Priority-1 block's key. This is the ticket's second Attack: documents in code why the field is required, not just in prose.

Misuse not explicitly in the ticket, covered because cheap and relevant to this exact mechanism:
- Entry-format block or dispatch-prompt section not found at all (file reorganized) — the helper functions `assert` with a message naming which anchor moved, so a future rename fails loudly instead of silently matching nothing (same intent as acceptance criterion 3's "next format change fails loudly").

Not applicable here: no network/concurrency/permissions dimension — this is a static-text consistency check over files already in the worktree.

## Decisions

None. The ticket's What/How are concrete and unambiguous; the only implementation choice (where the new test files live) follows an existing, uncontested repo convention, not a judgment call for the owner.

## Task List

1. Edit `~/.agents/skills/audit/SKILL.md`'s dispatch prompt (the paragraph under "## How to dispatch", ~line 47-49): replace `"architecture-review's exact entry format (## [date] [title], Status: pending, Impact, Effort, Why, What, How)"` with a pointer to architecture-review/SKILL.md's "Entry format:" block plus the full field list, naming `**Priority**` and `**Added**` explicitly, and dropping `## [date] [title]` entirely.
2. Add `~/.agents/lib/tests/test_audit_entry_format_sync.py` with the three tests above (field-presence check, fixture-drift check, stale-header check), using small regex helpers to extract architecture-review's Entry-format block and audit's dispatch-prompt section.
3. Add `~/.agents/skills/architecture-review/scripts/tests/test_sort_suggestions.py` with the `_sort_key()` missing-Priority ranking test.
4. Run the full test suite (not just the new files) per the full-suites-before-hand-merge rule, confirm the new tests fail against the pre-edit SKILL.md text (sanity-check via git stash of the edit) and pass after it.
5. Show Gil the diff of `audit/SKILL.md` via `marvin-show` before considering this done.