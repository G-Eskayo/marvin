# ADR 0056: The map snapshot publishes itself to production

**Status:** Accepted (2026-10-08, Gil)

## Context

Production (gileskayo.me) is promoted by Gil by hand: a push touching the portfolio repo's `deploy/` uploads it
(CONTEXT.md, Portfolio "Environments"), so nothing MARVIN runs pushes that repo. Gil wants the MARVIN map on the
website to stay current without him (#189).

## Decision

One exception: the privacy-scanned map snapshot may publish itself. `brain-map/publish_map.py` pushes only
`deploy/marvin-map/**`, from its own sparse checkout, after the snapshot passed the same privacy scan and checks as the
dev deploy (nightly and after MARVIN changes). It refuses if anything else would change.

Everything else (page text, the MARVIN page section that embeds the map, images, other pages) is still promoted by Gil.

## Consequences

- The map can show something new on the live site without a person looking first. The privacy scan (paths, secrets,
  locked private projects, anonymised machines) is the gate, so a gap in it reaches production. Keep its tests strict.
- A bad snapshot is fixed by the next publish, or reverted with a normal git revert of `deploy/marvin-map/`.
