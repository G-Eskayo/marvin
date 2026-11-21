## North-star fit

**Reuses:** the source/gather/render split in `lib/morning_brief.py` (`default_sources()`, `gather()` at `lib/morning_brief.py:207-232`, which already tolerates any one source failing without dropping the brief) and the `.built-by` sidecar pattern (`lib/morning_brief.py:310-316`) for the new items artifact. The per-source try/except in `gather()` is exactly the mechanism the ticket's "a feed failing must not drop the whole brief" case needs — no new error-isolation code required, just new sources feeding it. `brief_fallback.py` (Mini/MacBook ownership, ADR 0067) and `output_contracts.py`'s `_brief()`/`_digest()` consumption tracking are left untouched by keeping `<day>.md` + `.read` + `.built-by` as the externally-visible contract; `health_checks.check_brief_builder`, `job_catalog.py`, and `cron_health.py` key off those same two files and need no changes.

**Simplest sufficient approach:** add one new sidecar, `~/.claude/briefs/<day>.json`, holding the selected ≤5 items (section, rank, line, summary, source). `render()` becomes a pure function from items → markdown, so the existing `.md`/`.read`/`.built-by` machinery keeps working unchanged. No new feed is built for World & security or Your day's calendar/weather — CONTEXT.md says those feeds are still unidentified (`koala73/worldmonitor`, "God's Eye", "Pegasus" — all "still to be identified by Gil"), so those two sections legitimately render zero items today, which is the ticket's own "zero candidates" break-case, not a gap to fill here.

**Tokens:** zero model calls added — selection and ranking are pure Python over data MARVIN already fetches (GitHub REST/GraphQL, Health, overrides.json, the two digest files), same as today's `morning_brief.py` (marvin#306's point 1 fit: "costs no model run").

**User impact:** more capable, not more passive — it turns today's one free-text wall of text into ranked, capped, drill-downable items (line → summary → source), which is the ADHD-first mechanism CONTEXT.md asks for ("more on 3" / "put 1 on the mirror" later). Nothing here removes Gil's agency; it reduces what he has to read to decide what to act on.

