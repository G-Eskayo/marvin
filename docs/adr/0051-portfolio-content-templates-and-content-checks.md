# 0051. Portfolio content templates, content checks and a portfolio-page skill

Date: 2026-10-06. Status: accepted.

## Context

The portfolio's templates cover layout only: page and component markup, the evaluator's geometry checks, and an add-project
spec that takes one free-form `body_html`. Nothing says what a page should *say*. On 2026-10-06 five pages (MARVIN, Clarity
Captions, Resume Tailor, Paper Dive and SkineeDipping's fixes) were rebuilt by hand around a structure Gil approved: story first
in his voice, real evidence, architecture diagrams, verified claims, privacy blurring and links between MARVIN and what it
built. That knowledge lived only in one session. Gil asked for it to be captured in the templates and the Portfolio tab and
applied to more pages.

## Decision

1. **Content templates**, one per page type, in the portfolio repo at `templates/content/<type>.json`: `skill-tool`,
   `app-product`, `system`, `ml-study`. Each lists the lead's job and the sections in order, each with a `role` id, its purpose,
   whether it is required, and the evidence it needs (`real-output`, `screenshot`, `diagram`, `chart`, `numbers`, `link`).
   Diagram sections name a starter diagram (`setup`, `run`, `marvin`).
2. **Content files carry roles.** Each long-form page's source (`content/longform/<slug>.json`) gains `content_type`, and each
   section a `role` matching its template. Coverage (which required roles and evidence a page has) is computed from these
   files, never stored.
3. **The guide** (`templates/GUIDE.md`, edited in the Guide & rules tab) gains the content rules: the "sell it" voice (the
   writing-style skill's portfolio register), verified claims, the privacy checklist, never naming competitors, and honest status.
4. **Content checks in the Evaluation**, from `lib/portfolio_content.py`: AI-writing phrases and em-dashes in page copy; every
   long-form page has at least one evidence figure; every image has alt text; a page that says it was built with MARVIN links
   to the MARVIN page and the MARVIN page links back; coverage gaps against the page's template.
5. **A Content view in the Portfolio tab** shows each page's template and its gaps.
6. **A diagram kit**: the house Mermaid theme and starter diagrams in `templates/diagrams/`, and `lib/portfolio_diagrams.py`
   to render a page's diagrams (sources in `docs/diagrams/<slug>/`) to `deploy/longform/figures/<slug>/`.
7. **A `portfolio-page` skill** that runs the workflow: gather and verify facts, capture evidence, draw diagrams, write in the
   portfolio voice, author on the dev site, run the pipeline, review the rendered page.

## Consequences

- A new page starts from a template instead of from memory, and the Evaluation catches a page that drifts from it.
- Phrase checks are heuristics: they flag, a person decides. False positives are tolerated; the list lives in one place.
- Pages not yet converted to long form have no content file, so they show as "not on a template" rather than as failures.
- Templates are data in the portfolio repo (reviewed like any repo change); the checks and the skill live in MARVIN.
