# Skills

32 skills. Generated from each skill's own `SKILL.md` by `lib/skill_index.py`: edit the skill, not this file.

## Quality and debugging

| Skill | What it does and when it fires |
|---|---|
| [`diagnose`](../skills/diagnose/SKILL.md) | Disciplined diagnosis loop for hard bugs and performance regressions. |
| [`audit`](../skills/audit/SKILL.md) | Reactive background investigation comparing documented intent (docstrings, ADRs, roadmap markers) against actual system state to find gaps nobody's reported yet. |
| [`tdd`](../skills/tdd/SKILL.md) | Test-driven development with red-green-refactor loop. |
| [`qa-agent`](../skills/qa-agent/SKILL.md) | QA code agent — scans projects and captures session learnings into a searchable best-practices ChromaDB. |
| [`grill-with-docs`](../skills/grill-with-docs/SKILL.md) | Grilling session that challenges your plan against the existing domain model, sharpens terminology, and updates documentation (CONTEXT.md, ADRs) inline as decisions crystallise. |
| [`grill-me`](../skills/grill-me/SKILL.md) | Interview the user relentlessly about a plan or design until reaching shared understanding, resolving each branch of the decision tree. |
| [`improve-codebase-architecture`](../skills/improve-codebase-architecture/SKILL.md) | Find deepening opportunities in a codebase, informed by the domain language in CONTEXT.md and the decisions in docs/adr/. |
| [`safety-monitor`](../skills/safety-monitor/SKILL.md) | Calibrated verifier that scores an autonomous loop's output for risk (fabricated references, unsupported claims) before it ships, quarantining flagged artifacts for review instead of blocking the loop. |

## Research and reading

| Skill | What it does and when it fires |
|---|---|
| [`research`](../skills/research/SKILL.md) | Deep research with epistemic rigor — triangulates sources, tiers confidence levels, separates facts from interpretations, and steelmans competing views. |
| [`paper-dive`](../skills/paper-dive/SKILL.md) | Socratic reading partner for scientific papers. |
| [`research-colony`](../skills/research-colony/SKILL.md) | Autonomous research agent that monitors arXiv, GitHub, and HN daily, cross-references findings against MARVIN's knowledge base, and synthesises a digest. |
| [`zoom-out`](../skills/zoom-out/SKILL.md) | Tell the agent to zoom out and give broader context or a higher-level perspective. |

## Writing and creating

| Skill | What it does and when it fires |
|---|---|
| [`readme`](../skills/readme/SKILL.md) | Write, update or review a repository README so it does its job: orient a stranger, show the project working (not just describe it), get them to a first success, link everything, and stay true. |
| [`writing-style`](../skills/writing-style/SKILL.md) | Rewrites or drafts text so it reads in Gil's actual voice instead of generic AI writing — for portfolio project pages, resume text, outreach emails, and any other user-facing prose. |
| [`creative`](../skills/creative/SKILL.md) | Creative work that escapes safe, predictable, or generic outputs through constraint-based thinking, unexpected angles, and iterative divergence. |
| [`prototype`](../skills/prototype/SKILL.md) | Build a throwaway prototype to flesh out a design before committing to it. |
| [`resume-tailor`](../skills/resume-tailor/SKILL.md) | Maintain a master resume and generate tailored 1-page application packages from job descriptions. |

## Continuity and self-improvement

| Skill | What it does and when it fires |
|---|---|
| [`handoff`](../skills/handoff/SKILL.md) | Produce a structured handoff document before any context switch, topic change, or when a fresh model would improve outputs. |
| [`index`](../skills/index/SKILL.md) | Context retrieval using the manifest index. |
| [`self-improve`](../skills/self-improve/SKILL.md) | Meta-skill that runs autonomously after every non-trivial task — no user prompt needed. |
| [`architecture-review`](../skills/architecture-review/SKILL.md) | Autonomously reviews the WHOLE agent system (not just meta-config — every skill, script, hook, and cron job under ~/.agents and ~/.claude) and generates actionable optimization suggestions queued for user authorization in… |
| [`improve`](../skills/improve/SKILL.md) | Continuous improvement agent. |
| [`lexicon`](../skills/lexicon/SKILL.md) | Add, update, or review entries in the shared lexicon at ~/.claude/lexicon.md. |
| [`write-a-skill`](../skills/write-a-skill/SKILL.md) | Create new agent skills with proper structure, progressive disclosure, and bundled resources. |
| [`variable-tracker`](../skills/variable-tracker/SKILL.md) | Track Python variable definitions, uses, and scope across files |

## Project work and routing

| Skill | What it does and when it fires |
|---|---|
| [`setup-matt-pocock-skills`](../skills/setup-matt-pocock-skills/SKILL.md) | Sets up an `## Agent skills` block in AGENTS.md/CLAUDE.md and `docs/agents/` so the engineering skills know this repo's issue tracker (GitHub or local markdown), triage label vocabulary, and domain doc layout. |
| [`triage`](../skills/triage/SKILL.md) | Triage issues through a state machine driven by triage roles. |
| [`to-issues`](../skills/to-issues/SKILL.md) | Break a plan, spec, or PRD into independently-grabbable issues on the project issue tracker using tracer-bullet vertical slices. |
| [`to-prd`](../skills/to-prd/SKILL.md) | Turn the current conversation context into a PRD and publish it to the project issue tracker. |
| [`to-tasklist`](../skills/to-tasklist/SKILL.md) | Convert a confirmed design/requirements doc into a persisted markdown task list with per-task status checkboxes, for projects that have no issue tracker (private/local-only repos). |
| [`route`](../skills/route/SKILL.md) | Classify a task and surface the optimal Claude profile + model routing decision |
| [`caveman`](../skills/caveman/SKILL.md) | Ultra-compressed communication mode. |
