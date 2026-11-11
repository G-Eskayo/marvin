## North-star fit

- **Reuses**: the existing `docs/plans/` review-doc convention, the existing Decisions format/gate (`docs/agents/decisions-format.md`), and the existing `lib/tests/` pytest channel. No new component, no code change — this ticket is explicitly doc-only ("no code changes", "Building the chosen option is a follow-up ticket").
- **Simplest sufficient approach**: one markdown file + one pytest file that checks it against the **real** repo tree, re-verified this session by reading `DocsExplorer.jsx`, `FilesExplorer.jsx`, `outbox.js`, `App.jsx`, `Markdown.jsx`, `decisions-format.md`, issue #402's live body, and the actual prior doc/tests that were rejected.
- **Tokens**: spent up front re-verifying claims against real code (not the prior doc's prose) because the rejection was specifically about an internal contradiction and tests that checked the doc's own text instead of code — a third blind rewrite would cost more than one grounded pass.
- **Capability**: leaves Gil a structured choice among the ticket's own three lettered options, each traceable to real code paths, not a prose question or an invented option scheme.
- The ticket doesn't state its own north-star fit — nothing to correct there.

**What exactly was wrong last time, verified against real code this session, and the fix:**

| Must-fix (code review) | Root cause | Fix in this plan |
|---|---|---|
| `docs-vs-files-review.md:203` — #402 self-contradiction (Files-only fix vs. "shared Markdown.jsx improvement... benefits both tabs" vs. a third framing in Current Limitations) | I re-read #402's live issue body: it builds **one new reusable viewer component** scoped to the **Files/outbox tab only** (images via a dedicated outbox IPC + `data:` URL, markdown via an outbox-context-aware relative-path resolver, notebooks, CSV, PDF, HTML). It does **not** touch `Markdown.jsx`'s `resolveImage` (which stays GitHub-raw-URL-only, serving Docs). The "benefits both tabs" framing was simply wrong. | One consistent sentence used everywhere the doc mentions #402: *"#402 fixes Files-tab rendering only, via a new outbox-scoped viewer component built so a future merged tab (Option B/C) could reuse it — it does not change `Markdown.jsx` or fix Docs' own image-resolution gap."* |
| `test_docs_vs_files_review.py:121` (`test_8`) — parses `TABS` ids, never compares to the doc; only checks substrings "docs tab"/"files tab" | Confirmed: the old test discards `tab_ids` after computing it. | New `test_8` extracts the **real label list** from `App.jsx`'s `TABS` array (regex over the literal) and asserts the doc's own "TABS array: ..." listing (if present) names the same labels in the same count; also checks any "N to M tabs" claim's `N` equals `len(tab_ids)` from the real array. Fails loudly if the array can't be parsed. |
| `test_docs_vs_files_review.py:113` (`test_7`) — `\b[abc]\b` with `re.I` matches the article "a" | Confirmed by inspection. | Replace with `\bOption\s+[ABC]\b` (case-sensitive on the letter, "Option" case-insensitive) — only matches the doc's actual naming convention, never the English article. |
| `test_docs_vs_files_review.py:66` (`test_5`) — searches whole file despite claiming to be scoped; `option\s+a` matches the Recommendation heading alone | Confirmed: no section slicing in the old `test_5`. | Reuse the **same section-extraction helper** `test_6` already uses (slice from `#+\s*A[:\s]` to the next option heading) and run the anchor-phrase assertions only inside each slice — not the whole doc. Since each slice stops before "Recommendation" and before "Decisions", a bare "Option A" in the Recommendation heading, or "sidebar"/"pseudo-project" inside Decisions, can no longer satisfy it. |
| `test_docs_vs_files_review.py:233` (`test_14`) — only regex-matches the doc's own text, never greps real code, so it can't go stale against the code | Confirmed, and I independently grepped `dashboard/src` and `dashboard/electron/main` for `track\|analytics\|telemetry\|posthog\|mixpanel\|amplitude` myself: **10 + 3 file hits, all false positives** (CSS `tracking-wide`, git `--untracked-files`, a PR "seen-tracking" cache, the word "tracker" for the issue tracker) — zero real instrumentation. | New `test_14` runs that same grep itself (narrower pattern: `\b(analytics|telemetry|posthog|mixpanel|amplitude)\b|trackEvent|logEvent|sendAnalytics`, which excludes the false positives found above) against the live `dashboard/src` and `dashboard/electron/main` trees, asserts zero hits, **and** asserts the doc states usage is unknown. If anyone adds real analytics later without updating the doc, this test fails on the code change itself, not just doc drift. |

Also folding in two cheap, directly related corrections from the review's non-blocking notes (same root causes as the must-fixes above, so free to fix now): the Recommendation no longer promises to "measure with real usage data" when the doc itself states there's no instrumentation (now says it'll revisit on direct feedback, since building instrumentation is explicitly out of scope); and Option C's tab-count/removal claims are phrased consistently as deferred-to-follow-up everywhere, not asserted as settled fact in one place and hedged in another. Decisions-block id stays a single consistent string (`tabs_architecture`) between this plan and the file, which is the inconsistency one of the notes flagged.

## Tests to write first

No "How we'll try to break it" section exists on #403 (confirmed from the live issue body — it's a doc-only review ticket, same shape as the rejected attempt). Deriving misuse cases from the deliverable's required structure plus the adversarial checklist, same as before but with every test now checking the **real** repo tree where the prior attempt only checked the doc's own prose.

New file: `lib/tests/test_docs_vs_files_review.py`.

1. **Doc exists, non-trivial length** — unchanged, still needed as a baseline guard.
2. **Docs-tab state grounded** — anchored phrases for local-first/GitHub-fallback, uncommitted/unpushed badges, notebook conversion.
3. **Files-tab state grounded** — anchored to `~/.claude/outbox` scope, exactly the kinds `detectKind` supports today (`markdown`/`json`/`text`, nothing else), no search claimed.
4. **Overlap/gap coverage** — each dimension (search, rendering, relations, outbox-vs-plans) present.
5. **Options are the ticket's literal A/B/C, checked inside each option's own section slice** (shared slicing helper with test 6) — fixes must-fix #4.
6. **Each option has all four facets** (on-screen change, migration work, risk, what-breaks), checked inside that option's own slice.
7. **Recommendation exists, names `Option [ABC]` (word-boundary-safe), has real reasoning length** — fixes must-fix #3.
8. **Tab-bar description matches the real `App.jsx` `TABS` array** (label set and any stated before/after count, derived dynamically, not hardcoded) — fixes must-fix #2.
9. **Every file path cited in backticks exists**, extended to also resolve bare filenames (e.g. `` `docs_cache.js` ``) against the real tree by basename search, and to strip `:NN` / `:NN-MM` line-citation suffixes before checking the path portion exists (closes the same "unverified citation" gap that triggered the original rejection, flagged again as a note here).
10. **Decisions block structurally valid** — marker present, exactly one `### <id>: <question>` line, id matches `^[a-z0-9_-]+$`.
11. **Decisions options match the ticket's three literal options**, checked only inside the sliced Decisions section.
12. **Decisions unanswered** — no `- [x]` inside that same slice.
13. **#402 and #403 referenced with context, never as a bare numeric ID** — plus a new assertion that the doc's #402 description is internally consistent (the same single sentence — "Files-tab-only, new reusable component, doesn't touch Markdown.jsx" — appears everywhere #402 is explained; a doc with two different accounts of what #402 fixes fails this test). This directly re-targets must-fix #1.
14. **Usage-frequency claim re-verified against live code**, by actually grepping `dashboard/src` and `dashboard/electron/main` for real analytics-call patterns (not the doc's text) and asserting zero hits, plus asserting the doc states usage is unknown — fixes must-fix #5.

**Explicitly N/A, stated not silently dropped:** huge/malformed external input (no untrusted input path — the only "input" is the doc's own claims, which tests 2–14 defend against), repeats/concurrency (static read of committed text, idempotent), wrong permissions/dependency failure (plain file reads against a checked-out repo). **A person's mistake** is the dominant real risk here (wrong facts, self-contradiction, weak tests that don't catch drift) and is exactly what tests 1, 5, 8, 9, 13, 14 guard against — it is what broke both prior attempts.

**Process check** (task list, not a new test): run `pytest -q lib/tests/test_docs_vs_files_review.py` then the full suite before/after; confirm every new test independently fails against a deliberately-wrong doc (e.g. temporarily swap in the old rejected doc text) before passing against the corrected one — this is the verification step the prior review said was missing ("verify fails when code changes without a test changing").

## Decisions
<!-- marvin:decisions -->
### tabs_architecture: Docs and Files — keep separate, merge, or fold?
- [ ] A: Keep both tabs, rename them so they no longer read as synonyms
- [ ] B: Merge into one tab, with sources (Projects, Outbox, Plans) in its sidebar
- [ ] C: Fold the outbox into Docs as a pseudo-project, like the master doc

This block lives inside `docs/plans/docs-vs-files-review.md` itself (testable from the committed file), and the task below copies it verbatim into the PR body.

## Task List

1. [ ] Write `lib/tests/test_docs_vs_files_review.py` (tests 1–14 above) against the *current* (rejected) doc first, confirming each new/changed test fails for the specific reason the code review gave (e.g. test 7 fails on the old doc only because of the stale regex, not a missing section).
2. [ ] Rewrite `docs/plans/docs-vs-files-review.md`:
   - Today-state for each tab, unchanged factually from the verified table above (local-first/GitHub-fallback, uncommitted/unpushed badges, `detectKind`'s markdown/json/text-only support).
   - Overlap/gap table, with the #402 row and its own "Note on #402" paragraph both using the **single consistent sentence** about #402's scope (Files-only, new reusable component, no `Markdown.jsx` change).
   - Options A/B/C analyzed verbatim from the ticket, each with all four facets; Option C's tab-removal consequence phrased as deferred-to-follow-up everywhere it's mentioned (no fact/assumption split).
   - Recommendation naming one lettered option, reasoning that doesn't promise usage-data collection that doesn't exist (revisit on direct feedback instead).
   - The Decisions block above, embedded as its own section with id `tabs_architecture` (matching this plan).
3. [ ] Run `pytest -q lib/tests/test_docs_vs_files_review.py`, then the full suite — confirm all 14 pass against the rewritten doc and nothing else regresses.
4. [ ] Open the PR: review doc + test file are the only changes; PR body carries the Decisions block verbatim; links #403 and #402.