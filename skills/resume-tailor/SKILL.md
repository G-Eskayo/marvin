---
name: resume-tailor
description: Maintain a master resume and generate tailored 1-page application packages from job descriptions. Domain-siloed — job-search specific, local-only (master resume never leaves the machine). Use for /tailor, /add-to-master, /merge-resume, /parse-transcript.
tags: [intent:resume, intent:tailor, intent:document, type:skill]
---

# Resume Tailor Skill

**Triggers:** `/tailor`, `/add-to-master`, `/merge-resume`, `/parse-transcript`  
**Purpose:** Maintain a master resume and generate tailored 1-page application packages from job descriptions.

---

## Constants

- **Master resume:** `~/.claude/resume/master.md`
- **Output base:** `~/.claude/resume/tailored/`
- **Output pattern:** `~/.claude/resume/tailored/[company-slug]-[YYYY-MM-DD]/`
- **Scripts:** `~/.agents/skills/resume-tailor/scripts/`
- **Python:** `~/.agents/venv/bin/python`

---

## Command Routing

| Invocation | Handler |
|---|---|
| `/tailor [url] [--cover-letter]` | [TAILOR] |
| `/add-to-master "..."` | [ADD-TO-MASTER] |
| `/merge-resume [path]` | [MERGE-RESUME] |
| `/parse-transcript [path]` | [PARSE-TRANSCRIPT] |

---

## [TAILOR] — Full Application Package

### Phase 1: Intake

1. If a URL was provided: run `~/.agents/venv/bin/python ~/.agents/skills/resume-tailor/scripts/fetch_jd.py <url>`
   - If it succeeds: use stdout as the JD text
   - If it fails (non-zero exit): say "Couldn't fetch that URL — please paste the job description directly."
2. If no URL: ask "Please paste the job description."
3. If `--cover-letter` was NOT in the invocation: ask "Would you like a cover letter with this application? (yes/no)"

### Phase 2: Research

Search for:
- **Company:** mission, values, product, recent news (last 12 months), tech stack, team size/stage, culture signals (startup vs. enterprise)
- **Role:** seniority signals, team context, reporting structure if visible, tech signals
- **Contact:** hiring manager name, recruiter, team lead — check company site, LinkedIn, job post

Determine output folder name: slugify company name (lowercase, hyphens, no special chars) + today's date.  
Write `~/.claude/resume/tailored/[slug]-[date]/research.md` with all findings.

### Phase 3: Tailoring

Read `~/.claude/resume/master.md` in full.

**Extract from JD:**
- Job title → use verbatim as the header title line (all-caps). If ambiguous, infer the best match.
- Semantic concepts: domain areas, responsibility types, tech clusters, cultural signals
- Aerospace/defense signals: check for keywords — systems, engineering, simulation, physics, aerospace, hardware, robotics, defence, aviation, space, dynamics, structural, fluid, orbital, DoD, government, clearance

**Score every master resume entry:**
```
combined = (relevance × 0.7) + (recency × 0.3)

recency: 1.0 = current | 0.85 = <1yr | 0.65 = 1–3yr | 0.40 = 3–6yr | 0.20 = >6yr
relevance: 1.0 = direct match | 0.6 = transferable | 0.3 = adjacent
```
**Revised 2026-07-02 — no hard item caps.** Use the score to rank and curate, not to cut at a fixed count. Required sections (always include): Summary, Professional Experience, Projects, Education. Optional sections (include only if genuinely strong/JD-relevant; cut before padding): Technical Skills, Soft Skills, Relevant Training, Achievements. Typical good curation lands around 4 roles and however many projects are genuinely strong — that's a description of what good output looks like, not a count to hit. `render_pdf.py` now auto-shrinks to fit 1 page (Phase 5), so content length is no longer what keeps the resume on one page — curation quality is. Ties broken by recency.

**Preserve exact quantities when condensing master.md bullets.** Known failure mode from 2026-07-02: "14 charts, 2 tabs" (of one dashboard) got compressed into "14 dashboards" while tailoring — same number, false claim. Before writing a shortened bullet, check every number/unit in it against the master.md source sentence. If a number can't survive compression without becoming misleading, cut the number rather than let it drift.

**Aerospace crossover signal:** If JD has any aerospace/defense/systems keyword → surface the aerospace background in:
- The summary (explicitly mention dual-discipline background)
- The Engineering & Domain Knowledge skills category
- The cover letter unique angle paragraph

**Security clearance signal:** If JD is for a government/defense/cleared role → surface "Security Clearance: Secret (Reinstatable)" prominently in the header contact block.

