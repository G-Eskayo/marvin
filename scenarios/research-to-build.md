---
name: research-to-build
description: Full pipeline from unknown problem to tested implementation. Triggers when a feature or system needs designing before building — especially when domain is unclear or decisions are irreversible.
tags: [scenario:design-to-build, intent:plan, intent:build, intent:tdd, type:scenario]
calls: [grill-me, grill-with-docs, tdd, research]
---

# Scenario: Research → Design → Build

## When to use

- Domain is not yet understood well enough to write a test
- Architectural decision is hard to reverse (storage choice, protocol, API shape)
- Multiple valid approaches exist and the wrong one costs significantly
- Starting a new capability from scratch

## Skill sequence

```
research          ← if domain knowledge is missing
     ↓
grill-me          ← resolve unknowns one branch at a time, output: spec + ADR
     ↓
grill-with-docs   ← validate decisions against CONTEXT.md, sharpen terminology
     ↓
tdd               ← vertical slices, grill-with-docs checkpoint at each red-green cycle
     ↓
self-improve      ← ISF annotation: what improved, what sustained, what failed
```

## Handoff points

| Between | What to carry forward |
|---------|----------------------|
| research → grill-me | Key unknowns surfaced, sources consulted |
| grill-me → grill-with-docs | Resolved decisions, ADR candidates |
| grill-with-docs → tdd | CONTEXT.md terms locked, ADRs written, interface agreed |
| tdd cycle → next cycle | Passing tests, observable behavior confirmed |
| tdd → self-improve | Patterns noticed, failures hit, approaches that worked |

## Failure modes

- **Skipping grill-me**: building on unresolved assumptions → rework after first real constraint surfaces
- **Skipping grill-with-docs**: terminology drift → CONTEXT.md diverges from code
- **Horizontal TDD slices**: writing all tests before any implementation → tests verify shape not behavior
- **Skipping self-improve**: patterns lost, same mistakes next session

## Known companions

`lexicon` — fires inside grill-with-docs when new terms crystallise  
`diagnose` — fires inside tdd when a test fails unexpectedly  
`handoff` — fires at end of session if work is mid-cycle
