# Design Document — Resume Tailor

**Version:** 1.1-draft  
**Date:** 2026-06-29  
**Status:** Draft — awaiting template approval and resume/transcript uploads

---

## 1. User Flows

### Flow A: Full application package (`/tailor`)

```
User: /tailor [optional URL] [--cover-letter]

PHASE 1 — INTAKE
  → If URL given: fetch_jd.py attempts fetch
      → Success: JD text in context
      → Fail: "Couldn't fetch — please paste the job description"
  → User pastes JD (or fetch succeeded)
  → If --cover-letter not specified: "Would you like a cover letter? (yes/no)"

PHASE 2 — RESEARCH
  → Claude searches: company overview, mission, culture, recent news, tech stack
  → Claude searches: role context, team structure, seniority signals
  → Claude searches: potential contacts (hiring manager, recruiter, team lead)
  → Writes ~/.claude/resume/tailored/[company]-[date]/research.md

PHASE 3 — TAILORING
  → Claude reads ~/.claude/resume/master.md in full
  → Extracts JD concepts: skills, responsibilities, domain, tone, cultural signals
  → Scores all master resume entries: relevance × 0.7 + recency × 0.3
  → Selects top candidates for each template slot (ignores years requirements)
  → Mirrors company language; incorporates research findings

PHASE 4 — OUTPUT
  → Writes resume.md (fixed template, all caps enforced)
  → render_pdf.py → resume.pdf
  → If cover letter: writes cover-letter.md → cover-letter.pdf
  → "Done. Saved to ~/.claude/resume/tailored/acme-corp-2026-06-29/"
  → Prints package summary (files created, contact found/not found, key matches)
```

### Flow B: Add entry (`/add-to-master`)

```
User: /add-to-master "freelance ML consulting for Startup X, built a RAG pipeline, 3 months early 2026"
  → Claude identifies section: Experience
  → Claude formats as standard entry (action verbs, dates, bullets)
  → Claude inserts at correct chronological position
  → "Added to Experience. Review: ~/.claude/resume/master.md"
```

### Flow C: Merge uploaded resume (`/merge-resume`)

```
User: /merge-resume /path/to/old-resume.pdf
  → extract_text.py pulls plain text from file
  → Claude parses into sections
  → For each item, match against master (company+dates for roles; name for skills/certs):
      → New: add to master
      → Exact duplicate: skip
      → Same entity, different content: union of bullets, keep all, add <!-- REVIEW -->
  → Write merged master.md
  → "Merge complete: 7 added, 2 flagged for review, 14 unchanged"
```

### Flow D: Parse transcript (`/parse-transcript`)

```
User: /parse-transcript /path/to/transcript.pdf
  → extract_text.py pulls text
  → Claude reads all courses regardless of grade/pass-fail status
  → Extracts: domain knowledge areas, tools mentioned, lab/project work
  → Maps to skill categories (Technical Skills, Engineering & Domain Knowledge)
  → For courses implying hands-on work (labs, design courses, capstone):
      → Prompts: "ASEN 2001 Structures lab — did this involve a project worth adding?"
  → Adds extracted skills to master.md
  → "Parsed 47 courses. Added: 12 technical skills, 9 engineering domain skills,
     3 projects flagged for your review."
```

---

## 2. Skill Commands

| Command | Trigger | Produces |
|---|---|---|
| `tailor` | `/tailor [url] [--cover-letter]` | Full application package |
| `add-to-master` | `/add-to-master "..."` | Updated master.md |
| `merge-resume` | `/merge-resume [path]` | Merged master.md with diff summary |
| `parse-transcript` | `/parse-transcript [path]` | Skills/projects added to master.md |

---

## 3. Scoring & Selection Algorithm

### 3.1 Relevance score

For each master resume entry (role, project, skill):

1. Extract from JD:
   - **Job title** — used verbatim as the header title line (e.g. "SENIOR ML ENGINEER"). If the JD title is ambiguous or generic, Claude infers the most accurate match. Fallback: master resume default title.
   - **Concepts** — not keywords, but semantic units:
     - Domain areas ("distributed systems", "computer vision", "aerospace simulation")
     - Responsibility types ("led a team", "shipped production code", "client-facing")
     - Technology clusters ("Python + ML pipeline", "React + TypeScript front-end")
     - Soft signals ("fast-paced startup", "cross-functional collaboration", "ownership")

2. Score each master entry against those concepts semantically:
   - Direct match (same domain, same tech): high score
   - Transferable match (different domain, same concept): medium score
   - Indirect signal (related skill, adjacent domain): low score
   - Years-of-experience requirements: **ignored entirely**

### 3.2 Recency score

