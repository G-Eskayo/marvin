## North-star fit

**Reuses:** `gather()`'s per-source fault-isolation loop (`lib/morning_brief.py:222-232`, each source wrapped in try/except, failures collected into `missing` instead of killing the whole build) — the exact mechanism the ticket's "a feed failing must not drop the whole brief" needs, so I extend it rather than inventing a new fan-out. Reuses the existing readers `_open_prs`, `_red_checks`, `_human_tickets`, `_deadlines`, `_top_tickets`, `_digest_idea`, `_research_idea`, `_regressions`, `_auto_merge_report` unchanged — only what *consumes* their output changes. Reuses `write()`/`build()`/`show_today()`/`brief_dates()`/`read_dates()`/`builder_of()`'s existing public shape (consumed by `session_start_report.py:484-487`, `health_checks.py:1799-1808`, `output_contracts.py:125-135`) so none of those callers need to change. Reuses the idempotent-write + `.built-by` sidecar pattern (`write()`, `lib/morning_brief.py:299-316`) and the fallback-gate call in `build()` (`lib/morning_brief.py:319-329`) verbatim.

**Simplest sufficient approach:** one new small pure module (`lib/brief_items.py`) holding the item shape, sanitization, dedup, deterministic ranking and section rendering — no network/filesystem I/O, so it's cheaply unit-testable without mocking `gh`. `morning_brief.py` only changes what its source functions *return* (pre-built items instead of raw blobs) and how `render()` groups them. No new scheduling, no new storage backend, no new service.

**Token/resource cost:** no model calls added (brief build already costs zero LLM tokens, kept that way — north star 1); ranking is O(n log n) in-process Python over at most a few hundred candidates.

**Capability, not passivity:** the five-item cap and per-item line/summary/source layers mean Gil gets a short, scannable brief, with "why it matters" and a real source one layer down — fewer things to wade through, not less information available if he wants it.

