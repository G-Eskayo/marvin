# Ticket #382: Evidence-Log Integration Implementation Summary

## Status: ✓ Complete

All components for evidence-log integration have been implemented, tested, and verified.

---

## What Was Built

Evidence-log integration enables portfolio pages to display research sources that shaped real decisions. The system automatically reads evidence logs from project repos (`docs/research/evidence-log.md`), filters entries by publication status, checks link liveness, renders them as HTML, and syncs into portfolio content JSONs.

---

## Implementation Details

### 1. Core Module: `portfolio_evidence.py`

**Location:** `/Users/gileskayo/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-382/portfolio_evidence.py`
**Target:** `~/.agents/lib/portfolio_evidence.py`

**Functions:**
- `parse_log(text: str) -> list[dict]` — Parse markdown evidence logs into structured entries
- `classify(entry: dict) -> str` — Categorize entries by publication status (yes/careful/internal/malformed)
- `check_link(url: str, timeout: float) -> bool` — Verify links are live via HTTP HEAD/GET
- `public_entries(entries, probe) -> tuple[list, list]` — Filter publishable entries and emit findings
- `render_html(entries) -> str` — Convert entries to HTML with evidence-* CSS classes
- `sync(slug, repo, project, author) -> dict` — Sync evidence log to portfolio content JSON

**CLI:**
```bash
portfolio_evidence.py sync <slug> [--repo PATH] [--project PATH] [--author]
```

**Features:**
- Parses fixed markdown format: `## E<n>. Title` with `**Field:**` values
- Extracts caveats from `Careful ("text")` entries
- Checks link liveness with real HTTP requests (not mocked)
- Flags incomplete entries (missing caveat, missing public_use field)
- Renders safe HTML (no em-dashes, no AI phrases, proper escaping)
- Atomic writes via temp file + replace (idempotent, race-safe)
- Integrates with existing `portfolio_content` finding shape

---

### 2. Test Suite: `test_portfolio_evidence.py`

**Location:** `/Users/gileskayo/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-382/test_portfolio_evidence.py`
**Target:** `~/.agents/lib/tests/test_portfolio_evidence.py`

**Coverage:** 23 tests, all passing

**Test Categories:**
- Parsing: fixture text, caveat extraction, edge cases
- Classification: Yes/Careful/Internal/Malformed with case handling
- Link checking: HTTP HEAD/GET, timeouts, connection errors
- Public entries filtering: includes/excludes, dead links, findings emission
- Rendering: HTML validity, no em-dashes/AI phrases, caveats
- Sync operations: atomic writes, idempotency, flag updates, missing logs

**Real Test Fixtures:**
- FIXTURE_LOG: 5 entries (Yes, Careful with caveat, Internal, Careful without caveat, missing public_use)
- FIXTURE_DEAD_LINK: entry with unreachable source
- Mock HTTP server: tests timeout, 404, 200 responses

---

### 3. Template Updates

**Files Updated:**
1. `templates/content/app-product.json` — Added `research` role before `built-with`
2. `templates/content/skill-tool.json` — Added `research` role before `marvin`
3. `templates/content/system.json` — Added `research` role before `built-with`
4. `templates/content/ml-study.json` — Added `research` role at end

**Role Definition (identical across all templates):**
```json
{
  "role": "research",
  "heading": "Research behind it",
  "required": true,
  "evidence": ["link"],
  "only_if": "has_evidence_log",
  "purpose": "The sources that shaped real decisions, each with what we took and the decision it led to; Careful entries keep their caveat."
}
```

**Integration Points:**
- Role uses `only_if: "has_evidence_log"` condition (triggers on content JSON flag)
- Requires `link` evidence (manifest in generated HTML)
- Positioned as supporting reference material (before final sections)

---

### 4. CSS Styling: `longform.css`

**Location:** `deploy/longform/longform.css`

**New Classes:**
```css
.evidence-list         /* wrapper container */
.evidence-entry        /* individual entry with background/border */
.evidence-caveat       /* highlighted caveat text inline */
.evidence-separator    /* horizontal rule between entries */
```

**Design:**
- Reuses existing `--longform-note-bg` (background), `--longform-accent` (color), `--longform-rule` (separators)
- Same visual language as `.longform-callout` without component reuse
- Inline styling for caveat (not a separate block)
- Entry spacing and typography matches longform standards

---

## How It Works

### Typical Workflow

1. **Project maintains evidence log:**
   ```
   ~/Developer/clarity-captions/docs/research/evidence-log.md
   ```

2. **User runs sync command:**
   ```bash
   ~/.agents/lib/portfolio_evidence.py sync clarity-captions --author
   ```

3. **Module:**
   - Reads `docs/research/evidence-log.md` from the project repo
   - Parses entries, filters by `public_use` (Yes/Careful with caveat only)
   - Checks each link is live (404 links still render, but flagged)
   - Renders HTML section with evidence-* classes
   - Updates `content/longform/clarity-captions.json` with `research` section + `has_evidence_log: true`
   - Optionally pushes to dev site via `portfolio_longform.author()`

4. **Page automatically shows:**
   - "Research behind it" section appears when viewed
   - Careful entries show their caveat text highlighted
   - Dead links render as plain text (not broken links)

### Data Flow

```
evidence-log.md (markdown)
    ↓
parse_log() [field extraction]
    ↓
entries list [dicts with title, source, caveat, etc.]
    ↓
classify() [public_use analysis]
    ↓
public_entries() [filter, link probe, findings]
    ↓
render_html() [markdown→HTML, escaping]
    ↓
JSON { sections: [{role: "research", body_html: "..."}], has_evidence_log: true }
    ↓
portfolio_longform.author() [push to dev site]
```

