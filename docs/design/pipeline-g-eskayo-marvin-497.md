## North-star fit

This reuses the existing requirements.md numbering/ID convention itself — no new pattern, tool, or file is introduced. It's a pure renumber-in-place edit: continue the existing sequential heading scheme (`## 3.` already follows directly after the last `### 2.5`, confirming `### 2.6`/`### 2.7` are the slots the doc's own structure left open) and continue the existing FR-ID sequence from its current ceiling (FR-24 → FR-25...FR-34), rather than inventing a new ID scheme. Simplest sufficient approach: a documentation-only text edit, nothing to design. Token cost: trivial (one file, ~10 line edits); this is exactly why it's filed as a `docs-only: exempt` ticket. It leaves the user (and any future reader citing an FR-ID in this public repo) more capable: ambiguous citations become resolvable, which is a direct instance of north star 4 ("tool for tools: requirements that can be cited").

I verified the ticket's factual claims against the current file (`skills/resume-tailor/docs/requirements.md`) rather than trusting them blindly:
- Confirmed two `### 2.3` headings (line 34 "Tailoring", line 74 "Master Resume Updates") and two `### 2.4` headings (line 49 "Cover Letter", line 84 "Transcript Parsing").
- Confirmed the second set's FR-12–FR-16 (lines 78–82) and FR-17–FR-21 (lines 88–92) collide with the first set's FR-12–FR-16 (lines 42–46) and FR-17–FR-21 (lines 53–57).
- Confirmed FR-24 (line 60) is the highest ID currently in use, so FR-25–FR-34 is the correct, non-colliding continuation.
- Grepped all of `skills/resume-tailor/` for `FR-1[2-6]`, `FR-1[7-9]`, `FR-2[01]`, `### 2.3`, `### 2.4`: every hit is inside `requirements.md` itself — `design.md` and `architecture.md` only cite `FR-10`/`FR-11` and `NFR-02`, both from the untouched first set. No external citation of the colliding IDs exists, confirming the ticket's "none found" claim still holds. No `CONTEXT.md` decision references resume-tailor, so there's nothing to reconcile.

No open design questions — Decisions section is omitted.

## Tests

Ticket's "How we'll try to break it" section states: **Docs-only: exempt**. This is correct — the change is a Markdown text edit with no executable code path, no input surface, and no runtime behavior, so none of the standard misuse categories (bad/empty/huge/malformed input, dependency failure, concurrency, permissions, stale state) apply. There is nothing to test with a test file.

The acceptance criteria are themselves verification checks I will run after editing (not unit tests, since there's no code):
1. Grep `^### 2\.` headings in requirements.md → assert no duplicates.
2. Grep `FR-\d+` IDs across the table rows → assert no duplicates.
3. Grep `design.md` and `architecture.md` for any FR-ID in the old colliding ranges (FR-12–FR-16, FR-17–FR-21) → assert none point at the renumbered (second) section — already confirmed empty, re-check after edit to be safe.

## Task List

1. Edit `skills/resume-tailor/docs/requirements.md` line 74: `### 2.3 Master Resume Updates` → `### 2.6 Master Resume Updates`.
2. Edit the same section's table (lines 78–82): `FR-12`→`FR-25`, `FR-13`→`FR-26`, `FR-14`→`FR-27`, `FR-15`→`FR-28`, `FR-16`→`FR-29`, preserving requirement text and order.
3. Edit line 84: `### 2.4 Transcript Parsing` → `### 2.7 Transcript Parsing`.
4. Edit the same section's table (lines 88–92): `FR-17`→`FR-30`, `FR-18`→`FR-31`, `FR-19`→`FR-32`, `FR-20`→`FR-33`, `FR-21`→`FR-34`, preserving requirement text and order.
5. Re-run the grep checks above (unique `### 2.x` headings, unique `FR-NN` IDs, no stale cross-references in `design.md`/`architecture.md`) to confirm acceptance criteria are met.
6. Show the diff to the owner via `marvin-show` before opening the PR.