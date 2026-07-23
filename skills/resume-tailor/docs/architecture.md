# Architecture Document — Resume Tailor

**Version:** 1.0  
**Date:** 2026-06-29  
**Status:** Approved — ready for implementation

---

## 1. System Overview

Resume Tailor is a Claude Code skill. It has no standalone runtime — Claude Code IS the intelligence layer. Python scripts handle the mechanical work (PDF rendering, file extraction, URL fetching) that Claude cannot do natively. Everything personal stays local; everything reusable is in the public repo.

```
Claude Code session
    │
    ├── reads SKILL.md (routing + instructions)
    ├── reads ~/.claude/resume/master.md (local, personal)
    ├── calls scripts/ for mechanical tasks
    │       ├── fetch_jd.py        (URL fetch)
    │       ├── extract_text.py    (PDF/DOCX → plain text)
    │       └── render_pdf.py      (Markdown → PDF via WeasyPrint)
    └── writes ~/.claude/resume/tailored/[company]-[date]/
            ├── research.md
            ├── resume.md
            ├── resume.pdf
            ├── cover-letter.md    (if requested)
            └── cover-letter.pdf   (if requested)
```

---

## 2. Directory Structure

```
~/.agents/skills/resume-tailor/        ← PUBLIC REPO (G-Eskayo/resume-tailor)
├── SKILL.md                           ← skill definition + command routing
├── README.md                          ← public-facing setup guide
├── scripts/
│   ├── fetch_jd.py                    ← URL fetch, returns plain text or error
│   ├── extract_text.py                ← PDF/DOCX/MD → plain text
│   └── render_pdf.py                  ← Markdown → PDF via WeasyPrint
├── template/
│   └── resume.css                     ← PDF stylesheet (WeasyPrint)
└── docs/
    ├── requirements.md
    ├── design.md
    └── architecture.md  ← this file

~/.claude/resume/                      ← LOCAL ONLY — never in git
├── master.md                          ← master resume (all experience)
└── tailored/
    └── [company]-[YYYY-MM-DD]/
        ├── research.md
        ├── resume.md
        ├── resume.pdf
        ├── cover-letter.md
        └── cover-letter.pdf
```

---

## 3. Component Breakdown

### 3.1 SKILL.md
The entry point. Defines:
- Skill metadata (name, description, tags)
- Command routing table (`/tailor`, `/add-to-master`, `/merge-resume`, `/parse-transcript`)
- Per-command instruction blocks (what Claude does for each command)
- Master resume path constant: `~/.claude/resume/master.md`
- Output path pattern: `~/.claude/resume/tailored/[company]-[date]/`

### 3.2 `scripts/fetch_jd.py`
**Input:** URL string  
**Output:** Plain text of job description, or structured error  
**Behaviour:**
- HTTP GET with browser-like User-Agent header (reduces bot blocking)
- Strips HTML tags, navigation, footer boilerplate via BeautifulSoup
- Returns clean body text
- On any failure: prints clear error message, exits with non-zero code so Claude knows to request paste

### 3.3 `scripts/extract_text.py`
**Input:** File path (`.pdf`, `.docx`, `.md`, `.txt`)  
**Output:** Plain text  
**Behaviour:**
- `.pdf` → pdfminer.six
- `.docx` → python-docx
- `.md` / `.txt` → read directly
- Preserves section structure where detectable

### 3.4 `scripts/render_pdf.py`
**Input:** Path to `.md` file, path to output `.pdf`  
**Output:** PDF file written to disk  
**Behaviour:**
- Converts Markdown → HTML via markdown-it-py
- Post-processes HTML with BeautifulSoup: wraps the header cluster (h1 + next 3 `<p>`) in a `<div class="header">` for the two-column flex layout, keeping the underlying text order linear for ATS
- Applies `template/resume.css` via WeasyPrint
- Single-page enforcement (revised 2026-07-02, extended same day): **auto-fit-to-page**, bidirectional. Searches a generated ladder of font-size/margin/line-height steps (0.25pt increments, 13pt down to 8.5pt body) from largest to smallest, rendering each and checking `len(document.pages)`, keeping the largest step that still fits on 1 page — so short content grows toward filling the page and long content shrinks to fit, down to a legibility floor (then warns rather than shrinking further). Also flags visibly underfilled pages even at the largest step, recommending content additions over further growth. See ADR-006.
- Exits with error if WeasyPrint not installed, with install instruction