**Machine:** no change — this is pure library code, built wherever `morning_brief.build()` already runs (Mini primary, per ADR 0067 / #458, already shipped).

## Decisions

A few product-shape questions aren't settled by the ticket or CONTEXT.md and change what Gil actually sees each morning. Rather than guess, these go in the PR as a Decisions block:

```markdown
## Decisions
<!-- marvin:decisions -->
### overnight-fyi: What happens to today's non-actionable "FYI" content (merged PRs, model-run/cost counts, "Waiting on MARVIN" PRs, revisit-agent returns) once the brief is items-only?
- [ ] A: Dropped from the top-level brief entirely — still in the full gather() data for a later "what else?" drill-down, just not rendered until that exists
- [ ] B: Kept as a non-item footer below the five ranked items (like today's "Gaps" line) — visible but never counted toward the five-item cap

### late-night-note: Where does the "Balance" factual nudge (last night's late session) go?
- [ ] A: Drop it from this ticket — CONTEXT.md's four sections don't list it, and it isn't "calendar, deadlines, weather"
- [ ] B: Keep it as a non-item footer outside the five-item cap, same as the "overnight-fyi" footer above
- [ ] C: Fold it into a "Your day" item (counts toward the five-item cap, can be outranked on a busy day)
```

Everything else below is decided and not re-asked: ranking formula, dedup key, and storage shape are ordinary implementation choices I can make and the tests pin down.

## Tests first

One per "How we'll try to break it" case, plus the misuse cases the section didn't spell out. All in `lib/tests/test_morning_brief.py` (existing file, rewritten — the old assertions test the free-text shape the ticket replaces):

1. **Zero candidates** — all sources return empty/None → `select_items()` returns `[]`, `render()` produces a brief with no section bodies (no padding), and `write()` still writes a valid `<day>.json` (`{"items": []}`) and `<day>.md`.
2. **One candidate** — exactly one item anywhere → it is rank 1, appears in its section only, no other section renders.
3. **Hundreds of candidates** — stub a source returning 200 synthetic tickets → `select_items()` never returns more than 5, and selection doesn't hang or blow up on the full input size (a plain sort, no quadratic comparison).
4. **All candidates from one section** — e.g. 20 open PRs and nothing else → still capped at 5 total, all from "Your projects"; other sections absent.
5. **Ties in rank** — two items with identical score → tie-break is deterministic and documented (e.g. stable secondary key such as repo+number or section order), proven by running `select_items()` twice on the same input and asserting identical order.
6. **An item missing a layer** — a source that supplies only a line, no summary/source (e.g. a bare health-check string) → `select_items()` fills the missing layer with an explicit placeholder (not `None`, not a crash), and `render()` doesn't emit `None` or a raw KeyError.
7. **A source with no URL** — e.g. a digest "idea" with no article link → the item's `source` layer renders with `related` ticket links only, no broken `[link]()`.
8. **Duplicate items from two feeds about the same story** — e.g. the same ticket number surfaced by both `top_tickets` and `human_tickets` → dedup keeps one (the higher-scored), proven by asserting the ticket number appears exactly once across all sections.
9. **Huge summary text** — a source returns a 50k-character "summary" → `render()`/the line layer stays one sentence; the summary layer is capped length (symmetrical with `morning_brief.py`'s existing `BRIEF_MAX`/`_cap` pattern in `session_start_report.py`).
10. **Non-English titles** — a ticket/digest title with non-ASCII / RTL text (e.g. Hebrew, per Gil's own Seal Speak work) → renders without mangling or raising (UTF-8 round-trip, no silent `str()`-on-bytes assumption).
11. **Markdown/HTML injection inside a feed title** — a GitHub issue titled `](javascript:alert(1))` or containing `<script>` → the rendered `.md` either escapes it or at minimum doesn't corrupt the surrounding markdown structure (test asserts the known section headers still parse out correctly even when a title contains `##` or unmatched brackets).
12. **A feed failing must not drop the whole brief** — one source raises (existing `test_a_failing_source_is_named_not_hidden` pattern) → the other sections still populate and `missing` is recorded, reusing `gather()`'s existing try/except.
13. **Each dependency failing** — run case 12 for every individual source function (`_gh`, `owner_decisions.fetch`, `stamped.read`, overrides.json missing/corrupt) → brief still builds.
14. **Repeats/idempotency** — `write()` called twice for the same day with different inputs → second call is a no-op (existing `test_write_is_idempotent_against_an_existing_file`, extended to assert the `.json` sidecar is equally untouched).
15. **Concurrency** — two processes call `write()` for the same day "simultaneously" (simulate via monkeypatching the existence check between read and write) → no partial/corrupt `.json` (atomic write, e.g. write-to-temp-then-rename, matching the TOCTOU guard already used in `research_digest.py:160-163`).
16. **Wrong permissions** — `BRIEFS` directory not writable → `write()` raises a clear error rather than silently losing the brief (currently unhandled; add explicit handling or an accepted exception type).
17. **Stale state** — a `<day>.json` left over from a crashed previous run that is valid JSON but missing required keys (e.g. no `"items"`) → `show_today()`/the renderer treats it as "no brief yet" rather than crashing session start.
18. **A person's mistake** — Gil hand-edits `<day>.json` and breaks the JSON → `show_today()` fails closed (logs/skips) instead of taking down `session_start_report.main()`.
19. **Ranking favours active work** (AC-specific) — a hard deadline 2 days out and a p0 ticket both present alongside a routine PR review → both outrank the PR review; same inputs run twice produce the same order (determinism, AC #3).
20. **Never-padded cap holds under the real five-item max** (AC-specific) — exactly 6 strong candidates → exactly 5 ship, the 6th (lowest score) doesn't, and which one dropped is deterministic.
21. **Session start renders from items** (AC-specific) — `session_start_report.main()` with a `<day>.json` present but *no* legacy `<day>.md` → the brief still shows (proving the session-start path reads from items, not a vestigial markdown file) — this test pins down which of `render()`-writes-md-from-items vs. show_today()-reads-md is the source of truth.

## Task List

1. Add `lib/brief_items.py` (or extend `morning_brief.py` directly — decide while implementing based on file size) with the `Item` shape (`section`, `rank`, `line`, `summary`, `source: {url, related}`), the four fixed section names in CONTEXT.md order, and a `to_item(source_key, record) -> Item | list[Item]` mapping for each existing `default_sources()` producer.
2. Write the dedup key function (ticket/PR → `(repo, number)`; text-only items → normalized line prefix) and the deterministic scoring function (red Health > hard deadline by proximity > p0 ticket > p1 ticket > actionable PR review > soft deadline > digest/research idea), both pure and unit-testable in isolation (tests #5, #8, #19).
3. Write `select_items(data: dict, now: datetime) -> list[Item]`: build candidates from `gather()`'s existing output, dedup, score, sort, cap at 5, assign final rank 1..n. Handle missing layers (test #6), oversized text (test #9), non-ASCII/injection-bearing titles (tests #10, #11).
4. Resolve Decision `overnight-fyi` and `late-night-note` into code: either wire the chosen footer rendering or drop that content per the chosen option.
5. Rewrite `render(items: list[Item], now: datetime) -> str` to emit the four CONTEXT.md sections in fixed order, skipping empty ones, plus whatever footer the Decisions above resolve to.
6. Add atomic write for both `<day>.json` and `<day>.md` (temp file + rename) in `write()`, closing the TOCTOU/concurrency case (test #15), and explicit handling for an unwritable `BRIEFS` dir (test #16).
7. Update `write()` to call `select_items()` instead of passing `gather()`'s raw dict straight to the old `render()`, and to persist the items JSON sidecar alongside the existing `.md` and `.built-by`.
8. Harden `show_today()` against a stale/invalid `<day>.json` (tests #17, #18): fall back to "no brief yet" rather than raising, so `session_start_report.main()` can't be taken down by a corrupt sidecar.
9. Rewrite `lib/tests/test_morning_brief.py` for the new items shape (all 21 cases above), removing assertions tied to the old "Needs you / Overnight / Today" free-text sections.
10. Run the full existing suite touching this file (`output_contracts.py`, `health_checks.py::check_brief_builder`, `session_start_report.py` tests) to confirm no regressions from the `.md`/`.read`/`.built-by` contract staying stable.