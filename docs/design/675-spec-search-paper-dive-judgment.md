# Ticket 675: Spec search to tune paper-dive judgment (Claude as teacher)

**Status:** Design + Implementation in progress  
**Decisions:** A, A, A (resident-only on qwen2.5:3b, reimplement in-house, ~3.2-point bar)  
**Goal:** Use Claude as a teacher to spec-search tune `qwen2.5:3b` on paper-dive judgment, measuring accuracy, cost, and time before the $100 API credit runs out.

## Decisions (locked)

1. **search-space (A):** Resident-only on `qwen2.5:3b`; no re-downloading deleted models (7b/14b).
2. **vendor (A):** Reimplement the idea in-house, reusing bench.py's subprocess/sandboxing patterns.
3. **accept (A):** Accuracy bar = within ~3.2 points of Claude's own agreement-with-itself baseline (the OpenJarvis paper's reported gap).

## Plan (from ticket 675)

1. **Design doc** — this file  
2. **Tests first** — adversarial test list (items 1–8 from ticket), written against not-yet-written `bench/spec_search.py` and `bench/benchmark_from_chroma.py`
3. **Build benchmark_from_chroma.py** — pull abstracts from paper-knowledge, extract with qwen2.5:3b, label with Claude (teacher), write frozen benchmark JSON
4. **Build spec_search.py** — baseline measurement, loop proposing edits, re-measure, keep only non-regressions, hard-round cap
5. **Wire results** — write judgment_spec.json (prompt/params) or update models.json (model choice), per ADR 0085
6. **Run manually** — benchmark build + search, one-time outside pytest
7. **Report** — append to bench/RESULTS.md as "Run N", mark frozen benchmark "spent"
8. **Recommend next jobs** — if accuracy clears bar, suggest triage + daily-digest; if not, report plainly

## Reused patterns

- **Teacher call:** Reuses bench.py's `judge_run` subprocess pattern (lines 339-344, 465): `claude -p --output-format stream-json --verbose --tools ""` with sandboxing
- **chat_fn injection:** Reuses logic_auditor.py's injection points (`classify_paper_type`, `extract_structure`, `judge_extraction`, `check_inference_validity`) for mocking in tests
- **Model checking:** Reuses bench.py's `_ollama_available` for every candidate model, never trusts config/models.json (which #563 shows is stale)
- **Benchmark versioning:** Frozen benchmark JSON dated/versioned to prevent silent overwrites, marked "spent" after tuning uses it
- **Results format:** Reuses bench/RESULTS.md's "Run N" narrative (see Run 32) instead of inventing a new report file

## What's different from prior attempts

- **No bench/lib/metrics_registry.py** — comparisons are in-memory within one sequential run; no file-locking needed
- **No root-level scratch files** — stays within bench/ and skills/ directories per ADR 0029 convention
- **Tests run offline** — zero real network calls via chat_fn injection; no Ollama calls either (test fixtures)
- **Search runs manually** — outside pytest to avoid whole-suite timeout (which the Oct 23 attempt hit at 1200s)

## Testing adversarial list (from ticket 675)

1. **Empty/malformed input:** zero papers → empty benchmark + explicit warning; missing fields → "(not extracted)" marker; unparseable teacher → sample marked unusable
2. **Dependency failures:** Ollama down → clear error; Claude teacher timeout → abort + report; candidate round crash → mark failed, continue with best
3. **Repeats/concurrency:** re-run doesn't double-apply edits; first-ever run handled explicitly
4. **Stale state:** paper slug no longer in collection → skip + warn; stale config/models.json → call _ollama_available live
5. **Misuse:** `--rounds 0` → no-op; typo'd capability → KeyError propagates clearly
6. **Bounded search:** hard max-rounds cap; **zero real network calls** (test asserts this)
7. **Regression gate logic:** accuracy improvement + time regression → reject; unchanged → reject; two edits, one good one bad → keep only good
8. **External untrusted text:** injected instructions in abstracts can't escape the structured label format

## Benchmarking details

**Frozen benchmark schema:**  
```json
{
  "created_epoch": <unix timestamp>,
  "sample_count": N,
  "samples": [
    {
      "slug": "paper-slug",
      "title": "...",
      "abstract": "...",
      "extraction": {...},  // from qwen2.5:3b
      "claude_label": {...},  // ground truth from teacher
      "claude_full_response": "..."  // for auditing
    }
  ],
  "accuracy_baseline": 0.85,  // accuracy vs claude labels on initial student model
  "cost_estimate": "0.42 USD",  // spent getting these labels (one-time teacher calls)
  "spent": false  // set to true after this benchmark is used to tune
}
```

**Search loop:**  
- Baseline: measure current accuracy (qwen2.5:3b on extraction + judgment, excluding ERROR/TIMEOUT/UNPARSEABLE)
- Each round: propose one edit (prompt tweak / engine param / model swap if Decision A is "B")
- Re-measure: same benchmark, same accuracy metric
- Keep only if: accuracy doesn't regress AND (cost or time doesn't regress materially OR accuracy improves)
- Stop after: N consecutive non-improving rounds OR hard max-round cap

**Cost tracking:**  
- One-time teacher labels (benchmark build): $0.42 estimate (teacher calls only, once)
- Student evaluation (search): $0 (local qwen2.5:3b, offline)
- Winning edit applied: no recurring cost (runs locally)
- Report: compare local cost ($0 ongoing) vs estimated Claude-in-the-loop cost (what it would have cost to call Claude per judgment instead)

## Signal for success (north star 1 applies)

- Accuracy within ~3.2 points of Claude's labels → "good enough," recommend next jobs
- Accuracy doesn't clear bar → plainly report the gap, no escalating rounds
- Design handles all 8 adversarial cases without crashing or silent failures

---

Detailed task list: see PR description (task list 1–11, with Decisions 1–3 at the top).
