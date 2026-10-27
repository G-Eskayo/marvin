# Paper-Dive Judgment Specification Search — 2026-10-26

## Overview

Benchmark run to optimize the judgment extraction specification used by `logic_auditor.py`. The goal: find better prompt templates and/or model parameters that improve extraction reliability across empirical papers.

**Status**: Template. Run `skills/paper-dive/scripts/judgment_benchmark.py` on mac-mini to populate results.

## Experimental Setup

- **Benchmark size**: ~8–10 empirical papers pulled from paper-knowledge collection
- **Student model**: qwen2.5:7b (the default judgment model, per logic_auditor.py validation)
- **Evaluation metric**: binary match on categorical reliability level (high/moderate/low/very-low)
- **Teacher**: `marvin_launcher` utility-call to provide gold-standard reliability judgments
- **Search strategy**: keep-only-non-regressing-edits, max 4 iterations
- **Caching**: `~/.cache/judgment_benchmark.jsonl` persists samples and gold standards

## Baseline Configuration

The current default in `logic_auditor.py`:

```python
spec = {
    "temperature": 0.7,
    "prompt_template": None,  # Uses _JUDGMENT_PROMPTS[paper_type]
}
```

**Baseline accuracy**: [To be filled after run]

## Results

### Final Specification

[To be filled after run]

### Accuracy

| Configuration | Accuracy | Notes |
|---|---|---|
| Baseline | [%] | Current default (temperature 0.7, default prompts) |
| Final | [%] | After spec search |
| Improvement | [%] | Absolute gain |

### Iterations

- **Number of spec edits applied**: [N]
- **Convergence**: [Reached perfect score / Hit max iterations / Other]
- **Search history**: [To be appended from spec_search.search()["history"]]

## Analysis

### What changed

[Describe which parameters or prompt adjustments improved accuracy]

### Cost

- **Wall time**: [seconds]
- **API cost**: [tokens × rate]
- **Machine load**: [notes on resource usage]

### Generalizability

- **Scope tested**: empirical papers only (survey, benchmark, conceptual not included in this run)
- **Sample size limitation**: ~8–10 papers is small; patterns may not hold at scale
- **Gold standard robustness**: reliability levels from `marvin_launcher` — validates the spec against real MARVIN judgment, not a separate ground truth

## Recommended Next Steps

### To validate further

1. **Expand benchmark scope**: re-run with larger sample (~50+ empirical papers) to confirm pattern stability
2. **Cross-paper-type search**: separate searches for survey, benchmark, and conceptual papers (each has a different prompt/model combo in logic_auditor.py)
3. **Reliability level calibration**: current thresholds (0 findings → high, 1 → moderate, 2–3 → low, 4+ → very-low) are guesses; benchmark could inform better thresholds

### To integrate results

If accuracy improves significantly:

- **Option A (wire-in)**: update `_JUDGMENT_PROMPTS` and default params in `logic_auditor.py`, ship in next release
- **Option B (leave as recommendation)**: document the optimized spec in `docs/adr/` and reference it in suggestions.md for future adoption

The decision rests with #563 ("ship judgment tuning infrastructure") — this run is proof of concept that the infrastructure works.

## Notes

- **Benchmark caching**: subsequent runs on the same machine will reuse cached samples and gold standards unless `~/.cache/judgment_benchmark.jsonl` is deleted manually
- **Teacher availability**: requires `marvin_launcher.launch()` to work; if unavailable, samples will be built but gold standards will be "unknown"
- **Model availability**: assumes qwen2.5:7b and qwen2.5:3b are available locally via Ollama