```
recency_score = 1.0 if current role
recency_score = 0.85 if ended < 1 year ago
recency_score = 0.65 if ended 1–3 years ago
recency_score = 0.40 if ended 3–6 years ago
recency_score = 0.20 if ended > 6 years ago
```

### 3.3 Combined score

```
combined = (relevance × 0.7) + (recency × 0.3)
```

Score ranks entries for curation; it is not a cutoff. **Revised 2026-07-02:** no fixed count of roles/projects fills the template — Experience is one entry per company (synthesized overview, not per-bullet), Projects includes however many are genuinely strong. If two entries score equally, the more recent wins ties in ordering.

### 3.4 Aerospace crossover signal

When the JD contains any of: systems, engineering, simulation, physics, aerospace, hardware, robotics, defence, aviation, space, dynamics, structural, fluid, orbital — the skill SHALL surface the aerospace background prominently in:
- The summary (explicitly mention the dual-discipline background)
- The Engineering & Domain Knowledge skills section
- The cover letter unique differentiator paragraph

---

## 4. Template Slots — revised 2026-07-02

**Required, always present:** Header, Summary, Professional Experience, Projects, Education.
**Optional, included only when master.md has genuinely strong, JD-relevant content:** Technical Skills, Soft Skills, Relevant Training, Achievements — cut before padding.

```
HEADER          → always full (from frontmatter, never truncated)
SUMMARY         → 2–3 sentences, generated per role
TECH SKILLS     → optional; ~3–4 categories × ~4 items if included
SOFT SKILLS     → optional; up to ~6 items, JD-matched
EXPERIENCE      → required; ~4 roles, one synthesized overview paragraph each (not per-bullet), curated by strength
PROJECTS        → required, highest visual priority; however many are genuinely strong × ~2 bullets each, curated by strength — no count target
EDUCATION       → required; 1 line: Degree | Institution | Year (no GPA, no honors)
CERTIFICATIONS  → optional; up to ~3, omit entirely if empty
```

**Why this changed:** the original hard caps (§4 v1) were meant to guarantee 1-page fit, but they were violated in practice (a 3rd project was added mid-session, pushing the Charter-Spectrum resume to 2 pages) and they fight the actual goal — building the *strongest* resume from master.md, not filling every slot to a quota. Page-fit is no longer content's job; it's the renderer's (see §7, auto-shrink-to-fit). Content's job is to tell one coherent story: competent engineer, easy to work with, strong team addition. The counts above are what "well-curated" typically looks like, not limits to hit or avoid.

---

## 5. Cover Letter Structure

```
[Contact block: name, email, phone, date]

[Hiring manager name if found, else "Dear [Company] Hiring Team"]

PARAGRAPH 1 — HOOK (3–4 sentences)
  Specific, genuine opening. Reference something real about the company —
  a product, a stated mission, a recent announcement, a known challenge.
  State clearly what role and why this company specifically.
  NOT: "I am writing to apply for..." — that opener is dead.

PARAGRAPH 2 — STRONGEST MATCH (4–5 sentences)
  The single most relevant experience from the master resume mapped to the JD.
  Concrete: what was built, what was the impact, what was the scale.
  Use the JD's own language where it fits naturally.

  **Added 2026-07-02 — mandatory pre-step:** do NOT draft this paragraph from research.md/
  master.md facts alone. Restating resume bullets in prose is exactly what reads as generic/
  AI-written (confirmed both by user feedback on a real draft and by Ask a Manager's core
  finding: a good letter tells the reader something the resume can't). Before drafting,
  explicitly ask the user for the real story behind the chosen experience — what was hard,
  surprising, or required a judgment call, not just the outcome. Draft from their actual
  words, not synthesized-sounding facts.

PARAGRAPH 3 — UNIQUE ANGLE (3–4 sentences)
  What Giles brings that a typical candidate doesn't.
  Lead with the aerospace + CS crossover when JD has any engineering/systems angle.
  Otherwise: the self-directed MARVIN project, the cross-disciplinary background,
  the builder mentality with shipped public work.

PARAGRAPH 4 — CLOSE (2–3 sentences)
  Confident, not desperate. Express genuine enthusiasm for the conversation.
  Clear call to action. Match company's energy (direct for startups, measured for enterprise).
```

---

## 6. Prototype Output Sample

**STATUS: SUPERSEDED 2026-07-02 — re-approval given in session (two-column header, no manual
`---` dividers between sections, no hard content caps, blue accent color). The single-column
plain-text mockup below is stale; it predates the visual spec changes in §7. Section order and
content rules (§ requirements.md 6.1–6.2) still apply. New locked sample TBD once
`template/resume.css` v2 is rendered and approved.**

