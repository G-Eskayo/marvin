# Knowledge graphs in MARVIN: what we have, what the research says, what to change

**Date:** 2026-10-26
**Status:** research complete; every improvement below is a **proposal** (queued in `suggestions.md`), nothing built.
**Prompted by:** an Instagram reel by kem_glitch (a knowledge-graph practitioner), replying to a creator who
recommended Obsidian wiki-links plus the open-source graphify repo as agent memory. That is close to MARVIN's own
setup, so we took its claims as the test.

**How the evidence was gathered:**
- Two research passes: one surveyed our own systems by running the code and reading the data, the other surveyed the
  literature.
- Our own numbers were measured on 2026-10-26.
- External sources are rated **H** (primary paper or official docs, read), **M** (abstract-level or a single source)
  or **L** (vendor or practitioner opinion).
- Numbers we could not trace to a primary source are marked *unverified*.

---

## 1. The short answer

The reel's question is whether we have real knowledge graphs. The answer differs by system.

| System | Real KG by a practitioner's standard? | Why |
|---|---|---|
| **graphify code graph** | **Mostly yes, structurally.** | Built by AST parsing, with a fixed vocabulary of 16 relation types, all edges EXTRACTED. That is closer to the reel's "model it properly" standard than the LLM extraction the reel attacks. Its problem is **freshness and noise**, not schema. |
| **memory `[[links]]`** | **No.** | 328 links, and **no code anywhere parses or follows them**. They are text for a human or an LLM to read. That is exactly the reel's "grepping and jumping from note to note". |
| **brain-map** | **Yes, small and curated.** | Typed synapses derived from real config. But its IDs are free text, unconnected to any other system. |
| **dashboard relations** | **Yes, narrow.** | A fixed four-kind vocabulary, derived from text and deduplicated. Kept in memory only, with no history. |
| **qa-knowledge / research-feed** | **No.** | Vector stores. "Lateral query" is a metadata filter; the research-feed stores the first 100 characters of a match instead of the matched entry's ID. |
| **paper-knowledge** | **A tree, not a graph.** | Keeps only the first parent edge. Ran once (2026-07-13), and its one consumer filters on an edge type that matches 0 records. |

**The bigger finding is that MARVIN has eight graph-like systems and none of them share an ID scheme.**
- An ADR is a graphify `document` node, a relations.js `d` node, a brain-map `documented` synapse and a memory
  `[[ADR 0070]]` link, all with different identifiers.
- The same is true for tickets, skills and projects.

Each graph works alone, but you can't hop between them. That matters more than any single graph's internals.

---

## 2. What the reel claims, tested

