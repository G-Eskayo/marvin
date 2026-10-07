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

## Next steps (2026-10-07)

- **Tickets:** #221 resume page + master PDF → #222 in-browser match box → #223 matched PDF download. Layout/mobile: #219.
- **Blind A/B test** (`skills/resume-tailor/experiments/blind_ab.py`): 6 jobs chosen for spread (high and low
  agreement), AI-tailored vs browser-matched (keywords + priority, w = 0.5), both rendered with the same
  `render_pdf.py` template, randomly labelled X/Y. Gil rates locally in `~/.claude/resume/experiments/blind/rate.html`;
  the key is kept outside that folder. Score with `blind_ab.py score <ratings.json>`. Both versions share the
  header and the Education/Training/Achievements sections, so only summary, experience, skills and projects differ.
- **Export cleanup found while building it** (now in #221): master project bullets include tech-stack lines and
  `[Project Link]` placeholders, and a title carries italic markup; the public export must clean these.

## Blind A/B result (rated by Gil, 2026-10-07)

| Job | Preferred | Gap | Why (Gil's note, paraphrased) |
|---|---|---|---|
| DaVita AI SWE | **Browser** | clear | Browser picked better roles; AI version included Snorkel, which Gil wants off the master |
| Home Depot | AI | big | Browser version ran to **2 pages** |
| Google AI/ML | AI | small | — |
| York Space (defense) | Tie | clear both ways | AI chose better projects; browser text "looks more AI-generated" |
| Tokin' Jew | AI | small | AI a little more specific to the job |
| Check Point AI Security | AI | small | Browser version ran to **2 pages**, though it "looks a little higher in quality" |

Raw: AI 4, browser 1, tie 1. But 2 of the AI's 4 wins came from the browser version overflowing one page
(confirmed: job2-X and job6-Y are 2 pages; every other PDF is 1). That's a length-budget bug, not matching
quality, and in one of them Gil preferred the browser version's content. Without overflow: AI 2 small wins,
browser 1 clear win, 1 tie, 1 leaning browser. n = 6, one rater: directional only.

### Takeaways

- In-browser matching is **closer to the AI tailor in reader preference than the 63% overlap suggested**. The
  AI's real edge is domain reasoning on unusual roles (York Space) and small job-specific wording gains.
- **One-page length budget is mandatory** for the browser version: pick bullets under a character budget, not
  "top 2". Added to #223.
- **Master resume quality matters as much as the method:** the browser version shows master bullets verbatim, and
  they read as AI-written. A `writing-style` pass on the master improves both versions. Snorkel to be removed or
  marked never-include (Gil's call).
- **Chrome extension:** viable enough to explore. Matching + length budget + good master text gets close; Chrome's
  on-device model could add the job-specific wording. Re-run this blind test after those fixes before deciding.
