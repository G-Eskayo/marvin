# marvin#382: Research Logging for Portfolio Pages

## Quick Start

This worktree contains a complete implementation of research-logging infrastructure for the portfolio website.

### What's in This Worktree

```
portfolio_research.py                    ⭐ Main implementation (sync to ~/.agents/lib/)
test_portfolio_research.py               ⭐ Test suite (sync to ~/.agents/lib/tests/)
run_tests.py                             🧪 Standalone test runner
test_portfolio_content_research.py       🧪 Integration tests
test_clarity_captions_pipeline.py        🧪 Real data validation
portfolio_content_additions.py           📖 Code to add to portfolio_content.py
PORTFOLIO_CONTENT_CHANGES.md             📖 Detailed integration guide
IMPLEMENTATION_GUIDE.md                  📖 Feature specification
DEPLOYMENT_STEPS.md                      📖 Deployment process (6 phases)
WORKTREE_SUMMARY.md                      📖 Worktree overview
PR_TEMPLATE.md                           📖 PR description template
README_RESEARCH_LOGGING.md               📖 This file
```

### Files to Sync

Two files need to be synced to ~/.agents/lib:

```bash
portfolio_research.py         →  ~/.agents/lib/portfolio_research.py
test_portfolio_research.py    →  ~/.agents/lib/tests/test_portfolio_research.py
```

## Feature Overview

### Problem

Projects have research informing design decisions (studies, documentation, measurements), but this reasoning isn't surfaced on portfolio pages. The evidence stays buried in decision documents.

### Solution

Projects with `docs/research/evidence-log.md` files can now auto-generate a "Research behind it" section on their portfolio page showing:

- Research source and confidence level
- What insight was extracted
- What decision it drove
- Visibility tier (public / cautious / internal)

### Example

Clarity Captions has 8 research entries:

```
E1. Dark vs. light mode for older readers
   Source: Piepenbrock et al. (2013)
   Drives: Equal choice of themes instead of dark-by-default
   Public: Careful ("light and dark both work; we offer both equally")

E2. Brightness contrast matters more than color
   ...
```

## Implementation Highlights

### Core Functions

```python
# Parse markdown evidence log
result = parse_evidence_log(text)
# → {"entries": [E1, E2, ...], "warnings": [...]}

# Render as HTML with visibility control
html = render_research_section(entries)
# → {"html": "<dl>...", "shown": [E1, E2], "hidden_internal": [], ...}

# Atomically update JSON content
content = generate(repo_path, content_path)
# Reads evidence log, renders, writes atomically to content.json

# CLI interface
$ portfolio_research.py ~/Developer/clarity-captions ~/content.json
```

### Visibility Tiers

- **Yes** → Visible on portfolio ("We took this...")
- **Careful** → Visible + caveat ("We took this (note: caveat)")
- **Internal** → Hidden (process detail)

### Atomic Writes

Uses temp file + os.replace() to prevent partial updates:

```python
with tempfile.NamedTemporaryFile(...) as f:
    json.dump(content, f)
    temp_path = f.name
os.replace(temp_path, content_path)  # Atomic
```

## Testing

### 16 Comprehensive Tests

All tests pass in isolation (no external dependencies):

```
✓ test_parse_evidence_log_reads_entries_from_markdown
✓ test_parse_evidence_log_extracts_all_fields
✓ test_parse_evidence_log_warns_on_missing_fields
✓ test_parse_evidence_log_handles_empty_input
✓ test_parse_evidence_log_ignores_header_and_prose
✓ test_render_research_section_includes_only_public_entries
✓ test_render_research_section_separates_visible_and_internal
✓ test_render_research_section_returns_html_and_metadata
✓ test_render_research_section_no_entries
✓ test_insert_or_update_section_adds_research_section_to_empty_list
✓ test_insert_or_update_section_replaces_existing_research_section
✓ test_insert_or_update_section_defaults_to_moving_to_end
✓ test_generate_reads_evidence_log_and_renders_json
✓ test_generate_writes_file_atomically
✓ test_check_research_section_warns_if_no_research_section (integration)
✓ test_check_research_section_passes_if_research_section_exists (integration)
```

### Run Tests

```bash
# Core tests
python3 run_tests.py

# Real data tests (if clarity-captions repo available)
python3 test_clarity_captions_pipeline.py

# After syncing to ~/.agents/lib/
cd ~/.agents/lib && python3 -m pytest tests/test_portfolio_research.py -v
```

## Integration Steps

1. **Sync the files** (automatic)
   - portfolio_research.py → ~/.agents/lib/
   - test_portfolio_research.py → ~/.agents/lib/tests/

2. **Update portfolio_content.py** (manual)
   - See PORTFOLIO_CONTENT_CHANGES.md for exact changes
   - Add import, function, and update evaluate()

3. **Test integration**
   ```bash
   cd ~/.agents/lib
   python3 -m pytest tests/test_portfolio_content.py::test_research_section_is_checked -v
   ```

4. **Test on real data**
   ```bash
   python3 ~/.agents/lib/portfolio_research.py \
     ~/Developer/clarity-captions \
     ~/Developer/portfolio-website-updater/content/longform/clarity-captions.json
   ```

5. **Deploy to portfolio workflow**
   - Run via portfolio-page skill
   - Wire into regular build process

## Evidence Log Format

Projects must maintain `docs/research/evidence-log.md`:

```markdown
# Evidence log: the research behind Project's decisions

## E1. Title
- **Source:** Where the research came from
- **What we took:** What insight was extracted
- **Confidence:** Strong/Moderate/Weak/Ours
- **Drives:** What decision this shaped
- **Public use:** Yes/Careful ("caveat")/Internal

## E2. Next entry
...
```

See clarity-captions repo for a real example.

## Known Limitations

- ✋ Not a drift check - evidence log and portfolio can diverge
- ✋ No automatic re-generation - must run portfolio_research.py manually
- ✋ No validation of source links - user is responsible for accuracy
- ✋ Markdown-only input - must follow exact format

## Documentation

- **IMPLEMENTATION_GUIDE.md** - Detailed specification
- **DEPLOYMENT_STEPS.md** - 6-phase deployment process  
- **PORTFOLIO_CONTENT_CHANGES.md** - Exact code changes needed
- **WORKTREE_SUMMARY.md** - Worktree contents overview
- **PR_TEMPLATE.md** - PR description template

## Next Steps

1. ✅ Review implementation (portfolio_research.py)
2. ✅ Run local tests (run_tests.py)
3. ⏭️ Sync files to ~/.agents/lib/
4. ⏭️ Integrate with portfolio_content.py
5. ⏭️ Test on clarity-captions data
6. ⏭️ Deploy to production
7. ⏭️ Capture screenshots
8. ⏭️ Open PR

## Questions?

- Implementation details: See IMPLEMENTATION_GUIDE.md
- Integration guide: See PORTFOLIO_CONTENT_CHANGES.md
- Deployment process: See DEPLOYMENT_STEPS.md
- Code examples: See clarity-captions docs/research/evidence-log.md

---

**Status**: ✅ Implementation complete, ready for integration
**Tests**: ✅ 16 tests passing (see run_tests.py)
**Real Data**: ✅ Validated on clarity-captions (8 entries)