| # | Claim | Verdict | Evidence |
|---|---|---|---|
| 1 | A KG only works with an ontology modelled up front; that can't be outsourced | **Overstated.** | GraphRAG ([2404.16130](https://arxiv.org/abs/2404.16130)), HippoRAG 2 ([2502.14802](https://arxiv.org/abs/2502.14802)) and Zep/Graphiti ([2501.13956](https://arxiv.org/html/2501.13956v1)) all extract with an open schema and still show gains (H). But each adds structure afterwards: entity resolution, edge dedup, fixed write templates. Domains needing logical inference or precise joins do need a schema. |
| 2 | Auto-linking globbed files into YAML or markdown isn't a KG | **Largely right about the result.** | A practitioner test of graphify against `rg` on a 605-file monorepo found about 5% precision vs about 100%, hub files flooding traversals, and 23.5% of edges stale after one day ([write-up](https://praveenvijayan.substack.com/p/your-knowledge-graph-is-making-your); only 3 queries, L-M). The same test found graphify's community structure useful on prose (ADRs, plans). |
| 3 | No multi-hop traversal means not a KG, and burns context | **Half right.** | By definition, grep-hopping is search, not traversal. But on the benchmarks we have, file tools plus a capable agent are cheap and strong: Letta scored 74.0% on LoCoMo with plain file tools ([post](https://www.letta.com/blog/benchmarking-ai-agent-memory), M), and `rg` used about 300 tokens per query against about 2000 for graph queries in the test above. Graphs earn their cost on true multi-hop questions. |
| 4 | Karpathy's LLM-maintained wiki is untested hype | **Correct for the wiki.** | His [gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) calls itself an "idea file", gives no benchmarks, and says plain search is needed beyond about 100 sources (H). Its pieces (LLM-consolidated memory, background rewriting) are evaluated elsewhere and carry known risks. |

**What we take from it:** the schema is a dial, not a gate.
- Use a **fixed vocabulary where facts can be checked**: code relations, ticket, PR and ADR links, machines, skills.
- Use an **open vocabulary where they can't**: prose memory, with normalization afterwards.
- MARVIN already matches Karpathy's three layers: raw sources, LLM-maintained memory, and CLAUDE.md as the schema.
  What it lacks is his **lint** step and any **traversal**.

---

## 3. Patterns from the research

Ranked for a small, local, no-paid-API system. Full write-ups and sources for all 18 are in the research report this
summary came from; the ones that matter for us:

1. **Measure before believing (gold-question eval).**
   - LLM-judged graph-RAG win rates swung by more than 30 points just from answer order, comparing a system with
     itself ([2506.06331](https://arxiv.org/abs/2506.06331), H).
   - Use known-answer questions scored by recall@k and hit rate.
2. **Graph retrieval as a routing decision.**
   - Plain RAG beats GraphRAG on single-hop questions; graphs win on multi-hop
     ([2502.11371](https://arxiv.org/abs/2502.11371), [2506.05690](https://arxiv.org/abs/2506.05690), H).
3. **Hybrid retrieval.**
   - BM25 plus vectors plus k-hop graph expansion, fused with Reciprocal Rank Fusion (Zep's recipe, H).
   - BM25 catches exact IDs such as `#637`, `ADR 0071` and function names, which vectors miss.
4. **Provenance and evidence tiers.**
   - Store a source span on every edge. EXTRACTED outranks INFERRED, as Sourcegraph ranks compiler-precise results
     above search-based ones (H).
   - Never present a stale edge as EXTRACTED.
5. **Bi-temporal facts: invalidate, never delete** (Zep/Graphiti, H).
   - `valid_from`/`invalid_at` plus `learned_at`/`retired_at`.
   - Mem0's destructive update step was reported deleting still-valid facts (secondary).
6. **Entity resolution.**
   - Deterministic normalization first, then embedding candidates, then an LLM judge only for ambiguous pairs (Zep,
     KGGen).
   - Duplicate nodes kill PageRank and community detection.
7. **Incremental, hash-driven updates.**
   - Re-extract only changed files; recompute communities on a drift threshold (Zep's label propagation, LightRAG).
8. **Query-seeded Personalized PageRank (HippoRAG).**
   - `networkx.pagerank(G, personalization=seeds)` over graphs we already have, used for multi-hop questions only.
9. **Ranked repo map under a token budget (Aider, H).**
   - Expose graph queries as agent *tools* alongside grep, rather than as pre-loaded context.
10. **Lint and background consolidation** (Karpathy's lint, A-MEM, Letta sleep-time).
    - Orphans, dangling links, contradictions and stale claims are found and proposed off the hot path, and every
      change is logged.

**Avoid:**
- Full GraphRAG global-search indexing on local models: costly, and the mode that underperformed.
- LLM semantic extraction with small Ollama models: Graphiti's docs and Cognee's tests report schema failures.
- A graph database: networkx and SQLite are enough at our scale.

---

## 4. Our systems against the patterns

Measured 2026-10-26.

### graphify (`graphify-out/graph.json`, 15,252 nodes / 22,196 edges)
- **Stale.**
  - It was built at `535c264` (2026-10-24). HEAD is `569ca07`, which is not a descendant of it; 84 commits since.
  - The post-commit hook skips merges, rebases and cherry-picks, and pulls and merges are how most commits land here.
  - The edges still say EXTRACTED at full confidence. Breaks pattern 4 and 7.
- **Unbounded growth.**
  - `graphify-out/` is **242 MB**, with 22 dated snapshots (about 15 MB/day) and no pruning code.
  - The 2026-10-01 snapshot is broken (37 nodes).
- **Noisy hubs.**
  - Communities are dominated by `ticket-NN.md` files and vendored `motion.12.42.2.js`.
  - 450 labels are shared by more than one node (`path` ×119, `main()` ×114). That's correct for code, but it means
    label lookups are ambiguous.
- **Unknown value.**
  - CLAUDE.md tells agents to query graphify first, but the last recorded query was 2026-10-15.
  - We have never measured whether it beats `rg` for us (pattern 1).
- **Unused spec.** The semantic layer, hyperedges and provenance fields in its extraction spec are entirely absent.
  Given the small-model evidence, that is probably fine.

### Memory (163 files, 328 `[[links]]`)
- **Nothing traverses them.**
  - No code parses `[[…]]` (checked: `lib`, `skills`, `tools`, `bin`, dashboard, hooks).
  - Only 35 manifest entries are embedded in Chroma, so about 160 memory files are reachable only by the always-loaded
    index.
- **Lint debt.**
  - 5 dangling links, including one broken across a line.
  - 52 files with no inbound link.
  - Inconsistent `node_type` frontmatter (113 of 162).
  - Unresolved git conflict markers in `MEMORY.md` and one other memory file.
- **Missing temporal model.**
  - "Dropped" decisions (for example, removed features) are written as new memories next to old ones.
  - Nothing marks the old fact invalid, which is the case pattern 5 handles.

### Cross-system identity
- There is no canonical ID for a project, ticket, ADR, skill or doc, so nothing links across systems (pattern 6).
- The research-feed stores matched *text* instead of the matched ID.
- Brain-map node IDs are display names.
- Blocked-by logic exists twice (`relations.js` and `needs_you.js` `blocksGraph`).

### Citation graph
- `CONTEXT.md` § "Citation-graph knowledge base" says "in design, not yet built". In fact it was built and run once
  (129 papers).
- `continuity_checker.py` filters on `edge_type == "citation"`, but every record is `reference`. It silently finds
  nothing.

---

## 5. Proposed improvements (ranked)

Ordered by what each unlocks. Nothing here is approved.

| Rank | Change | Patterns | Effort | Space/time |
|---|---|---|---|---|
| 1 | **graphify freshness.** Also rebuild on `post-merge`/`post-rewrite` (trigger-based, not polling). On query, warn when `built_at_commit` isn't HEAD. Prune snapshots to the last N. Exclude `vendor/` and ticket docs from hub ranking. | 4, 7 | Low | Disk goes from O(days) to O(N); rebuild stays incremental |
| 2 | **Gold-question eval.** About 30 real MARVIN questions with known answers. Compare `rg` vs Chroma vs graphify vs hybrid, by recall@k and tokens used. Decides whether CLAUDE.md should keep telling agents "graphify first". | 1, 2 | Low | One-off; O(questions) per run |
| 3 | **Memory lint**, run trigger-based on memory writes. Reports dangling links, orphans, conflict markers and missing frontmatter. Proposes links, never edits silently. | 10 | Low | O(changed files) |
| 4 | **Canonical entity IDs.** A small fixed vocabulary (`project:`, `ticket:repo#n`, `pr:`, `adr:NNNN`, `skill:`, `doc:path`, `machine:`, `memory:slug`, `paper:doi`). The four systems emit these alongside their own IDs. research-feed stores IDs, not text. | 6, schema dial | Medium | O(1) lookups via one registry |
| 5 | **Make memory links traversable.** A tiny tool: `neighbors`, `path`, `k-hop`, and PPR seeded from the query, over `[[links]]` plus canonical IDs. Exposed as an agent tool next to grep. | 8, 9 | Low–Med | Graph of about 160 nodes; under 10 ms |
| 6 | **Hybrid retrieval** for memory and qa-knowledge: SQLite FTS5 BM25 plus existing vectors, fused with RRF. Embed all memory files. | 3 | Low–Med | One FTS index; incremental |
| 7 | **Bi-temporal memory frontmatter**: `valid_from`, `invalid_at`, `superseded_by`. Dropped or changed decisions invalidate the old fact instead of sitting beside it. | 5 | Low | No growth beyond fields |
| 8 | **Citation-graph fixes**: correct the CONTEXT.md status, fix the `citation`/`reference` filter mismatch, and store every parent edge rather than only the first, so it's a graph and not a tree. | 4 | Low | Edges grow O(refs) |

Only after rank 2 shows a gap: query routing plus PageRank for multi-hop questions (patterns 2 and 8), and lazy cached
community summaries.

---

## 6. Not verified

- The reel speaker's credentials.
- graphify's "71.5x token reduction" claim (vendor).
- The LazyGraphRAG 700x query-cost figure.
- Exact HippoRAG 2, A-MEM, KGGen and Mem0 (V3) numbers.
- Sleep-time compute gains.
- Any evidence that LLM edge-confidence scores are calibrated (none found).
- A head-to-head of graph code retrieval against plain grep agents on SWE-bench (none found).
- Best practice for maps of content (MOCs) and dangling links (no primary source).
