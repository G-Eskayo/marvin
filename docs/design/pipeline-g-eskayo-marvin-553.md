## North-star fit

Reuses `skills/research/scripts/academic_search.py:67`'s `search_arxiv()`, which already calls `https://export.arxiv.org/api/query` for the same host — this fix brings `source_monitor.py:21` in line with that existing precedent, no new abstraction. It's the simplest sufficient change: one string literal (`http://` → `https://`) plus one regression test; no retry logic, no new dependency, no new file beyond the test. Token/compute cost: negligible — one extra assertion in a new small test file. Saves against north star 5 ("unattended inputs arrive over authenticated transport"): `fetch_arxiv()`'s `title`/`summary` fields flow verbatim into `research_digest.py`'s `DIGEST_PROMPT`, which runs headless daily via `marvin_launcher` (per `docs/adr/0014-research-colony-event-driven-merge-trigger.md`); over plain HTTP, anyone on the network path could inject text into that unattended prompt. Fixing it leaves the user strictly safer with nothing new for them to do — not a capability trade, a closed hole. No recorded ADR or CONTEXT.md decision argues against this.

I checked the ticket's own "North-star fit" claim (in the collapsed original-ticket text) against the code: it's accurate — `fetch_arxiv()` is indeed the only plain-HTTP call in `source_monitor.py` (confirmed by reading the whole file; `fetch_github()` and `fetch_hackernews()` already use `https://`), and there is genuinely no existing test file for this script (`skills/research-colony/scripts/tests/` only has `test_run_colony.py` and `test_sbir_monitor.py`), so a new `test_source_monitor.py` is required, not a duplicate.

## Tests first (`skills/research-colony/scripts/tests/test_source_monitor.py`, new file)

Following the existing pattern in `test_sbir_monitor.py`/`test_run_colony.py` (sys.path insert for the script dir + `lib/`, then `import source_monitor as sm`, `monkeypatch.setattr`):

1. **`test_fetch_arxiv_requests_an_https_url`** — monkeypatch `sm.urlopen` with a fake that records the URL passed and returns a context-manager object yielding a minimal valid arXiv Atom XML (so the happy path also exercises parsing). Assert the captured URL `.startswith("https://")`. This is the ticket's required regression test and fails if the URL reverts to `http://`.
2. **`test_fetch_arxiv_parses_the_returned_items`** — same fake, assert the returned list has the expected `title`/`summary`/`url`/`source`/`date`/`tags` shape from one well-formed entry — covers "malformed input" only in the sense of confirming the happy path isn't broken by the edit (ticket's own acceptance criterion: still returns items).
3. **`test_fetch_arxiv_on_network_or_tls_failure_returns_empty_list_without_retrying_over_http`** — monkeypatch `sm.urlopen` to raise (e.g., `OSError("TLS reset")`), assert `fetch_arxiv()` returns `[]` and that `urlopen` was called exactly once (no fallback/retry to a second, `http://`, URL). Covers the ticket's "How we'll try to break it" TLS-error case.
4. **`test_fetch_arxiv_on_malformed_xml_returns_empty_list`** — fake `urlopen` returns garbage (non-XML) bytes; assert `[]` and no raised exception — adversarial-input case the ticket's break-list didn't name but the north-star tests-try-to-break-it principle requires (malformed input from the "dependency").
5. **`test_no_plain_http_arxiv_url_remains_in_the_module_source`** — grep-style check reading `source_monitor.py`'s source text and asserting the literal string `"http://export.arxiv.org"` does not appear. This is the ticket's named "grep check" acceptance criterion, made part of the automated suite so it can't silently regress.

No test needs a live network call; `urlopen` is mocked throughout. Verify-fails property: if `source_monitor.py:21` reverts to `http://`, tests 1 and 5 fail without any test file change — satisfying "verify fails when code changes without a test changing."

## Decisions

None. The ticket is fully specified (one-line fix, exact test shape named), nothing is ambiguous, and no recorded ADR/CONTEXT.md decision conflicts with it.

## Task List

1. Edit `skills/research-colony/scripts/source_monitor.py` line 21: change `http://export.arxiv.org/api/query` to `https://export.arxiv.org/api/query`.
2. Create `skills/research-colony/scripts/tests/test_source_monitor.py` with the 5 tests above, run them, confirm all fail against the pre-fix code and pass after the fix (red-green per `tdd` default).
3. Run the full `skills/research-colony/scripts/tests/` suite (plus `skills/research/scripts/tests/test_academic_search.py`, since it touches the same host) to confirm no regression.
4. Manually run `fetch_arxiv()` once by hand (e.g. `python3 -c "import source_monitor; print(len(source_monitor.fetch_arxiv()))"` from the script dir with `lib/` on `sys.path`) against the real network; note the returned item count in the PR description. If a TLS reset occurs against this host (per `paper_graph.py`'s noted flakiness), retry by hand — do not add an http fallback.
5. Open the PR naming issue #553 ("Closes #553"), including the manual-run item count from step 4.