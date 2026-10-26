## North-star fit

**Reuses:**
- `skills/paper-dive/scripts/logic_auditor.py:judge_extraction` / `check_inference_validity` — both already take an injectable `chat_fn` parameter. That's the exact seam spec search needs: swap in a Claude-teacher call or a student-model call with a candidate prompt, with zero changes to the judged functions themselves.
- `bench/bench.py:judge_run` — the existing "one-shot `claude -p <prompt> --output-format text --tools ""`" invocation is the established pattern for a zero-tool, no-environment-leak Claude call. Reused verbatim for both teacher-labeling and teacher-proposes-an-edit steps, instead of inventing a new way to call Claude headlessly.
- `bench/bench.py:_check_quota` — the quota preflight `select_model.py` already runs before any multi-call sweep; a spec-search loop burns several Claude calls per round and needs the same guard.
- `bench/select_model.py` — structurally the closest existing "spec search": try a candidate, require repeat passes, lock in only on success, escalate otherwise. The new search loop reuses this round/lock-in shape, applied to prompt edits instead of model choice.
- `bench/RESULTS.md`'s Run-N ledger and its own route.py tuning discipline (Runs 25/27/28: diagnose the *specific* miss → one small targeted edit → regression-check against a frozen holdout, confirmed cleanest when edits are small) — this is the literal "propose an edit, keep only if no regression" loop OpenJarvis's spec search describes, already proven out by hand in this repo. The new code formalizes it, it doesn't invent a new philosophy.
- `logic_auditor.py`'s own `__main__` (seeds-json slug→title, fetched from the `paper-knowledge` ChromaDB collection) — reused to source "benchmark samples from our own past runs" rather than building a new paper-selection mechanism.

**Simplest sufficient approach:** OpenJarvis's spec search can edit prompts, tools, model, and engine settings. For one Ollama chat call with no tool surface and exactly one surviving candidate model (`qwen2.5:3b` — `config/models.json` and `#563` both confirm 14b/7b are gone and nothing else fills `local-judge-medium`/`local-inference-large`), the only live search axis is the **prompt text**. Building generic multi-axis search machinery for a search space that currently has one axis would be the Watts-check failure (machinery serving itself). Scope is deliberately narrowed to prompt search now; the generic loop is still written as its own small module (see Task List) so triage/digest — which the ticket explicitly names as next jobs — can plug in their own axes later without a rewrite.

**Tokens:** spent on Claude-as-teacher calls (labeling + proposing edits) during the spike only; the eventual win, if the spike succeeds, is routing paper-dive's judgment step to a free local call instead of a Claude call, every future run. A no-adoption result (matching sibling spike `#674`'s own framing, "measured, no adoption yet") still spends tokens once to answer a yes/no question MARVIN would otherwise never answer, which is strictly cheaper than guessing.

**More capable, not more passive:** this is infra/background tuning work, invisible to Gil day-to-day except as a `bench/RESULTS.md` entry and a recommendation he reads once — it doesn't remove any judgment he currently exercises himself.

## Decisions

<!-- marvin:decisions -->
### repull: Temporarily re-pull qwen2.5:7b/14b (13.7 GB, already deleted once for disk) to measure the pre-#563-deletion baseline, or skip that and compare teacher-Claude vs. untuned-3b vs. spec-searched-3b only?
- [ ] A: Re-pull both temporarily for the spike, delete again afterward
- [ ] B: Skip it — compare only Claude (teacher/current de-facto baseline since the local path is broken) vs. untuned-3b vs. spec-searched-3b

### label-check: Should Gil spot-check a sample of the Claude-generated "gold" benchmark labels before they're frozen as ground truth, or trust them outright for this spike?
- [ ] A: Spot-check a few before freezing the benchmark
- [ ] B: Trust Claude's labels outright, same as `bench.py`'s existing judge is already trusted elsewhere

## Tests first

The ticket carries no "How we'll try to break it"/Attacks list, so these are derived from the standing misuse checklist, applied to each new piece:

1. **`judge_extraction`/`check_inference_validity` with a candidate prompt** — already covered by existing tests (`test_logic_auditor.py`) for parsing; new tests only needed for the search driver, below.
2. **Benchmark loader** (pulls seed papers from `paper-knowledge` collection):
   - empty collection → raises/clear error, not a silent empty benchmark
   - a seed slug missing from the collection → skipped with a logged warning, not a crash (mirrors `logic_auditor.py --main--`'s existing `if slug in abstracts` filter)
   - malformed/empty abstract text for a found slug → excluded, not fed to a model as a blank prompt
3. **Teacher call (`claude -p` subprocess)**:
   - Claude CLI exits non-zero / times out → the round aborts loudly (same `infra_error`/quota-abort behavior `select_model.py` already has), never silently treated as "no edit proposed" or "benchmark sample passed"
   - quota already exhausted at preflight → whole search aborts before spending any calls (reuse `_check_quota`)
   - Claude's response doesn't parse into the expected edit/label format → treated as a failed round, not guessed at
4. **Student call (Ollama)**:
   - Ollama not running / connection refused → run aborts with a clear error, not scored as a failure-looks-like-regression
   - the student model (`qwen2.5:3b`) itself missing locally → fails fast with an explicit message (this is literally `#563`'s unresolved failure mode — the new tool must not repeat it silently)
   - model returns empty string / garbage unparseable response → scored as a miss, not as a crash
5. **Search loop accept/reject logic**:
   - a proposed edit that improves one sample but flips a currently-passing sample to failing → rejected (no net regression is the literal rule)
   - a proposed edit identical to the current prompt (teacher proposes a no-op) → loop terminates/doesn't loop forever
   - repeated rounds with no improving edit found → loop terminates after a bounded number of rounds, not indefinitely
   - two rounds in a row produce the exact same rejected edit → doesn't retry it a third time
6. **Concurrency / repeats / stale state**:
   - running the search script twice concurrently against the same `results/` output path → no clobbered/corrupted JSON (same atomic-write discipline as `model_registry.py`'s `_write`)
   - re-running after a previous run already wrote a `bench/RESULTS.md` entry → appends a new Run-N section, doesn't overwrite history
7. **A person's mistakes**:
   - wrong working directory / run from outside the repo → relative paths (`CHROMA_PATH`, `bench/RESULTS.md`) still resolve correctly or fail with a clear message
   - benchmark set accidentally containing 0 samples → script refuses to report a 100%-on-nothing number

## Task List

1. Freeze the benchmark: write a small loader that pulls the existing 15 seed-paper slugs (or whatever subset actually has abstracts) from the `paper-knowledge` ChromaDB collection, reusing `logic_auditor.py`'s own seeds-json pattern. Write its tests first (benchmark-loader misuse cases above).
2. Generate teacher (Claude) gold labels for each benchmark sample's `judge_extraction` + `check_inference_validity`, via `judge_run`'s existing `claude -p ... --tools ""` invocation shape. Resolve Decision `label-check` before freezing these as ground truth.
3. Score the untuned student (`qwen2.5:3b`, current prompts unchanged) against the frozen benchmark, via the existing `chat_fn` injection — no code changes to `logic_auditor.py` needed for this step.
4. If Decision `repull` resolves to A, temporarily re-pull `qwen2.5:7b`/`14b`, score them the same way for the historical baseline, then delete them again.
5. Build the generic spec-search loop (new small module, e.g. `bench/spec_search.py`): propose-one-edit → score-against-full-frozen-benchmark → accept only if no sample regresses → bounded round count → no-op/repeat-edit termination. Write its tests first (search-loop misuse cases above).
6. Build the paper-dive driver that wires the generic loop to `judge_extraction`/`check_inference_validity`'s prompts and a teacher-proposes-an-edit Claude call (reusing `judge_run`'s invocation shape again). Write its tests first (teacher/student-call misuse cases above).
7. Run the search to convergence or the round cap; record accuracy, Claude-call cost/tokens, and wall-clock time for each variant (today's de-facto baseline, untuned student, spec-searched student, and the historical 7b/14b baseline if Decision `repull` = A).
8. Append a new Run-N entry to `bench/RESULTS.md` with the comparison table and a plain adopt/don't-adopt recommendation.
9. If the result is positive, list the next candidate jobs to run spec search on (triage classification, daily digest) in the same entry, per the ticket's explicit ask — no implementation of those, just the list.
10. No changes to `config/models.json`/`model_registry.py` or the live pipeline — that's `#563`'s scope, left alone here.