**Mirror company language:** Use their terminology, not generic buzzwords.

### Phase 4: Build Resume

Write `~/.claude/resume/tailored/[slug]-[date]/resume.md` using this exact template structure.

**CRITICAL FORMATTING RULE:** Every paragraph element (bullets, project titles, achievement lines) MUST be separated by a blank line. Items within the same markdown block merge into a single visual line. One blank line = one visual paragraph break.

```markdown
# GIL ESKAYO

[JD-DERIVED TITLE — ALL CAPS]

gileskayo.me  |  geskayo@gmail.com  |  linkedin.com/in/gileskayo

(650) 867-2527  |  github.com/G-Eskayo  |  U.S. Citizen[  |  Security Clearance: Secret (Reinstatable) — if defense/gov role]

[SUMMARY — 2–3 sentences. Tailored to the specific role. No "I am a..." opener. Lead with what you build, then the crossover if relevant, then the current work.]

## PROFESSIONAL EXPERIENCE

**[Company Name]** *[Title, Dates]*

[ONE synthesized overview paragraph, 2–4 sentences: role scope, tasks, and value delivered — action verbs, quantified impact where available, mirrors JD language. Do NOT split this into multiple bullets that each repeat the bold company name — that's the Projects section's shape, not this one. Combine what master.md lists as separate bullets for this role into one flowing paragraph.]

**[Company Name]** *[Title, Dates]*

[overview paragraph for the next role]

[Required section. Curate to the strongest ~4 roles — not a hard cap, a description of good curation. One entry per company/role, not per achievement. If a company genuinely has two distinct stints (e.g. promoted, or left and came back), those are two entries; multiple bullets for one continuous role are not.]

## TECHNICAL SKILLS

• **[Category] –** [skill], [skill], [skill], [skill — max 4 items per category]

• **[Category] –** [skill], [skill], [skill], [skill]

• **[Category] –** [skill], [skill], [skill], [skill]

• **[Category] –** [skill], [skill], [skill], [skill]

[Optional section — include only if genuinely strong/JD-relevant. Typically ~3–4 categories. Include Cybersecurity if JD is security-relevant. Include Engineering & Domain Knowledge if aerospace signal detected.]

## SOFT SKILLS

[skill]  ·  [skill]  ·  [skill]  ·  [skill]  ·  [skill]  ·  [skill — up to ~6, JD-matched, on one line]

## PROJECTS

**[Project Name]** *([tech stack] — [rough date, e.g. "2026" or "Q2 2026"])*

• [bullet 1 — what was built, impact, scale]

• [bullet 2 — optional, max 2 per project]

**[Project Name]** *([tech stack] — [rough date])*

• [bullet 1]

[Required section, and the resume's highest-visual-priority one (render_pdf.py gives project names a larger/bolder treatment than other bold text — see design.md §7.1). Include the strongest, JD-relevant projects — no fixed count, curated by strength. Always include a rough date in the italic parenthetical alongside tech stack — signals recency; year-level precision is enough, don't make it look like a formal dated entry.]

## EDUCATION

**B.S. Computer Science** – University of Colorado Boulder  |  August 2025

## RELEVANT TRAINING

• **[Cert name]** – [Issuer] – [one-line description of what was built/learned]

• **[Cert name]** – [Issuer] – [description]

• **[Cert name]** – [Issuer] – [description]

[Optional section — include only if present in master and genuinely relevant. Typically up to ~3, most relevant to JD. Each cert on its own blank-line-separated paragraph.]

## ACHIEVEMENTS

• **U.S. Armed Forces Veteran** – Chemical, Biological, Radiological & Nuclear (CBRN) Defense Specialist[, Security Clearance: Secret (Reinstatable) — append if defense/gov role]

• **Eagle Scout** – Highest rank in Boy Scouts; 31 merit badges and two Eagle Palms

[Include both for leadership/character-signal roles. Include just Veteran for defense/gov roles if space is tight. Bulleted + bold lead-in, same pattern as Technical Skills/Relevant Training — see the "Formatting system" note below Slot caps.]
```

**Revised 2026-07-02 — required sections and guidance, not hard caps:**
- Required, always present: Summary (2–3 sentences), Professional Experience, Projects, Education (1 line only — this one stays a hard format rule, not a content-length one)
- Optional, include only if genuinely strong: Technical Skills, Soft Skills, Relevant Training, Achievements
- Typical well-curated shape: ~3–4 skill categories × ~4 items, ~6 soft skills, ~4 roles (one synthesized overview each), however many projects are genuinely strong × ~2 bullets, ~3 certs — guidance for what good curation looks like, not limits to enforce
- 1-page fit is now the renderer's job (Phase 5 auto-shrink-to-fit), not content's job — see architecture.md ADR-006

