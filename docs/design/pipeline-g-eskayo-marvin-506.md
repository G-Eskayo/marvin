## North-star fit

- **Reuses:** the existing doc-accuracy test pattern in `skills/qa-agent/scripts/tests/test_qa.py` (`extract_fenced_block` + direct `SKILL.md` text assertions, e.g. `test_sub_agent_snippet_no_tilde_and_check_true`, lines 254–343) for the new regression tests, and the existing `make_project`-style tmp-dir pattern for a tmp `CHROMA_PATH`. No new test infrastructure, no new file.
- **Simplest sufficient approach:** this is a one-line doc edit (`SKILL.md` line 100) plus tests that pin the doc to the real behavior of `qa_scan.store_entries()` / `qa_capture.store_entry()`. I confirmed by grep (`cosine`, case-insensitive) that `skills/qa-agent/` has exactly one promise of the cosine check — `SKILL.md:100` — and no README exists in that folder, so the "grep for other promises" acceptance criterion needs no extra edits, only a regression test to keep it true.
- **Token/compute cost:** net negative — removes a false promise that would otherwise cost future agents a wasted `col.query()` design detour (as the two prior failed attempts likely took), for the price of one doc line and ~3 small tests.
- **North star:** the ticket's stated fit (2, "the docs say what the code does") maps onto north star 2's "Reliability is its precondition: nothing may break silently" — a doc that promises an unimplemented check is exactly a silent-break risk for anyone who trusts it. It also directly serves the guiding principle **"Verified, not assumed"** ("a connection or claim counts only when code checks it... not when a prompt or doc says so") — I'll cite both in the PR rather than override the ticket's choice, since both are accurate.
- **More capable, not more passive:** fixes a trust defect in the KB's own documentation so future agents (human or AI) stop assuming a dedup guarantee that isn't there; doesn't remove any human judgment.

No Decisions needed — the owner already chose the direction on #1293 ("fix the doc... measure in a separate ticket", now #1314); this ticket has no open fork left to ask.

## Why prior attempts likely failed

No PR exists yet for #506 (checked `gh pr list --head "pipeline/g-eskayo/marvin#506"`), and the issue comments only say "code review found must-fix issues" with no specifics. My best-supported guess, given the ticket explicitly says "No code change here": prior attempts probably either touched `qa_scan.py`/`qa_capture.py` (scope creep against the ticket's own instruction) or shipped the doc edit with no test proving criterion 1 ("doc matches the code"). This plan avoids both: doc-only edit, plus tests that assert the doc's claim against the real `store_entries`/`store_entry` behavior.

## Tests to write FIRST (in `skills/qa-agent/scripts/tests/test_qa.py`)

1. **`test_skill_md_dedup_rule_states_sha256_not_cosine`** — read `SKILL.md`, isolate the `## Behaviour rules` section (same `extract_fenced_block`-style helper, adapted to grab a `##` section instead of a fenced block, or a simple substring search since this section isn't fenced code), assert it contains `"SHA-256"` and does **not** contain `"cosine"`.
2. **`test_skill_md_dedup_rule_links_1314`** — assert the dedup line contains `"#1314"`.
3. **`test_no_cosine_promise_anywhere_in_qa_agent_skill_folder`** — walk every file under `skills/qa-agent/` (the `SKILL.md` plus `scripts/*.py`) and assert none contain the substring `"cosine"` case-insensitively. This is the regression form of the ticket's "grep the skill folder for other promises" step — it keeps the acceptance criterion true even if someone re-adds a cosine mention later. (Confirmed today, before any edit: only `SKILL.md:100` matches; no other file in the folder does.)
4. **`test_store_entries_skips_exact_duplicate_content`** — against the **real** `chromadb` (not mocked), monkeypatch `qa_scan.CHROMA_PATH` to a `tmp_path`, build two byte-identical entries via `scan()`'s `add()`/`_make_id` (or hand-built dicts matching its shape), call `store_entries()` twice: first call stores 1, second call (same content) stores 0 new. Proves the "exact content already exists → skipped" doc claim against `qa_scan.py`.
5. **`test_store_entries_does_not_dedup_near_identical_content`** — same tmp `CHROMA_PATH`, two entries whose documents differ by one character (e.g. a shifted line number): both get stored (`store_entries()` returns 2 new, not 1). Proves the doc's new "near-identical paraphrases are not deduplicated yet" clause is actually true of the code, not just asserted.
6. **`test_store_entry_skips_exact_duplicate_content`** — same pair of checks (exact-dup skip, near-dup not skipped) against `qa_capture.store_entry()` with a monkeypatched `CHROMA_PATH`, since the ticket's acceptance criterion names both `store_entries()` and `store_entry()` explicitly.

Scope note: concurrency/corrupted-store edge cases of `store_entries`/`store_entry` are pre-existing behavior this ticket doesn't touch (no code change) — not adding tests for those here would be scope creep for a doc ticket; flagging this explicitly rather than silently skipping it.

## Task List

1. Edit `skills/qa-agent/SKILL.md` line 100: replace `- Dedup: before inserting, check if near-identical content already exists (cosine > 0.95).` with `- Dedup: entries are skipped if their exact content already exists in the KB (SHA-256 hash match). Near-identical paraphrases are not deduplicated yet; see #1314.`
2. Add test 1 and 2 above (SKILL.md text assertions) to `test_qa.py`.
3. Add test 3 above (folder-wide "no cosine promise" regression guard) to `test_qa.py`.
4. Add tests 4, 5, 6 above (real-chromadb, tmp-path dedup behavior checks for `store_entries()` and `store_entry()`) to `test_qa.py`.
5. Run `~/.agents/venv/bin/python -m pytest skills/qa-agent/scripts/tests/test_qa.py -v` and confirm all pass (old and new).
6. Open the PR with body `Closes #506`, per `docs/agents/issue-tracker.md`'s "a PR names its ticket" convention; no Decisions section (none open).