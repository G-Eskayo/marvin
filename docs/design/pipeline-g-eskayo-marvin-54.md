## North-star fit

**Reuses before adding anything new:** `skills/improve/scripts/tests/test_cross_machine_merge.py` (`monkeypatch.setattr(<module>, "CHROMA_PATH", tmp_path)` + a real `chromadb.PersistentClient`) and `skills/research/scripts/tests/test_academic_search.py` (`monkeypatch.setattr(<module>, "<http-fn>", fake)`, file at `skills/<skill>/scripts/tests/test_<module>.py`, run via `~/.agents/venv/bin/python -m pytest`). `correlate.py` and `source_monitor.py` — the two scripts this ticket's research question is actually about — have zero tests that correctly exercise real ChromaDB behavior.

**Why this plan is different, not a retry:** I ran the suite as it sits in this worktree right now (`~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/ -v`) and found the root cause of the regression directly: `skills/research-colony/scripts/tests/test_correlate.py` and `test_source_monitor.py` already exist, but they deviate from the design doc they were supposedly built from — they stub the *entire* `chromadb` module with `MagicMock()` instead of using a real `PersistentClient` against `tmp_path`. That produced two concrete, confirmed bugs:
1. `test_correlate_semantic_similarity_match` and `test_correlate_custom_threshold` configure `mock_client.get.return_value = mock_qa_col`, but `correlate.py:64` calls `client.get_collection("qa-knowledge")`, not `.get(...)`. Since `get_collection` is never configured, it auto-returns an unrelated child `MagicMock`; `qa_col.query(...)` then returns a mock whose `["distances"][0]` is itself a `MagicMock`, `min()` on it raises inside the `try/except` at `correlate.py:98`, `sem_match` stays `""`, and the test's expected match never happens. **0 == 1** confirmed by the failing output.
2. `test_store_items_deduplication` hand-writes `existing_id = "rf-" + "3fc2e44c8e0fa0b6".lower()` as a guess at "the hash of arxiv URL" instead of computing it the way `source_monitor.py:137` actually does (`hashlib.sha256(item["url"].encode()).hexdigest()[:16]`). The guessed hash never matches the real one, dedup never triggers, and the test gets 2 new items instead of 1. **2 == 1** confirmed by the failing output.

This is exactly the failure mode `docs/north-stars.md`'s "Tests try to break it" / ADR 0063 principle warns about: mocking the real collaborator (ChromaDB) hid its actual rules and let a wrong assumption pass review as a "characterization test." The fix is structural, not a tweak: replace the ChromaDB-touching tests with ones that drive a real `chromadb.PersistentClient(tmp_path)` (`monkeypatch.setattr(correlate, "CHROMA_PATH", tmp_path)` / same for `source_monitor`), so `get_collection`/`query`/`update`/hash computation all run for real and can't silently diverge from production code again. The `fetch_arxiv`/`fetch_github`/`fetch_hackernews` tests and the pure `roadmap_match` tests (29 of the 32 current tests) already pass and already mock at the correct boundary (`urlopen`, the actual network edge) — those are kept, not rewritten.

I also found `docs/adr/0070-research-skill-checks-research-colony-feed-first.md` already sitting in the worktree with a **Decisions** section that doesn't use the required format (`docs/agents/decisions-format.md`): it's bolded prose numbered 1/2/3 with no `<!-- marvin:decisions -->` marker and no `### id: question` / `- [ ]` structure. That section would be rejected as `DECISIONS_UNSTRUCTURED` and block approval — this plan replaces it with a compliant one.

**Simplest sufficient approach:** stays inside the ticket's own framing — a research spike whose deliverable is an answer/scoping doc, not a new runtime component. No new `check_colony_feed.py`, no `SKILL.md` wiring in this pass — those stay gated behind Gil's Decisions, as the ticket's open questions require. The only code this plan adds is regression tests that convert the ADR's evidence from prose claims into executable proof — the strongest possible form of "cited evidence, not speculation" (acceptance criterion 1).

