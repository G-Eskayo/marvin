# Acknowledgements

MARVIN is built on the shoulders of excellent open-source work. This project
exists because of the ideas, code, and standards created by the people and
organisations listed here. Everything is clearly credited and linked; nothing
is misrepresented as original.

---

## Direct inspirations & dependencies

### [Hermes Agent — NousResearch](https://github.com/NousResearch/hermes-agent)
**License:** MIT

The primary architectural inspiration for MARVIN. Hermes pioneered the
*closed learning loop* pattern for AI agents: autonomous skill creation from
experience, self-improvement during use, cross-session recall via FTS5 +
LLM summarisation, and the fork-to-review autonomy model (forked reviewer
+ tool whitelist = safe, bounded self-improvement). MARVIN's self-improve,
handoff, and memory systems are directly shaped by studying Hermes.

> "The self-improving AI agent built by Nous Research… the only agent with a
> built-in learning loop." — Hermes README

---

### [Matt Pocock's Skills](https://github.com/mattpocock/skills)
**Standard:** [agentskills.io](https://agentskills.io)

The engineering skill set installed in `skills/` originates from Matt Pocock's
`skills` repo (previous link here pointed at a repo that doesn't exist —
corrected 2026-07-07) and the `agentskills.io` open standard. Skills authored
by Matt Pocock and used here under the agentskills.io open standard:
`tdd`, `diagnose`, `grill-with-docs`, `zoom-out`, `handoff`, `self-improve`,
`improve-codebase-architecture`, `prototype`, `research`, `write-a-skill`,
`to-issues`, `to-prd`, `triage`, `grill-me`, and `setup-matt-pocock-skills`
(the last five were verified directly against his repo 2026-07-07 — a real
gap in this list before that, not previously credited here). Several were
adapted/wired into MARVIN's own workflow beyond their original form —
`self-improve` and `handoff` in particular gained real MARVIN-specific
infrastructure (ChromaDB-backed quality gates, retrospective logging,
session-continuity wiring) not present in the originals. MARVIN extends this
base with new skills (`qa-agent`, `caveman`, `index`, `lexicon`,
`self-optimize`) and wires the system into Claude Code.

---

### [ChromaDB — Chroma Core](https://github.com/chroma-core/chroma)
**License:** Apache 2.0

MARVIN uses ChromaDB as its vector store for semantic memory retrieval and
the `qa-knowledge` best-practices database. The `skills` and `qa-knowledge`
ChromaDB collections back MARVIN's persistent cross-session knowledge layer.

---

### [Ollama](https://ollama.ai)
**License:** MIT

Local embedding generation via `nomic-embed-text` for semantic similarity
in the MARVIN memory layer. Ollama makes it possible to run embeddings
entirely on-device with no API cost.

---

### [Anthropic Claude Code](https://github.com/anthropics/claude-code)
**License:** Proprietary (Anthropic)

The agent runtime MARVIN runs on. Claude Code provides the CLI, tool
execution, MCP integration, permission model, and hook system that MARVIN's
skills and memory layer plug into.

---

### [FastMCP](https://github.com/jlowin/fastmcp)
**License:** MIT

FastMCP is the reference for storage-level and semantic caching at the MCP
layer. MARVIN's roadmap includes integrating FastMCP-style semantic caching
to reduce token spend on repeated or near-identical context. Cited here
because the architecture informs MARVIN's planned caching layer even before
full integration.

---

## Research & writing that shaped this project

- **Vertus AI** — public research on inference-time token optimisation,
  semantic response caching, and latency reduction that directly informed
  the token optimisation best-practices in `best-practices/token-optimization.md`.

- **"Attention Is All You Need"** (Vaswani et al., 2017) — the transformer
  architecture underlying all Claude models, whose attention mechanism
  behaviour shapes how MARVIN structures prompts and caches context.

- **KV Caching, Flash Attention, Paged Attention** — ongoing research from
  the academic community and inference-serving teams (vLLM, FlashAttention)
  that informs MARVIN's self-hosted model track roadmap.

---

## Contributing

If you build on MARVIN, please continue this tradition: link back, give credit,
and describe clearly what you changed or added. The goal is a transparent,
attributable lineage — not a proprietary black box.
