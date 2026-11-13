## North-star fit

**Reuses:** the optional-override-with-fallback pattern already used by `extract_core_claim`/`classify_continuity` (`chat_fn=None`, computed inline when absent) for the new `find_citation_pairs(..., data=None)` parameter (`skills/paper-dive/scripts/continuity_checker.py:52-56,76-82`); the `by_id` dict `build_continuity_report` already builds (`continuity_checker.py:131`); and the stderr+`sys.exit(1)` diagnostic pattern main() already uses for the empty-report case (marvin#699, `continuity_checker.py:225-229`). No new abstraction, no new file.

**Simplicity:** the fix is a short post-pass over `seed_slugs` after `find_citation_pairs` returns, classifying each pairless seed by one `by_id` lookup — reusing data already in memory, not a new query path or a new module.

**Tokens/resources:** directly serves north star 1 — a `continuity_checker.py` run that finds nothing currently burns the ollama/qwen2.5:14b claim-extraction budget on good seeds only to leave a silent blank for the bad one, and a user re-runs blind. This makes the one wasted run self-explaining and removes a redundant `collection.get` round-trip to ChromaDB.

**Capability:** leaves the user more capable — they get a precise, actionable reason per seed (wrong key vs. correctly-keyed-but-edgeless) instead of guessing between "I keyed it wrong" and "there really are no edges," and SKILL.md stops actively mis-instructing them to key by slug for DOI-seeded graphs.

**Machine:** no execution-target implications — pure local script/doc edit, runs wherever paper-dive already runs.

No ticket-stated fit to correct; the ticket's own stated fit (north star 1, resources) matches the code.

## Decisions

None. The ticket is fully specified (`ready-for-agent`), has no comments, and no open design choice needs the owner — exact message wording is quoted verbatim in the ticket.

## Tests to write first

From "How we'll try to break it" + acceptance criteria, plus misuse cases the section didn't name:

1. **`find_citation_pairs` reuses passed-in `data`** — call with `data=` (a pre-fetched dict) against a collection whose `.get` is call-counted; assert `.get` is called 0 times and pairs are still correct.
2. **`find_citation_pairs` falls back to `collection.get` when `data` is omitted** — call-counted collection, assert exactly 1 call; locks in the "default keeps today's behaviour" requirement so the existing no-`data` tests keep passing unchanged.
3. **`build_continuity_report` calls `collection.get` exactly once per run** (AC) — call-counted fake collection wrapping a real one.
4. **Seed absent from the collection** → stderr line naming the seed and "not in the collection ... key by DOI/arXiv id, or session slug only for no-DOI seeds" (AC + "seeds-json keyed by slug for a DOI-seeded graph" attack).
5. **Seed present, zero linked children** → stderr line naming the seed and "in the collection but nothing links to it ... search-seeded seeds get no edges" (AC).
6. **Seed present whose only children have an unknown `edge_type`** → same "nothing links to it" line, not a crash (attack case).
7. **One good DOI-seeded seed + one absent seed** → report holds only the good seed's pairs; stderr names only the absent seed, no line for the good one (AC).
8. **Empty `seeds-json` (`{}`) through `main()`** → still exits 1 with the existing generic "no citation or reference edges found" message only, no per-seed lines (attack case).
9. **Duplicate seed slugs** passed to `build_continuity_report` (a person's mistake / library-misuse case not in the ticket) → the absent/pairless seed's reason line is printed once, not once per duplicate.
10. **`collection.get` raising** (dependency failure, not in the ticket) → propagates out of `build_continuity_report` uncaught, rather than being silently swallowed.
11. **SKILL.md's `/continuity-check` paragraph** names the id key (DOI/arXiv id, session-slug-only-if-no-DOI) and the search-seeded-seeds-have-no-edges caveat, and no longer contains the old `{slug: title` wording (AC).

Existing tests (`test_find_citation_pairs_uses_both_edge_directions`, `_ignores_unrelated_papers`, `test_build_continuity_report_extracts_and_classifies_pairs`, `_handles_missing_papers`, `test_main_fails_loudly_when_no_pairs_are_found`) must keep passing unmodified — they exercise the no-`data`/multi-pair paths this change must not disturb.

## Task List

1. Add `data: dict | None = None` parameter to `find_citation_pairs`; when `None`, call `collection.get(include=["metadatas"])` exactly as today, else use the passed-in dict directly (`continuity_checker.py:105-120`).
2. In `build_continuity_report`, pass its already-fetched `data` (from the existing `collection.get(include=["documents","metadatas"])` call) into `find_citation_pairs(collection, seed_slugs, data=data)` so no second ChromaDB call happens (`continuity_checker.py:130,143`).
3. After computing `pairs` in `build_continuity_report`, iterate the de-duplicated `seed_slugs` and, for each seed with no entry in `pairs`, print to stderr: `"<seed>: not in the collection (key by DOI/arXiv id, or session slug only for no-DOI seeds)"` if absent from `by_id`, else `"<seed>: in the collection but nothing links to it (search-seeded seeds get no edges)"`.
4. Update `skills/paper-dive/SKILL.md` line 196: replace `` where seeds-json is `{slug: title, ...}` `` with `` where seeds-json is `{id: title, ...}` keyed by paper-knowledge id (the seed's DOI or arXiv id; its session slug only if it had no DOI). Search-seeded seeds have no edges, so they can't be checked. ``
5. Write the 11 tests above in `skills/paper-dive/scripts/tests/test_continuity_checker.py` (new tests only; leave existing ones untouched) plus one reading `SKILL.md`'s content directly for item 11.
6. Run the full `test_continuity_checker.py` suite (and `test_paper_graph.py`, since both touch the same `parent_doi`/`edge_type` metadata contract) to confirm no regressions.