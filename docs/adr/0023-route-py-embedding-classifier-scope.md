# 0023 — route.py's keyword classifier: replace with an embedding classifier, phased and flag-gated

## Status

Accepted (2026-08-13)

## Context

Grew out of a bitter-lesson audit (2026-08-13, prompted by Gil reading Sutton's essay) that
flagged `route.py`'s `INTENTS` keyword-scored classifier (`skills/route/scripts/route.py:24-108`,
4 hand-listed categories, `MIN_HITS = 2`, ties fall back to `architecture`) as the sharpest
instance of a repeated pattern: hand-encoded rule tables that need a human edit for every new
case, instead of a general mechanism that improves with more data. `route.py` is also the one
piece of this pattern actually tracked in the roadmap (§G, `[done]` with a noted live gap: the
"lean saves 9-10% on coding" claim doesn't hold on harder tasks per bench Run 13/15 — a separate,
pre-existing problem this ADR doesn't attempt to fix).

Two adjacent mechanisms already exist in this codebase and were used as direct precedent rather
than invented fresh:

- `skills/self-improve/scripts/retrieve.py` already embeds queries via a local Ollama
  `nomic-embed-text` call and queries ChromaDB collections created with
  `metadata={"hnsw:space": "cosine"}` (`skills/self-improve/scripts/rebuild-embeddings.py:78-80`),
  falling back to manifest tag-matching when Ollama/ChromaDB is unavailable. Confirmed live:
  Ollama is running locally with `nomic-embed-text` installed.
- `skills/safety-monitor/scripts/calibrate.py` computes a threshold from labeled approve/deny
  outcomes, falling back to a conservative fixed default until enough labels exist — but that
  loop is fed by the quarantine review workflow, which routing has no equivalent of. Building a
  parallel labeling mechanism for routing decisions was judged out of scope for this pass (see
  Decision, point 2).

Also found live during scoping: `qa-knowledge`/`research-feed` (queried by `correlate.py`) use
ChromaDB's own default embedder, not Ollama nomic-embed — a second embedding backend already
coexists in this system today. This ADR does not change that; it only adds a third, separate
collection on the nomic-embed backend, consistent with `retrieve.py`'s pattern specifically.

Scoped via `grill-with-docs`, four questions resolved in sequence (recorded below).

## Decision

**1. Phased, route.py only this pass.** The suggestion this ADR implements
(`~/.claude/suggestions.md`, priority 9, 2026-08-13) also named `CLAUDE.md`'s duplicate Auto-route
keyword table and `correlate.py`'s `ROADMAP_KEYWORDS`/`threshold=1.1` as instances of the same
pattern. Both are deferred until this build proves out — smaller diff, benchable in isolation,
avoids extending an unproven mechanism to two more call sites at once.

**2. Fixed similarity threshold for v1, no calibration loop.** Unlike safety-monitor, routing has
no existing right/wrong labeling mechanism. Building one (e.g. a `--correct` flag, or inferring
from whether Gil overrides the suggested intent) is real, separate design surface, deferred as a
fast-follow once real usage data exists. Ships with a hand-picked fixed threshold, same
fallback-until-labeled shape `calibrate.py` already uses for `DEFAULT_TAU`.

**3. Reference set: a new `intent-routing` ChromaDB collection, not a keyword-list embedding.**
5-8 example task descriptions per intent, written from the *concepts* behind the current keyword
lists (not the literal keyword strings), embedded via the same Ollama call `retrieve.py` makes,
stored in a collection created with `metadata={"hnsw:space": "cosine"}` — matching
`rebuild-embeddings.py`'s existing pattern exactly. Classification = nearest example match by
cosine similarity, not one blended vector per intent.

**4. Flag-gated burn-in, not a hard cutover.** Ships as `route.py --embed`, opt-in. The existing
keyword classifier stays in the code, serving two roles: the burn-in comparison baseline, and the
automatic fallback when Ollama/ChromaDB is unreachable at runtime (mirroring `retrieve.py`'s own
`tag_fallback` degradation path). Default only flips to the embedding classifier once a real bench
comparison run (roadmap §G: "every routing decision must be bench-validated before shipping")
shows it matches or beats the keyword classifier on route.py's existing task-type cases.

## Consequences

`CLAUDE.md`'s duplicate Auto-route table and `correlate.py`'s `ROADMAP_KEYWORDS`/`threshold=1.1`
remain unchanged for now — still hand-maintained, still drift-prone against each other and against
whatever route.py becomes. Revisit as separate suggestions once this proves out, not folded in
here.

No learned-threshold loop means a real accuracy regression on the fixed threshold won't
self-correct — it needs Gil to notice and manually adjust, the same maintenance shape as the
keyword thresholds this ADR is trying to move away from, just one number instead of several
keyword lists. Judged an acceptable, smaller-scope tradeoff for v1.

Classifier quality is now bounded by the quality of the 5-8 example descriptions per intent,
rather than by keyword-list completeness — a different maintenance burden, not zero. Reference
examples are easy to add to (no code change, just a collection entry), which is the point, but
nothing currently curates or prunes them if reference-set quality drifts.

Built same-day (2026-08-13): `~/.agents/lib/intent_classify.py` + `intent-routing` ChromaDB
collection, `route.py --embed` flag with keyword-classifier fallback, 16 passing tests. Bench
run (`bench/RESULTS.md` Run 17) confirmed the embedding classifier beats keyword on a held-out
fixture (60% vs 35%) but wasn't yet accurate enough to flip the default. Fast-follow (Run 18):
reference set doubled to 12 examples/intent, targeting Run 17's actual misses; re-run on the same
small fixture hit 85%. Second fast-follow (Run 19), same day: grew the fixture from 20 to 40
items plus a separate 8-item ambiguous set (scored against acceptable-sets, not folded into
accuracy) — the 85% didn't hold on the wider fixture, landing at 70% (keyword 30%), with
`research` phrasing the weakest category. Third fast-follow (Run 20): targeted `research`-only
reference-set expansion (12→20 examples), overall 70%→72%, `research`-specific 50%→70%, with a
genuine side effect — one previously-correct `recall` item flipped, showing reference-set growth
in one intent isn't free for neighboring intents in a shared embedding space. Run 21 finally closed
the fresh-held-out-set gap Run 19 opened: built `bench/holdout_fixture.py` + `validate_holdout.py`,
a genuinely never-tuned-against 40-item set, verified zero overlap with every other fixture. Result:
**70% on real fresh data**, matching the 72% tuning-set read within noise — the accuracy claim
survives independent validation, though ambiguous-case handling (8/8 on the tuning set) dropped to
3/6 on fresh ambiguous cases, suggesting that number was a small-n artifact. 70%/keyword-25% is now
a trustworthy number, not just a directional one.

**Default flipped 2026-08-13** (Gil's call, after Run 21's validated 70%): before flipping, found
and fixed a real bug in `classify()`'s score formula — `1.0 - dist` assumed ChromaDB cosine
distance is 0-1, but it's actually 0-2 (documented gotcha already in qa-knowledge, discovered
while checking whether the ingested repos had anything relevant to improving accuracy). Empirical
check showed the bug's practical effect was worse than the formula alone: `THRESHOLD=0.35` never
rejected anything, even genuinely off-topic probes ("what time is it in Tokyo", "sing me a song")
scored 0.60-0.80 under the broken formula. Fixed the formula (`1.0 - dist/2.0`) and recalibrated
`THRESHOLD=0.72` empirically against the holdout fixture's on-topic distribution (max dist 0.524)
vs. 8 off-topic probes (min dist 0.396) — the two distributions overlap substantially at this
reference-set size, so this is a weak sanity floor, not reliable off-topic detection; a real fix
still needs the calibration loop deferred by decision 2. `route.py`'s CLI flipped: embedding is now
the default, `--keyword` opts back into the old classifier (renamed from `--embed`, which is no
longer meaningful as a flag now that it's the default). Re-validated on the holdout fixture after
the fix: still 70%, unchanged — the bug didn't affect on-topic accuracy, only the (previously
non-functional) off-topic floor.

