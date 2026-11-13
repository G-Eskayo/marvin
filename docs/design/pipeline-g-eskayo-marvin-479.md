Have enough context now. Here's the plan.

## North-star fit

- **Reuses**: the warning-on-malformed-input pattern this exact file's own docstring points to ("same lesson as `process_quarantine_reviews.py`"), and the existing `HEADER_RE`/`PRIORITY_RE`-style line-anchored regexes already in `sort_suggestions.py` (`skills/architecture-review/scripts/sort_suggestions.py:31-35`) — the fix is one more small `re.findall(..., re.MULTILINE)` helper in the same idiom, not a new parsing approach. It also reuses the isolation pattern from `test_background_architecture_review.py` (`monkeypatch.setattr(module, "SUGGESTIONS_FILE", tmp_path / "suggestions.md")`) rather than inventing a new test-fixture style. The test file `skills/architecture-review/scripts/tests/test_sort_suggestions.py` already exists (added by sibling ticket #480, merged in `924acb48`) — I extend it, I do not create a new file (the ticket's "new file" framing is stale now).
- **Simplest sufficient approach**: a pure boolean check (`_looks_merged`) plus one `print(..., file=sys.stderr)` call in the existing loop over `blocks`. No new data structures, no change to `_split_entries()`'s splitting logic, no change to sort order or output bytes — satisfies "sorting continues unchanged" directly by construction (the check is read-only; it runs on the same `blocks` list already being sorted, no block content is mutated).
- **Tokens**: spends a few lines of code and ~10 small unit tests (cheap, deterministic, no LLM calls) to close a silently-wrong-sort bug that would otherwise cost a human (or MARVIN) a misleading priority read on every run — net saving versus re-discovering this corruption by hand again, as the issue's "Why" section shows happened once already.
- **User capability**: this is backlog-integrity plumbing, not something Gil would otherwise do by hand (he can't watch every merge of a `## ` header) — leaves him strictly more informed, no change to what he must do himself. Fits north star 4 (tool for tools: the backlog that drives improvements reports its own corruption).
- No north star argues against this.

## Files read

- `skills/architecture-review/scripts/sort_suggestions.py` (full file, current state above)
- `skills/architecture-review/scripts/tests/test_sort_suggestions.py` (already exists — one test from #480, unrelated to merged-header detection)
- `skills/architecture-review/scripts/tests/test_background_architecture_review.py` (monkeypatch/tmp_path isolation pattern)
- `lib/inbox.py` (`pile_exists`, `EFFORT_RANK`/`IMPACT_RANK` — confirms the inbox-pile early-return path `sort_suggestions.py:76-77` is untouched by this change)
- `CONTEXT.md` §"Loops (ADR 0083...)" — confirms `suggestions.md` is mid-migration to the inbox but the legacy script (and this fix) is still live until that pile exists
- Issue #479 body and its one comment (generic "must-fix issues" failure notice, no specific defect text — no extra requirement to extract beyond the issue body itself)

## Tests to write first

All added to the existing `skills/architecture-review/scripts/tests/test_sort_suggestions.py`, isolating `SUGGESTIONS_FILE` via `monkeypatch.setattr` to `tmp_path` (never touching the real `~/.claude/suggestions.md`), and reading stderr via `capsys`:

1. **Two `**Added**:` lines in one block** → prints `[sort-suggestions] warning: entry '<title>' looks merged with a neighbour (missing '## ' header?)` naming that block's own header title. *(acceptance criterion 1)*
2. **Two `**Priority**:` lines in one block** (the other half of the "or" in the ticket) → same warning fires.
3. **`**Added**:` quoted mid-line inside an entry's Why text** (e.g. `**Why**: ... mentions **Added**: nothing here`) → no warning; only line-start fields count. *(break-it bullet 1)*
4. **Entry with no `**Added**:` at all** → no warning; missing is not merged. *(break-it bullet 2)*
5. **Clean file, multiple normal entries** → no warning printed, and sort order is identical to the pre-fix behavior (byte-for-byte same written file as today, captured by asserting against the file written with the warning-loop stubbed out / asserting on `_sort_key` ordering directly). *(acceptance criteria 2 and 3)*
6. **Empty file** → early-return path, no warning, file gets `DEFAULT_HEADER`, unchanged from current behavior. *(break-it bullet 3)*
7. **Inbox pile exists (`SUGGESTIONS_FILE.parent / "inbox" / "suggestions"` is a real dir)** → early-return `-1` path, no warning, file untouched. *(break-it bullet 3)*
8. **Two separate merged blocks in the same file** (malformed/stress case) → two distinct warning lines, each naming its own block's title, in input order — not a combinatorial/garbled single message.
9. **Running `sort_suggestions()` twice in a row on an already-warned file** (repeats case) → warning prints again both times (it's stateless per run, not deduped-forever), output file identical after the second run (idempotent sort).
10. **Triple-merged block (three `## `-less entries stacked)** → still exactly one warning line for that block, naming the first (outermost) title — not one warning per extra field.

Not adding tests for: file permission errors (unchanged pre-existing behavior, this change doesn't touch file I/O error handling) or concurrency (the script has no new shared-state access; its existing single-process file read/write is untouched).

## Task List

1. In `sort_suggestions.py`, add `_looks_merged(block: str) -> bool`: returns `True` if `re.findall(r"^\*\*Added\*\*:", block, re.MULTILINE)` has more than one match, or the same for `^\*\*Priority\*\*:`.
2. In `sort_suggestions()`, right after `preamble, blocks = _split_entries(text)` (and before `blocks.sort(...)`, since sort order must stay byte-identical), loop over `blocks` in their original order; for each where `_looks_merged(block)` is true, extract the title via `HEADER_RE.match(block)` and print `[sort-suggestions] warning: entry '<title>' looks merged with a neighbour (missing '## ' header?)` to `sys.stderr`.
3. Write tests 1–10 above in `skills/architecture-review/scripts/tests/test_sort_suggestions.py`, alongside the existing `test_missing_priority_field_sorts_below_every_real_priority` (don't touch that test).
4. Run the test file and confirm all pass, including the pre-existing #480 test (regression check).
5. Do **not** touch `~/.claude/suggestions.md` — the issue marks that data fix as "done by hand in triage," outside this repo change, and it's outside the sandboxed home-dir write path anyway.