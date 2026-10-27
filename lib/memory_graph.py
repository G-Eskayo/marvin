#!/usr/bin/env python3
"""Follow memory's [[links]] instead of grepping for them (marvin#696).

The memory notes link to each other, but until now nothing could answer "what's connected to X" or "what's related to
this question" except grep. This builds the link graph fresh from the files on every call (memory_lint.lint parses
them: same resolution rules, dangling links dropped), so there is no stored graph to go stale. About 160 notes:
milliseconds.

- neighbors: the notes a note links to, and the notes linking to it.
- path: the shortest chain of links between two notes, in either direction.
- related: Personalized PageRank (the HippoRAG pattern) seeded from the notes whose name or description matches the
  query, blended half and half with the direct match. Closeness to the seeds outranks raw popularity, and a note the
  seeds can't reach scores nothing.

    memory_graph.py [--dir D] neighbors <note>
    memory_graph.py [--dir D] path <a> <b>
    memory_graph.py [--dir D] related "<query>" [--k N]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import memory_lint  # noqa: E402

DAMPING = 0.85


class UnknownNote(KeyError):
    def __str__(self) -> str:
        return f"no memory note called '{self.args[0]}'"


def load(memory_dir: Path | None = None) -> nx.DiGraph:
    if memory_dir is None:
        import host_os
        memory_dir = host_os.memory_dir()
    r = memory_lint.lint(Path(memory_dir))
    g = nx.DiGraph()
    for stem, meta in r["meta"].items():
        g.add_node(stem, **meta)
    g.add_edges_from(r["edges"])
    return g


def resolve(g: nx.DiGraph, ref: str) -> str:
    key = ref.strip().lower()
    for stem, data in g.nodes(data=True):
        if stem.lower() == key or str(data.get("name", "")).lower() == key:
            return stem
    raise UnknownNote(ref)


def neighbors(g: nx.DiGraph, ref: str) -> dict:
    stem = resolve(g, ref)
    return {"note": stem, "out": sorted(g.successors(stem)), "in": sorted(g.predecessors(stem))}


def path(g: nx.DiGraph, a: str, b: str) -> list[str] | None:
    try:
        return nx.shortest_path(g.to_undirected(as_view=True), resolve(g, a), resolve(g, b))
    except nx.NetworkXNoPath:
        return None


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3}


def related(g: nx.DiGraph, query: str, k: int = 10) -> list[dict]:
    q = _words(query)
    seeds = {}
    for stem, data in g.nodes(data=True):
        hits = len(q & _words(f"{stem} {data.get('name', '')} {data.get('description', '')}"))
        if hits:
            seeds[stem] = hits
    if not seeds:
        return []
    u = g.to_undirected()
    # Teleport only to the seeds, so a note scores only by being reachable from them. A dangling node's mass also
    # returns to the seeds (nx's default would spread it everywhere, giving unreachable notes a score).
    pr = nx.pagerank(u, alpha=DAMPING, personalization=seeds, dangling=seeds)
    reach = set().union(*(nx.node_connected_component(u, s) for s in seeds))
    # Blend in the direct match: plain PPR ranks the middle of a chain above the note that matched (it collects mass
    # from both sides). Half how well the note matches the query, half how close it is to the notes that do.
    top_pr, top_hits = max(pr[s] for s in reach), max(seeds.values())
    score = {s: 0.5 * seeds.get(s, 0) / top_hits + 0.5 * pr[s] / top_pr for s in reach if pr[s] > 0}
    ranked = sorted(score.items(), key=lambda x: (-x[1], x[0]))[:k]
    return [{"note": s, "score": round(v, 3), "description": g.nodes[s].get("description", "")} for s, v in ranked]


def _cli(argv: list[str]) -> int:
    memory_dir = None
    if "--dir" in argv:
        i = argv.index("--dir")
        memory_dir, argv = Path(argv[i + 1]), argv[:i] + argv[i + 2:]
    k = 10
    if "--k" in argv:
        i = argv.index("--k")
        k, argv = int(argv[i + 1]), argv[:i] + argv[i + 2:]
    if not argv or argv[0] not in ("neighbors", "path", "related") or len(argv) < (3 if argv[0] == "path" else 2):
        print(__doc__.strip().splitlines()[-3:], file=sys.stderr)
        return 2
    g = load(memory_dir)
    try:
        if argv[0] == "neighbors":
            n = neighbors(g, argv[1])
            print(f"{n['note']}\n  links to:    {', '.join(n['out']) or '-'}\n  linked from: {', '.join(n['in']) or '-'}")
        elif argv[0] == "path":
            p = path(g, argv[1], argv[2])
            print(" → ".join(p) if p else f"no chain of links between {argv[1]} and {argv[2]}")
        else:
            for r in related(g, " ".join(argv[1:]), k=k):
                print(f"{r['score']:.2f}  {r['note']}  — {r['description']}")
    except UnknownNote as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
