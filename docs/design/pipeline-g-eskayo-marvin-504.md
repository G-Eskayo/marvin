## North-star fit

**Reuses:** The file's own "Source Hierarchy for Related Papers" section (`skills/paper-dive/SKILL.md:221-226`) is already correct — it lists only Semantic Scholar and arXiv, no scihub, and already matches what `fetch_related.py` does. This ticket's three edits just bring the `/pull-related` command doc (line 136), the L4 section (line 76), and the frontmatter `description` (line 3) into line with that already-correct section and with `fetch_related.py`'s actual printed output (`## Supporting / Extending` / `## To Explore for Contradictions / Challenges`, confirmed by reading the full script) — no new pattern invented.

**Simplest sufficient approach:** three one-line prose edits in one file, zero code changes (ticket says explicitly "No change to `fetch_related.py`"). Verified current state first — the frontmatter still says `scihub.org` and line 136 still says `3–5 papers that contradict or challenge it`, so both acceptance-criteria `rg` checks fail today; the fix is exactly these three edits, nothing more and nothing less.

**Tokens:** negligible — a documentation-only patch, no runtime cost, no new dependency, no model calls.

**User benefit:** north star 3 — the command's documented promise now matches what the user actually gets back when they run `/pull-related`, so they aren't surprised by two features (a third source, contradicting papers) that were never real.

**Out of scope, by design:** the issue's `## Recurrence check` ("Probe: none yet: add one counting source names listed in paper-dive/SKILL.md that fetch_related.py never calls") is outside the ticket's "What to build" and "Acceptance criteria" sections, which are the authoritative scope here (same reasoning applied in `docs/design/pipeline-g-eskayo-marvin-488.md`'s "Out of scope, by design" note for an analogous ticket). It also doesn't fit the registered shape: every entry in `lib/purpose_metrics.py`'s `PROBES` dict (`_replanned_tickets`, `_prd_dispatches`, `_mirror_failures`, etc., lines 102-442) counts timestamped events in an existing log over a rolling day-window; "diff the source names in a doc against the function calls in a script" is a one-time static check, not a recurring log metric, so it doesn't slot into that pattern without its own design (where it lives, what triggers it, how a static-text probe gets a `days`/`now` window). Per CONTEXT.md (lines 1802-1806), a Recurrence check must be "registered code in `lib/purpose_metrics.py` `PROBES`, never ticket text" — building something ad hoc here to satisfy ticket prose would violate that decision, not satisfy it. Flagging for a follow-up ticket rather than guessing at a design now.

**Decisions:** none needed — the three replacement texts are given verbatim or near-verbatim by the ticket, and the acceptance criteria are unambiguous `rg` checks. No owner choice to surface.

## Tests to write FIRST

This is a docs-only change (ticket: "How we'll try to break it: Docs-only: exempt") — there is no code path, so none of the standard misuse categories (bad/huge/malformed input, dependency failure, concurrency, permissions, stale state) apply; there's no `requests` call, no file I/O, no script logic touched. Verification is direct inspection via the three `rg` acceptance criteria themselves, which double as the "tests":

1. `rg -n -i "scihub" skills/paper-dive` → no output (currently fails: line 3 has `scihub.org`).
2. `rg -n "contradict or challenge it" skills/paper-dive/SKILL.md` → no output (currently fails: line 136).
3. Manual check: after edit, every bullet under `/pull-related` (lines 134-139) maps to a section `fetch_related.py` actually prints — "support or extend" → `## Supporting / Extending`; the new `/challenge` line → `## To Explore for Contradictions / Challenges` (script lines 241-243). No scihub or "contradict... it" claim remains anywhere else in the file (checked once by re-reading the full file after edit, not just the two `rg` lines, since a stray mention elsewhere wouldn't trip criteria 1/2 if phrased differently).

No pytest test is warranted for a single prose line — matching the precedent in `docs/design/pipeline-g-eskayo-marvin-488.md` ("no existing precedent in this repo for pytest-asserting on skill markdown prose, and inventing one for a single doc line isn't warranted").

## Task List

1. `skills/paper-dive/SKILL.md` line 3 (frontmatter `description`): change "Pulls related papers from Semantic Scholar / arXiv / scihub.org." to "Pulls related papers from Semantic Scholar / arXiv."
2. `skills/paper-dive/SKILL.md` line 76 (L4 section): change "Run `scripts/fetch_related.py` to pull supporting and contradicting papers." to "Run `scripts/fetch_related.py` to pull supporting papers, then `/challenge` for contradicting ones."
3. `skills/paper-dive/SKILL.md` line 136 (`/pull-related` section): replace the bullet "- 3–5 papers that contradict or challenge it" with a line stating contradicting/challenging work is not fetched here and comes from `/challenge` instead, worded to match `fetch_related.py`'s own `## To Explore for Contradictions / Challenges` output (script lines 241-243).
4. Run the three acceptance-criteria checks (`rg -n -i "scihub" skills/paper-dive`, `rg -n "contradict or challenge it" skills/paper-dive/SKILL.md`, and the manual category-mapping check against `fetch_related.py`'s printed sections) to confirm all pass.
5. Re-read the full `SKILL.md` once more end-to-end to confirm no other stray scihub/contradiction-promise mentions remain outside the three edited spots.