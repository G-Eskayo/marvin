---
name: readme
description: Write, update or review a repository README so it does its job: orient a stranger, show the project working (not just describe it), get them to a first success, link everything, and stay true. Use when asked to write or update a README, review READMEs across repos, check a README is accurate and linked, or when a project's front page needs to show more than tell.
tags: [intent:write, intent:review, intent:document, domain:docs, type:skill]
model-scope: all
---

# README

A README is the front door of a repository. The criteria, and the evidence behind them, are in
[`docs/readme-criteria.md`](../../docs/readme-criteria.md): read it once per session before judging a README. This skill is the
procedure; the criteria are the standard.

**The six jobs** (every decision serves one): ORIENT (what and why, first screen) -> PROVE (show it working) -> START (first
success, and it works) -> NAVIGATE (every link resolves, deeper docs reachable) -> TRUST (status, accurate, current) -> SCOPE
(a front door, not the manual).

**Show more than tell.** For every claim about what the project does, put something a visitor can see next to the sentence: a
screenshot, a real command and its output, a Mermaid or SVG diagram, a result chart. Playbook by kind of project in the
criteria doc.

## Quick start

```bash
~/.agents/venv/bin/python ~/.agents/lib/readme_audit.py G-Eskayo/<repo>            # one repo, markdown report
~/.agents/venv/bin/python ~/.agents/lib/readme_audit.py G-Eskayo/a G-Eskayo/b --json   # many repos, JSON
```

The audit is mechanical (links, paths, commands, images, freshness, structure). It finds what a program can know and never
says a README is *good*: that judgement is the review step below.

## Workflow: write or update one README

1. **Audit first.** Run the audit; keep the report. It shows what is broken and what is missing.
2. **Understand the repo from the repo, not from the old README.** Read the code layout, the docs, the entry points, recent
   commits. The old README is a claim to check, not a source.
3. **Pick the profile** (app / library-CLI / skill-or-tooling / research project / infrastructure) from the criteria doc and
   start from [`TEMPLATES.md`](TEMPLATES.md).
4. **Decide what to show** before writing prose: list the 2-4 things a visitor should *see*. Produce them: take the
   screenshot, run the command and paste its real output, draw the diagram (Mermaid in the README, or an SVG in
   `docs/images/`). Never invent output: run it.
5. **Write top-down:** title, one-line what + why, the visual, quickstart, how it works (diagram), docs map, status, contributing,
   license. One idea per section; headings a skimmer can use; a contents list if it passes ~100 lines.
6. **Verify every claim against the repo** (accuracy is Goal 5): each file path exists; each command runs (run it); each
   count (skills, tests, pages) matches the repo today; each link resolves. Remove what you cannot verify.
7. **Re-audit.** Zero fails; warns either fixed or knowingly kept (say why in the commit message).
8. **Link it outward and inward:** the README links to the deeper docs; the docs link back; the GitHub description and
   topics match the README's first line.

## Workflow: review READMEs across repos

1. Run the audit on every repo (one call, many repos). Save the JSON.
2. Rank by the lowest goal scores, but read the findings: a fail on PROVE (no visual) is the most common and the most valuable
   to fix; TRUST failures (a path or command that does not exist) are the most embarrassing.
3. Write the review as a table (repo x goal) plus the concrete fixes per repo, and put it in the repo's docs so it shows in
   the dashboard Docs tab. Fixing is per repo and each repo's pushes are the owner's call: propose, then apply what is approved.

## The review step (what the audit cannot do)

Ask, and answer in the review notes:
- Is the one-liner **specific**, or could it describe a hundred repos?
- Does each image/diagram **explain** something, and does a sentence say what to notice?
- Does the quickstart work on a **clean machine** (did you run it)?
- Is every number **still true** (checked against the repo today)?
- Does it say honestly what is **not** built or not supported?
- Would a stranger **trust** it?

## Rules

- Never fabricate output, metrics, screenshots or features. If you cannot show it, say it is planned.
- Images go in the repo (`docs/images/`) with alt text; prefer Mermaid/SVG for diagrams.
- Keep the README a front door: move long reference or design material to `docs/` and link it.
- Do not push to a repository you were not asked to change; show the diff first for repos that deploy anything.
