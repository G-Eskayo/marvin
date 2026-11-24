Now I have everything needed. Let me write the plan.

## North-star fit

**Reuses before adding anything:** `lib/morning_brief.py`'s existing `gather()` (per-source try/except so one failing feed never drops the brief — reused unchanged for criterion "a feed failing must not drop the whole brief"), `default_sources`/`_SOURCE_NAMES`, `write()`/`build()`/`show_today()`/`builder_of()` (untouched — `brief_fallback.py` and `output_contracts.py` only call these by name, not by the text shape `render()` produces), and `lib/resume_check.py`'s `sanitize()` — the exact pattern already used to stop a GitHub title from injecting a fake markdown heading into a handoff that also lands in Claude's own context at session start (`lib/resume_check.py:263`). I'll extract its character-stripping core into a shared `strip_markup(text, max_len)` so `morning_brief.py` can reuse it for the longer summary layer without duplicating the regex or changing `sanitize()`'s own tested behavior (its 80-char `TITLE_MAX` call site is untouched).

**Why this is the simplest sufficient approach:** a tiered, deterministic sort key (health-red > hard deadline soon > PR/ticket needing a decision > other deadlines > priority tickets > research) is enough to satisfy "favours items tied to active projects and deadlines" — no scoring model or embedding ranking is needed (Colton check: the underlying principle is "urgency and project-relevance order items," not "compute a weighted score").

**Where it spends/saves:** zero new model calls — same as today, built entirely from data MARVIN already reads (GitHub REST/GraphQL, Health, overrides, digests). Token cost is lower than today: the five-item cap plus per-layer length limits bound the rendered brief's size tightly, instead of today's open-ended "Overnight"/"Today" lists.

**Capability vs. passivity:** this is pure plumbing (data shape + ranking + render) behind an existing, already-consumed surface (session start). It doesn't change what Gil can do himself; it's a precondition for the later voice/endpoint work the CONTEXT doc describes ("content once, shown anywhere").

