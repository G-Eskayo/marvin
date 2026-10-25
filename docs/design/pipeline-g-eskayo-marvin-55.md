Confirmed: `--lateral` does retrieval-time cross-domain filtering (excludes the queried domain, returns transferable patterns), not a persistent clustering/abstraction layer — exactly as the parked memory noted. That's enough grounding to write the plan.

---

## North-star fit

**Existing pattern this reuses:** `qa_query.py` (`~/.agents/skills/qa-agent/scripts/qa_query.py`, `query()` with `--lateral`, lines 28-66) already does retrieval-time cross-domain combination over qa-knowledge's raw entries — but it's query-time filtering, not a persistent abstraction layer, so it doesn't answer this ticket's question on its own; it's the closest prior art to check any clustering design against. `MEMORY.md`'s pointer-index-not-inline-content shape (`~/.claude/projects/-Users-gileskayo/memory/MEMORY.md`) is the one structural precedent already in production for "reference, don't duplicate," and is the shape `lexicon.md` would need to move toward if concept nodes feed it.

**Why this plan doesn't propose a build:** issue #55 is explicitly tagged `research-spike` and its own body states *"the deliverable is an answer/scoping doc, not an implementation."* Its triage comment (the one existing comment) is a denial: *"This ticket is missing: a 'What to build' section. Add those and it can be picked up."* There is no 'What to build' section in the issue — triage flagged exactly that and said it should **not** yet be picked up for building. The parked memory (`project-qa-knowledge-concept-clustering.md`, 2026-08-19) confirms this is a real, unresolved design tension (bottom-up technical concepts from qa-knowledge vs. top-down behavioral concepts in hand-curated memory) that Gil explicitly deferred to its own `grill-with-docs` session rather than resolving ad hoc.

Writing a concrete implementation plan now would mean inventing the resolution to the open tension myself, silently, in a pipeline run with no human present — precisely the failure mode the ticket is trying to avoid ("needs its own grill-with-docs pass"). That fails the Watts check (machinery serving the system's own momentum to produce *a* plan, not a plan that serves the real open question) and the "verified, not assumed" principle: the fit between qa-knowledge clustering and the existing memory layer hasn't been checked by anyone, including me, today.

**Token cost:** spending effort here to force a fake implementation plan would cost more tokens than it saves — it would need rework once the real `grill-with-docs` session runs anyway. Flagging now instead of building is the cheaper path.

**User capability:** forcing a build plan here would make Gil *less* able to make the actual call — the ticket needs his judgment on a genuine two-way architecture split (one concept layer vs. two), not a default I pick for him.

## Decisions

This ticket cannot proceed to build without the owner resolving the structural question it names. Per `docs/agents/decisions-format.md`:

<!-- marvin:decisions -->
### d1: Before this ticket can carry a 'What to build' section, which shape should qa-knowledge concept clustering take?
- [ ] One unified concept layer — qa-knowledge clustering and hand-curated feedback/project memories feed the same lexicon.md structure
- [ ] Two separate layers — qa-knowledge clustering produces technical/code concepts; feedback/project memories stay the separate behavioral/collaboration layer; lexicon.md references both but keeps them distinct
- [ ] Run the `grill-with-docs` session the ticket calls for, then re-file this ticket with its answer

## Task List

TOO_VAGUE: Issue #55 is a research spike whose own body says the deliverable is an answer/scoping doc, not an implementation, and its only comment is a triage denial stating the ticket is missing a required 'What to build' section ("Add those and it can be picked up"). There is nothing to break into implementation tasks yet — the acceptance criteria ask for an answered open question, a findings write-up, and a recommendation, not code. The real next step is the `grill-with-docs` session the ticket itself calls for (resolving the one-layer-vs-two-layer tension above), not a task list. I did not invent a build plan to fill this section.