# MARVIN — Context Glossary

Domain terms only. No implementation details — see `docs/adr/` for decisions and rationale.

## Voice client (in design, not yet built)

- **Online mode**: the voice client has connectivity to the Agent SDK backend. Full MARVIN capability — real Claude model, existing skills, memory.
- **Offline mode**: the voice client has no connectivity of any kind (true off-grid — no local network, no cellular, nothing nearby to reach). Falls back to a small local/open-weight model running on-device. Degraded capability — no MARVIN skills, no memory read/write, conversational only.
- **Agent SDK backend**: the server-side process (Claude Agent SDK) that runs the real MARVIN agent loop — skills, memory, tools. Lives on a machine already in MARVIN's Tailscale network (desktop/laptop), not on the phone.
- **Voice client**: the native iOS app itself — the thing that captures speech, talks to the Agent SDK backend when reachable, and falls back to the local model when not.

## Citation-graph knowledge base (in design, not yet built)

- **Seed paper**: the paper a citation-graph traversal starts from — all relevance scoring is
  similarity-to-seed, not similarity-to-parent-node.
- **Reference edge**: a backward link — a paper the current node cites. The primary-source
  backbone of the traversal.
- **Citation edge**: a forward link — a paper that cites the current node. Situational context
  (what got built on top of this), not primary substance.
- **Relevance floor**: the minimum embedding-similarity-to-seed a candidate paper must clear to be
  expanded at all. Shared across both edge types.
- **Result-intent bypass**: a citation Semantic Scholar tags as substantively engaging with the
  seed's findings (as opposed to a passing "background" mention) is pulled in regardless of its
  rank against the top-K cutoff — an imperfect but real safeguard against silently dropping
  rebuttals.
- **`paper-knowledge` collection**: the persistent ChromaDB collection storing every paper ever
  ingested via any citation-graph traversal, across all investigations — the visited-check that
  prevents re-fetching/re-embedding a paper already known queries this collection, not a
  per-traversal temporary set.
