## North-star fit

**Reuses before adding anything new:**
- `lib/marvin_launcher.py:launch()` / `KINDS` table (ADR 0059) for every Claude-as-teacher call — it already gives cost_usd, wall time, error classification (`classify_exit`) and a `runner=` injection point for tests. No hand-rolled `subprocess.run(["claude","-p",...])` (bench.py's `_check_quota` and select_model.py's ladder predate this and would just duplicate it).
- `lib/metrics_registry.py:record()`/`compare()` for the baseline-vs-tuned accuracy/cost/time report — the exact primitive CONTEXT.md says formalizes "the `bench/RESULTS.md` pattern ... baseline, change, re-measure, iterate until genuinely better."
- `skills/paper-dive/scripts/logic_auditor.py:judge_extraction`, `compute_reliability_signal`, `EXTRACTION_FIELDS`, `model_registry.resolve_capability` — the actual judgment step being tuned; its existing `chat_fn=` injection convention (also in `competing_ideas.py`) is reused for every new test, so nothing needs a real Ollama/Claude call to be tested.
- `skills/paper-dive/scripts/competing_ideas.py`'s `CHROMA_PATH`/`COLLECTION_NAME` and `semantic_search` — reused to pull real, already-ingested abstracts ("our own past runs") instead of inventing a second Chroma access path or synthetic text.
- `bench/bench.py:_ollama_available()` for the local-model liveness check, and `bench/select_model.py`'s "only lock in after it actually passes, cheapest-first" discipline, carried over as "only keep an edit that doesn't regress."

**Why this is the simplest sufficient approach:** OpenJarvis's three edit types are prompts, tools, model/engine settings. Here "tools" is N/A (judgment is a single chat completion, no tool use) and "model" is N/A (only `qwen2.5:3b` survived #563's deletion — there is nothing to switch *to*). So the real search space collapses to two knobs: judgment prompt wording and one Ollama option (temperature). Building a generic two-function loop (`propose_edit`, `evaluate`) over an injected spec dict is the least machinery that still matches OpenJarvis's shape and stays reusable for the two named follow-on jobs (triage classification, daily digest) — a bespoke one-off script tuned only to paper-dive would not survive reuse.

**Why both prior attempts failed, and what changes:** the first failed "after 3 iterations" and the second timed out at 1200s — both symptoms of treating this as a **tunable-subsystem ticket** (CONTEXT.md: gate = `metrics_registry.compare().passing` must be literally `True`, live, inside the pipeline's verify step) when it is actually a **build-type ticket carrying a spike** (CONTEXT.md: "a build-type ticket's passing gate is mechanical ... tests pass, build is clean" — not a forced metrics-improvement verdict). This plan's pytest gate is 100% offline/fake-injected (mirrors `logic_auditor.py`'s own testing convention) and finishes in seconds; the one real, paid, live run (real Ollama + real Claude, producing the actual numbers the ticket asks for) happens once as part of implementation and is written to a report — it is never re-executed by the merge gate, the same way clarity-captions' Spike-app-build tier is optional and simply says "not verified: ..." rather than blocking merge.

**Tokens:** spent deliberately but small — one teacher call per benchmark sample to build gold labels (cached to disk, never re-paid), one teacher call per spec-search iteration (bounded, `utility-call` kind = minimal context layers, not a full agent session), capped sample count and iteration count. Saves tokens going forward only if the spike succeeds: it is the thing that lets paper-dive's judgment step run on-device instead of needing a model that's already gone from disk.

**Phone-OS / capability direction:** this is explicitly the "move high-volume, low-judgment jobs to local models" leg of the $20-plan governor (M3, 2026-11-27) that #594/#563 depend on — a direct, named input to that milestone, not a tangent.

**More capable or more passive:** the user-facing payoff here is Gil, not an end user watching paper-dive — it leaves *Gil* able to keep running paper-dive's judgment step for free, locally, after the $100 plan ends, instead of either losing the capability or being forced to keep paying for it. Automating the search itself (rather than hand-tuning prompts the way route.py's classifier was hand-tuned over many runs) is appropriate here because the task-is mechanical pattern-search, not judgment Gil would learn from doing himself.

## Decisions

<!-- marvin:decisions -->
### wire-in: If spec search finds a prompt/temperature that beats today's setup, what happens to it now?
- [ ] A: Ship it as logic_auditor.py's new default in this same PR (judgment step starts using it immediately)
- [ ] B: Leave logic_auditor.py untouched; this PR only reports the winning spec as a recommendation, and wiring it in is left to #563 (which already owns "paper-dive should say so plainly and either pull it on first use ... or fall back to a stated alternative" for this exact gap)

## Tests first

