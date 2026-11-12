## North-star fit

Reuses the existing split in `skills/research/scripts/academic_search.py` almost unchanged: `search_semantic_scholar()` / `search_arxiv()` stay single-purpose source fetchers, `main()` stays the only place that aggregates and formats, and `lib/s2_client.get_with_retry()` stays the one retry client (ticket's own fit note already identifies this correctly — confirmed against the code, no correction needed). No new files, no new abstraction: the fix is moving the "swallow to `[]`" behavior that currently lives inside each search function up into `main()`, which is where a "did a source fail" decision belongs since `main()` is the only caller that knows about other sources and formats output. Simplest sufficient approach: let the two search functions raise naturally (removing their blanket `try/except`) rather than inventing a result/error tuple type — `main()` already wraps each source call in its own block today in spirit (two `if` branches), so adding a `try/except` per branch is the smallest change that gives it visibility into failure. Token cost is low (a bounded, mechanical change to one file + its SKILL.md consumer); it pays off by stopping every future research run from silently misreporting "no literature" when S2 is rate-limited — i.e. it leaves the user (and any agent reading the JSON) more capable: they get a correctly-scoped "this source failed" signal instead of a false negative.

No decisions needed — the ticket specifies every string, key name, parameter value, and the exact line 98 replacement verbatim, leaving no genuine open choice for the owner.

## Tests first (`skills/research/scripts/tests/test_academic_search.py`)

From "How we'll try to break it" + acceptance criteria:
1. S2 raises → `main()`'s JSON has `errors.semantic_scholar` with a reason, `arxiv` results still populated (replaces current `test_main_graceful_degradation_when_one_source_fails`'s inverse case).
2. Both sources fail → both named in `errors`, output is still valid JSON (`json.loads` succeeds), process exits 0.
3. S2 responds 200 with no `data` key → `search_semantic_scholar` returns `[]`, no entry in `errors.semantic_scholar`.
4. arXiv returns non-XML (e.g. `"not xml"` body) → `ET.ParseError` propagates out of `search_arxiv`, caught by `main()`, `errors.arxiv` set.
5. A genuinely empty search (both sources return 200 with no matches) → no `errors` key present at all in the JSON.
6. One malformed `<published>` entry among several valid ones → the malformed entry's `year` is `None`, every other entry (including itself) is still returned — `search_arxiv` must not raise on this input.
7. The semantic-scholar `get_with_retry` call is invoked with `max_retries=3`; a direct check that `s2_client.get_with_retry`'s own default parameter is still `8` (guards against the shared default drifting).
8. `--format markdown` prints the `⚠️ ... unavailable (<reason>) — results below are incomplete` line when a source errored, and prints no such line when both sources succeed.

Misuse cases the ticket section didn't spell out, added because they're reachable through this same code path:
9. `search_semantic_scholar` raising with only `--source semantic-scholar` requested → `errors` contains only `semantic_scholar`, no `arxiv` key appears anywhere in the result (confirms the restructuring didn't start always populating both source keys).
10. `resp.json()` raising `ValueError` (malformed JSON body from S2, not just a network exception) → still surfaces as `errors.semantic_scholar`, exercising a non-`requests`-exception failure path through the same `except Exception`.
11. Query string containing special/metacharacters (e.g. `"a&b<c>"`) → passed through to `requests`' `params=` untouched (no manual string concatenation anywhere in this file), confirming no injection surface was introduced by the refactor.
12. `search_arxiv` entry with an empty `<published>` (existing "missing year" case) still returns `year: None` — confirms the new one-line guard (`published[:4].isdigit()`) subsumes the old "missing field" case, not just the "malformed field" case.

Tests against the real collaborator's shape: these all mock only `s2_client.get_with_retry` (the actual network boundary, as the existing suite already does) — never mock `search_semantic_scholar`/`search_arxiv` themselves, so the retry-count and error-surfacing logic run for real.

## Task List

1. `lib/s2_client.py`: no change (confirms default `max_retries=8` stays the shared default — covered by test 7, not a code edit).
2. `skills/research/scripts/academic_search.py` — `search_semantic_scholar()`: remove the blanket `try/except`, let exceptions propagate; pass `max_retries=3` on its `get_with_retry` call.
3. `academic_search.py` — `search_arxiv()`: remove the blanket `try/except`, let exceptions (network, `ET.ParseError`) propagate; leave its `get_with_retry` call's `max_retries` at the shared default (untouched).
4. `academic_search.py` — `search_arxiv()` line 98: replace `year = int(published[:4])` guard with `year = int(published[:4]) if published[:4].isdigit() else None`, keeping it inside the per-entry loop so one bad entry doesn't abort the rest.
5. `academic_search.py` — `main()`: wrap each of the two source calls in its own `try/except Exception`, building an `errors` dict (`{"<source>": str(e)}`) only for sources that actually failed, defaulting that source's result to `[]`, and keeping the existing stderr warning print. Add `results["errors"] = errors` only when non-empty.
6. `academic_search.py` — `_print_markdown()`: print the `> ⚠️ <Source> unavailable (<reason>) — results below are incomplete` line for each entry in `results.get("errors", {})`, before the per-source sections; nothing printed when `errors` is absent/empty.
7. `skills/research/scripts/tests/test_academic_search.py`: update the two existing "`returns_empty_on_error`" tests to assert raising instead of swallowing (the swallow-to-`[]` behavior moves to `main()`), update `test_main_graceful_degradation_when_one_source_fails` to also assert `errors.arxiv`, and add tests 1–12 above.
8. `skills/research/SKILL.md`: under "Source Priority" → "Scientific/academic claims" step 1, add a line instructing agents to check the JSON for an `errors` key, say which source failed, and never report a failed source's missing results as an absence of literature.
9. Run the full test file plus the rest of the repo's Python suite (per `merge-failures-check-disk-and-main-first` / full-suite-before-hand-merge convention) before considering this done.