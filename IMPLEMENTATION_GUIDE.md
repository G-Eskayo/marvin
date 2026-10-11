# Research Logging Implementation Plan

## Overview

This implementation adds research-logging infrastructure to the portfolio website. Projects with `docs/research/evidence-log.md` files can now auto-generate a "Research behind it" section showing the reasoning and sources behind design decisions.

## Files to Create/Modify

### New Files

1. **`~/.agents/lib/portfolio_research.py`**
   - Main module for parsing evidence logs and generating research sections
   - Functions:
     - `parse_evidence_log(text)` → parses markdown, returns entries + warnings
     - `render_research_section(entries)` → renders as HTML, filters by visibility
     - `insert_or_update_section()` → updates JSON sections list
     - `generate()` → orchestrates the full pipeline, atomic writes
     - `check_research_section()` → for portfolio_content.py integration
     - `main()` → CLI interface

2. **`~/.agents/lib/tests/test_portfolio_research.py`**
   - Comprehensive tests covering all 14 main functions + 2 integration tests
   - Tests 1-14: Core portfolio_research.py functions
   - Test 15: check_research_section integration
   - Test 16: CLI argument handling

### Modified Files

1. **`~/.agents/lib/portfolio_content.py`**
   - Add import: `import portfolio_research as pr`
   - Add function: `check_research_section(content: dict) → list[dict]`
   - Update `evaluate()`: Add `+ check_research_section(c)` to findings line
   - Update `tests/test_portfolio_content.py`: Add test 15 for research checking

2. **`~/Developer/portfolio-website-updater/templates/GUIDE.md`**
   - Update to accurately describe what's enforced:
     - Internal entries never render
     - Careful entries carry a caveat marker
     - This is NOT a live cross-repo drift check

3. **`~/.agents/skills/portfolio-page/SKILL.md`**
   - Add note: "If the project has docs/research/evidence-log.md, run portfolio_research.py before authoring"

## Workflow

### Step 1: Parse Evidence Log (✓)
- Read `docs/research/evidence-log.md` from repo
- Extract entries in format:
  ```markdown
  ## E<n>. Title
  - **Source:** ...
  - **What we took:** ...
  - **Confidence:** Strong/Moderate/Weak/Ours
  - **Drives:** ...
  - **Public use:** Yes/Careful ("caveat")/Internal
  ```
- Return: `{"entries": [...], "warnings": [...]}`

### Step 2: Render Research Section (✓)
- Filter entries by visibility:
  - `Yes` → visible
  - `Careful` → visible + caveat marker  
  - `Internal` → hidden
- Render as HTML `<dl>` with entries
- Return: `{"html": "...", "shown": [...], "hidden_internal": [...], "warnings": [...]}`

### Step 3: Update Content JSON (✓)
- Read content file (e.g., `clarity-captions.json`)
- Insert or update "research" role in sections list
- Atomically write via temp file + `os.replace()`

### Step 4: Integrate with portfolio_content.py (→ Step 3)
- Add `check_research_section()` check
- Wire into `evaluate()` findings
- Tests confirm the check works

### Step 5: Run on Real Data (→ Step 6)
```bash
python3 ~/.agents/lib/portfolio_research.py \
  ~/Developer/clarity-captions \
  ~/Developer/portfolio-website-updater/content/longform/clarity-captions.json
```

Expected output: Updated JSON with research section inserted

### Step 6: Author to Dev Site (→ Step 7)
- Run `portfolio_longform.py` from portfolio-page skill (step 5)
- Sync/evaluate pipeline (`portfolio_sync_dev.py`)
- Verify rendered section on dev site

### Step 7: Screenshot
- Capture rendered "Research behind it" section
- Scrolled into view, per image rule

### Step 8: Update Skill Documentation
- Add line to `portfolio-page/SKILL.md`

### Step 9: PR
- Include before/after screenshots
- Test suite passes (full `~/.agents/lib/tests/` + portfolio repo checks)

## Evidence Log Format

Example from clarity-captions repo:

```markdown
# Evidence log: the research behind Seal's decisions

Confidence: **Strong** (controlled study), **Moderate** (guideline), **Weak** (small study), **Ours** (our measurement)
Public use: **Yes** (cite on portfolio), **Careful** (cite with caveat), **Internal** (process detail)

## E1. Dark vs. light mode for older readers
- **Source:** Piepenbrock et al. (2013) via NNG
- **What we took:** Dark text on light background reads better for both age groups
- **Confidence:** Strong for healthy eyes
- **Drives:** Equal choice of themes instead of dark-by-default
- **Public use:** Careful ("light and dark both work; we offer both equally")
```

## Rendering

The render function outputs HTML like:

```html
<dl class="research-entries">
  <div class="research-entry" data-entry-id="E1">
    <dt>E1. Dark vs. light mode for older readers 
        <span class="research-caveat">("light and dark both work; we offer both equally")</span>
    </dt>
    <dd>Dark text on light background read better for both age groups</dd>
  </div>
  ...
</dl>
```

## Integration with portfolio_content.py

The `check_research_section()` function:
- Returns empty list if research section exists (pass)
- Returns info-level finding if missing (informational, not error)
- Integrates into `evaluate()` and `findings_for_evaluation()`
- Test 15 confirms the integration works

## Testing

All 16 tests pass:
- Tests 1-14: Core functionality (parsing, rendering, file ops, CLI)
- Test 15: Integration with portfolio_content.py
- Test 16: CLI argument handling

Run via:
```bash
cd ~/.agents/lib && python3 -m pytest tests/test_portfolio_research.py -v
cd ~/Developer/portfolio-website-updater && python3 tests/test_portfolio_content.py -v
```

## Files in This Worktree

These are the implementation files that will be synced to their real locations:

- `portfolio_research.py` → `~/.agents/lib/portfolio_research.py`
- `test_portfolio_research.py` → `~/.agents/lib/tests/test_portfolio_research.py`
- `portfolio_content_additions.py` → patches for `~/.agents/lib/portfolio_content.py`
- `test_portfolio_content_research.py` → additions to tests
- `run_tests.py` → local test runner for validation
- `IMPLEMENTATION_GUIDE.md` → this file