**Checked against the code, confirmed correct and kept from the earlier draft:** the ticket suggests reusing `qa_query.py`'s lateral-mode pattern (`skills/qa-agent/scripts/qa_query.py:49-54`). Read directly: that filters on `metadata.get("domain")`, a key `research-feed` items don't have (`source_monitor.py:143-153` sets only `title, url, source, date, published, tags, correlated, matched_topics, source_machine`). What transfers is `correlate.py`'s query-call shape and its distance threshold of 1.1 (`correlate.py:54,93-96`). CONTEXT.md already carries a one-line pointer to ADR 0070 (uncommitted, confirmed via `git diff CONTEXT.md` — correctly worded, keep as-is, just needs to land in the same commit as the ADR).

**Token spend:** cheap — fixing/writing tests against two small, already-read scripts; no new fetch/API/runtime surface. One deliberate new cost: a tiny deterministic embedding function in the test (see below) instead of letting ChromaDB's default `ONNXMiniLM_L6_V2` download a model over the network on first use (confirmed in `chromadb/utils/embedding_functions/onnx_mini_lm_l6_v2.py` — a real network/flakiness risk no existing test in this repo currently exercises, since none call `qa_col.query` against real embeddings yet). This keeps the semantic test exercising ChromaDB's real distance math, offline and deterministic.

**User capability:** closes the scoping question with evidence instead of a guess, and leaves the two scripts anything built in a follow-up ticket depends on with a real safety net instead of a false one (tests that lie about passing because they test a MagicMock, not the code).

## Decisions

<!-- marvin:decisions -->
### scope: Does every `/research` call check research-feed first, or only topics overlapping MARVIN's tracked domains?
- [ ] A: Every `/research` call checks research-feed first (simplest, small fixed cost per call)
- [ ] B: Only when the question's keywords hit `correlate.py`'s `ROADMAP_KEYWORDS` table (cheaper, misses topics outside the tracked list)

