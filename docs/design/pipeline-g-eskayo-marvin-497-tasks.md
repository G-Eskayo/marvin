1. Edit `skills/resume-tailor/docs/requirements.md` line 74: `### 2.3 Master Resume Updates` → `### 2.6 Master Resume Updates`.
2. Edit the same section's table (lines 78–82): `FR-12`→`FR-25`, `FR-13`→`FR-26`, `FR-14`→`FR-27`, `FR-15`→`FR-28`, `FR-16`→`FR-29`, preserving requirement text and order.
3. Edit line 84: `### 2.4 Transcript Parsing` → `### 2.7 Transcript Parsing`.
4. Edit the same section's table (lines 88–92): `FR-17`→`FR-30`, `FR-18`→`FR-31`, `FR-19`→`FR-32`, `FR-20`→`FR-33`, `FR-21`→`FR-34`, preserving requirement text and order.
5. Re-run the grep checks above (unique `### 2.x` headings, unique `FR-NN` IDs, no stale cross-references in `design.md`/`architecture.md`) to confirm acceptance criteria are met.
6. Show the diff to the owner via `marvin-show` before opening the PR.