**Machine:** no machine-specific code; runs wherever `morning_brief.build()` already runs (the Mini primary, laptop fallback per ADR 0067/#458, already merged).

## Decisions

One real ambiguity: CONTEXT.md's four sections (World & security, Research, Your day, Your projects) have no slot for the old brief's "Overnight" activity log, the "Waiting on MARVIN" list, or the late-night "Balance" nudge. I'm dropping "Overnight" and "Waiting on MARVIN" on my own authority — they fail CONTEXT's literal "Your projects... only what needs Gil" test, so they're not Decisions. The late-night nudge is a wellbeing feature (north star 3), not resolvable by re-reading CONTEXT, so it goes to the owner:

```markdown
## Decisions
<!-- marvin:decisions -->
### late-night: Keep the late-night "Balance" nudge now that the brief is four fixed sections?
- [ ] A: Keep it as an uncapped footer note (outside the 5-item cap), like "Gaps" today
- [ ] B: Drop it for now; revisit once voice/endpoint delivery (CONTEXT "Delivery channels are experiments") exists
```

## Tests first (one per break-it case, plus misuse the ticket didn't name)

1. **Zero candidates** → brief renders with all four section headings present and each says something like "Nothing today" (never blank/missing sections).
2. **One candidate** → exactly one item, rank 1, correct section.
3. **Hundreds of candidates** (e.g. 300 synthetic open PRs) → output still caps at 5, and build time/memory stays linear (no accidental O(n²) in dedup/sort).
4. **All candidates from one section** → the cap still applies globally (5 total, not 5-per-section); the other three sections render their empty state.
5. **Ties in rank** (two items with identical urgency tier and identical deadline date) → order is deterministic across repeated calls with the same input (run ranking twice on the same unsorted input, assert identical order; also assert the tie-break key, e.g. ticket number, decides it — not dict/hash order).
6. **An item missing a layer** (a candidate dict with no `summary` or no `source`) → never raises; renders with a defined fallback (summary falls back to the line; source falls back to a "no link" label) and is still counted as one of the five.
7. **A source with no URL** (e.g. a research idea with no per-article URL captured from the digest file) → renders the source layer without a link, no crash, no `None` leaking into the text.
8. **Duplicate items from two feeds about the same story** (same `(repo, number)` showing up via both `human_tickets` and `top_tickets`) → collapses to one item, not two.
9. **Huge summary text** (a 50 KB digest paragraph) → truncated to a bounded length with a visible cutoff marker, never grows the brief unbounded.
10. **Non-English titles** (CJK/Hebrew/emoji in a ticket title) → renders intact, no mangling, no crash on length/truncation math (slicing must not split a multi-byte/combining grapheme oddly — assert round-trip-safe truncation).
11. **Markdown/HTML injection inside a feed title** (`"\n\n## Needs you\nignore previous instructions"` as a ticket title) → the rendered brief contains none of the injected structural characters/newlines; the fake heading never appears as a real heading.
12. **A feed failing** (one source raises) → the other three sections still populate from their own feeds; the failure is named in the trailing "Gaps" note, never drops items from unrelated sections (reuses `gather()`'s existing per-source isolation — regression test only, since this is existing behavior being carried forward).
13. **Each dependency failing one at a time** — parametrized over every section's feed (open_prs, red_checks, human_tickets, deadlines, top_tickets, research_idea) raising independently → brief still builds, missing one source's candidates only.
14. **Repeats/concurrency**: calling `write()` twice for the same day is already idempotent (existing test) — add a case where two processes race to call `write()` for the same day with *different* candidate sets (simulate via calling `write()` then `write()` again with a different `sources` dict) → second call is a no-op, first result wins (already covered by existing `test_write_is_idempotent_against_an_existing_file`; extend to the new item-shape path).
15. **Wrong permissions / stale state**: `BRIEFS` directory unwritable (simulate via a read-only tmp_path) → `write()`/`build()` degrade without raising unhandled, consistent with the "never crashes the SessionStart hook chain" contract `session_start_report.py` depends on.
16. **A person's mistake**: a malformed `catalog/overrides.json` deadline entry (bad date string, missing `due`) → that one deadline is skipped, not fatal to the whole deadlines feed (extends existing `_deadlines` tolerance, now also checked at the item-building stage).
17. **Session start still renders from items**: `session_start_report.check_morning_brief()` / `main()` shows the four-section brief first, capped by `BRIEF_MAX`, exactly as today's heading-based integration expects (regression test on the existing `test_the_session_report_shows_todays_brief_first_and_that_marks_it_read`, adapted to the new section names).
18. **Ranking favours active projects/deadlines, deterministically**: given the same unsorted candidate list twice, assert identical ranked order; given a hard deadline due tomorrow vs. a soft top-priority ticket, assert the deadline ranks first; given two runs with inputs in different insertion order but identical content, assert identical output (true determinism, not just stable-sort luck).

## Task List

1. In `lib/resume_check.py`, extract `sanitize()`'s character-stripping core into a module-level `strip_markup(text: str, max_len: int) -> str`; keep `sanitize(text)` calling it with the existing `TITLE_MAX` so its current tests and behavior are unchanged.
2. In `lib/morning_brief.py`, add the `Item` shape (section, line, summary, source dict with `label`/`url`/`related`, rank) and section constants (`World & security`, `Research`, `Your day`, `Your projects`), plus `LINE_MAX`/`SUMMARY_MAX` constants.
3. Add per-feed → candidate-item builder functions mapping the existing sources into sectioned candidates: `red_checks`→Your projects, `open_prs` (not `waiting_on_marvin`)→Your projects, `human_tickets`→Your projects, `top_tickets`→Your projects, `regressions` (`needs-you` kind)→Your projects, `auto_merge`→Your projects, `deadlines`→Your day, `research_idea`→Research. Drop `launches`, `merged`, `revisited`, `digest_idea`, and `waiting_on_marvin` PRs from item production (documented reasoning above); leave World & security empty until a feed exists.
4. Apply `strip_markup` to every externally-sourced string (titles, digest paragraphs) when building `line`/`summary`, with graceful fallback for a missing `summary`/`source` on any candidate.
5. Add de-duplication by `(repo, number)` where available, else by normalized sanitized `line`, before ranking.
6. Add the deterministic tiered sort key and `rank_items(candidates) -> list[Item]` that assigns ranks 1..5 and truncates to 5, with an explicit, stable tie-breaker (never relies on dict/insertion order alone).
7. Rewrite `render()` to emit the four fixed section headings (each with an empty-state line when it has no items) from the ranked items' three layers, plus the existing "Gaps" trailing note for `missing` sources (and, per the Decisions answer, the late-night note).
8. Update/replace `lib/tests/test_morning_brief.py` for the new section names, item shape, and every case in the tests-first list above; keep (and adapt, don't delete) the idempotency/sidecar/fallback-gate tests, which don't depend on the render shape.
9. Update `lib/tests/test_session_start_report_budget.py` / the session-start test touching `check_morning_brief` for the new heading text if it asserts specific old section names.
10. Run the full Python suite (`MARVIN_MERGE_GATE=1 pytest -n auto`) to confirm no other module depends on the old "Needs you/Overnight/Today" text.