Run 23 investigated the off-topic detection gap directly (margin-based scoring, an explicit "other"
reference category) — both came back negative, logged as a real finding, nothing shipped. Run 24
(2026-08-13): redirected to `research`/`coding` accuracy (both at 60% per Run 21) — grew both
reference sets (research 20→26, coding 12→18) targeting `FIXTURE`'s specific misses. Real gain on
both targets (+2/+3), but a real disclosed cost to `recall` (10/10→7/10 tuning set, 9/10→8/10
holdout) — the same cross-category mechanism Run 20 first found, now larger. Net positive both
sets (72%→80% tuning, 70%→78% holdout-informational), not a clean win. Named explicitly: this
round's holdout number is informational only, not independently validated — the decision to target
research/coding was itself holdout-informed (category-level leakage), even though wording came
only from the already-contaminated `FIXTURE`. A genuinely fresh holdout is now the honest
prerequisite before trusting further accuracy claims at Run 21's level of confidence.

Run 25 (2026-08-13): fixed the `recall` regression by diagnosing the specific pulls (Run 24's new
research/coding examples sharing surface patterns with genuine recall phrasing) rather than adding
generic reinforcement — clean on the tuning set (`recall` 7→10/10, zero cost to research/coding),
but one small new cost surfaced on the informational holdout (`architecture` 7→6). Current state:
87.5% tuning set / 80% holdout-informational, every category has now moved at least once, treated
as provisional per Run 25's own finding until a fresh holdout validates it independently.

