# In-browser resume matching vs the AI resume tailor — 2026-10-07

## Question

Gil wants the gileskayo.me resume page to have the master resume (PDF download button) plus a "tailor to a job"
option. Before choosing in-browser matching (free, nothing leaves the visitor's browser) or an AI step, measure
how close in-browser matching gets to the AI resume tailor. If it reaches parity, a **Chrome extension resume
tailor** becomes a project idea.

## Decided page shape

One resume page: master resume shown, a **Download master PDF** button, and the "paste a job description →
download tailored PDF" box on the same page.

## Experiment (zero paid LLM calls)

- **Reference:** the 12 resumes the AI tailor already produced (`~/.claude/resume/tailored/*/resume.md`), each
  with its job description summarised in `research.md` (role, qualifications, responsibilities).
- **Inputs to the browser methods:** the job text (research.md minus company / contact / signals / sources) and
  the master resume (`~/.claude/resume/master.md`).
- **Methods** (all runnable in a browser):
  - **A. Keywords:** TF-IDF-weighted word overlap (plain JavaScript).
  - **B. Meaning:** all-MiniLM-L6-v2 sentence embeddings, the model transformers.js runs in the browser (~23 MB).
    Same ONNX model locally via chromadb's default embedding function.
  - **C. Hybrid:** average of A and B (rank-normalised).
- **Measured:**
  1. **Project selection:** overlap between a method's top-k projects and the k the AI chose (k = 3–5 of ~15).
     Random baseline ≈ k/15.
  2. **Order:** whether the AI's first-listed project is in the method's top-k.
  3. **Skills:** overlap between the method's top skill terms and the terms the AI listed.
- **Not measurable by in-browser matching (qualitative):** rewriting bullets and the summary in the job's
  language, company research, cover letters.

## Privacy

`master.md` is never committed. Per-job outputs stay in `~/.claude/resume/experiments/`. Only the script and
aggregate numbers are committed here.

## Results

Run 2026-10-07, `skills/resume-tailor/experiments/browser_parity.py`. 12 jobs, 15 master projects, 127 skill
terms, 46 of 47 AI project titles mapped back to the master (1 unmapped). n = 12 jobs with 3–5 picks each, so
differences under ~10 points are noise.

### Project selection: agreement with the AI tailor

| Method (all in-browser) | Projects in common with the AI | AI's #1 project in top-k | Skills in common |
|---|---|---|---|
| Random | 26% | — | 15% |
| Fixed favourites only (no job reading)¹ | 54% | — | — |
| A. Keywords | 55% | 75% | 37% |
| B. Meaning (MiniLM) | 49% | 75% | 32% |
| C. Hybrid | 50% | 75% | 38% |
| **Hybrid + flagship weight (w = 0.5)¹** | **65%** | 75% | — |

¹ Flagship weight = how often the AI picked each project for the *other* 11 jobs (leave-one-out, so no job
sees its own answer). On the site this would be a priority Gil sets once per project.

### What it means

- The AI's picks are about half **editorial**: Agent Topology was chosen for 9/12 jobs and MARVIN for 8/12.
  Always showing the same favourites already matches 54%, as well as keyword matching does.
- Reading the job adds ~10 points on top of good favourites (65% best). The misses are **domain reasoning**:
  York Space (defense/space) — the AI chose "Designing for Defense — Orbital Data Fusion", keywords scored 0%;
  Google ML infra — keywords chose Social Media and Resume Tailor on shallow word overlap.
- The small meaning model (MiniLM) did **not** beat keywords here; it is too small to know that "battle
  management" relates to "orbital data fusion".
- Not measured, and not possible with matching: the AI **rewrites** every bullet and the summary in the job's
  language and researches the company. That is most of what makes a tailored resume read as tailored.

### Verdict

- **Website:** in-browser matching is good enough for "reorder and highlight my real projects for this job", with
  Gil-set flagship priorities. Not parity with the AI tailor; frame it as "matched", not "tailored".
- **Chrome extension at AI parity:** not with matching alone. Possible next step: Chrome's on-device model
  (Gemini Nano via the built-in Prompt/Rewriter APIs, free, nothing leaves the device; availability to verify)
  for the rewriting step. Worth its own experiment before calling it a project.
- **Caveat:** the AI tailor is the reference, not ground truth. A blind A/B (Gil rates two versions per job
  without knowing which is which) would test whether the gap matters to a reader.
