## North-star fit

**Reuses:** `lib/code_review_gate.py:37-57` `build_prompt()` — the resources paragraph and the must-fix/note wording change are edits inside this existing function's rubric string, not a new mechanism. The only structural change is lifting the rubric from a local variable into a module-level `RUBRIC` constant (same pattern as the existing module-level `MAX_DIFF_CHARS`), so tests can inspect it directly instead of re-deriving it from `build_prompt()`'s output. Tests reuse the existing `_judge()` helper (`lib/tests/test_code_review_gate.py:266`) for behavioural cases and the existing `north_stars.load()` pattern (`lib/tests/test_north_stars.py`) for the wording check. No new file, no new function beyond one tiny test helper.

**Simplest sufficient approach:** a text edit to one prompt string plus one doc line, calibrated with a single contrastive sentence ("a small, bounded, one-off loop is a micro-optimisation, not a resources regression") so the must-fix/note boundary is explicit rather than left for the judge to guess at.

**Resources:** spends nothing ongoing — this *is* the token-vs-resources framing change itself. It makes the review gate block the five already-observed resource regressions' *shape* (O(n)-per-request reads, unbounded/un-cleaned growth, wasted calls in a loop) before merge instead of after, which is strictly fewer repeat-fix cycles. Net token cost: one small diff reviewed once.

**More capable, not more passive:** this raises the bar the automated judge enforces; it doesn't remove any human judgment — Gil already made the call (2026-10-14) that complexity is as important as correctness, this just encodes it.

**Correction to the ticket's own text:** "What to build" says "an O(new) or indexed read exists" — "O(new)" is a typo in the ticket body itself (flagged by the previous attempt's reviewer too). I'll write "O(1) or indexed/cached read" instead; same meaning, no invented term.