All of the following inject fakes for every side-effecting call (`chat_fn`, `teacher_fn`, `student_fn`, `runner`) — same convention `logic_auditor.py`/`competing_ideas.py` already use — so none of them touch a real Ollama server, ChromaDB, or the `claude` binary. This is itself one of the tests (#16).

**`lib/spec_search.py` (new generic primitive):**
1. `evaluate()` with an empty benchmark-sample list returns a defined, non-crashing result (no `ZeroDivisionError` on an empty mean) — empty input.
2. `evaluate()` where `student_fn` raises on one sample (simulated Ollama failure) propagates/surfaces that failure rather than silently scoring it as a pass — dependency failing.
3. `propose_edit()` when `teacher_fn` returns non-JSON / malformed text → no-op (current spec unchanged), never a crash — malformed input from the teacher.
4. `propose_edit()` when the teacher's JSON is well-formed but has a missing key or an out-of-range value (e.g. `temperature: 5`) → rejected the same way as #3 — malformed structured input.
5. `search()` discards an edit that regresses accuracy (fake teacher proposes a worse prompt) — final spec equals the initial spec. This is the core OpenJarvis "only keep non-regressing edits" contract.
6. `search()` halts at `max_iterations` even when the fake teacher keeps proposing different edits forever — bounded loop, no runaway cost.
7. `search()` stops early once accuracy hits 1.0, without spending remaining iterations — token-minimization check.
8. `search()` given the identical fake teacher/student call sequence twice produces identical results both times — no hidden shared mutable state between runs.
9. A repo-hygiene test asserts `search()`/`evaluate()` make **zero** real `urllib`/`subprocess` calls when every collaborator is injected — directly guards against repeating the 1200s-timeout failure.

**`skills/paper-dive/scripts/judgment_benchmark.py` (new, paper-dive wiring):**
10. `build_benchmark_samples()` against a missing/empty `paper-knowledge` collection raises a clear, loud error — never silently returns an empty benchmark (which would make `search()` trivially "pass") — matches #563's own "never fail silently" rule.
11. Requesting more samples than exist in the collection returns what's available with an explicit note, not padded/duplicated — bad input size.
12. The student call (local `qwen2.5:3b`) against a down Ollama server / model not pulled raises a clear, distinguishing error (reusing `bench.py:_ollama_available()`'s shape) rather than a generic traceback — dependency failing.
13. Gold-label building, when the teacher's `marvin_launcher.launch()` call comes back `classify_exit() == "usage-limit"`, aborts loudly with that reason surfaced — not cached as a false "gold" label — dependency failing, reuses the existing error taxonomy instead of inventing a new one.
14. `score_fn`: identical reliability level between student and gold scores 1.0; a different level scores 0.0; a malformed/unparseable student response scores 0.0 rather than raising — a model's own mistake must not crash scoring.
15. Running `build_benchmark_samples()` twice is idempotent (reads the on-disk cache, makes zero further teacher calls) — cost discipline — and a truncated/corrupted cache file is detected and rebuilt rather than silently trusted — stale state / a person's mistake.
17. On a machine with no Ollama/Chroma available at all (e.g. a laptop profile), the script states plainly "not available on this machine" rather than hanging — reuses `project_profile.py`'s existing phrasing for this exact situation.

**`logic_auditor.py` additive change (new optional `prompt_template` param on `judge_extraction`):**
18. Calling `judge_extraction(extraction, paper_type, chat_fn=fake)` with no `prompt_template` produces byte-identical prompt text to today — regression guard; all existing tests in `test_logic_auditor.py` must keep passing unmodified.
19. Calling it with `prompt_template=<custom>` sends the custom template's formatted text instead of `_JUDGMENT_PROMPTS[paper_type]` — verified via the fake `chat_fn` capturing the literal prompt sent.

## Task List

1. Add `judge_extraction(..., prompt_template: str | None = None)` to `skills/paper-dive/scripts/logic_auditor.py` — additive, default preserves current behavior exactly (tests #18–19). No other change to this file.
2. Write `lib/tests/test_spec_search.py` covering tests #1–9 against the not-yet-written `lib/spec_search.py` (red).
3. Implement `lib/spec_search.py`: `evaluate(spec, samples, student_fn, score_fn)`, `propose_edit(spec, failing_samples, teacher_fn)` (validates the teacher's JSON spec, no-ops on anything malformed), `search(initial_spec, samples, student_fn, teacher_fn, score_fn, max_iterations)` implementing the keep-only-non-regressing-edit loop with early stop on perfect score (green).
4. Write `skills/paper-dive/scripts/tests/test_judgment_benchmark.py` covering tests #10–17 against the not-yet-written `judgment_benchmark.py` (red).
5. Implement `skills/paper-dive/scripts/judgment_benchmark.py`:
   - `build_benchmark_samples(n, collection=None, teacher_fn=None, cache_path=...)`: pulls real "empirical"-type abstracts from the `paper-knowledge` collection (reusing `competing_ideas.py`'s Chroma constants), runs today's real `extract_structure` (qwen2.5:3b, still alive) to get a real extraction per sample, calls the teacher once per sample for the gold reliability level, caches to disk.
   - `student_fn(extraction, spec)`: calls local `qwen2.5:3b` via a small Ollama helper that accepts `options={"temperature": spec["temperature"]}`, using `judge_extraction(..., prompt_template=spec["prompt_template"])` from step 1.
   - `score_fn`: binary match on `compute_reliability_signal`'s categorical level (student vs. gold).
   - `main()`: wires `marvin_launcher.launch(kind="utility-call", ...)` as the real teacher, calls `spec_search.search(...)`, records baseline and final metrics (accuracy, `cost_usd`, wall time) via `metrics_registry.record("paper-dive-judgment", ...)` / `compare(...)`. Not imported or executed by any test (green).
6. Run `main()` for real, once, on the mac-mini, scoped small (≈8–10 "empirical" samples, ≤4 search iterations) — produces the actual accuracy/cost/time numbers the ticket asks for.
7. Write the report doc, `docs/research/paper-dive-judgment-spec-search-2026-10-26.md`: today's-setup vs. tuned numbers, whether it worked, and (per the ticket's explicit ask) the recommended next jobs to search — triage classification, the daily digest — plus the two paper types ("survey", "conceptual") and the excluded "benchmark" type (still needs the now-deleted 14b, a #563-shaped gap, not re-solved here).
8. Add a short CONTEXT.md glossary entry for the new `spec_search` primitive (what it is, that it's teacher/student, that the live run is a manual/optional tier never required by the merge gate) — same convention every other named mechanism here follows.
9. Apply the **wire-in** decision once answered (ship into `logic_auditor.py`'s defaults, or leave as a recommendation for #563) — held open until Gil answers; nothing in steps 1–8 depends on the answer.