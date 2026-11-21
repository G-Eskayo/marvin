## North-star fit

- **Reuses before adding:** the whitespace-collapse idiom `" ".join(s.split())` already used in `skills/safety-monitor/scripts/process_quarantine_reviews.py:_clean_note` (generalizing it with a length/limit parameter, not inventing a new idiom); the compact-JSON convention `separators=(",", ":"), ensure_ascii=False` already used at CLI-output boundaries in `lib/gh_merge_guard.py:58` and `lib/deliverable_location_guard.py:67`; and the markdown path's own existing `abstract[:200]` truncation, which this replaces with the configurable call instead of adding a second truncation mechanism. No new files; the only touched files are `skills/research/scripts/academic_search.py` and `skills/research/SKILL.md`.
- **Blocker cleared:** #548 ("silently reports failed sources as empty results") is already merged — current `main()` has `errors` handling, `max_retries=3` on the S2 call, and the fixed arXiv year parse. #549 can proceed on top of it without conflict.
- **Simplest sufficient approach:** one helper (`_clean`), one flag (`--abstract-chars`), one escape hatch (`--full`) that bypasses all of the new shaping and reproduces exactly today's output. No new output schema, no config file, no branching beyond the single `if not args.full` gate.
- **Token cost/savings:** spends a small, bounded diff to one file; saves on every future call. Because `academic_search.py --source both` is a shared utility every `research`/`paper-dive`/`diagnose` invocation reuses, the ~5-9k → ~2-3k cut compounds across future calls rather than being one-off (north star 1, guiding principle "compounding leverage").
- **More capable, not more passive:** triage view keeps title/year/citation-count/URL/link, so the agent can still make a provenance-backed judgment call; full text is one flag away (`--full --limit 3`) when actually needed. Nothing is silently dropped from library callers — `search_semantic_scholar`/`search_arxiv` still return raw data; only `main()`'s CLI output is shaped.
- **Machine:** no machine-specific concern — local script edit + pytest run, no scheduled job, no heavy build.
- **Judgment call, not a Decision:** the ticket's "Purpose" prose mentions dropping `openAccessPdf` too, but the concrete "What to build"/"Acceptance criteria" sections only specify dropping `externalIds` by default. I'm following the concrete spec (drop `externalIds` only) since it's the operative text, not the throwaway motivating prose — not escalating as an owner Decision since the acceptance criteria are unambiguous on this point.
- Ticket's own stated north-star fit (reuse `--full` escape hatch, compounding savings across every future call) checks out against the code as read — no correction needed.

## Tests to write first

In `skills/research/scripts/tests/test_academic_search.py`, network mocked (existing fixture style: `monkeypatch.setattr(s2_client, "get_with_retry", ...)`, `patch.object(sys, "argv", ...)`).

**From "How we'll try to break it":**
1. `_clean`: one 400-char word, limit 300 → hard-cut at 300 chars (no space to break on), still ends in `…`.
2. `_clean(None, limit)` → returns `None`, no crash (mirrors S2 sending `abstract: null`).
3. Non-ASCII title (e.g. `"Über Café"`) survives `main()`'s default JSON path as literal characters, not `\uXXXX` escapes (`ensure_ascii=False`).
4. `--abstract-chars -5` → argparse rejects it (`SystemExit`, exit code 2) via a custom `type=` function, not a post-hoc check.

**From Acceptance criteria (concrete, code-level):**
5. `_clean`: whitespace runs and embedded newlines (arXiv Atom entries) collapse to single spaces.
6. `_clean`: text over the limit ends in `…` cut at a word boundary; text at/under the limit is returned unchanged (byte-identical, no trailing `…`).
7. `--full`: `main()`'s JSON output for a given mocked S2+arXiv response is byte-identical to today's pre-change output — `indent=2`, `externalIds`/`openAccessPdf` present, raw (uncollapsed) whitespace, default `ensure_ascii=True`. This is the regression/equivalence test guarding the escape hatch.
8. `--abstract-chars 0` → a long abstract (over 300 chars) passes through `_clean` untouched, no truncation.
9. Default (no `--full`): JSON uses `separators=(",", ":")`, no `indent`, and `externalIds` is absent from S2 paper dicts.