### 3.5 `template/resume.css`
WeasyPrint stylesheet. Defines all visual properties per the PDF Visual Spec in `design.md §7`. Key rules (revised 2026-07-02):
- `@page { size: letter; margin: 0.6in 0.65in; }` (starting values — auto-shrink-to-fit may reduce)
- `.header { display: flex; justify-content: space-between; }` — two-column header, see 3.4
- Name: starts 20pt bold all-caps, blue accent color
- Section headers: 8.5pt bold all-caps, 1.5px letter-spacing, `border-bottom` — the only divider mechanism (no manual `<hr>` in the template)
- Body: starts 10pt, line-height 1.3
- Dividers: `border-bottom` on `h2` only — see ADR-006
- Blue accent on name/headers; body text stays black for print contrast. Color does not affect ATS parsing (parsers read the text stream, not pixel color) — the prior "black text only (ATS safe)" rule was based on an incorrect premise; see ADR-006.
- Font: system sans-serif stack, no `@font-face` — see ADR-010 (Inter's @font-face broke bold/italic rendering; removed 2026-07-02)
- Cover letter shares font + accent color + header treatment with the resume (previously the cover letter CSS only overrode font-size, with no shared visual identity)

---

## 4. Data Flow

### Tailor command

```
/tailor [url] [--cover-letter]
    │
    ├─ [if URL] fetch_jd.py → JD text
    │           └─ [on fail] → Claude prompts for paste
    │
    ├─ [if no --cover-letter flag] → Claude asks yes/no
    │
    ├─ Claude searches: company, role, contacts
    │   └─ writes research.md
    │
    ├─ Claude reads master.md
    │
    ├─ Claude scores all entries (relevance × 0.7 + recency × 0.3)
    │
    ├─ Claude fills template slots → writes resume.md
    │
    ├─ render_pdf.py resume.md → resume.pdf
    │
    ├─ [if cover letter] Claude writes cover-letter.md
    │                    render_pdf.py cover-letter.md → cover-letter.pdf
    │
    └─ Claude prints package summary
```

### Merge command

```
/merge-resume /path/to/file
    │
    ├─ extract_text.py → plain text
    │
    ├─ Claude parses into sections
    │
    ├─ For each item:
    │   ├─ No match in master → add
    │   ├─ Exact match → skip
    │   └─ Same entity, different content → union + <!-- REVIEW -->
    │
    └─ Claude writes merged master.md + prints diff summary
```

### Parse-transcript command

```
/parse-transcript /path/to/transcript
    │
    ├─ extract_text.py → plain text
    │
    ├─ Claude reads all courses (ignores grades/pass-fail)
    │
    ├─ Maps courses → skill categories
    │   ├─ CS courses → Technical Skills
    │   └─ Aerospace/engineering courses → Engineering & Domain Knowledge
    │
    ├─ For hands-on courses (labs, design, capstone) → prompts user to confirm projects
    │
    └─ Claude inserts extracted skills into master.md
```

---

## 5. Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| Intelligence / tailoring | Claude Code (host session) | No API key, no SDK, no extra cost |
| PDF rendering | WeasyPrint | Pure Python, CSS-based, predictable output |
| HTML conversion | markdown-it-py | Fast, no system deps, accurate CommonMark |
| PDF text extraction | pdfminer.six | Pure Python, no system deps |
| DOCX extraction | python-docx | Pure Python, handles modern Word format |
| URL fetching | requests + BeautifulSoup4 | Lightweight, controllable |
| Runtime | `~/.agents/venv/bin/python` | Consistent with all MARVIN scripts |

**Install:**
```bash
~/.agents/venv/bin/pip install weasyprint markdown-it-py pdfminer.six python-docx requests beautifulsoup4
```

---

## 6. Privacy Boundary

| Location | In git? | Contains personal data? |
|---|---|---|
| `~/.agents/skills/resume-tailor/` | Yes (public) | No |
| `~/.claude/resume/master.md` | No | Yes — full PII |
| `~/.claude/resume/tailored/` | No | Yes — full PII |
| `template/resume.css` | Yes (public) | No |
| `scripts/*.py` | Yes (public) | No — paths use `Path.home()` |

Scripts reference the master resume via `Path.home() / ".claude" / "resume" / "master.md"` — no hardcoded personal paths in the public repo.

---

## 7. Architecture Decision Records

### ADR-005: Dynamic title line, fixed experience format
**Decision:** Header title is derived from the JD title each time (dynamic). Experience uses inline bullet-point style (`• **Company:** description`) not traditional "Title | Company | Dates" blocks.  
**Rationale:** Dynamic title signals direct alignment with the role. Inline experience format is the format from the resume that landed Gil's current job — proven effective, kept as-is.  
**Trade-off:** Inline experience format is less conventional for conservative industries. Accepted: format is not modified unless Gil explicitly requests it.

### ADR-001: Claude Code skill over standalone script
**Decision:** Implement as a Claude Code skill, not a CLI script calling the Anthropic API.  
**Rationale:** Claude Code is already the execution environment; no API key management, no SDK dependency, no extra cost per run. The intelligence is the host session.  
**Trade-off:** Requires a Claude Code session to run (not usable as a pure CLI). Acceptable given the workflow.

### ADR-002: Fixed template over render-and-trim for 1-page enforcement
**STATUS: SUPERSEDED by ADR-006 (2026-07-02).**
**Decision:** Enforce 1-page via fixed slot caps (max 4 roles × 3 bullets, etc.), not by rendering and iteratively trimming.
**Rationale:** Render-and-trim requires multiple render cycles and contradicts the measure-once philosophy. Fixed caps are deterministic, fast, and produce consistent results.
**Trade-off:** Occasionally a slightly shorter output than possible. Acceptable — consistent format is a feature.
**Why superseded:** the caps were violated in practice (a 3rd project was added mid-session on 2026-07-02, pushing output to 2 pages) — "deterministic" only holds if the caps are actually respected, and there was no mechanism enforcing that. It also fought the real goal: building the strongest possible resume from master.md, not filling slots to a quota. See ADR-006.

### ADR-003: Union rule for resume merges
**Decision:** Merge always adds, never removes. Conflicts flagged with `<!-- REVIEW -->`, not resolved automatically.  
**Rationale:** Silent content deletion in a master resume is unacceptable. Human resolves ambiguity; Claude flags it.  
**Trade-off:** Master resume may accumulate `<!-- REVIEW -->` comments requiring cleanup. Acceptable given the stakes.

### ADR-004: Grades ignored in transcript parsing
**Decision:** Extract skills from all courses regardless of grade or pass/fail outcome.  
**Rationale:** Grade outcome reflects institutional factors; capability is demonstrated by having taken and engaged with the coursework. The aerospace background (~80% of a degree) is a genuine differentiator regardless of grade record.

### ADR-006: Auto-fit-to-page replaces fixed slot caps; content curated by strength, not quota
**Decision:** Replace ADR-002's fixed caps with (a) a required-sections + strength-curation content rule (design.md §4) and (b) an auto-fit render step in `render_pdf.py` that owns the 1-page guarantee mechanically.
**Rationale:** Separates two concerns that ADR-002 conflated: "what content is worth including" (a curation/writing judgment) and "does it fit on one page" (a rendering/layout mechanism). Judgment calls shouldn't be enforced by hard-coded counts; page-fit should be enforced by something that can't be silently violated by adding one more bullet.
**Trade-off:** Adds render cycles (the thing ADR-002 explicitly avoided) — accepted because WeasyPrint renders are fast (sub-second for a 1-page doc) and the alternative (silent 2-page overflow) is worse than a few extra render passes.
**Extended 2026-07-02 — bidirectional, not just shrink:** the original ladder only went downward from a fixed baseline, so a lighter resume that already fit at baseline size just stayed small, sometimes leaving the page visibly underfilled — direct user feedback. `FIT_LADDER` was rebuilt as a continuous search rather than fixed points: `_build_fit_ladder()` generates a step every 0.25pt (`BODY_STEP_PT`) from `MAX_BODY_PT` (13pt — user-specified hard ceiling, a resume shouldn't read as padded/oversized even when content is short) down to `MIN_BODY_PT` (8.5pt, the legibility floor), with every other size (name/h2/entry-title/role-header/margin/line-height) derived from body size by fixed ratios (`_make_fit_step`) — those ratios were reverse-engineered from what had been 6 hand-tuned points, where name was consistently exactly 2x body across all of them. The search keeps the *largest* body size that still fits on 1 page, so a short resume grows toward filling the page rather than sitting small in a sea of margin.

Additionally measures actual content-box fill via WeasyPrint's layout tree even at the best-fitting step; below `MIN_FILL_RATIO` (0.85), prints a note recommending added content (next-strongest project, expanded entry) rather than growing the font past the 13pt ceiling. **This measurement had a real bug on first implementation:** the recursive walk included the page's own container box when computing "how far down does content reach," and a container box's height is fixed by the CSS margins regardless of how much content it holds — so every render reported ~100% fill even for deliberately sparse test content. Fixed by only measuring leaf boxes (no children) — those reflect actual rendered text extent; container/intermediate boxes are walked through but not measured. Verified after the fix: a sparse test resume correctly reports ~52% fill, the real (content-dense) Charter resume reports ~100%. The fill-ratio check uses a private WeasyPrint API (`document.pages[0]._page_box`) with no stable public equivalent in v69 — wrapped in a try/except that returns `None` on failure, so a future WeasyPrint upgrade breaking this only silently loses the sparse-page hint, it doesn't break rendering.

### ADR-007: Blue accent color, corrected ATS rationale
**Decision:** Add a blue accent color (name text, section-header rule color); body copy stays black.
**Rationale:** Researched via CrossRef/Semantic Scholar (2026-07-02): no strong evidence that a specific color reads as "friendlier" or more trustworthy in professional documents — treat as a low-stakes aesthetic choice, not an evidence-backed lever. What *is* solid: ATS parsers extract the text stream, not pixel color, so color carries zero parsing risk. The original "black text only (ATS safe)" rule in ADR/architecture predates this check and was based on an untested assumption.
**Trade-off:** None identified — this is a free aesthetic improvement.

### ADR-008: Two-column header as a bounded exception to single-column body
**Decision:** Header (name/title/contact, ≤4 lines) uses a CSS flex two-column layout; the document body (Summary onward) remains strictly single-column.
**Rationale:** The real ATS risk is multi-column *body* text (a skills sidebar next to an experience column) — that reliably scrambles extraction order across parsers, since the reading order is spatial, not stream-based, at that point. A short header laid out via flexbox keeps the underlying HTML/PDF text stream linear (name → title → contact) regardless of visual position, because there's no reflowing body text competing across the columns. Implemented via BeautifulSoup wrapping the header cluster (see 3.4), not `column-count` CSS.
**Trade-off:** Requires HTML post-processing (was previously pure CSS-on-markdown-output) — accepted, `bs4` is already an installed dependency (used by `fetch_jd.py`).

### ADR-009: Single divider mechanism (h2 underline), manual `<hr>` removed
**Decision:** Remove all manual `---` thematic breaks from the resume markdown template. The only divider is a rule applied to every `h2` automatically.
**Rationale:** The two mechanisms (manual `hr` + automatic `h2` underline) were never meant to be visually distinguishable, but users could — some sections had a hand-placed `hr` after their content, others only had the (differently-positioned) `h2` underline before the *next* section's heading, so the page read as inconsistent. One automatic mechanism applied to every section closes off an entire class of "forgot to add the divider here" bugs.
**Trade-off:** None — strictly a simplification.
**Amended 2026-07-02:** the underline mechanism itself changed from CSS `border-bottom` to `box-shadow: 0 1pt 0 0 <color>`. Border-bottom hairlines in WeasyPrint can land on different sub-pixel Y-offsets depending on how much content precedes them, so some section headers rendered with a visibly thicker line than others (observed under Soft Skills/Achievements) — a second inconsistency bug within the "fixed" divider mechanism itself. `box-shadow` renders as a filled rectangle rather than a stroked border and isn't subject to that anti-aliasing variance.

### ADR-010: System font stack, no custom `@font-face`
**Decision:** Remove the "Inter" `@font-face` declaration; use a system sans-serif stack (`-apple-system, "Helvetica Neue", Helvetica, Arial, sans-serif`) instead.
**Rationale:** Discovered 2026-07-02 while investigating why bold Projects/Experience titles weren't visually distinct: the `@font-face` declared `font-weight: 100 900; font-style: normal;` for a single linked file that is actually only a static regular-weight, non-italic instance. WeasyPrint matched every bold/italic request to that one file anyway (the declaration said it qualified) rather than falling through to a font that actually has bold/italic faces — so every `<strong>`/`<em>` in every resume and cover letter generated by this tool had been silently rendering as plain text, since before this file's initial approval. System fonts have real, distinct bold/italic faces and don't depend on a network fetch at render time.
**Trade-off:** Loses the specific Inter typeface aesthetic in favor of the OS default sans-serif — accepted, correctness (bold/italic actually working) matters more than a specific typeface choice, and this resolves design.md §9's previously-open "Font decision" item in the offline-safe direction.

### ADR-011: Experience = one overview per company; Projects gets visual priority
**Decision:** Professional Experience uses one entry per company (bold company name + italic title/dates, one synthesized overview paragraph) instead of multiple `• **Company:**` bullets per role. Projects entries get a dedicated larger/bolder `.entry-title` treatment and the `PROJECTS` section header gets accent-colored text, distinguishing it as the resume's highest-priority section.
**Rationale:** User feedback 2026-07-02: the per-bullet Experience format (each bullet re-stating the bold company name) visually duplicated the Projects section's shape — both read as "bold label + bullet list," so Experience and Projects looked interchangeable instead of serving different purposes (narrative overview vs. itemized achievements). Fixing required both a content-structure change (Experience) and a typographic-hierarchy change (Projects) — the two were the same underlying problem (no visual/structural differentiation between section *types*), not two separate bugs.
**Trade-off:** Experience entries lose bullet-level ATS keyword granularity in favor of a synthesized paragraph — accepted, since the concept-matching approach this whole tool is built around (FR-10/FR-11) already de-prioritizes keyword-stuffing.

---

## 8. Implementation Order

1. `scripts/fetch_jd.py` + `scripts/extract_text.py` — input layer, no Claude involvement
2. `template/resume.css` — visual spec, iteratable before any logic
3. `scripts/render_pdf.py` — mechanical output, testable standalone
4. `SKILL.md` — command routing + tailoring instructions (core intelligence layer)
5. End-to-end test: paste a real JD, produce resume + PDF
6. `scripts/render_pdf.py` cover letter mode
7. `/add-to-master` command
8. `/merge-resume` command
9. `/parse-transcript` command
10. README + public repo setup
