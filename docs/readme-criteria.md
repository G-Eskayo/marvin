# What a README is for, and how to tell a good one

Status: working criteria, 2026-10-05. Used by the `readme` skill (`skills/readme/`) and checked in part by
`lib/readme_audit.py`. Evidence is tiered the way the research skill tiers it; read the confidence notes before treating any
single criterion as law.

## The job

A README is the front door of a repository. A visitor arrives with one question ("is this what I need, and can I trust it?")
and a few seconds. It must answer that, get them to a first success, and point them to everything deeper. It is **not** the
whole manual (see Scope).

Six goals follow. Each has a test a reader can apply and, where possible, a check a program can run.

| # | Goal | The reader's question | Mechanical check (`readme_audit.py`) |
|---|---|---|---|
| 1 | **ORIENT** | What is this, and why would I want it? | title; a one-line statement near the top; the intro says why |
| 2 | **PROVE** | Does it actually work / what does it look like? | a screenshot, diagram or demo; alt text; local images exist; a worked example |
| 3 | **START** | What do I type first, and will it work? | a getting-started section; commands name scripts and files that exist |
| 4 | **NAVIGATE** | Where is the rest? | relative links resolve; external links alive; the repo's docs/CONTRIBUTING/LICENSE are reachable from here |
| 5 | **TRUST** | Is this current and honest? | status stated; paths in the text exist; counts flagged for checking; README not left behind by the code; GitHub description set |
| 6 | **SCOPE** | Is it the right size? | a contents list when long; reference material not piled into the README |

## Show more than tell (the principle Gil asked for)

Prose claims; evidence convinces. For every claim a README makes about what the project does, ask what a visitor could *see*
instead of *read*:

| If the project is... | Show... |
|---|---|
| an app with a UI | a screenshot or short screen recording of the one screen that matters; before/after for a transformation |
| a command-line tool or library | a real terminal session: the command and its actual output |
| a system of parts | one architecture or data-flow diagram (Mermaid renders natively on GitHub, adapts to light/dark, and diffs as text) |
| an ML / analysis project | the result: a chart, a confusion matrix, a table of metrics, with one line saying what it means |
| a pipeline or agent | the stages as a diagram, and one real run's output |
| research / a paper | the figure that carries the argument |

Craft rules: every image has alt text that says what it shows; images live in the repo (`docs/images/`) so they cannot rot or
vanish; prefer SVG / Mermaid for diagrams, compress screenshots, avoid transparent PNGs that disappear on dark mode; a
caption or sentence says what to notice. A README with a diagram but no sentence of orientation fails Goal 1; a wall of
screenshots with no way to run the thing fails Goal 3.

## What the evidence says (with confidence)

- **Established.** The core questions a README answers are what, why, how to start, where to get help, who maintains it:
  GitHub's own guidance and the Open Source Guides agree. *(official documentation; consistent across both)*
- **Established, with a date caveat.** In a manual study of 4,226 README sections from 393 repositories (Prana, Treude, Thung,
  Atapattu, Lo, 2018, arXiv 1802.06997), "what" and "how" were common while **purpose ("why") and status were often missing**.
  That is why ORIENT checks for *why* and TRUST checks for *status*. *(one large study, 2018, GitHub-wide)*
- **Speculative (correlation only).** Across 1,950 READMEs in ten languages, popular projects' READMEs were better organised
  "using lists and images", had more external links, contribution guidelines and references (Venigalla & Chimalakonda,
  2022, arXiv 2206.10772). The authors state this is correlation; popular projects may simply invest more. We use it as a
  reason to try visuals and structure, not as proof they cause attention.
- **Practitioner consensus, thin causal evidence.** Screenshots, GIFs and "examples with the output they produce" are
  recommended by Make a README and the Standard Readme spec's banner/usage sections. *(no controlled study found)*
- **Established that setup instructions rot.** An analysis of 1,163 README commits that touched installation text found
  maintainers repeatedly revising setup, installation steps, post-install configuration, support links and external links
  (Gao et al., 2023, arXiv 2312.03250). So START and its links need re-verification, which is why the audit runs commands
  against the file list and checks freshness.
- **Convention, not evidence.** The Standard Readme spec (title, short description, table of contents, install, usage,
  contributing, license; optional badges, banner, security, API, maintainers) is a widely used convention. We borrow its
  ordering and its rules (no broken links; short description under about 120 characters; a contents list over about 100
  lines) without claiming they are proven.
- **Practitioner framework.** Divio's four-part documentation system separates tutorials, how-to guides, reference and
  explanation because they serve different needs and degrade when mixed. We use it for Scope: the README orients and links;
  it does not try to be all four. *(I read only the overview page of that system, not the full pages.)*
- **Not verified.** I could not retrieve "The Art of README" (the source of the "cognitive funnel" idea of ordering from
  broad to specific); the ordering rule is also in the Standard Readme rationale, so the criterion stands without it.

## Profiles (what "good" looks like by kind of repo)

- **App / desktop or iOS:** one-line purpose, a screenshot above the fold, install or build, a short "how it works" diagram,
  status and platform support, link to docs and issues.
- **Library / CLI:** one-liner, install, a real usage example with output, API link, contributing, license.
- **Claude Code skill / agent tooling:** what it does for the user in plain words, a transcript or output sample, how to
  install it, what it touches, limits.
- **Research or coursework project:** the question, the method in a diagram, the result figure with one sentence, how to
  reproduce, the report link.
- **Infrastructure / system (MARVIN):** what problem it solves, an architecture diagram, a quickstart that works on a clean
  machine, a map of the docs (CONTEXT.md, ADRs), current status and what is not built.

## What a program cannot judge

The audit never says a README is good. A reviewer (the skill's review step) still asks: Is the one-liner specific, or could it
describe a hundred repos? Does the diagram explain, or decorate? Does the quickstart really work on a clean machine (run it)?
Is every number still true (check it against the repository)? Is the tone one a stranger would trust?

## Re-audit cadence

Re-run the audit when the code changes materially (a new top-level feature, a renamed command, a new dependency) and at
least quarterly for active repositories. The freshness check flags a README untouched while many commits landed.