Format derived from Gil's AI Engineer resume (the resume that landed his current job). Additions vs. source: Soft Skills section, Engineering & Domain Knowledge skills category (aerospace background), dynamic title line.

---

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GIL ESKAYO
AI SOFTWARE ENGINEER

Portfolio: gileskayo.me  |  geskayo@gmail.com  |  linkedin.com/in/gileskayo
(650) 867-2527  |  github.com/G-Eskayo  |  U.S. Citizen

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

AI engineer and systems builder with a rare crossover in aerospace engineering
and computer science, specializing in agentic systems, LLM evaluation pipelines,
and AI-driven data products. Currently leading back-end architecture for an
AI-powered mobile app and building LLM benchmarking infrastructure at Snorkel AI.

PROFESSIONAL EXPERIENCE

• Nourished Mobile App: Leading Python-based back-end development and system
  architecture for a swipe-based food discovery app, designing APIs, feed
  algorithms, and dietary preference systems for AI-driven personalization.

• Snorkel AI (Forbes Top 50 AI): Developing Python-based LLM benchmarking tasks,
  evaluation workloads, and task execution pipelines for reasoning models in
  Dockerized environments.

TECHNICAL SKILLS

• AI & Machine Learning – LLM, RAG, Autonomous Agents, Supervised & Unsupervised
  Learning, NLP, Model Evaluation, Feature Engineering, NumPy, scikit-learn,
  pandas, TensorFlow, LightGBM

• Programming & Software Engineering – Python, SQL, JavaScript, Node.js, Java,
  Flask, RESTful APIs, PostgreSQL, Data Structures, Algorithms, Design Patterns

• Frameworks, Platforms & Dev Tools – Git/GitHub, Docker, AWS, Claude Code,
  ChromaDB, Ollama, VS Code, Jupyter Notebook, Unix/Linux Shell Scripts

• Engineering & Domain Knowledge – Aerospace Systems, Orbital Mechanics,
  Structural Analysis, Fluid Dynamics, Thermodynamics, Space Domain Awareness,
  Systems Engineering, SysML

SOFT SKILLS

Systems thinking  ·  Technical communication  ·  Cross-functional collaboration
Self-directed learning  ·  Ownership mentality  ·  Iterative problem-solving

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PROJECTS

Hackathon 1st Place – Autonomous Marketplace Flipper AI Agent (AI Tinkerers SF)
• Built intelligent buyer/seller/broker AI agents on LiquidMetal AI Raindrop and
  Vercel V0 to scan listings, value assets, negotiate, and flip inventory with
  live P&L tracking.

MARVIN – Memory-Augmented AI Skill Layer for Claude Code  (GitHub)
• Self-improving memory and skill system with semantic retrieval, AST-based code
  quality analysis, and 20+ auto-invoked skills; benchmarked and publicly released.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

EDUCATION
B.S. Computer Science – University of Colorado Boulder  |  August 2025

RELEVANT TRAINING
• ML-Powered Resume Selector with Naive Bayes – Coursera – NLP pipeline achieving
  97–100% accuracy classifying resumes via bag-of-words features.
• The Complete Python Developer – Zero to Mastery (Udemy) – Advanced Python,
  OOP, RegEx, Functional Programming.
• Web Security & Bug Bounty – Zero to Mastery (Udemy) – Attack vectors and
  mitigation strategies.