**Scope note (not a Decision — reasoned, not asked):** the ticket's "Recurrence check" section reads `Probe: none yet: add one counting merged PRs later fixed for a resource defect ... as part of the fix`. That phrase isn't a registered name — `purpose_metrics.outcome_gap()` flags it (non-blocking warning, confirmed from PR #1343's posted north-star-fit check). Building that probe for real means a new `purpose_metrics.PROBES` entry that queries `gh` for closed `bug`-labelled issues naming a merged PR and "O(N)"/"unbounded"/"never cleaned" — a second, independently-scoped piece of work not named in "What to build" or any acceptance-criteria checkbox. I'm leaving it out of this pass and saying so here rather than silently skipping it or inventing scope; it's a reasonable candidate for its own follow-up ticket.

## Files read

`lib/code_review_gate.py` (full), `lib/tests/test_code_review_gate.py` (full), `lib/north_stars.py` (full), `lib/tests/test_north_stars.py` (full), `lib/purpose_metrics.py` (full, to resolve the probe scope question), `docs/north-stars.md`, `docs/adr/0063-tests-try-to-break-it-enforced-at-every-gate.md`, `docs/adr/0065-delete-by-replacement-cost.md`, `docs/agents/decisions-format.md`, `CONTEXT.md` (grepped — no conflicting recorded decision). Confirmed via grep that `docs/north-stars.md:31` is the only live, in-scope occurrence of "saves tokens". Also read PR #1343 (the prior, denied attempt on this same ticket) and both rounds of its review feedback in full, to avoid repeating its mistakes — see "Lessons from the denied attempt" below.

## Lessons from the denied attempt (PR #1343 — these are requirements, not suggestions)

1. **No OR-fallback assertions that let a required phrase go unchecked.** The old `"resource regression" in X or any(other phrases)` passed regardless of whether the specific claim was true. New tests assert each distinct concept once, with no escape-hatch `or`.
2. **No fixed-character-window slicing** (`text[idx:idx+300]`) — fragile to rewording. Slice between real anchors that exist in the text (`RUBRIC.index("- [must-fix]")` to `RUBRIC.index("- [note]")`), as the reviewer itself suggested.
3. **No tautological truncation test.** The old test compared two slices of the *same* static rubric, which structurally cannot differ regardless of correctness. Exporting `RUBRIC` as a module constant lets the test independently assert `build_prompt(huge_diff).startswith(RUBRIC + "\n\nDIFF:\n\n")` — a regression that truncated the whole prompt instead of just the diff would actually fail this.
4. **No redundant substring checks** (`"cleans up"` and `"never cleans up"` — the second contains the first).
5. **Gloss ADR 0065 in the prompt text itself** (one phrase on what "disposable, clean it up" means), not just "ADR 0065" by number — the judge model only sees the diff and the prompt, not the ADR.
6. **Design docs must be self-contained.** No leaked scratch/thinking text as a doc's first line, no "the tests above" references in a tasks file that has nothing above it. This plan's own Task List is written to stand alone.
7. **Define the must-fix/note boundary explicitly** — not just "hot path" but a direct contrast sentence, so the judge doesn't flag every small bounded loop.

## Tests (write first)

New rubric text (exact, see Task 1 below) makes `RUBRIC` a module constant containing a `Resources:` paragraph and revised `[must-fix]`/`[note]` bullets. All new tests live in `lib/tests/test_code_review_gate.py` (reusing `_judge()`), plus one in `lib/tests/test_north_stars.py`.

Covering the ticket's "How we'll try to break it":

1. `test_a_resources_must_fix_finding_blocks` — a `[must-fix]` finding with resources wording (e.g. `O(n) read inside the request handler on every call, no cache`) → `clean is False`, finding text preserved.
2. `test_a_resources_micro_optimisation_note_stays_a_note` — a `[note]`-tagged micro-optimisation finding → `{"clean": True, "findings": [], "notes": [...]}`.
3. `test_truncating_a_huge_diff_never_touches_the_rubric` — `build_prompt(huge_diff).startswith(RUBRIC + "\n\nDIFF:\n\n")` and the diff itself carries `[... diff truncated ...]`. Not tautological: fails if a regression truncates the assembled prompt instead of just the diff.
4. `test_an_unknown_tag_on_a_resources_finding_still_blocks` — `[perf] ... unbounded cache, never evicted` → `clean is False`, `notes == []` (ambiguity never resolves to safe — same invariant the existing `test_an_untagged_or_unknown_tag_counts_as_must_fix` already covers generically; this instance just uses resources wording).

Covering the acceptance criteria directly ("a test asserts the rubric wording"):

5. `test_resources_paragraph_names_time_space_cleanup_and_wasted_calls` — slice `RUBRIC` between `"Resources:"` and `"Respond with exactly one line"`; assert it names: `"O(1)"` or `"indexed"` (time), `"never cleans up"` and `"ADR 0065"` (space/cleanup), and all three of `"network"`, `"token"`, `"subprocess"` (wasted calls).
6. `test_must_fix_bullet_names_resources_regression_and_note_bullet_names_micro_optimisation` — slice the `[must-fix]` bullet line (`RUBRIC.index("- [must-fix]")` to `RUBRIC.index("- [note]")`) and assert `"resources regression"` in it; slice the `[note]` bullet (to `"\n\nIf clean"`) and assert `"micro-optimisations"` in it and `"performance"` not in it.

In `lib/tests/test_north_stars.py`:

7. `test_north_star_fit_asks_about_resources_not_only_tokens` — `north_stars.load()` contains `"saves resources"` and does not contain `"saves tokens"`.

**Misuse already covered, not re-tested:** this change only edits rubric *text* and bullet-categorization wording; it adds no new code path through `parse_verdict`/`review_diff`. Empty diff, a crashing/timing-out judge, two VERDICT lines, case-insensitive tags, concurrent reviews, binary-file diffs, an adversarial diff forging a VERDICT marker, a missing git base, and huge-diff truncation of the *diff* are all already exercised by the existing suite (`lib/tests/test_code_review_gate.py:16-336`) and are untouched by this change — no mock stands in for a real collaborator here since there isn't one (the judge is already a fake in every existing test, exactly as the file's own tests all do; the only "real collaborator" surface in this file, `gh pr diff` via `fetch`, is also unchanged).

**Verify-fails check:** every line changed in `lib/code_review_gate.py` (the `RUBRIC` extraction and wording) is covered by tests 1-6 above; the one line changed in `docs/north-stars.md` is covered by test 7.

## Decisions

None. The strictness question the ticket's own embedded "Original ticket text" posed ("A: must-fix now" vs "B: note for two weeks then must-fix") is already settled in the issue body's own summary: *"Gil's rule (2026-10-14): space and time complexity are as important as correctness, which settles the strictness question: blocking now, not after a grace period."* No other open design choice remains — the must-fix/note boundary is specified concretely in the Task List below rather than left for the owner to pick.