**Formatting system, added 2026-07-02 — apply to every section, no exceptions.** Sections were drifting into random per-section formatting (some bulleted, some stacked plain lines; some bold labels, some not) with no underlying logic — direct user feedback. Every section is one of exactly two patterns:
- **Pattern A — itemized list** (2+ discrete parallel entries: skill categories, certs, achievements): `•` bullet, **bold the entry's label** (category name / cert name / achievement title), then the detail. Applies to: Technical Skills, Relevant Training, Achievements, and Projects' sub-bullets sit under this pattern too (though the project name bolding lives in the entry-title line above them, not the bullets themselves).
- **Pattern B — flowing content** (one paragraph or one line, not a list of parallel items): no bullet. Applies to: Summary, Experience's overview paragraph (though its company/title header line above it is its own bold+italic element — see Phase 4 Experience format), Soft Skills (a single comma/middot-separated descriptor line — intentionally not itemized, these are single terms not label:detail pairs), Education (bold the degree as the "label," rest of the line is detail, same convention as Pattern A's bold-then-detail shape, just without a bullet since it's one line).
When in doubt for a new/unusual master.md entry, ask: is this one of several parallel items, or one flowing statement? That answers which pattern it uses — don't invent a third shape.

### Phase 5: Render PDF

Run:
```
~/.agents/venv/bin/python ~/.agents/skills/resume-tailor/scripts/render_pdf.py \
  ~/.claude/resume/tailored/[slug]-[date]/resume.md \
  ~/.claude/resume/tailored/[slug]-[date]/resume.pdf
```

**Read stderr, not just stdout.** The renderer's auto-fit (architecture.md ADR-006) prints one of three things worth surfacing to Giles, not silently swallowing:
- `WARNING: content still spans N pages...` — content overflows even at the smallest legible size. Trim content.
- `NOTE: page is only ~X% full...` — content is sparse but plausibly fixable. Suggest the next-strongest Project from master.md or expanding an existing entry.
- `FLAG: page is only ~X% full even at the 13pt ceiling...` — **added 2026-07-02, per explicit user direction.** Content was never close to overflowing at any size in the ladder. Surface this directly and honestly: this isn't a formatting gap, it's a signal that master.md may not have enough genuinely JD-relevant content for this role. Say so plainly and let Giles make the call on whether to proceed — don't pad the resume to hide it, and don't silently proceed as if the sparse output were normal.

### Phase 6: Cover Letter (if requested)

**Mandatory pre-step, added 2026-07-02 — do this before drafting Paragraph 2.** Do NOT synthesize the "strongest match" paragraph from research.md/master.md facts alone — restating resume bullets in prose is what makes a letter read as generic/AI-written (confirmed both by direct user feedback on a real draft, and by Ask a Manager's core finding that a good letter tells the reader something the resume can't). Pick the single most relevant experience, then explicitly ask the user for the real story behind it: what was hard, surprising, or required a judgment call — not just the outcome. Draft Paragraph 2 from their actual words. Also ask, separately, why this company/role specifically — don't infer or invent motivation; if the honest reason is sensitive or shouldn't appear verbatim in the letter (e.g. career-strategy calculus), ask what can be said instead rather than fabricating generic enthusiasm.

Also, before finalizing, re-read the drafted opener against the Paragraph 1 rule below — "I'm writing to apply for..." and close variants (e.g. "I am excited to apply...") are easy to slip into even when the rule is known; this happened in the same 2026-07-02 session that produced the rule.

Write `~/.claude/resume/tailored/[slug]-[date]/cover-letter.md`. **Use blank-line separation between the name/contact/date lines** (same rule as the resume header, SKILL.md Phase 4) — without it, markdown collapses consecutive lines into one paragraph with soft line breaks, which most renderers (including this one) flatten into a single run-on line instead of three. This exact bug shipped once already (2026-07-02) before being caught.

