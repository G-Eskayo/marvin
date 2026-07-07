# Epistemic Framework — Confidence Tier Definitions

Every major finding gets exactly one tier. These mirror the four categories used when "mapping
the space" (SKILL.md step 2) — the tier is the same judgment, just attached to a specific claim
instead of a whole topic area.

## Established

Multiple independent, credible sources converge on the same conclusion, ideally including at
least one primary source (not just summaries of summaries). For scientific claims: replicated
findings, consistent direction across studies, no major unaddressed methodological objection.
For practical/technical claims: official documentation confirms what multiple independent
implementation reports also show.

> **Finding**: X is associated with Y in controlled studies.
> **Confidence**: Established (multiple RCTs, consistent direction, replicated)

## Contested

Credible sources or credible experts land on genuinely different conclusions, and neither side
has a decisive evidence advantage. Steelman both positions (see SKILL.md step 4) rather than
picking a side and presenting it as settled. Contested is not the same as "one side is obviously
right and I'm being diplomatic" — reserve it for real, unresolved disagreement.

> **Finding**: Whether X causes Y or Y causes X is disputed.
> **Confidence**: Contested (Group A's studies show →, Group B's show ←, methodological
> critiques exist on both sides, no resolving study yet)

## Speculative

Plausible, interesting, and worth mentioning, but resting on thin evidence — a single study, a
theoretical argument without empirical test, an analogy from an adjacent domain that hasn't been
directly verified. State speculative findings as speculative, not as tentative-sounding facts —
don't hedge with "may" or "could" while implying more confidence than the evidence supports.

> **Finding**: X might extend to domain Z based on structural similarity to domain Y.
> **Confidence**: Speculative (no direct study in domain Z; inference from analogy only)

## Unknown

Genuinely open — not yet studied, or the available evidence doesn't bear on the question at all
in either direction. Say so plainly rather than filling the gap with the most plausible-sounding
inference and presenting it as an answer. "Unknown" is a valid, sometimes the most useful,
research output.

> **Finding**: No studies address this specific question directly.
> **Confidence**: Unknown (adjacent research exists but doesn't transfer cleanly — see
> Speculative note above if attempting the transfer anyway)

## Applying tiers

- One tier per finding, not one tier for a whole research session — a single investigation
  typically produces findings across several tiers.
- Downgrade rather than upgrade when uncertain. Calling something "Established" that's actually
  "Contested" is the specific failure mode this framework exists to prevent.
- Caveats belong with the finding, not buried in a separate section — a reader should never have
  to hunt for the reason a confidence tier isn't higher.
