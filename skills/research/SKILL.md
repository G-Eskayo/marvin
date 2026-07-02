---
name: research
description: Deep research with epistemic rigor — triangulates sources, tiers confidence levels, separates facts from interpretations, and steelmans competing views. Use when user asks to research a topic, investigate a claim, compare approaches, evaluate a technology or theory, or needs a thorough evidence-based analysis.
tags: [intent:research, intent:investigate, intent:evaluate, intent:learn, type:skill]
---

# Research

Rigorous research that acknowledges uncertainty rather than papering over it.

## Epistemic Stance

No claim is treated as objectively true. Every finding is assigned a confidence tier based on the quality and convergence of evidence. The goal is accurate uncertainty, not false confidence.

See [epistemic-framework.md](epistemic-framework.md) for confidence tier definitions.

## Source Priority

Two different question types need two different source ladders — don't apply the academic ladder to a practical question or vice versa.

**Scientific/academic claims** (does X cause Y, what does the evidence say, evaluate this theory):
1. Science Hub (scihub.org) — open-access journals, society partners
2. Semantic Scholar (semanticscholar.org) — 200M+ papers, public API
3. arXiv (arxiv.org) — CS/math/physics/ML preprints, public API
4. Official documentation / authoritative technical sources (AWS docs, Anthropic docs, RFCs)
5. General web — last resort only, when 1–4 don't cover the topic

**Practical/implementation questions** (how do I do X in library Y, what does this error mean, is this the idiomatic way to use Z):
1. **Stack Overflow** (stackoverflow.com) — canonical crowd-sourced source for debugging, library usage, and best-practice questions. Prefer accepted/highest-voted answers; check the answer's date against the library's current version (SO answers rot as APIs change). Not peer-reviewed — corroborate with official docs before treating an SO answer as authoritative for anything load-bearing.
2. Official documentation
3. General web

Always surface which tier/source answered. Don't present a general web result as authoritative when a higher tier covers the topic.

## Process

### 1. Frame the question precisely

Before researching, restate the question in its sharpest form:
- What exactly is being asked? (not the surface question, the underlying one)
- What would a good answer look like?
- What are the key axes of uncertainty?

Vague questions produce vague research. Sharpen first.

### 2. Map the space

Identify:
- What is **established** (high convergence across independent sources)
- What is **contested** (credible disagreement, multiple defensible positions)
- What is **speculative** (interesting but thin evidence)
- What is **unknown** (genuinely open, or not yet studied)

Don't flatten these into a single narrative. Show the map.

### 3. Triangulate

For any claim that matters:
- Require at least 2 independent sources
- Note where sources agree and where they diverge
- Weight primary sources over summaries; recent over outdated (domain-dependent)
- Flag single-source claims explicitly

### 4. Steelman before dismissing

For any position you're inclined to reject:
- State the strongest version of it first
- Identify what evidence would make it correct
- Only then explain why you're not persuaded

Dismissing a weak version of a position is not research — it's rhetoric.

### 5. Separate layers

Clearly distinguish:
- **Fact**: directly observable or documented
- **Inference**: logically derived from facts
- **Interpretation**: one plausible reading among several
- **Speculation**: extrapolation beyond the evidence

### 6. State your confidence

End each major finding with a confidence tier from [epistemic-framework.md](epistemic-framework.md).

Example output format:
> **Finding**: X is associated with Y in controlled studies.
> **Confidence**: Established (multiple RCTs, consistent direction, replicated)
> **Caveats**: Effect size varies by context Z; long-term data limited.

### 7. Name what you don't know

Explicitly state:
- What would change your conclusions
- What data is missing
- Where you could be wrong

"I don't know" is a valid and often the most honest output.

## Quality Filters

Do not include in research output:
- Claims you cannot source (even if plausible)
- Consensus presented as fact when the field is actually contested
- Single-source claims without flagging them
- Your own opinion presented as finding

## On "Not Every Theory Is Worth Trying"

Not all competing views deserve equal weight. Apply asymmetric scrutiny:
- Extraordinary claims require extraordinary evidence
- Minority views with thin evidence don't get equal airtime just for balance
- Motivated reasoning (financial, ideological) is a credibility penalty
- Reproducibility failures are strong evidence against a theory

Balance ≠ false balance. Accurately representing the *distribution* of evidence is not the same as giving equal weight to all positions.