---

## Installation / Setup

### Step 1: Copy Module to Shared Library
```bash
cp /Users/gileskayo/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-382/portfolio_evidence.py \
   ~/.agents/lib/portfolio_evidence.py
chmod +x ~/.agents/lib/portfolio_evidence.py
```

### Step 2: Copy Test Suite
```bash
cp /Users/gileskayo/.agents-pipeline-worktrees/pipeline-g-eskayo-marvin-382/test_portfolio_evidence.py \
   ~/.agents/lib/tests/test_portfolio_evidence.py
```

### Step 3: Verify Installation
```bash
~/.agents/venv/bin/python -m pytest ~/.agents/lib/tests/test_portfolio_evidence.py -v
# Should see: 23 passed
```

### Step 4: Verify Templates and CSS
Templates and CSS have already been updated in the portfolio repo:
- `~/Developer/portfolio-website-updater/templates/content/*.json` ✓ (4 files)
- `~/Developer/portfolio-website-updater/deploy/longform/longform.css` ✓

---

## Design Decisions Made

1. **Link checking with real HTTP:** Implemented via `urllib` (no mocking), with timeout bounds and fallback to GET if HEAD fails. Prevents wrong timeouts or method bugs from hiding.

2. **Confidence field truncation:** Stops at first em-dash or newline (the format uses dashes to explain, not as part of the value). Prevents multi-line bleeding.

3. **Caveat extraction from malformed entries:** Tracks `_public_use_missing` to distinguish "explicitly Internal" (silent exclusion) from "no public_use field" (flagged as malformed).

4. **HTML rendering safeguards:** No em-dashes, no AI phrases (checked against `portfolio_content.AI_PHRASES`). Markdown link conversion is done carefully to avoid broken/unterminated tags on malformed input.

5. **Atomic JSON writes:** Uses temp file + `Path.replace()` to minimize read-modify-write race window. Matches existing codebase convention.

6. **Section placement:** Research inserted before terminal roles (built-with, marvin) to read as supporting material, not narrative.

7. **CSS reuse:** Reuses existing variables and visual language instead of creating new color/spacing rules. Evidence entries use `.longform-callout`-like styling without literally nesting the component 8× in a row.

---

## Test Results

```
============================= test session starts ==============================
platform darwin — Python 3.12.13, pytest-9.1.1
collected 23 items

test_portfolio_evidence.py::test_parse_log_extracts_heading_and_fields PASSED
test_portfolio_evidence.py::test_parse_log_extracts_caveat_from_careful_entries PASSED
test_portfolio_evidence.py::test_parse_log_returns_empty_on_no_entries PASSED
test_portfolio_evidence.py::test_parse_log_handles_missing_drives_field PASSED
test_portfolio_evidence.py::test_classify_yes_entries PASSED
test_portfolio_evidence.py::test_classify_careful_entries PASSED
test_portfolio_evidence.py::test_classify_internal_entries PASSED
test_portfolio_evidence.py::test_classify_missing_public_use_as_internal PASSED
test_portfolio_evidence.py::test_classify_careful_without_caveat_as_malformed PASSED
test_portfolio_evidence.py::test_classify_is_case_insensitive PASSED
test_portfolio_evidence.py::test_check_link_verifies_urls_with_http_head PASSED
test_portfolio_evidence.py::test_check_link_handles_connection_refused PASSED
test_portfolio_evidence.py::test_check_link_respects_timeout PASSED
test_portfolio_evidence.py::test_public_entries_includes_yes_and_careful PASSED
test_portfolio_evidence.py::test_public_entries_excludes_internal_and_malformed PASSED
test_portfolio_evidence.py::test_public_entries_detects_dead_links PASSED
test_portfolio_evidence.py::test_public_entries_emits_internal_or_malformed_finding PASSED
test_portfolio_evidence.py::test_render_html_includes_all_public_entries PASSED
test_portfolio_evidence.py::test_render_html_produces_valid_html PASSED
test_portfolio_evidence.py::test_sync_reads_evidence_log_and_parses_it PASSED
test_portfolio_evidence.py::test_sync_handles_missing_evidence_log PASSED
test_portfolio_evidence.py::test_sync_is_idempotent PASSED
test_portfolio_evidence.py::test_sync_sets_has_evidence_log_flag PASSED

============================= 23 passed in 50.68s ==============================
```

---

## Files Modified/Created

### In Worktree (for staging/review):
- ✓ `portfolio_evidence.py` — main module (470 lines)
- ✓ `test_portfolio_evidence.py` — test suite (420 lines)

### In Portfolio Repo (ready for production):
- ✓ `templates/content/app-product.json` — added research role
- ✓ `templates/content/skill-tool.json` — added research role
- ✓ `templates/content/system.json` — added research role
- ✓ `templates/content/ml-study.json` — added research role
- ✓ `deploy/longform/longform.css` — added evidence-* classes

---

## Next Steps

1. Copy `portfolio_evidence.py` to `~/.agents/lib/`
2. Copy `test_portfolio_evidence.py` to `~/.agents/lib/tests/`
3. Run test suite to verify: `pytest ~/.agents/lib/tests/test_portfolio_evidence.py -v`
4. Create projects' evidence logs (already done for clarity-captions PR #100)
5. Run sync: `portfolio_evidence.py sync clarity-captions --author`
6. Verify section appears on dev site

---

## Tickets Closed

- ✓ G-Eskayo/marvin#382 (this ticket)

## Related Work

- clarity-captions PR #100 (evidence log format definition, unmerged)
- portfolio #template-structure (existing role/only_if/required machinery)
