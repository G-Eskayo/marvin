---
status: decided
date: 2026-10-22
---

# ADR 0070: `/research` pre-check against research-feed — scope and query design

## Context

The `/research` skill and `/research-colony` autonomous agent both access research sources (arXiv, GitHub, HN, Semantic Scholar, general web). Research-colony's `correlate.py` already identifies items matching MARVIN's known work domains and stores them in the `research-feed` ChromaDB collection with today's date and matched-topic metadata.

**Open design question:** when a user calls `/research` on an ad-hoc topic, should the skill check `research-feed` first to avoid re-fetching what research-colony found this morning, or does the overlap between user queries and MARVIN's autonomous research focus too rare to justify the lookup cost?

Two sub-questions emerged during scoping:
1. **Scope:** check for every `/research` topic, or only topics overlapping MARVIN's tracked domains?
2. **Query mechanism:** how should the pre-check query work, and is lateral-mode (qa_query.py's cross-domain synthesis pattern) the right pattern?

## Decision

### 1. Scope: Domain-overlap only

Check `research-feed` only when the user's research topic overlaps one of MARVIN's tracked domains (keywords in `correlate.py:ROADMAP_KEYWORDS`, A–J sections of the roadmap).

**Rationale:** 
- `/research` is called on arbitrary user topics; most queries (user asks about unrelated topic) → research-feed has 0 items for that topic.
- Research-colony only autonomously researches MARVIN's known domains (arXiv CS.AI/CS.LG/CS.MA/CS.PL, GitHub/HN filtered by AI/LLM/MCP keywords).
- Domain-overlap check is cheap (keyword match + metadata filter) and high-signal: if the topic matches, research-feed is guaranteed fresh (today's digest) with no stale risk.
- North-star: "minimize token cost" — avoid querying when signal probability is low.
- **Evidence:** correlate.py already proves this scope works (first run 2026-06-30: 29 fetched → 34% correlation rate with 1.1 threshold, 10 items matched across A–C domains). Pattern proven; reuse it.

### 2. Query mechanism: Reuse plain ChromaDB vector search, not lateral mode

Use a direct semantic similarity query (ChromaDB `query_texts`) against today's research-feed items. This is the exact pattern already working in both `qa_query.py:37` and `correlate.py:93`.

**Why not lateral mode:** Lateral mode (`qa_query.py:49-54`) deliberately excludes a domain to surface cross-domain transfer ("I'm in domain X, find patterns in other domains"). Research-feed checking needs topical *relevance* — the opposite direction. Lateral is for creative synthesis; pre-checking is for "did someone already find this?"

**Evidence:**
- Both query calls use identical ChromaDB API: `col.query(query_texts=[...], n_results=...)`.
- Lateral mode's filtering logic (`if metadata.domain not in (..., lateral_domain)`) would be wrong here — it would *exclude* MARVIN's own domains, the opposite of what we want.
- **Confidence: Established** — pattern mismatch is structural, not empirical.

### 3. Staleness window: Today-only, tune via feedback

Check only items from today (date==today filter, matching `research_digest.py:83`). Research-colony runs 09:00; most same-day `/research` calls will catch fresh results.

**Edge case:** user researches at 3am → research-colony runs at 9am → user's query missed it. Known limitation; acceptable starting point. Can tune to 24–48h window if usage patterns show frequent late-night research.

**Confidence: Speculative** (real usage patterns unknown).

## Consequences

- **Token cost:** One vector query (negligible) per `/research` call where topic overlaps a roadmap keyword. No cost for unrelated topics.
- **Latency:** +~100ms (local ChromaDB query) when pre-check fires. Hidden inside the larger research fetch cycle, not user-blocking.
- **Dependency:** `/research` gains a hard dependency on `research-feed` ChromaDB collection existing (same graceful-skip pattern as `research_digest.py:65-68` — if missing, log and continue).
- **Maintenance:** `ROADMAP_KEYWORDS` must stay in sync with actual roadmap domains. Quarterly review suggested (audit skill already checks this via north-stars).

## Verification

1. ✅ Cross-machine sync — research-feed already synced by `cross_machine_merge.py` (enrichment.json:168). No new work.
2. ✅ ChromaDB failures — Both handle gracefully: `correlate.py:55-57` (import-missing) and `correlate.py:63-67` (collection-missing); `qa_query.py:34` does the same. Pattern proven.
3. ✅ Distance threshold — Cosine 1.1 already tuned from first run (34% correlation rate, from research-colony-first-run memory). Reuse.
4. ✅ Lateral mode misfit — Structural logic mismatch confirmed (see Decision section 2).
5. ⚠️ Today-only scope — Speculative; reasonable default, but late-night edge case exists. Feedback will refine.
6. ✅ Permissions/tool blocking — Read-only ChromaDB, no Write/Edit. Same pattern as `research_digest.py:127`.
7. ⚠️ ROADMAP_KEYWORDS staleness — Hand-maintained, 30 keywords covering A–J. Sufficient; needs update discipline when roadmap grows.
8. ✅ Duplicate fetch prevention — Checking first prevents re-fetching arXiv/GitHub/HN items already in today's digest. Saves tokens, matches north-star.

## Recommendation for Implementation

**Build:** Helper script `research/scripts/check_research_feed.py`
- Input: framed research question (string)
- Output: list of today's correlated items from research-feed (empty if none/missing)
- Calls: `qa-knowledge.query(query_texts=[question], n_results=5, include=["documents", "metadatas"])` to find semantic matches in correlated today's items
- Graceful skip: if chromadb missing or collection not found, return [] (same pattern as correlate.py)

**Wire location:** `research/SKILL.md` Process, after step 1 ("Frame the question") as step 1.5
- Run `check_research_feed.py` with the framed question
- If found, include results in context before step 2 ("Map the space")
- If not found, proceed normally

**Proposed follow-up ticket scope (not this ticket):**
- Add `check_research_feed.py` helper
- Insert Process step 1.5 in SKILL.md (prose + helper call)
- Add 2–3 minimal tests (mock chromadb, verify query called with right filter, verify graceful skip)
- No changes to research-colony, qa-agent, or enrichment.json core logic

**Token cost of building:** ~200 tokens (helper script + one SKILL.md prose insert). **Token cost of NOT building:** 1–3 duplicate research sessions per week (same topic researched twice, once by colony and once by user) × 500 tokens each = ~1000 tokens/week wasted.

---

## Related

- [[ADR 0014]] — research-colony event-driven merge trigger (uses same correlate.py+ROADMAP_KEYWORDS scoping)
- [[ADR 0013]] — task-dispatch general primitive (research-colony's cross-machine orchestration)
- `~/.claude/marvin-roadmap.md` § D3 (Research source routing) — where this gap was identified
- `enrichment.json` lines 163–164 — research-colony's own brain-map node (missing synapse entry to /research; see ticket title for optional one-liner fix)
