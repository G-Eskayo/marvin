## North-star fit

**Reuses, before adding anything new:**
- `skills/paper-dive/scripts/logic_auditor.py`'s existing `chat_fn` injection point on `classify_paper_type`, `extract_structure`, `judge_extraction`, `check_inference_validity` — these already accept a pluggable chat callable (built for testing); the same hook lets a teacher (Claude) call and a tunable student (Ollama) call both drive the *same* judgment code, with zero changes to that file.
- `lib/metrics_registry.py`'s `record`/`latest`/`compare` three-function interface (CONTEXT.md's "Verification/trust mechanism": baseline → change → re-measure → iterate until genuinely better, already formalizing `route.py`'s classifier pattern). Spec search's accept/reject-an-edit decision is exactly this loop — no new comparison logic.
- `bench/bench.py`'s `judge_run` mechanism (lines 403-462): `claude -p` pinned to `CLAUDE_CONFIG_DIR=clean`, stripped `CLAUDE_CODE_*` env, `--tools ""`. This is the proven fix for two already-documented footguns (`bench/RESULTS.md` Runs 13 & 15: a judge's own tool access or own empty environment leaking into its verdict). Reused for every teacher/judge call this ticket needs (gold-labeling, edit-proposing, findings-scoring) rather than re-discovering those bugs.
- `bench/select_model.py`'s ascending-ladder, lock-in-after-N-passes shape and its `_check_quota` preflight — mirrored for the accept/reject/stop logic and quota safety, not copied verbatim (its task shape is fs/qa-task-specific, spec search's input is title+abstract).
- `model_registry.py` / `config/models.json` as-is for model presence — no registry changes if the student stays `qwen2.5:3b` (already registered, already present, already free).

**Why this is the simplest sufficient approach:** the alternative — writing a bespoke scorer, a bespoke comparison gate, and a bespoke headless-Claude-call mechanism — would re-solve three problems this repo already solved and documented. The only genuinely new code is the paper-dive-specific glue (benchmark builder, spec definition, scorer) and one small generic loop (`bench/spec_search.py`) that `#594`'s item 2 already anticipates extending `bench/select_model.py`-style tuning to more task types.

**Where it spends/saves:** spends teacher-model (Claude) tokens only in bounded rounds (quota-preflighted, capped), against the $100 API credit that's expiring (`[[project-subscription-sunset-throughput]]`, `[[project-monthly-api-credit]]`) — exactly the resource this spike must use before it's gone. It deliberately does *not* re-pull the deleted 9GB/4.7GB models by default, saving disk and avoiding re-litigating #563's own removal, unless Gil opts into that search space (see Decisions).

**Phone-OS direction:** moves one more recurring job (paper-dive judgment) toward running fully on-device, which is the explicit path to the $20 plan (`[[project-subscription-sunset-throughput]]`, #594) and to Independence (Vitals' measured bar: quality within 5%, latency within 1.5× of the paid baseline).

**More capable or more passive?** This is infrastructure/tooling work, not something that touches Gil's own judgment or learning — it makes MARVIN better at building/tuning tools (north star 4), with no coaching-vs-automating tension.

**Blocking dependency, not a design choice:** issue #675's own "What to build" frames this as filling "the gap #563 left." #563's fix is **PR #1408, currently open, not merged** (fail-loud `resolve_or_raise`, clearer errors) — reviewed with non-blocking notes but tasks 4/5/8 of its own plan still missing. This ticket's code must work against whatever `model_registry` shape is on `main` at build time (today: the bare `resolve_capability`/assert shape I read in `lib/model_registry.py`), not assume #1408's `resolve_or_raise` exists yet.

## Tests first

The ticket has no "How we'll try to break it" section, so these are derived from the general adversarial principle, per component:

**`ollama_chat.py` (+ new `options` passthrough)**
1. Every existing caller (unchanged call signature) produces a byte-identical payload to today — regression guard.
2. `options=None` → `"options"` key omitted from the payload, not sent as `null`.
3. `options={...}` → forwarded verbatim.
4. Ollama unreachable (connection refused) → raises clearly, not swallowed.
5. Ollama returns malformed JSON / no `"message"` key → raises a clear error, not a bare `KeyError` three frames deep.

**`judgment_benchmark.py` (teacher gold-labeling)**
6. `paper-knowledge` Chroma collection missing or empty → fails loud, never silently builds an empty benchmark.
7. A requested slug has no matching abstract in Chroma's `get()` result → skipped with a logged reason (mirrors `logic_auditor.py`'s own `__main__` filter), doesn't crash the batch.
8. Requested sample size > papers available → builds from everything available and says so, doesn't silently truncate or error.
9. One paper's teacher call errors/times out → that paper is skipped and logged; the run reports N succeeded / N failed, never claims a full benchmark when it isn't.
10. Benchmark file write is atomic (temp + `os.replace`, same pattern as `model_registry._write`/`metrics_registry._write_atomic`) — a crash mid-write never leaves a half-written fixture.
11. Hand-corrupted/truncated benchmark JSON on load → raises a clear error naming the file, not a bare `JSONDecodeError`.

