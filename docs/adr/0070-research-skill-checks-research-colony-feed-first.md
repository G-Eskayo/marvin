# 0070 — Research skill checks the research-colony feed first

## Status

Proposed (2026-10-22)

## Context

The research skill (epistemic, manual, rigorous) and research-colony skill (autonomous daily monitor of arXiv/GitHub/HN) operate in the same domain with no integration. When a user asks the research skill to investigate a topic, the skill immediately calls source APIs, unaware that:

1. **Research-colony may have already found it**: if the topic touches AI/ML/research domains the colony monitors, a recent run may have already fetched relevant papers or tools, correlated them against MARVIN's knowledge base, and stored them in ChromaDB `research-feed` collection.
2. **The feed holds structured metadata**: each item in `research-feed` carries `correlated: true/false`, `matched_topics`, and semantic embeddings — information that took CPU to compute, not available from raw API results.
3. **No visibility into existing work**: the research skill has no awareness of the colony's output, so it redoes API calls for papers/repos that are already stored, wasting quota and redundantly fetching.

## Lateral-mode design pattern

The research skill is designed for "deep research" mode: user asks a specific question, skill spends time triangulating and vetting sources. Research-colony runs daily autonomously: monitors feeds continuously, correlates everything to context, surfaces anomalies to the brief. These are different *modes* with different constraints, not the same process run twice.

**Lateral wiring** (research checks feed first) bridges the gap without collapsing the distinction: research stays responsible for deep investigation; colony stays responsible for autonomous monitoring. The check is a reference path between two separate systems, not a hierarchy.

This is a standing design decision: research-colony was added after research skill shipped, and the wiring to check existing work was never completed (CONTEXT.md line 1376–1380: "Research digest attaches findings to the tickets or north stars they relate to ... integration with research skill pending, ADR 0070").

## Evidence

- **Schema**: `research-feed` collection exists in ChromaDB at `~/.claude/chroma` with metadata keys `correlated: bool`, `matched_topics: str`, `source: str`, `date: str` (verified via regression test `test_store_items_metadata_structure` — real ChromaDB with temp directory).
- **Daily runs**: research-colony scheduled `com.marvin.research-colony` at 09:00 on both Macs (CONTEXT.md line 191).
- **Output contract**: research-colony output synced cross-machine via `cross_machine_merge.py` (CONTEXT.md line 44).
- **Correlation logic**: `skills/research-colony/scripts/correlate.py::correlate()` queries today's items against roadmap keywords and qa-knowledge embeddings (verified via regression tests `test_correlate_roadmap_keyword_match`, `test_correlate_multiple_keywords`, `test_correlate_date_filtering` — real ChromaDB with temp directory).
- **No current reference**: research skill's Process section (lines 35–97 of `skills/research/SKILL.md`) does not mention checking `research-feed` or querying ChromaDB before calling source APIs.
- **Regression test suite**: all correlate/source_monitor tests (test_correlate.py, test_source_monitor.py) use real `chromadb.PersistentClient(tmp_path)`, not mocks, for characterization of existing behavior.

## Decisions
<!-- marvin:decisions -->

### check_mechanism: How should the research skill query the research-feed?
- [ ] A: Query ChromaDB directly in Process step 1; show only items where `matched_topics` intersects the question
- [ ] B: Parse the day's `research-digest/YYYY-MM-DD.md` (rendered prose); extract items related to the topic by re-reading the digest with the LLM
- [ ] C: Check only on certain question types (e.g., academic claims about AI/ML, not general web queries)
- [ ] D: Don't check — research is orthogonal to colony and should stay independent; colony feeds into the brief, not the skill

### presentation: If items are found in the feed, what should the research skill output?
- [ ] A: Summarize feed findings + note that fresh search was skipped; offer "I want to search fresh" button if user wants more
- [ ] B: List feed items as "Already found by research-colony" section, then do fresh search in addition
- [ ] C: Show feed items only; skip fresh API calls if feed has enough coverage for the question
- [ ] D: Defer pending the check_mechanism decision (if A chosen, then B; if B chosen, then A; if D chosen, moot)

### scope: In what cases should the check run? (optional)
- [ ] A: Always, for every research request
- [ ] B: Only for queries on topics in the roadmap (`docs/north-stars.md`, `docs/marvin-roadmap.md`) or keywords the colony monitors
- [ ] C: Only if the user explicitly asks "what has the colony found on this" (add a flag or mode)

## Consequences (pending decisions)

- If check runs (not Decision 1D): research skill becomes a consumer of research-colony output, closing the loop described in CONTEXT.md line 1376.
- If feed covers the topic (Decision 2): reduces API quota usage and latency for questions the colony already monitors.
- The research skill remains the source for deep, user-driven investigation; colony remains the autonomous background monitor. The check is a lateral reference, not a hierarchy change.
- Implementation is small: one query function (new `skills/research-colony/scripts/check_colony_feed.py` reusing the connection/threshold pattern from `correlate.py`) + integration point in the Process section. Gated by decisions, not by scope uncertainty.

## Known findings

**`store_items()` deduplication (documented, not fixed)**: The pagination loop (lines 116–163 of `source_monitor.py`) uses `offset` to enumerate all existing items before deduplicating. This works correctly for single-machine daily runs but doesn't scale well if colony monitoring expands to hourly fetches on multiple machines (offset-based pagination can miss insertions from concurrent writers). **This is not a defect in the current implementation** — it is consistent with the design. Tagged in regression test `test_store_items_deduplication` (verifies the actual behavior: concurrent items are deduplicated by hash-of-URL before add). Revisit if scope changes.
