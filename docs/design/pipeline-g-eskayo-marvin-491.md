## North-star fit

Reuses `lib/s2_client.py`'s `get_with_retry`, `s2_id`, `S2_PAPER_BASE` exactly as `skills/paper-dive/scripts/paper_graph.py` already does (`paper_graph.py:19-23`, its `fetch_neighbors_from_s2`/`_fetch_seed_abstract` call sites) — same import preamble, same exception-catch-and-degrade shape `fetch_arxiv_pdf_text` (`paper_graph.py:65-109`) already uses ("network error → gracefully degrade, don't crash"). No new library, no new retry logic: `fetch_related.py` is the one S2 caller in the folder that skipped the pattern its sibling file already established. Simplest sufficient approach — wire the existing client in, add a module-level `failures` list and one warning line, nothing more. Token cost: slightly higher per *failing* run only (backoff sleeps replace an instant empty return), near-zero on the common clean-run path; this is a reliability/honesty fix, not a cost optimization, so spending a bit of time under contention to avoid a silent wrong answer is the correct trade under north star 3. Human-experience fit (north star 3) directly: today a 429 hands back an incomplete list dressed up as complete, or a traceback; after this, the command either gets the data or says plainly what it couldn't reach — the user stays in control of whether to trust/retry, which is "more capable," not "more passive."

No Decisions needed — the ticket is fully specified (`ready-for-agent`, no comments, no open design branches); every behavior below is pinned by the ticket text itself.

One correction to the ticket's own `S2_BASE` carry-over: since `S2_PAPER_BASE` (imported) is byte-identical to the current local `S2_BASE + "/paper"`, I'll drop the now-redundant local `S2_BASE` constant and point both `s2_paper_by_doi` and `s2_search` at `S2_PAPER_BASE`, matching `paper_graph.py`'s own usage — avoids keeping two names for the same URL.

## Tests first (`skills/paper-dive/scripts/tests/test_fetch_related.py`, HTTP layer monkeypatched, no network — same style as `test_paper_graph.py`'s `monkeypatch.setattr("requests.get", fake_get)` / `_FakeResponse`)

Setup: an autouse fixture that does `fetch_related.failures.clear()` before each test, since `failures` is module-level mutable state.

From the ticket's acceptance criteria / "How we'll try to break it":
1. Persistent 429 on `s2_search` (or doi lookup) exhausting `get_with_retry`'s own backoff (monkeypatch `requests.get` to always return 429, `time.sleep` to a no-op, like `test_get_with_retry_gives_up_after_max_retries`) → warning line present, process returns normally (no raised exception), exit 0.
2. `s2_paper_by_doi` raising via a mocked `get_with_retry` that returns a 429 response directly is impossible (it always raises on exhaustion) — cover the *other* half explicitly: mock `fetch_related.get_with_retry` to raise `requests.ConnectionError` directly (fast path, no backoff timing) → caught, no crash, failure recorded.
3. `ConnectionError` raised from `get_with_retry` specifically during the DOI lookup → no crash, `failures` contains an entry whose source is `"DOI lookup"` (and the printed warning names it).
4. Clean run (`get_with_retry` and `requests.post` all succeed) → no warning line in output, `failures` empty.
5. `s2_recommendations`'s POST returns HTTP 500 (`resp.status_code == 500`, no exception raised by `requests.post` itself) while `s2_search` succeeds → `all_supporting` still has the search results, warning names `"recommendations"` only.
6. `s2_search` returns `status_code == 200` with `resp.json()` raising (malformed JSON) → treated as a failure (recorded, empty list returned), not a crash. Same shape test repeated for `s2_recommendations`'s malformed-JSON case, since it parses JSON independently of `get_with_retry`.

Additional misuse not already covered, per the "try to break it" checklist in the repo's north stars:
7. All three S2 calls fail simultaneously *and* `arxiv_search` also returns `[]` (mock it to raise/return empty) → `main()` still completes, prints an empty "Supporting / Extending" section plus the warning naming all three sources, no crash, no `IndexError`/`ZeroDivisionError` from `fmt_paper`/`rank_papers` over an empty list.
8. Calling `main()` twice in the same process (two `sys.argv` invocations via direct call, first run failing, second run clean) → second run's output has **no** warning line, proving `failures` is reset at the top of `main()` rather than leaking across invocations (this is the concrete regression the module-level-list design invites if not handled — I'll add `failures.clear()` as the first statement in `main()` and this test pins it).
9. Existing no-input behavior preserved: no `--doi`/`--title`/`--slug`/keywords → still prints the `ERROR:` message to stderr and `sys.exit(1)`, unaffected by the new failure-tracking code (regression guard, since `main()` is being edited).
10. Malformed DOI-shaped input that *is* arXiv-shaped (e.g. `"2503.03704"`) still goes through `s2_id()` and gets `ARXIV:`-prefixed rather than `DOI:`-prefixed, matching `paper_graph.py`'s existing handling — regression guard for the `s2_id()` swap-in itself (not a new behavior, but the ticket explicitly calls out this as the reason for the swap, so it needs its own assertion on the captured URL, same technique as `test_fetch_neighbors_from_s2_uses_arxiv_prefix_for_arxiv_shaped_seed`).

Concurrency/permissions/stale-state: out of scope for a finding — this is a one-shot CLI subprocess (one `failures` list per process lifetime), never imported into a concurrent or long-lived context, so no locking is warranted (elegant sufficiency); noting this rather than silently skipping it.

## Task List

1. Edit `skills/paper-dive/scripts/fetch_related.py`: add the `sys.path[:0] = [...]` preamble and `from s2_client import get_with_retry, s2_id, S2_PAPER_BASE` import, matching `paper_graph.py:19-23`. Remove the now-redundant local `S2_BASE` constant.
2. Add module-level `failures: list[tuple[str, str]] = []`.
3. Rewrite `s2_paper_by_doi` to call `get_with_retry(f"{S2_PAPER_BASE}/{s2_id(doi)}", ...)`, catching `requests.RequestException` (via the existing `get_requests()` helper, for the exception type) and JSON-decode errors, appending `("DOI lookup", reason)` to `failures` and returning `None` on either.
4. Rewrite `s2_search` the same way against `S2_PAPER_BASE`, with source label `"search"`.
5. Wrap `s2_recommendations`'s existing POST in try/except for `RequestException`, add an explicit non-200 status check, and a JSON-decode guard — all three failure modes append `("recommendations", reason)` and return `[]`.
6. In `main()`: `failures.clear()` as the first statement; after building `lines` and before appending `"## Supporting / Extending"`, insert the warning line (`> Semantic Scholar unavailable (<joined source: reason pairs>): results below are arXiv-only`) directly under the `# Related Papers` heading when `failures` is non-empty.
7. Edit `skills/paper-dive/SKILL.md` line ~223: replace "free, no key required for basic use" with "free but rate-limited (shared anonymous pool); calls go through `s2_client.get_with_retry`, and `S2_API_KEY` is used if set".
8. Write `skills/paper-dive/scripts/tests/test_fetch_related.py` covering the 10 cases above, following `test_paper_graph.py`'s monkeypatch/`_FakeResponse` style and sys.path setup.
9. Run `~/.agents/venv/bin/python -m pytest skills/paper-dive/scripts/tests/test_fetch_related.py -v` and the existing `test_paper_graph.py` suite (regression check on the shared `s2_client` import path) before calling this done.