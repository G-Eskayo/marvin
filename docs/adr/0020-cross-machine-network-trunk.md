# 0020 — Add a Cross-Machine Network trunk to brain-map

## Status

Accepted (2026-07-09)

## Context

The brain-map graph had exactly 4 top-level trunks (Memory, Skills, Infrastructure, Autonomous
Agents) and no representation at all for a real chunk of recent work: the exo distributed
inference cluster (Mac Mini + MacBook Pro running distributed LLM inference over Tailscale, fully
working as of 2026-07-08), the general task-dispatch primitive (`~/.agents/lib/task_dispatch.py`,
[[0013]]), and the registered-machine model underpinning both
(`~/.claude/marvin-network.json`). This isn't a staleness bug like [[0018]]/[[0019]] — nothing
claimed to depict these, so nothing was wrong, just incomplete. Trunk creation is inherently a
manual naming/scoping decision (per [[0018]]'s "known gaps" section: no filesystem signal says "a
new category of thing exists, go make it a trunk").

`marvin-network.json` turned out to already be a live, structured file — a `devices` dict keyed by
machine id — the same shape as `manifest.json` for skills, making at least part of this trunk
genuinely auto-derivable rather than fully hand-authored like Memory/Infrastructure/Autonomous
Agents were before their fixes.

## Decision

Add a fourth hand-declared trunk, "Cross-Machine Network", to `enrichment.json`'s `structural`
list. Its device nodes (`mac-mini-1`, `macbook-pro-1`, ids taken from `marvin-network.json`'s
`devices` keys) are auto-discovered live from that file the same way skills come from
`manifest.json` — new machines appear with no `enrichment.json` edit the next time a machine is
registered. Two additional nodes, `exo` and `task-dispatch`, are hand-authored (there's no
enumerable list backing "distributed capabilities," just these two fixed concepts, same as
Memory's ChromaDB/hook nodes).

`cross-machine-merge` (the daily sync agent, [[0018]]) stays under Autonomous Agents rather than
moving here — it's fundamentally a recurring cron job and belongs with the trunk defined around
that shape. It conceptually operates over the devices this trunk depicts, so an `extra_synapses`
edge connects it here rather than relocating the node.

## Consequences

The graph now depicts distributed-systems work that previously had zero representation. The
device sub-list won't go stale the way Autonomous Agents/Infrastructure did, because it's sourced
from the same live file that already drives real machine registration — no parallel bookkeeping
to forget.

Known gap: `exo` and `task-dispatch` are still flat hand-authored nodes with no live signal behind
them (no manifest, no plist, no settings.json entry exists for either concept) — if either grows a
structured config file of its own, this trunk should be revisited the same way [[0018]]/[[0019]]
replaced hand-authored lists once a live source appeared.
