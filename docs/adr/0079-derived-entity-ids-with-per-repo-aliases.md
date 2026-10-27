# 0079 — Entity IDs are derived, never stored; aliases live in each project's repo

## Status

Accepted (2026-10-27, by the owner on PR #704). Grilled with the owner on marvin#697. Numbered 0076 while in review; 0076 went to union merge first.

## Context

MARVIN has eight graph-like systems: graphify, brain-map, the dashboard's relations.js, memory `[[links]]`,
qa-knowledge, research-feed, paper-knowledge and the skill manifest. None of them shares an ID scheme. One ADR is a
graphify path-stem, a relations.js `project/path`, a brain-map display name and a memory `[[ADR 0070]]`. Nothing can
follow a link from one system into another (`docs/research/knowledge-graphs-2026-10-26.md` §1, §4).

The research's "schema dial" says to be strict where facts can be checked. The owner's standing rule says to derive
relations, not store them.

Alternatives considered:
- **A central registry file of every entity and its aliases.** Rejected: it's one more store to keep in sync, and stale
  stores are the failure we had just fixed in graphify ([[marvin#691]]).
- **One alias table in the private instance ([[0071]]) or in the public engine.** Rejected for per-repo declaration:
  a project's other names belong next to the project, and travel with it to whoever runs it (the universal and
  marketplace direction, [[0072]]).
- **An alias line in each repo's CONTEXT.md.** Rejected for a small `marvin.json`: unambiguous to parse.
- **Symbol-level code IDs.** Deferred: a symbol's ID vanishes on rename or move and breaks every link to it.
- **Python-only or JS-only implementations.** Rejected: one side would pay a process call per reference.
- **Staged rollout.** Rejected by the owner in favour of one change across all systems.

## Decision

Every entity's ID has the form `kind:key`. It is derived by one function from what a system already holds; it is never
assigned or stored centrally. The only hand-kept names are aliases, declared in a project's own repo in `marvin.json`.

Kinds (v1):
- `ticket:<owner>/<repo>#<n>`, `pr:<owner>/<repo>#<n>`
- `adr:<repo>/<NNNN>`, `doc:<repo>/<path>`, `code:<repo>/<path>` (files only)
- `project:<repo>`, `skill:<name>`, `machine:<id>`
- `memory:<slug>`, `paper:<doi>`, `qa:<id>`, `feed:<id>`

Rules:
- A bare "ADR NNNN" means the ADR of the repo the text lives in. In memory, which belongs to no repo, it is ambiguous
  and flagged.
- A project with no repo is `memory:<slug>` until it gets a repo; the repo then lists that ID as an alias.
- Text-bearing stores (qa-knowledge, research-feed) carry the **mentions** they refer to, derived when they're written.
  A research-feed correlation names the matched lesson by `qa:` ID, not by a copy of its text.
- The function exists twice, `lib/entity_id.py` and `dashboard/src/lib/entity_id.js`, and both must pass one shared
  JSON file of examples, so they can't drift.

## Consequences

- **Unlocks:** links that cross systems. "Everything that references adr:marvin/0070" becomes one query across tickets,
  PRs, docs, memory and lessons. The memory graph (#696) and relations.js can merge into one picture.
- **Cost:** one large change touching every system at once. That includes backfilling mentions on about 5,200 Chroma
  entries (O(entries), one pass, local), and renumbering the duplicate marvin ADR 0074 (done 2026-10-27: test-exactly-what-lands became 0078, with a note
  in the renamed file).
- **Risk:** a derivation bug is everywhere at once. The shared example file is the guard; every new reference shape
  found in the wild is added there first.
- **Gaps left open:**
  - A file rename is only followed where git's rename detection sees it.
  - Symbol-level code IDs wait for a way to follow renames.
  - A project whose repo isn't on this machine has its aliases only after its repo has been read once (the project
    catalog already reads every repo).