Run 26 (2026-08-13): built that fresh holdout (v2, `bench/holdout_fixture.py`; v1 archived intact
as `holdout_fixture_v1_spent.py`). **Result: 72%, not 87.5%** — almost exactly back to Run 21's
original 70%, meaning three tuning rounds moved the true accuracy by ~2 points while the
tuning-set number moved 17. `recall`/`research` held up genuinely (10/10, 9/10); `coding` dropped
to 6/10 and `architecture` to 4/10 (the worst category measured in this whole sequence, never
once the deliberate target of a tuning pass — only ever noted as collateral damage). 72% is the
number to trust now; `architecture` is the clear next priority, evidence-backed rather than
assumed.

Run 27 (2026-08-13): diagnosed and fixed `architecture` (its first expansion since Run 17, 12→22
examples) — the largest single-round gain in this sequence, confirmed by held-out data:
`architecture` went 4/10→10/10 on the fresh v2 holdout. Real disclosed cost: `research` dropped
9→7 on the same holdout (architecture's expanded territory pulling from research). Overall fresh
number: 72%→82.5%. `coding` remains unaddressed at 6/10, unchanged since Run 26 — the clear next
target. v2 holdout is now spent at the category level for `architecture`, same lifecycle as v1.

Run 28 (2026-08-13): diagnosed and fixed `coding` (18→23 examples) using a deliberately small,
5-example expansion to test Run 27's hypothesis that smaller expansions cost less. Confirmed:
`coding` went 6/10→10/10 on the fresh holdout with **zero collateral cost anywhere** — the second
fully clean fix in this sequence (after Run 25's recall fix, also small), versus every large
expansion (Runs 20, 24, 27) costing something. Current state: 92.5% on both FIXTURE and the v2
holdout, but v2 is now spent across all four categories — a v3 holdout is the honest prerequisite
before claiming 92.5% as independently validated at Run 21/26's level of rigor. `research` is the
one category never yet the target of a clean, diagnosed fix.

Run 29 (2026-08-13): built v3 (v2 archived intact as `holdout_fixture_v2_spent.py`). **Result:
87.5%, independently confirmed** — and the gap to the tuning-set number (92.5%) has narrowed to 5
points, down from Run 26's 15.5-point gap, a real sign the diagnose-before-expand discipline
(Runs 25, 27, 28) produces gains that transfer rather than fixture-fitting. `research` scored
perfect (10/10) for the first time in this sequence. v3 is fresh as of this entry — nothing yet
diagnosed from its small new misses (`recall`↔`architecture` confusion, one `coding` miss).
Ambiguous-case handling (50-67% across all three holdout versions) remains the one consistent,
never-addressed weak spot. 87.5% independently validated, up from Run 21's original 70%, is a
reasonable point to treat this as either continuing (fix the new small misses) or closing out.

**Phase 2 (2026-08-13, Gil's direction: treat route.py as done, move to CLAUDE.md's Auto-route
table).** Investigated before building: `CLAUDE.md`'s Auto-route step is documented as part of
Session Start but is NOT one of the 11 items the `SessionStart` hook automates — it's model-applied
prose, evaluated against the user's first message. A `SessionStart` hook fires before any user
input exists, so it structurally cannot see that message; the original suggestion's "route it
through the same classifier" needed a `UserPromptSubmit` hook instead (has access to `user_prompt`
and `session_id` per stdin JSON), not an extension of the `SessionStart` hook.

While investigating hook wiring, found a separate, larger bug: `session_start_report.py` — which
CLAUDE.md documents as the wired `SessionStart` hook producing the identity banner and all 11
checklist items — was not actually referenced anywhere in `settings.local.json`. Confirmed live
(this session's first reply never received the banner). Queued and, on Gil's approval, fixed:
appended it to the existing chained `SessionStart` command (verified `code_sync.py pull`'s
stash-refusal path doesn't `sys.exit`, so the existing `&&` chain wasn't silently broken by it).
See `suggestions.md`'s "session_start_report.py..." entry (priority 10, resolved 2026-08-13).

Built `skills/route/scripts/auto_route_hook.py` (TDD, 14 tests): a `UserPromptSubmit` hook that
fires at most once per session (tracked by `session_id` in `~/.claude/auto-route-state.json`),
calls `route.resolve_intent(prompt, use_embed=True)` — the same default classifier route.py itself
uses — and prints a routing suggestion for recall/coding/research, staying silent on architecture
or low-confidence, matching the original prose's behavior exactly. Any failure (Ollama down,
unexpected exception) exits silently rather than blocking the user's prompt. Wired into
`settings.local.json`. `CLAUDE.md`'s old hand-maintained `Routing keywords: recall=..., coding=...,
research=...` line — the second of the two duplicate keyword tables the original bitter-lesson
audit flagged — is deleted; Auto-route's CLAUDE.md entry now just documents the hook, per the same
"don't re-perform hook-automated checks by hand" convention already used for the other 11 Session
Start items. `correlate.py`'s `ROADMAP_KEYWORDS`/`threshold=1.1` remains the one deferred phase
left from the original suggestion.