**Scope cuts I'm making, explicitly called out (not owner Decisions — directly implied by the ticket's own closed scope):**
- The brief's four sections are **World & security, Research, Your day, Your projects** — nothing else. The current brief's "Overnight" (model-run counts, merged PRs, "returned from hold") and "Balance" (late-night nudge) don't fit any of the four sections and don't need Gil's action, so they're dropped from the brief along with their now-dead reader functions (`_launches`, `_merged`, `_revisited`, `_late_night`) and tests. This is a visible behavior removal — flagging it plainly here rather than silently; Health/Vitals remain the place for that operational info (lexicon: Workshop vs Vitals split).
- `_auto_merge_report()`'s "switch on auto-merge" line and `_regressions()`'s `needs-you` lines move into **Your projects** (they're project decisions/breakage); `_regressions()`'s `fixed` kind is dropped from the brief (nothing needed from Gil).
- "World & security" has no wired feed yet (World Monitor/God's Eye View integration is future work per #468/#469's resolutions, not yet built) — its candidate source returns `[]` today. That's not a gap in this ticket: "a quiet day has fewer and nothing pads it" explicitly covers a whole section being empty.
- Per-item safety-check and the held-back list are **#463**, not this ticket. Cross-machine delivery to both Macs is **#464**. Fixing the research-digest bullet-format/merged-vs-Mini bugs is **#459** — I carry `_digest_idea`/`_research_idea` forward unchanged (same known limitations), wrapped as one `research` item.
- Calendar/weather for "Your day" is **#673** (still `needs-info`, not built) — "Your day" for now surfaces only deadlines from `overrides.json`, which is the one "day" feed that already exists.

## Tests written first

New file `lib/tests/test_brief_items.py` (pure logic, no mocking needed):
1. Zero candidates → `rank_and_cap([])` is `[]`; `render_sections([])` produces no section headers, no padding.
2. One candidate → single item, rank 1, correct section shown.
3. Hundreds of candidates (synthetic, mixed tiers) → output length is exactly capped at 5.
4. All candidates from one section → only that section's header appears; others absent.
5. Ties in tier/order_key → deterministic stable order (earlier-inserted item wins); repeated runs on freshly-built identical input give identical output (the acceptance criterion's determinism, tested directly).
6. An item built without `summary`/`url` (`make_item(..., summary=None, url=None)`) still has non-None `summary` (defaults to the line) and a `source` dict with `url: None, related: []` — never a missing layer.
7. Source with no URL renders as plain text, never a literal `None` or a dangling `(None)` link.
8. Duplicate items from two synthetic "feeds" (same normalized title or same URL) → only the higher-ranked one survives and counts once toward the 5-item cap.
9. A 5000-character summary is truncated to a bounded length at construction; a very long line is truncated for the rendered bullet.
10. A non-English (Hebrew/CJK/emoji) title passes through intact, unmangled, non-crashing.
11. A title containing `evil](http://attacker.example)` / raw `<script>` is sanitized so the rendered bullet cannot inject a second markdown link or raw HTML (brackets/angle-brackets neutralized).
12. An item candidate with an empty/blank `line` is rejected by `make_item` (never reaches rendered output as a blank bullet).
13. A near hard-deadline item and a generic research-idea item both compete for the last of 5 slots → the deadline item wins (ranking favours projects/deadlines).

New/updated in `lib/tests/test_morning_brief.py` (rewritten for the new shape — the old "Needs you/Overnight/Today/One idea each/Balance" tests are replaced since that structure is gone):
14. A feed-failing scenario (one candidate-builder raises) still produces a brief with the other sections' items and a Gaps note naming the failed feed (adapts the existing `test_a_failing_source_is_named_not_hidden` pattern to the new shape).
15. `write()` stores items as structured data: a `<day>.json` sidecar exists after `write()` with `section`, `rank`, `line`, `summary`, `source` on every item (the literal "stored as items" acceptance criterion).
16. `show_today()` / the rendered `.md` is generated from those same items (not a separate free-text path) — session start shows the brief rendered from the items (acceptance criterion).
17. `write()` called twice the same day doesn't overwrite (idempotency — adapt existing test to new content).
18. `write()` records who built it (existing `.built-by` sidecar test, unchanged behavior, adapted fixtures).
19. `build()` still checks the fallback gate with `usual_hour=9, usual_minute=15` (existing tests, adapted fixtures only).
20. A corrupted/partial `<day>.json` (stale or malformed from an earlier crashed write) doesn't crash `show_today()`/rendering — treated as "no stored items," mirroring the existing `stamped.read` defensive-read pattern already used for `HEALTH_STATUS` in this same file.
21. Concurrent/repeat `write()` calls for the same day (two processes) — covered by the idempotency check (#17) plus the existing TOCTOU-safe pattern already used in `research_digest.generate()`, reused rather than reinvented.

Update in `lib/tests/test_incident_ladder.py`: `test_the_morning_brief_says_what_the_ladder_did` currently calls the old flat-dict `render()`. Rewrite it to build a `needs-you` regression candidate item via the new builder and assert it surfaces under "Your projects"; drop the "fixed" assertion since fixed-kind regressions no longer reach the brief (documented scope cut above).

## Decisions

None — the open design choices (feed→section mapping, tier ordering, dropping Overnight/Balance) are resolved above as implementation judgment calls explicitly delegated to day-one by CONTEXT.md ("day one, items rank by fit... After that MARVIN also learns"), not owner-level tradeoffs with real competing options.

## Task List

1. Add `lib/brief_items.py`: `SECTIONS`/`SECTION_LABELS` (fixed order: world_security, research, your_day, your_projects), `sanitize()` (collapse whitespace/control chars, escape `[`/`]`/`<`/`>`, truncate with bound), `make_item()` (guarantees all three layers present, rejects empty `line`), `_dedup_key()`, `rank_and_cap()` (stable sort by tier/order_key/insertion index, dedupe, cap at 5, assign `rank`), `render_sections()` (markdown bullets grouped by fixed section order, skipping empty sections).
2. Write `lib/tests/test_brief_items.py` covering items 1–13 above; implement `brief_items.py` against them.
3. In `lib/morning_brief.py`, replace the old raw-data source functions feeding `render()` with item-returning builders per section:
   - `your_projects`: red checks (tier 0), PR-needs-review (tier 1), human tickets (tier 1), regressions filtered to `needs-you` (tier 0), auto-merge decision line (tier 1), top tickets by priority (tier 2), daily-digest idea (tier 3).
   - `your_day`: deadlines, tier by urgency (hard + ≤7 days highest).
   - `research`: research-digest idea (tier 2).
   - `world_security`: returns `[]` (no feed yet).
4. Rewrite `gather()` to call each builder inside the existing try/except-and-collect-missing loop, concatenate all returned items, and call `brief_items.rank_and_cap()`; rewrite `render()` to emit `# Morning brief, <day>` plus `brief_items.render_sections(items)` plus a Gaps footer from `missing`.
5. Update `write()` to also persist `<day>.json` (the items store) alongside the existing `.md` and `.built-by` sidecar; add `read_items(now)` for future tickets (#463/#467) to consume; make `show_today()`/render path defensively tolerate a corrupted/missing `<day>.json`.
6. Delete now-dead `_launches`, `_merged`, `_revisited`, `_late_night` and their `default_sources`/`_SOURCE_NAMES` entries (Overnight/Balance dropped per scope above); remove their now-obsolete tests.
7. Rewrite `lib/tests/test_morning_brief.py`'s brief-content tests (items 14–20 above) against the new shape; keep the plumbing tests (idempotency, sidecar, fallback-gate) with fixtures updated to the new source-function shape.
8. Update `lib/tests/test_incident_ladder.py`'s single `morning_brief.render()`-dependent test to the new item shape.
9. Run the full Python suite (per CLAUDE.md's "full suites before a hand-merge") to confirm no other consumer of `morning_brief` broke.