ACHIEVEMENTS
U.S. Armed Forces Veteran – Chemical, Biological, Radiological & Nuclear (CBRN) Defense Specialist
Eagle Scout – Highest rank in Boy Scouts; 31 merit badges and two Eagle Palms
```

---

---

## 7. PDF Visual Specification (`template/resume.css`) — revised 2026-07-02

| Property | Value |
|---|---|
| Page size | US Letter (8.5" × 11") |
| Margins | scale with the auto-fit ladder (0.25pt body-size increments, 13pt ceiling down to 8.5pt floor — see architecture.md ADR-006) |
| Header layout | two-column flex row: name+title left, contact links right (bounded exception to NFR-02, see requirements.md) |
| Name | starts at 20pt, bold, all-caps |
| Section headers | 8.5pt, bold, all-caps, 1.5px letter-spacing, `border-bottom` — the **sole** divider mechanism |
| Body text | starts at 10pt |
| Line height | starts at 1.3 |
| Dividers | h2 `border-bottom` only. Manual `---` thematic breaks between sections are **removed** from the template — they were the cause of the inconsistent "some sections have a line, some don't" bug (some sections got a hand-placed `<hr>`, others only had the (invisible-looking, attached-to-heading-text) h2 underline). One mechanism, always applied, can't drift out of sync. |
| Accent color | a professional blue accent (exact hex TBD in CSS), applied to name text and/or h2 border color. Body copy stays black for print contrast/readability. **Correction to prior spec:** color does not affect ATS parsing — parsers read the text stream, not pixel color — so "black only (ATS safe)" was based on an incorrect premise. The real ATS risk is multi-column *body* layout (§ NFR-02), not color. |
| Font | System sans-serif stack (`-apple-system, "Helvetica Neue", Helvetica, Arial`) — no custom @font-face. **Revised 2026-07-02:** the prior Inter @font-face falsely claimed weight range 100-900/normal style for a single static regular file; WeasyPrint matched bold/italic requests to it anyway instead of falling through, so every `<strong>`/`<em>` silently rendered as plain text. Resolves the open Font decision item below in favor of offline-safe/reliable. |
| Bullet symbol | `•` en-dash style, not `–` |
| Single-page enforcement | **Auto-shrink-to-fit**, not fixed caps: render, check WeasyPrint page count, step font-size/margin/line-height down through a small ladder until page count is 1 or a legibility floor is hit (below which: warn the user and suggest trimming content rather than shrinking further). Replaces the old "content capped to guarantee 1 page" approach, which broke when content exceeded the caps mid-session. |

Cover letter shares the resume's font, accent color, and header treatment (name/date block styled to match) so the two documents read as one visual system — this was previously undocumented/inconsistent (cover letter CSS overrode font-size only, no shared accent or header style).

### 7.1 Visual hierarchy pass — revised 2026-07-02 (second pass, post-first-render feedback)

The first render fixed structural consistency (one divider mechanism, 1-page fit) but was visually flat — everything read as the same weight of bulleted text, so Experience and Projects looked like duplicates of each other, and nothing signaled which section mattered most. Fixes:

| Property | Value |
|---|---|
| Experience format | One entry per company (bold name + italic title/dates), one synthesized overview paragraph — not repeated `• **Company:**` bullets. See requirements.md §6.2. This was the actual duplication bug: Experience and Projects had converged on the same "bold label + bullets" shape. |
| Projects visual priority | Project name paragraphs get a dedicated `.entry-title` class (post-processed via BeautifulSoup, not just `<strong>`): larger font-size than body text, bold. Tech stack + rough date share an italic parenthetical directly after the name (e.g. `**Cost Intelligence Platform** *(Lambda, EventBridge, Aurora Serverless v2 — 2026)*`) — signals recency without a formal dated-entry look. The `PROJECTS` `h2` itself also gets slightly stronger treatment than other section headers (accent-colored text, not just the underline) to read as the resume's highest-priority section. |
| Bold/italic system | Bold = names (company, project). Italic = context (title, dates, tech stack). This pairing is applied consistently everywhere it appears, not just in Projects — Experience company/title line uses the same convention. |
| Portfolio link | No `Portfolio:` label — the bare domain (`gileskayo.me`) is self-evidently a portfolio link; the label was redundant. |
| Divider rendering fix | `h2 { border-bottom }` is a hairline border, and WeasyPrint hairline borders can land on different sub-pixel Y-offsets depending on how much content precedes them, making some render crisper/thinner than others (observed under Soft Skills/Achievements — less content above them shifted their border to a different fractional position than sections with more preceding text). Switched to `box-shadow: 0 1pt 0 0 <color>` on `h2`, which renders as a filled rectangle rather than a stroked border and isn't subject to the same anti-aliasing variance — thickness now genuinely uniform regardless of position on the page. |

---

## 8. Merge Logic Detail

```python
for each section in uploaded_resume:
    for each item in section:
        match = find_in_master(item, method="semantic + company + dates")
        if match is None:
            master.add(item)                        # new — add it
        elif content_identical(item, match):
            pass                                    # exact dup — skip
        else:
            master.union_bullets(item, match)       # keep all bullets
            if ambiguous_entity(item, match):
                annotate("<!-- REVIEW: same company/dates, different title or content -->")
```

Ambiguous = same company + overlapping dates but different title or significantly different bullet content. Claude keeps everything and flags for human review rather than choosing.

---

## 9. Open Items (resolve before implementation)

- [ ] **Template approved** — Giles reviews §6 sample, confirms or requests changes
- [ ] **Resumes uploaded** — format refined to match newer resume style
- [ ] **Transcript uploaded** — aerospace courses extracted into master
- [ ] **Location** — confirm city/state for frontmatter header
- [ ] **WeasyPrint install confirmed** — `~/.agents/venv/bin/pip install weasyprint`
- [x] **Font decision** — RESOLVED 2026-07-02: system font (offline-safe), after the Inter @font-face was found to silently break all bold/italic rendering. See §7.
- [ ] **Repo created** — `G-Eskayo/resume-tailor` on GitHub