**Misuse the section didn't name, added per the break-it checklist:**
10. Empty-string abstract (`""`) → `_clean` returns `""`, not `"…"` and no crash (distinct from the `None` case).
11. `--abstract-chars` given a non-integer (`"abc"`) → argparse rejects it (same mechanism as #4, confirms the custom type doesn't swallow the standard `int()` error path).
12. `--full` combined with `--abstract-chars 10` → `--full` wins; output is full/untruncated (a person passing both flags shouldn't silently get truncation).
13. Markdown format with a non-default `--abstract-chars` (e.g. 50) → the printed abstract respects the flag, not the old hardcoded `[:200]`.
14. Interaction with #548's error path: one source fails (empty list via mocked exception) while the other returns a long abstract → `errors` key still present, surviving source's abstract still gets cleaned/truncated correctly (confirms the two tickets' changes to the same `main()` don't fight each other).
15. Default `--abstract-chars` (omitted entirely) behaves as 300 end-to-end through `main()` (sanity check tying the flag default to actual output, not just the argparse spec).

**Explicitly out of scope, with reason:** concurrency/repeats/wrong-permissions/stale-state — not applicable; this is a stateless CLI with no shared state or file writes beyond stdout, one call per process. Non-string title/abstract input (e.g. a dict or number) — not tested; S2 and arXiv's API contracts guarantee `str` or `null` for these fields, so this isn't a scenario that can happen, per "don't add validation for scenarios that can't happen."

No Decisions section — nothing here needs the owner to choose; the ticket is fully specified and the one interpretive call (external fields to drop) is resolved from the ticket's own concrete text, not guessed.

## Task List

1. Add `_clean(s, limit)` to `academic_search.py`: `None` passthrough, `" ".join(s.split())` whitespace collapse, then word-boundary truncation with `…` when `limit > 0` and collapsed length exceeds it (hard-cut with no boundary found, e.g. one long word).
2. Add a local `_nonneg_int(value)` argparse type function (calls `int(value)`, raises `argparse.ArgumentTypeError` on negative) and register `--abstract-chars` with `type=_nonneg_int, default=300`.
3. Add `--full` boolean flag (`action="store_true"`) to the parser.
4. In `main()`, after building `results` (and after the existing `errors` handling from #548), gate on `not args.full`: for each S2 paper, clean `title`/`abstract` via `_clean(..., args.abstract_chars)` only when the key is present (don't introduce the key if absent) and `pop("externalIds", None)`; for each arXiv paper, clean `title`/`summary` the same way.
5. In `main()`'s JSON branch, switch serialization: `args.full` → unchanged `json.dumps(results, indent=2)`; else → `json.dumps(results, separators=(",", ":"), ensure_ascii=False)`.
6. In `_print_markdown`, remove the hardcoded `abstract[:200]`/`summary[:200]` + trailing `"..."` and print the (already-cleaned-or-full, depending on the flag) text as-is, since truncation now happens once upstream in `main()`.
7. Update `skills/research/SKILL.md` step 1 with the ticket's exact guidance line: "Results are trimmed for triage. Re-run with `--full --limit 3` for the papers worth reading."
8. Write the 15 tests listed above in `skills/research/scripts/tests/test_academic_search.py`, following the existing `monkeypatch`/`FakeResponse`/`patch.object(sys, "argv", ...)` fixture style already in that file.
9. Run the full existing test suite (`~/.agents/venv/bin/python -m pytest skills/research/scripts/tests/test_academic_search.py -v`) to confirm no pre-existing test's exact-match assertions break under the new default (compact/no-indent) JSON shape.
10. Run one live `--source both` call, capture real before/after `wc -c` for default vs. `--full` output, and record the measured numbers in the PR body, replacing the ticket's estimated 5-9k→2-3k token figures. If the environment has no network access when this is attempted, state that constraint plainly in the PR rather than fabricating numbers.