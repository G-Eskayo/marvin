## North-star fit

**Reuses before adding anything new:**
- `bench/select_model.py`'s ascending-cost ladder + `bench.py`'s `_check_quota`/`run_once`/`run_once_ollama`/`judge_run` — the search loop's "try a candidate, score it, keep the winner" mechanic is the same shape OpenJarvis's spec search needs; extended, not duplicated.
- `docs/design/pipeline-g-eskayo-marvin-563.md`'s unfinished task 8 (`bench/tasks/task-0XX-paperdive-judge-<slug>/`, `task-0XX-paperdive-inference-<slug>/`) — never built (PR #1408's own review flagged tasks 4/5/8 as missing from the diff). This *is* "build the benchmark samples from our own past runs": the 2026-07-13 ground truth already validated and recorded in `test_logic_auditor.py` (StrongREJECT/sorry-bench/jailbreakbench, 14b-vs-7b).
- `lib/model_registry.resolve_or_raise` (shipped by #563/#1211) — the new code calls this instead of a bare `ollama_chat`, so the fail-loud guarantee covers the new search path too.
- `select_model.py`'s `bench/results/model-select-<task>-<timestamp>.json` naming convention — spec-search output reuses it as-is, no new file-safety mechanism invented.
- ADR 0085 point 6 ("tune the harness before the weights," citing OpenJarvis directly) and `docs/research/local-models-review-2026-11-11.md` §"Fine-tuning our local agents" already decided the sequencing and the training-data boundary this ticket sits inside.

**Why this is the simplest sufficient approach:** OpenJarvis's mechanism, as the ticket itself describes it, never touches model weights — it searches **prompts, tool choices and engine settings**, gated by a fixed benchmark. That means this spike needs no fine-tuning infrastructure at all: a small propose→gate loop on top of the existing ladder/bench primitives. Vendoring OpenJarvis's actual `learning/spec_search` code was considered and rejected — pulling in an unreviewed third-party research codebase for a bounded spike adds more audit surface than writing the ~150-line loop ourselves against primitives already in this repo.

**Where it saves resources:** if the tuned local spec holds the benchmark, this is one recurring job (paper-dive judgment: `judge_extraction`, `check_inference_validity`, and — ground-truth permitting — `classify_stance`) that stops needing Claude at runtime, directly feeding north star 1 and ADR 0085's Independence metric. Reuses `bench.py`'s existing Claude-cost capture (`parse_stream`) for the baseline arm instead of building new cost instrumentation.

**Where it spends resources:** the live sweep re-pulls `qwen2.5:7b`/`14b` (13.7 GB) and burns bounded Claude tokens as the *proposer* during search (never as the runtime judge). Per the #563 lesson (10+ timeouts from running a live multi-model Ollama sweep inside a 900–1200s gated step), the live sweep runs as a **separate, non-gated step**, not inside this PR's verification — this is the single most likely reason this ticket has failed 5 times with no visible diagnosis (no PR was ever raised on any attempt, so the actual must-fix findings aren't recoverable; this is the most plausible root cause plus the conflict below).

**Leaves Gil more capable:** produces a real, measured go/no-go (accuracy/cost/time, Claude vs. untuned-local vs. tuned-local) instead of another guess, and a prioritized list of next jobs to search — feeding the M3 deadline (2026-11-27) without spending more subscription time than necessary.

**Machine:** code/tests run wherever the worktree runs. The live sweep must run on the Mac mini (only machine with Ollama + the measured headroom, per #563's doc) — note the ticket's `claimed:macbook-pro` label looks stale against that.

**A likely cause of the repeated failures, flagged rather than worked around:** the ticket's own framing — "Claude is the teacher, and the local model is the student" — reads as knowledge distillation (train the student on the teacher's outputs). ADR 0085's "Training data" consequence and the research doc it's built on (`docs/research/local-models-review-2026-11-11.md` §"Fine-tuning our local agents") are explicit: training data is **only MARVIN's own outcomes, never Claude-written text**, because Anthropic's Consumer Terms §3 forbid using the service to train a competing model, and "whether a private MARVIN agent competes is a question for Gil, not an agent." No model weights get trained in spec search (it only edits prompts/settings), so the letter of that rule isn't triggered — but if a prior attempt let the *proposer* see the ground-truth label and optimize straight toward reproducing it, that's distillation in spirit even without a gradient step, and is exactly the kind of thing a code reviewer enforcing ADR 0085 would flag as a must-fix. I'm not willing to guess silently here — see Decision `training-signal` below.

## Tests first

No "How we'll try to break it" / Attacks section exists on this ticket, so these are derived from the guiding principle against the concrete new surfaces this plan touches.

**`skills/paper-dive/scripts/ollama_chat.py` (add optional `options` kwarg: temperature, `format` JSON-schema, `num_predict`):**
1. `options=None` → payload unchanged from today — regression guard for the ~40+ existing tests across `logic_auditor.py`/`competing_ideas.py`/`argument_mapper.py` that call this with no options.
2. `options={...}` → passed through verbatim in the request payload, untouched/unvalidated (explicit no-clamping contract, tested either way).

**New `bench/spec_search.py` — `evaluate_spec(spec, fixtures, chat_fn)`:**
3. A fixture missing its ground-truth field → raises a named error, never scores as a silent pass or 0.0.
4. Empty fixture set → raises/returns a clear "no cases" result, not a misleading 100% or a `ZeroDivisionError`.
5. `chat_fn` raises for one case (Ollama drops mid-eval) → that case is recorded as a named failure; the rest of the sweep still completes (one dependency failure doesn't abort the batch).
6. A fixture whose recorded ground truth is internally contradictory (malformed data) → rejected at load time, not silently resolved one way.

**New `propose_edit(current_spec, failing_cases, propose_fn)` — the safety-critical boundary:**
7. The payload built for `propose_fn` is asserted, in the test, to **never contain the case's ground-truth/expected-answer string** — the concrete regression guard encoding Decision `training-signal`'s recommended option below.
8. `propose_fn` returns a malformed/unparseable edit → the current spec is kept unchanged; the loop doesn't crash or silently adopt garbage.
9. `propose_fn` returns a no-op (identical to the current spec) → the loop detects no progress and stops rather than looping forever.
10. `propose_fn` raises (Claude call fails/rate-limited) → that round aborts cleanly, the best-so-far spec is kept, and the failure is reported — no silent progress loss.

**Search loop bounds (direct regression test against this ticket's own timeout history):**
11. A fixture crafted to always fail still terminates at the iteration cap, never loops unbounded.
12. An edit that fixes one case but regresses a previously-passing case is rejected — "only edits that don't regress the benchmark are kept," tested with a crafted two-case fixture.
13. Two back-to-back runs against the same fixtures with the same mocked `propose_fn` sequence produce identical kept/rejected verdicts — no hidden mutable state carried between runs.

**New paper-dive bench fixtures (`bench/tasks/task-0XX-paperdive-{judge,inference}-<slug>/`):**
14. Each loads via `bench.load_task()` without error, reusing the real 2026-07-13-validated StrongREJECT/sorry-bench ground truth from `test_logic_auditor.py` verbatim (not fresh/invented labels).
15. A malformed fixture directory (missing `task.json`) hits `select_model.py`'s existing "has no task.json" exit — no special-case handling needed.

**Output writer / wrong machine:**
16. Results write to `bench/results/spec-search-<task>-<timestamp>.json` using the same naming scheme as `select_model.py` — unique per (task, timestamp), no new locking/concurrency machinery built beyond what that existing convention already gives.
17. Running the live-sweep path with Ollama unreachable fails loud via `model_registry.resolve_or_raise` (not a bare `ollama_chat` call) — the new code path gets the same fail-loud guarantee #563 already built for the four original call sites.

**Verify-fails-without-a-test guard:** tests 1–16 run with Ollama stopped and are fully green — only test 17 and the live sweep itself touch the network, and only outside the gated step.

## Decisions

<!-- marvin:decisions -->
### training-signal: What may the frontier model (Claude) see while proposing an edit during spec search?
- [ ] A: Claude sees only the local model's bad output, the task, and the current prompt/spec — never the ground-truth/expected answer. The benchmark's pass/fail gate (scored deterministically against ground truth MARVIN already has, outside Claude's view) is the sole arbiter of whether an edit survives. (recommended — keeps this a harness/prompt search per ADR 0085 point 6, not distillation; no Claude-written text becomes a training target)
- [ ] B: Claude is also shown the ground-truth answer when proposing an edit, so it can suggest a fix that directly targets the correct output (closer to the ticket's literal "teacher/student" wording, but is the exact pattern ADR 0085's training-data rule and the Anthropic Consumer-Terms note in `docs/research/local-models-review-2026-11-11.md` flag as needing the owner's call, not an agent's)

### benchmark-scope: Which paper-dive judgment functions get a built benchmark for this spike?
- [ ] A: `logic_auditor.judge_extraction` and `logic_auditor.check_inference_validity` only — the two functions with already-validated (2026-07-13) ground truth to build fixtures from. (recommended — `competing_ideas.classify_stance` has no reviewed ground truth yet; inventing fresh labels for it now would be the "guess the ticket forbids" #563's own comment already called out)
- [ ] B: Also build fresh ground truth for `competing_ideas.classify_stance` now, by having Gil review a sample of its past stance calls before this ticket closes

### candidate-models: Which local model candidates does the live sweep try, beyond today's qwen2.5:7b/14b?
- [ ] A: Today's config only (qwen2.5:3b/7b/14b) — narrowest possible scope for this spike, defers the ADR-0085-recommended Qwen3.5 migration to its own ticket (optional)
- [ ] B: Also include Qwen3.5-4B/9B (ADR 0085's already-decided starting point for the local tier) in the same sweep, so this spike's numbers double as that migration's first real evidence (optional)

## Task List

1. Add optional `options` kwarg to `skills/paper-dive/scripts/ollama_chat.py` (temperature, `format`, `num_predict`), defaulting to today's exact request shape. Write tests 1–2 first.
2. Build `bench/tasks/task-0XX-paperdive-judge-<slug>/` and `task-0XX-paperdive-inference-<slug>/` fixtures from the already-validated 2026-07-13 findings in `test_logic_auditor.py` (StrongREJECT/sorry-bench/jailbreakbench). Write tests 14–15 first.
3. Add `bench/spec_search.py`: `evaluate_spec()` scoring a spec (prompt/model/options) against the fixtures via `model_registry.resolve_or_raise` + the extended `ollama_chat`. Write tests 3–6, 17 first.
4. Add `propose_edit()`: builds the ground-truth-blind payload for an injected `propose_fn`, parses its proposed spec edit, validates it before adoption. Write tests 7–10 first.
5. Add the bounded search-loop driver (max-iteration cap, regression-reject rule, result trace), writing to `bench/results/spec-search-<task>-<timestamp>.json` per `select_model.py`'s existing naming convention. Write tests 11–13, 16 first.
6. Run the full new/changed test set with Ollama stopped — confirm it's green with zero live network calls, at or above the current baseline.
7. Resolve the Decisions above with Gil before the live sweep runs; implement `propose_edit`'s payload construction to match the answer to `training-signal`.
8. Run the live sweep on the Mac mini, as a separate non-gated step (not inside this PR's verification): pull/confirm the chosen candidate model(s) per `candidate-models`, run the Claude-baseline arm (reusing `bench.py`'s `run_once`/`parse_stream` for cost/time capture) and the untuned-local and spec-searched-local arms against the fixtures.
9. Write up the comparison (accuracy/cost/time, all three arms) as a new dated entry in `bench/RESULTS.md`, plus the "next jobs to search" list the ticket asks for (triage classification, daily digest).
10. If the spec-searched local setup clearly holds the benchmark, wire its winning spec into `logic_auditor.py`'s judgment call sites (and `config/models.json` if the winning model differs) in the same PR; if it doesn't, report that plainly rather than forcing a switch.
11. Force-unload any Ollama models pulled only for this sweep once done; confirm `ollama ps` is empty.