## North-star fit

**Reuses:** the pagination loop already written three times in `skills/improve/scripts/cross_machine_merge.py` — once inline in `sync_research_feed()` (lines 156–163), once in `sync_qa_knowledge()` (lines 215–222), once in `sync_paper_knowledge()` (lines 279–286) — and the shared `(remote_id, host, sync_state)` signature `sync_qa_knowledge`/`sync_paper_knowledge` already both use. Nothing new is invented; the only new code is two thin wrapper functions, required by the ticket so `main()` and both functions' call sites stay untouched.

**Simplest sufficient approach:** extract-method, no new abstraction layer, no dependency-injection scaffolding. `_existing_ids(col)` and `_sync_collection(collection, remote_id, host, sync_state)` are plain functions parameterized on the one thing that actually varies (the collection name) — matches the ticket's own spec exactly, nothing added beyond it.

**North star 5 (every machine works, none overloaded):** this is the direct point of the ticket — `qa-knowledge`, the collection both machines' QA lookups depend on, currently has zero test coverage and could silently drift from the tested `paper-knowledge` copy. Putting both on one tested path is exactly "every machine works."

**Tokens:** saves ~60 lines of duplicated logic and a third copy of the pagination loop; a future fix to cursor/dedup logic now lands once instead of three times. Spends a small, bounded amount now (new tests) to close a real coverage gap — proportionate to a ~60-line dedup, not a rewrite.

**More capable, not more passive:** this is pure maintenance load reduction for whoever (human or agent) next touches cross-machine sync — it doesn't change what Gil does, it removes a trap (editing the tested copy without remembering the untested twin).

No recorded ADR/CONTEXT.md decision governs this file's internal structure, so nothing here contradicts prior decisions.

**Prior attempt note:** the issue has one denial comment — "code review found must-fix issues" after 3 iterations, no specifics given (no PR was ever opened, so there's nothing concrete to recover from the GitHub side). Treated as: get the string-for-string behavioral equivalence exactly right the first time, since that's the part most likely to hide a subtle bug in this kind of refactor.

## Tests to write FIRST

In `skills/improve/scripts/tests/test_cross_machine_merge.py`, parametrize the 7 existing sync tests over `[("qa-knowledge", cmm.sync_qa_knowledge), ("paper-knowledge", cmm.sync_paper_knowledge)]` (ids=`["qa-knowledge", "paper-knowledge"]`), renaming off the `_paper_knowledge` suffix:

1. `test_sync_imports_new_entries_and_advances_cursor` — was `..._paper_knowledge_imports...`
2. `test_sync_skips_already_known_ids`
3. `test_sync_uses_prior_cursor_in_the_dump_command`
4. `test_sync_skips_gracefully_when_remote_unreachable`
5. `test_sync_skips_gracefully_on_malformed_json`
6. `test_sync_no_new_items_leaves_state_untouched`
7. `test_sync_never_downloads_the_embedding_model`

Each body swaps the hardcoded `cmm.sync_paper_knowledge(...)` / `"paper-knowledge"` for the parametrized `sync_fn(...)` / `collection`. This is what actually closes the ticket's stated coverage gap — `sync_qa_knowledge` gets the same assertions `sync_paper_knowledge` already had (AC #1).

New tests, closing gaps the ticket's "How we'll try to break it" doesn't cover:

8. `test_existing_ids_pages_through_exact_page_boundary` — direct unit test of `_existing_ids()` against a fake collection object whose `.get(limit=5000, offset=...)` returns exactly 5000 ids on the first call and more on the second; asserts every id is returned once, none dropped or duplicated at the boundary. (AC #3's actual bullet — "collection with exactly 5000 ids" — is about the extracted helper itself, not the sync wrappers.)
9. `test_one_collection_unreachable_does_not_block_the_other` — a single `ssh_run` stub that returns `None` for the paper-knowledge dump command but a valid dump for qa-knowledge; calls `sync_qa_knowledge` then `sync_paper_knowledge` in sequence (mirroring `main()`'s loop) and asserts qa-knowledge's state updates while paper-knowledge's is left untouched and nothing raises. (The ticket's bullet #2, "remote unreachable for one collection: the other still syncs," is really a claim about sequencing across two calls, not about one function in isolation.)
10. `test_sync_skips_gracefully_when_chromadb_not_installed` (parametrized over both collections) — `monkeypatch.setitem(sys.modules, "chromadb", None)` to force a real `ImportError` on the function's local `import chromadb`, asserting it returns without raising and leaves `sync_state` untouched. Dependency-failure case the ticket didn't list but north-star testing requires ("each dependency failing").
11. `test_sync_is_idempotent_when_run_twice_in_a_row` (parametrized over both collections) — same remote dump fed to `sync_fn` twice back-to-back; asserts the second call imports 0 new ids and `sync_state`'s cursor doesn't regress or duplicate. Covers "repeats" from the misuse checklist.

Run the full suite (`~/.agents/venv/bin/python -m pytest skills/improve/scripts/tests/test_cross_machine_merge.py -v`) before touching `cross_machine_merge.py` to confirm the current baseline (7 tests, all passing against `sync_paper_knowledge` only), and again after the refactor to confirm all 11 tests pass with no regressions to the 5 untouched `run_merge_authority` tests in the same file.

No Decisions section — the ticket fully specifies the design (helper names, signatures, what each function parameterizes) and this is a mechanical, no-behavior-change refactor; there is no open option for the owner to choose between.

## Task List

1. Add `_existing_ids(col) -> set[str]` to `cross_machine_merge.py` (the pagination loop, verbatim logic, extracted once).
2. Replace the inline pagination loop in `sync_research_feed()` with a call to `_existing_ids(col)`.
3. Add `_sync_collection(collection: str, remote_id: str, host: str, sync_state: dict) -> None`, built from `sync_paper_knowledge`'s current body with `"paper-knowledge"` replaced by `collection` in the dump command, `get_or_create_collection`, the `sync_state` key, and all log lines; call `_existing_ids(col)` instead of the inline loop; keep the `# Preserve the remote entry's own source_machine tag...` comment (currently only in `sync_qa_knowledge`) above `new_metas.append(meta)`. Give it a short generic docstring (shared shape, used by both collections) rather than paper-knowledge-specific history.
4. Rewrite `sync_qa_knowledge(remote_id, host, sync_state)` and `sync_paper_knowledge(remote_id, host, sync_state)` as two-line wrappers calling `_sync_collection("qa-knowledge", ...)` / `_sync_collection("paper-knowledge", ...)` respectively; move `sync_paper_knowledge`'s existing historical docstring (the 2026-07-13 `created_epoch`/`.gitignore` note) onto its own wrapper, since that history is specific to paper-knowledge, not the shared helper.
5. Confirm `main()` needs no changes (same call sites, same signatures).
6. Update `test_cross_machine_merge.py`: parametrize the 7 existing sync tests over both collections (tests #1–7 above), add the 4 new tests (#8–11), and fix the module docstring's claim that it only covers `sync_paper_knowledge`.
7. Run the test suite before the edit (confirm baseline) and after (confirm all pass, including the newly-covered `qa-knowledge` path and the 4 new gap-closing tests).
8. Grep the repo for any other caller of `sync_qa_knowledge`, `sync_paper_knowledge`, or the inline pagination pattern outside this file, to confirm nothing else needs updating (expected: none, per the ticket's scope).