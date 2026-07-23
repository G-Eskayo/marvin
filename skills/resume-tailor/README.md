# Resume Tailor

A Claude Code skill that maintains a master resume and generates tailored 1-page application packages — resume + cover letter — from any job description.

**Public repo:** code only. All personal data stays local.

---

## What it does

- **Researches** the company, role, and contacts before tailoring
- **Semantically matches** your experience to the job description (concepts, not keywords)
- **Scores and curates** experience entries: relevance × 0.7 + recency × 0.3 — no fixed item counts, the strongest entries win and a bidirectional auto-fit render step (13pt down to 8.5pt) guarantees one page regardless of how much content is genuinely strong
- **Renders PDF** via WeasyPrint — system-font bold/italic (a broken `@font-face` silently made every resume's bold/italic render as plain text until this was caught), a two-column header, and one consistent divider mechanism across every section
- **Writes cover letters** grounded in company research and *your actual story* — the strongest-match paragraph is drafted from what you say happened, not synthesized from resume facts alone; no "I am writing to apply for..." openers
- **Maintains a master resume** locally: add entries, merge uploaded resumes, parse transcripts

---

## Commands

| Command | What it does |
|---|---|
| `/tailor [url] [--cover-letter]` | Full application package from a JD URL or paste |
| `/add-to-master "..."` | Add a new experience, project, cert, or skill in natural language |
| `/merge-resume [path]` | Merge an uploaded resume file into your master (union rule — never deletes) |
| `/parse-transcript [path]` | Extract skills and domain knowledge from an academic transcript |

---

## Setup

### 1. Install system dependency (macOS)

WeasyPrint needs Pango from Homebrew:

```bash
brew install pango
```

### 2. Install Python dependencies

```bash
~/.agents/venv/bin/pip install weasyprint markdown-it-py pdfminer.six python-docx requests beautifulsoup4
```

### 3. Create your master resume

```bash
mkdir -p ~/.claude/resume
```

Create `~/.claude/resume/master.md` with this frontmatter:

```yaml
---
name: Your Name
title: Your Default Title
email: you@example.com
phone: (000) 000-0000
location: City, State
linkedin: https://linkedin.com/in/yourhandle
github: https://github.com/YourHandle
portfolio: https://yoursite.com
citizenship: U.S. Citizen
---
```

Then add your full experience, projects, skills, education, certs, and achievements — no length limit. This is your single source of truth.

### 4. Wire the skill (Claude Code)

Add to your `~/.claude/CLAUDE.md` skill routing table:

```
| `resume-tailor` | `/tailor`, `/add-to-master`, `/merge-resume`, `/parse-transcript` |
```

---

## How tailoring works

1. Fetches the job description (URL or paste)
2. Researches the company: mission, culture, tech stack, recent news, contacts
3. Extracts semantic concepts from the JD — not keywords, but ideas, domains, responsibility types
4. Scores every master resume entry on relevance (0–1) and recency (0–1), combined as `relevance × 0.7 + recency × 0.3`
5. Curates by score — Experience, Projects, Summary, and Education are required; Skills/Training/Achievements only make the cut if genuinely strong. No fixed role/project counts; the renderer's auto-fit handles page-length, not content curation
6. Mirrors the company's language and surfaces the experiences most likely to resonate
7. Writes resume.md → renders resume.pdf

Years-of-experience requirements in the JD are ignored entirely.

---

## Output

Each application generates a complete package at `~/.claude/resume/tailored/[company]-[YYYY-MM-DD]/`:

```
research.md        — company, role, and contact research
resume.md          — tailored 1-page resume (Markdown)
resume.pdf         — tailored 1-page resume (PDF)
cover-letter.md    — tailored cover letter (Markdown, if requested)
cover-letter.pdf   — tailored cover letter (PDF, if requested)
```

---

## Privacy model

| Location | Public? | Personal data? |
|---|---|---|
| This repo (`~/.agents/skills/resume-tailor/`) | Yes | No |
| `~/.claude/resume/master.md` | No — local only | Yes |
| `~/.claude/resume/tailored/` | No — local only | Yes |

Scripts use `Path.home()` for all personal paths. No hardcoded personal information anywhere in this repo.

---

## Tech stack

| Component | Library |
|---|---|
| PDF rendering | [WeasyPrint](https://weasyprint.org/) |
| Markdown → HTML | [markdown-it-py](https://github.com/executablebooks/markdown-it-py) |
| PDF extraction | [pdfminer.six](https://github.com/pdfminer/pdfminer.six) |
| DOCX extraction | [python-docx](https://python-docx.readthedocs.io/) |
| URL fetching | [requests](https://docs.python-requests.org/) + [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) |
| Runtime | `~/.agents/venv/bin/python` (shared with [MARVIN](https://github.com/G-Eskayo/marvin)) |

---

## Related

- **[MARVIN](https://github.com/G-Eskayo/marvin)** — Memory-Augmented AI Skill Layer for Claude Code. Resume Tailor is installed as a MARVIN skill and uses the shared venv.