```
# [Name]

[email]  |  [phone]

[Date]

[Hiring Manager Name], [Title] at [Company]   ← use researched name if found
[else: Dear [Company] Hiring Team,]

PARAGRAPH 1 — HOOK (3–4 sentences)
  Reference something specific and real about the company — a product, stated mission, recent
  announcement, or known challenge. Never open with "I am writing to apply for..."
  State the role and why this company specifically.

PARAGRAPH 2 — STRONGEST MATCH (4–5 sentences)
  The single most relevant experience mapped to the JD.
  Concrete: what was built, what was the impact, what was the scale.
  Use the JD's own language where it fits naturally.

PARAGRAPH 3 — UNIQUE ANGLE (3–4 sentences)
  What Giles brings that a typical candidate doesn't.
  Lead with aerospace + CS crossover if JD has any engineering/systems angle.
  Otherwise: MARVIN (self-directed agentic systems project), cross-disciplinary builder mentality,
  shipped public work.
  If clearance-relevant: mention Secret clearance reinstatable status.

PARAGRAPH 4 — CLOSE (2–3 sentences)
  Confident, not desperate. Genuine enthusiasm for the conversation.
  Clear call to action. Match company energy (direct for startups, measured for enterprise).
```

Then render:
```
~/.agents/venv/bin/python ~/.agents/skills/resume-tailor/scripts/render_pdf.py \
  ~/.claude/resume/tailored/[slug]-[date]/cover-letter.md \
  ~/.claude/resume/tailored/[slug]-[date]/cover-letter.pdf \
  --cover-letter
```

### Phase 7: Package Summary

Print:
```
✓ Application package ready: ~/.claude/resume/tailored/[slug]-[date]/
  Files:
    resume.md / resume.pdf
    [cover-letter.md / cover-letter.pdf — if generated]
    research.md

  Key matches: [top 3 JD concepts → master resume entries that scored highest]
  Title used: [derived title]
  Contact found: [name + title if found, else "not found — used generic salutation"]
  Aerospace signal: [yes/no — surfaced or not]
  Clearance surfaced: [yes/no]
```

---

## [ADD-TO-MASTER] — Add New Entry

Input: natural language description of a new experience, project, skill, cert, or achievement.

1. Identify which section the entry belongs in (Experience / Projects / Skills / Relevant Training / Achievements)
2. Format it following the conventions in that section
3. For Experience: convert to action-verb bullets, extract implicit dates if mentioned
4. Insert at the correct chronological position (most recent first)
5. Write the updated master.md
6. Confirm: "Added to [Section]. Review: ~/.claude/resume/master.md"

---

## [MERGE-RESUME] — Merge Uploaded Resume

Input: file path to .pdf, .docx, .md, or .txt resume

1. Run `~/.agents/venv/bin/python ~/.agents/skills/resume-tailor/scripts/extract_text.py <path>`
2. Parse the extracted text into sections matching master.md structure
3. For each item:
   - **No match in master:** add to master in correct section and position
   - **Exact match:** skip (already present)
   - **Same entity, different content** (same company + overlapping dates, different title or bullets): keep ALL content, add `<!-- REVIEW: same company/dates, different content — verify and consolidate -->`
4. Write merged master.md
5. Print: "Merge complete: N added, N flagged for review (<!-- REVIEW --> comments), N unchanged"

**Rule:** NEVER silently remove any content from the master resume. Union only.

---

## [PARSE-TRANSCRIPT] — Extract Skills from Academic Transcript

Input: file path to transcript (.pdf or .txt)

1. Run `~/.agents/venv/bin/python ~/.agents/skills/resume-tailor/scripts/extract_text.py <path>`
2. Read ALL courses regardless of grade or pass/fail status
3. Map courses to skill categories:
   - CS/programming/data/AI courses → Technical Skills (add to appropriate subcategory)
   - Aerospace/engineering/physics/math courses → Engineering & Domain Knowledge
   - Leadership/military courses → Achievements section (if veteran-relevant) or Soft Skills
4. For courses implying hands-on work (labs, capstone, design courses, experimental courses):
   - Ask: "[Course name] — did this involve a project worth adding to your Projects section?"
5. Identify any new skills not already in master.md and add them
6. Print: "Parsed [N] courses. Added: [N] skills to Technical Skills, [N] to Engineering & Domain Knowledge, [N] projects flagged for review."

**Rule:** Grades do not gate skill extraction. ~80% of an aerospace engineering degree = genuine domain knowledge regardless of grade record.

---

## Quality Checks (apply to all outputs)

- No "Responsible for..." openers — use action verbs (Built, Designed, Led, Developed, Implemented)
- No years-of-experience filtering from JD applied to master resume entries
- No GPA, no honors, no coursework in Education section of tailored resume
- No photo placeholder
- No personal data in any file under `~/.agents/skills/resume-tailor/` (public repo)
- All scripts run via `~/.agents/venv/bin/python`