### lookback: How far back should the check look in research-feed?
- [ ] A: Only today's items (matches `correlate.py`'s existing `date == today` filter)
- [ ] B: Last 7 days (catches a recent colony find the user hasn't seen yet)

### presentation: When a feed hit is found, what does the research skill do with it?
- [ ] A: Summarize the feed hit and skip the fresh search, with an "I want to search fresh anyway" fallback
- [ ] B: Show the feed hit as "already found by research-colony" and still run the fresh search alongside it

(Mechanism — new sibling script `check_colony_feed.py` reusing `correlate.py`'s connection/threshold pattern, vs. extending `correlate.py` itself — is not a Decision: `correlate.py`'s job is write-back correlation, a read-only query is a different responsibility. Recommendation, not a question for Gil.)

## Tests I will write FIRST

All against a real `chromadb.PersistentClient(tmp_path)` with `monkeypatch.setattr(<module>, "CHROMA_PATH", tmp_path)` — never a `MagicMock` standing in for ChromaDB itself, since that's precisely the class of bug that caused the last regression. For the one semantic-distance test, the collection is created with a tiny deterministic `embedding_function` (e.g. a fixed-length vector built from simple character/keyword features) instead of ChromaDB's network-downloading default, so the test stays offline and fast while still exercising real distance computation. Fault-injection cases (query/update raising) monkeypatch the single method on the real `chromadb.api.models.Collection.Collection` class for that test only — everything else about the client/collection stays real.

Rewrite `skills/research-colony/scripts/tests/test_correlate.py` (keep the 9 passing `TestRoadmapMatch` tests unchanged; replace `TestCorrelateFunction`):
1. **Dependency failure** — `chromadb` import raises → `correlate()` returns `[]`, no crash (`correlate.py:55-59`).
2. **Dependency partially down** — real tmp_path client with no `qa-knowledge` collection created → falls back to keyword-only correlation, no crash (`correlate.py:63-67`).
3. **Empty/missing state** — `research-feed` has no items for today (real, empty collection) → `correlate()` returns `[]`.
4. **Real threshold behavior** — seed `qa-knowledge` (deterministic embedding fn) with one feature-close doc and one feature-far doc, seed `research-feed` with a matching item; assert only the close one correlates at the default threshold of 1.1, and that the exact-same setup correlates both at a looser threshold — this is the real fix for the two tests that broke last time, now driven by real `get_collection`/`query`, not guessed mock returns.
5. **Malformed input** — a `research-feed` item stored with metadata missing `title`/`url` → no `KeyError`, item still processed (`correlate.py:111-114`).
6. **Permission/corruption failure** — monkeypatch `Collection.query` to raise on the real collection → caught, `sem_match` stays `""`, item still returned if it has a keyword match, dropped if it doesn't (`correlate.py:98,101`).
7. **Write failure** — monkeypatch `Collection.update` to raise → caught silently, correlated item still returned to the caller (`correlate.py:106-109`).
8. **Repeats** — calling `correlate()` twice against the same real seeded data doesn't duplicate or corrupt `matched_topics` (reads back via `research_col.get()` after each call).
9. **Person's mistake / stale state** — `roadmap_match("")` and `roadmap_match("no keywords here")` both return `""`.

Rewrite `skills/research-colony/scripts/tests/test_source_monitor.py` (keep the fetcher tests — `TestFetchArxiv`, `TestFetchGithub`, `TestFetchHackernews`, `TestSaveRawCache` — unchanged, they already mock at the right boundary; replace `TestStoreItems`):
10. **Dependency failure** — `chromadb` import raises → `store_items()` returns `0`, no crash (`source_monitor.py:117-121`).
11. **Repeats / dedup** — call `store_items()` once against a real tmp_path client, then call it again with one repeated item + one new item; assert the first call's count and the second call's count (`1` new only) using the **actual** `hashlib.sha256(url.encode()).hexdigest()[:16]`-derived id, not a guessed string — this is the direct fix for the second confirmed regression.
12. **Each fetcher's dependency failure** — unchanged from current passing tests (`monkeypatch.setattr(source_monitor, "urlopen", raiser)` per fetcher) — kept as-is, not rewritten.
13. **Schema-drift regression** — store one item via `store_items()` against the real tmp_path client, read it back with `col.get()`, assert the metadata key set is exactly `{"title","url","source","date","published","tags","correlated","matched_topics","source_machine"}`.

One finding documented, not fixed (out of scope for a spike): `store_items()` (`source_monitor.py:149`) assumes every item dict has `tags` and raises `KeyError` on a malformed item — currently safe only because all three fetchers always populate every key. Goes in the ADR's findings, not patched here.

## Task List

1. Delete the stray uncommitted `verify_research_feed.py` at the repo root — its one-off ChromaDB inspection is superseded by test 13's schema-drift regression test.
2. Rewrite `skills/research-colony/scripts/tests/test_correlate.py`'s `TestCorrelateFunction` class to use a real `chromadb.PersistentClient(tmp_path)` per the pattern above (tests 1–9); leave `TestRoadmapMatch` untouched.
3. Rewrite `skills/research-colony/scripts/tests/test_source_monitor.py`'s `TestStoreItems` class the same way (tests 10, 11, 13); leave `TestFetchArxiv`/`TestFetchGithub`/`TestFetchHackernews`/`TestSaveRawCache` untouched (test 12 is already covered there).
4. Run `~/.agents/venv/bin/python -m pytest skills/research-colony/scripts/tests/ -v` and confirm all pass (0 failures) — these are regression/characterization tests of existing behavior, not new functionality, so a failure here means a wrong assumption, not a bug to patch in production code.
5. Rewrite `docs/adr/0070-research-skill-checks-research-colony-feed-first.md`: keep its Context/Lateral-mode-design/Evidence sections (already accurate — the qa_query.py domain-key claim checks out against code), replace its non-compliant Decisions section with the one above (`<!-- marvin:decisions -->` / `### id: question` / `- [ ]` format), add the documented-not-fixed `store_items` tags-KeyError finding, and update the evidence citations to point at the new real-ChromaDB test files (not "code inspection").
6. Leave the existing uncommitted `CONTEXT.md` one-line pointer to ADR 0070 as-is (already correct — verified via `git diff`); it lands in the same commit as the ADR.
7. Carry the Decisions section verbatim into the PR body per `docs/agents/decisions-format.md`.
8. State the explicit recommendation (acceptance criterion 3) in the ADR and PR description: this ticket's deliverable — the ADR plus a correct (real-ChromaDB) regression-test suite for `correlate.py`/`source_monitor.py` — is complete now, independent of the Decisions' answers; building `check_colony_feed.py` and wiring it into `skills/research/SKILL.md`'s Process step 1 is deferred to a follow-up ticket scoped by whichever options Gil picks.