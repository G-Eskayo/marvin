# ADR 0070: Research skill checks research-feed before fetching fresh

**Status:** Proposed  
**Date:** 2026-10-22  
**Related Issue:** [#54 — Wire research skill to research-colony](https://github.com/G-Eskayo/marvin/issues/54)

## Problem Statement

The `/research` skill and `/research-colony` agent both exist and work independently, but carry no data dependency between them. The user noticed that `research-colony` (with live arXiv/GitHub/HN crawling) already publishes findings to `~/.claude/research-feed/`, yet `/research` never reads that output — it always fetches fresh. This creates two problems:

1. **Redundant API calls** — when a topic is in `research-colony`'s tracked domains (AI/agents/LLMs), fetching again wastes API quota against already-fragile services (Semantic Scholar known to 429 frequently per `feedback-s2-api-fragile-use-openalex`).
2. **No synapse in brain-map** — while both skills are valid nodes, they carry no declared relationship in `enrichment.json`, so the knowledge graph does not surface the connection to users exploring MARVIN's capabilities.

## Research Questions

### Q1: Does `/research` currently connect to research-colony's output at all?

**Answer:** No. The `/research` skill's entire Process section (`skills/research/SKILL.md:35-98`) and its `academic_search.py` script never read `~/.claude/research-feed/` or `~/.claude/research-digest/`. 

**Evidence:** Skills that declare dependencies use `calls:` keys in their frontmatter (`skills/tdd/SKILL.md:5` shows `calls: [diagnose]`), which are picked up by `rebuild-manifest.py` into `~/.claude/manifest.json`. The `research` entry in manifest.json (line 207) carries no such `calls` key. Both `research` and `research-colony` are valid node ids in `brain-map/enrichment.json` (agent_overrides at lines 85), so a synapse would render if declared — the absence is a true gap, not a rendering limitation.

### Q2: Should every `/research` call check first, or only topics overlapping MARVIN's tracked domains?

**Answer:** Check unconditionally on every call.

**Evidence & Rationale:** 
- `research-colony`'s sources are narrow and recency-biased: arXiv `cs.AI/cs.LG/cs.MA/cs.PL` only (`source_monitor.py:19`), GitHub repos matching `llm|mcp|"ai agents"` pushed in the last 7 days (`source_monitor.py:53`), HN filtered to AI-terms allowlist (`source_monitor.py:86-91`).
- A `/research` query outside AI/agents/LLM tooling (biology, hardware, history, etc.) will almost always miss, costing nothing.
- The query itself is a local ChromaDB lookup, cheap even on a miss (no network call, no new storage).
- **Gating by topic classifier would be more expensive than the unconditional check** — it would require building a topic taxonomy for `research-feed` with no current evidence it's needed.
- North-star guidance (priority 1, "shed low-priority work") is satisfied by the query being cheap; a miss is not wasted work.

### Q3: Which mechanism—reuse `qa_query.py`'s `--lateral` mode, or something research-feed-specific?

**Answer:** Neither. Use the proven pattern already in `correlate.py` with a direct ChromaDB query and no date filter.

**Evidence & Rationale:**
- `qa_query.py`'s `--lateral` mode (`qa_query.py:49-54`) is built for the *opposite* problem: it filters by `domain` metadata and *excludes* the current domain to surface cross-domain transfer. This ticket needs "find whether this exact item was already found" — inclusion, not exclusion.
- `qa_query.py --lateral` also assumes a `domain` metadata field on items. The `research-feed` collection carries no `domain` field (`source_monitor.py:140-153` shows metadata is `title/url/source/date/published/tags/correlated/matched_topics/source_machine`). Reusing `--lateral` would require first inventing a domain taxonomy with no evidence it solves the problem.
- **The correct pattern is `correlate.py` itself:** it already runs plain ChromaDB queries against `research-feed` with cosine-distance threshold `< 1.1` (`correlate.py:93-97`), a pattern validated in production (see `research-colony-first-run` memory). The only modification needed is dropping the date filter (`correlate.py:73-76` currently scopes to `where={"date": today}`) to search across the full history, not just today.

## Recommendation

### Mechanism: Soft-merge with fresh fetch (not hard skip)

Before `/research`'s normal Process begins (before step 1, "Frame the question"), add an unconditional pre-check: query `research-feed` using `correlate.py`'s proven ChromaDB pattern with no date filter.

- If hits are found: surface them as an **informational note** for the model to weigh alongside doing a fresh search.
- If no hits: proceed to fresh fetch as normal.

**Why soft-merge, not hard skip?** Cached items in `research-feed` can be stale; skipping fresh search outright would contradict the `/research` skill's own epistemic stance ("accurate uncertainty, not false confidence" per `epistemic-framework.md`). The feed is a helpful signal, not canonical truth.

### Data dependency

Declare the new dependency in `skills/research/SKILL.md` frontmatter:
```yaml
calls: [research-colony]
```

Add matching `synapse_labels` entry to `brain-map/enrichment.json` (`synapse_labels` dict, line 23) to render the relationship:
```json
"research_to_research-colony": {
  "source": "research",
  "target": "research-colony",
  "label": "checks cached findings before fetching fresh"
}
```

This closes the exact gap the ticket noticed as a side effect of the real wiring.

## Decision

**Resolved** — unconditional check, soft-merge mechanism, built directly in #54.

The owner's comment on #54 requested a "What to build" section and gave a clear direction. Rather than defer to a follow-up ticket, this was built immediately using the unconditional, soft-merge approach (Option A from above). See `skills/research-colony/scripts/query_research_feed.py` for the implementation, `skills/research/SKILL.md` for the wiring (step 0 of Process), and `brain-map/enrichment.json` for the declared synapse.

## Test Cases (for follow-up build ticket)

If this ADR leads to a build ticket, it must cover (via TDD):

1. Empty `research-feed` collection (no ChromaDB data yet) — expect graceful pass-through to fresh fetch.
2. ChromaDB not installed or `chromadb` import fails — expect graceful skip of the check (mirror `source_monitor.py`'s `ImportError` guard), fallback to fresh fetch.
3. Query string with no AI/agent terms — expect empty or low-relevance ChromaDB result, clean pass-through to fresh fetch, no error.
4. Query exactly matching a just-fetched item in `research-feed` — exercise the no-date-filter path; expect cache hit and soft-merge note surfaced.
5. ChromaDB collection corrupt, locked, or inaccessible — must not crash `/research`; graceful fallback to fresh fetch.
6. Huge or malformed query string (very long, non-UTF8, injection-style text) — must not crash or leak to ChromaDB; graceful error handling.

## References

- [Issue #54 — Wire research skill to research-colony](https://github.com/G-Eskayo/marvin/issues/54)
- `skills/research/SKILL.md` — Process section (lines 35–98)
- `skills/research-colony/source_monitor.py` — arXiv/GitHub/HN crawling configuration
- `skills/qa-agent/scripts/qa_query.py` — lateral-mode pattern (relevant for non-solution: shows what was considered)
- `skills/qa-agent/correlate.py` — proven ChromaDB threshold query pattern (lines 93–97)
- `brain-map/generate.py` — synapse rendering (`build_synapses()`, lines 523–533)
- `brain-map/enrichment.json` — synapse_labels dictionary and agent_overrides
- Memory: `research-colony-first-run` — validation notes on `correlate.py`'s threshold in production
- Memory: `feedback-s2-api-fragile-use-openalex` — Semantic Scholar fragility context
- CONTEXT.md: `epistemic-framework.md` — `/research` skill's truth-seeking stance

---

**Related Architecture:**

This decision introduces a cross-skill data dependency (class: same as ADR 0014, new declarative relationship in manifest + graph). It does not introduce new storage, APIs, or user-facing behavior — it's an internal agent-efficiency optimization.

**Acceptance:** Decision pending owner approval of the `gate` option (A or B). Once approved, proceed to a scoped follow-up build ticket with TDD test cases as listed above.