**`bench/spec_search.py` (generic propose/score/accept loop)**
12. Teacher's proposed edit isn't parseable (malformed LLM output) → treated as "no edit," loop continues with the current spec, never crashes.
13. A syntactically valid but semantically broken edit (model name not in the allowed candidate set, or a prompt template missing a `{field}` placeholder `.format()` needs) → rejected *before* scoring, logged, not discovered via a mid-score crash.
14. A score within `metrics_registry.RELATIVE_TOLERANCE` of baseline → classified "unchanged" (reuse `_direction`'s existing tolerance), accepted but not counted as improvement; N consecutive "unchanged" rounds ends the search (no infinite chasing of noise).
15. `max_rounds <= 0` → zero iterations, returns the initial spec's own score, no crash.
16. Quota preflight (`bench.py::_check_quota`) reports the account already at its limit → the whole search aborts cleanly before spending anything, same as `select_model.py`'s existing behavior.
17. Two spec-search runs against the same subsystem concurrently → `metrics_registry`'s atomic writes prevent a corrupted snapshot file; document (don't silently hide) that an accept/reject decision can still race against a concurrent run's `latest()`.

**`judgment_spec.py` (score_spec: student vs. gold)**
18. Empty benchmark → returns a clear "no samples" result, never divides by zero / produces `NaN`.
19. Gold label missing a field (teacher itself omitted it — `logic_auditor.py` already documents this as legitimate) → scored as a miss for that field, not a `KeyError`.
20. Student model returns unparseable garbage for a paper (qwen2.5:3b's own documented failure mode: "literal single-word non-answers") → counted as a failure, never dropped from the denominator (a model can't look better by shrinking its own sample).
21. The findings-equivalence judge call itself errors/times out → marked unavailable/excluded with a note, never defaulted to pass or fail.
22. Re-running `score_spec` on the identical spec+benchmark gives the same accuracy within tolerance — confirms `temperature: 0` in the default spec's engine settings is actually wired through, not a no-op.

**CLI driver / report**
23. `--search` run before `--build-benchmark` has ever produced a file → fails loud with the fix command, never fabricates a tiny default benchmark.
24. First-ever write to the outbox (directory doesn't exist yet) → created, not crashed.
25. Behavior pinned against the *current* `lib/model_registry.py` shape via a stub/fake in tests, so a later #1408 merge changing that module's API doesn't silently break this code without a test catching it.

## Decisions
<!-- marvin:decisions -->
### search-space: Which local models can spec search try as the student?
- [ ] A: `qwen2.5:3b` only (already present, zero re-download — matches north star 1 and avoids re-litigating #563's removal)
- [ ] B: 3b plus allow re-pulling `qwen2.5:7b`/`qwen2.5:14b` as explicit candidates if 3b can't be tuned to an acceptable bar (asks first, per #563's own requirement; costs 4.7GB/9GB of disk)

### wiring: What happens if the tuned spec passes?
- [ ] A: Report only this round (accuracy/cost/time vs. the Claude-teacher baseline, written to the outbox) — wiring the winning spec into `logic_auditor.py`'s production functions is a separate follow-up ticket
- [ ] B: If the tuned spec clears the accept-threshold, wire it directly into `logic_auditor.py` in this same ticket (replaces the hardcoded 14b/7b model asserts)

### threshold: Minimum agreement with the Claude-teacher baseline to count the tuned local spec as "good enough"?
- [ ] A: 90%
- [ ] B: 95%
- [ ] C: Other (text)

### budget: Maximum teacher-proposal rounds per spec-search run (bounds $100-credit spend before it expires)?
- [ ] A: 5 rounds
- [ ] B: 10 rounds
- [ ] C: Other (text)

## Task List

1. Extend `skills/paper-dive/scripts/ollama_chat.py::ollama_chat()` with an optional `options: dict | None = None` param, forwarded into the request payload only when not `None` (tests 1-5).
2. Build `skills/paper-dive/scripts/judgment_benchmark.py`: sample papers from the `paper-knowledge` Chroma collection, generate gold labels by calling `logic_auditor.py`'s existing functions with a zero-tool, `clean`-profile Claude teacher (new small shared helper mirroring `bench.py::judge_run`'s subprocess mechanism), atomic JSON save/load (tests 6-11).
3. Build `skills/paper-dive/scripts/judgment_spec.py`: `DEFAULT_SPEC` capturing today's real prompts/model/engine-settings from `logic_auditor.py`, and `score_spec(spec, benchmark)` comparing a student run against gold (exact-match for type/inference labels, zero-tool Claude judge for findings-set equivalence) (tests 18-22).
4. Build `bench/spec_search.py`: generic `propose_edit()` (zero-tool Claude call proposing one edit to prompt/model/engine-settings) and `run_search()` wired to `lib/metrics_registry.record`/`compare`, reusing `bench.py::_check_quota` preflight and `select_model.py`'s accept/reject/stop shape (tests 12-17).
5. Build `skills/paper-dive/scripts/run_judgment_spec_search.py` CLI driver (`--build-benchmark`, `--search`) tying 2-4 together; writes the final report (accuracy/cost/time vs. the Claude-teacher baseline, plus the "next jobs to search" list: triage classification, daily digest) to the outbox (tests 23-25).
6. Append a dated "Run N" narrative entry to `bench/RESULTS.md`, matching its existing per-run convention, summarizing method and result.
7. Run the full existing `pytest` suite (`skills/paper-dive/scripts/tests/`, `lib/tests/test_model_registry.py`, `bench/tests/`) to confirm no regressions, per the merge gate's full-suite requirement.
8. Carry the Decisions section above into the PR body per `docs/agents/decisions-format.md`, so Gil picks search space, wiring scope, threshold and round budget before/alongside the spike's result landing.